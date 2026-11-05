"""Move research findings into the catalog, where a writer exists for them.

Research and catalog are different things. A finding is what a source said,
with the sentence that says it; a catalog row is a fact the product answers
questions from. This is the deliberate step between them, and it only moves
what there is somewhere to move — the rest is reported, not silently dropped.

Findings arrive typed (app/ingest/research/finding_types.py), so this file maps
fields to columns. It does not parse. The version before it read free text with
regular expressions and refused a real figure because it could not tell crore
from rupees, which was the good half of that failure mode.
"""

from __future__ import annotations

import collections
import logging
from datetime import UTC, datetime
from typing import Any

from app.ingest.catalog.matcher import Match, _is_foundation, name_key, resolve_funder, resolve_org, variants
from app.ingest.catalog.promote_documents import (
    staff_dataset_rows,
    write_document_links,
    write_documents,
    write_programs,
)
from app.ingest.catalog.promote_facts import write_facts
from app.ingest.catalog.promote_records import (
    FOLDED,
    MERGEABLE,
    NAME_MATCHES,
    ORG_WRITE_ORDER,
    STATES,
    csr_years_from,
    funder_from,
    guarded,
    legacy_grants,
    org_from,
    settle,
    settle_identity,
    unsettled,
    write_record_tags,
)
from app.ingest.catalog.rows import (
    FunderRecord,
    OrgRecord,
)
from app.ingest.catalog.writer import GATE, Gate, Owner
from app.ingest.catalog.writer_funder import cin_holder, write_csr_year, write_funder
from app.ingest.catalog.writer_org import org_alias_holders, write_org
from app.ingest.reading import staff_sources, vault
from app.ingest.research import source_guards
from app.ingest.research.expectations import PROMOTABLE
from app.ingest.research.finding_types import TYPED_SINCE

logger = logging.getLogger(__name__)


async def _parent(conn: Any, record: FunderRecord, report: dict[str, Any]) -> int | None:
    """The parent company's funder id, when it is already in the catalog.

    A parent that does not resolve is reported, never created. "Never merge a
    company with its foundation" cuts both ways: inventing Axis Bank Limited
    because Axis Bank Foundation mentioned it puts a row in the catalog that no
    source was read for.
    """
    if not record.parent_name:
        return None
    match = await resolve_funder(conn, record.parent_name)
    # Explicit about the methods rather than relying on Match.resolved: a
    # trigram hit happens to carry funder_id=None, so this was safe by accident
    # of the dataclass. A near-miss parent — ITC Limited against ITC Infotech —
    # is precisely the link that must not be stored quietly.
    if match.method in MERGEABLE:
        return match.entity_id
    if match.method == "trigram":
        names = ", ".join(c["name"] for c in match.candidates)
        report["held"].append(
            f"parent {record.parent_name!r} of {record.name!r} resembles {names} without "
            f"matching. Not linked — a person decides which, if either, it is."
        )
        return None
    report["held"].append(
        f"parent {record.parent_name!r} of {record.name!r} is not in the catalog, so the link "
        f"is not stored. Research the parent and promote it first."
    )
    return None


async def _org_parent(conn: Any, record: OrgRecord, match: Match, report: dict[str, Any]) -> int | None:
    """The parent body's org id when Sangam holds it; otherwise a held line, never a new row."""
    if not record.parent_name:
        return None
    parent = await resolve_org(conn, record.parent_name)
    if parent.method in MERGEABLE and parent.entity_id != match.entity_id:
        return parent.entity_id
    if parent.method == "trigram":
        names = ", ".join(c["name"] for c in parent.candidates)
        report["held"].append(f"parent {record.parent_name!r} of {record.name!r} resembles {names} without "
                              f"matching. Not linked — a person decides which, if either, it is.")
        return None
    report["held"].append(
        f"parent {record.parent_name!r} of {record.name!r} is not an organisation Sangam holds, so the link "
        f"is not stored. Research the parent and promote it first."
    )
    return None


async def _link_research(
    conn: Any, row: dict[str, Any], *, org_id: int | None = None, funder_id: int | None = None
) -> None:
    """What this research row became. Both columns, always: the pair existed
    unwritten and unread since 0011, and filling one of them would leave the
    other looking deliberately empty."""
    await conn.execute(
        "UPDATE entity_research SET resolved_org_id = %s, resolved_funder_id = %s WHERE id = %s",
        (org_id, funder_id, row["id"]),
    )


async def _reconcile_org_aliases(
    conn: Any, record: OrgRecord, match: Match, report: dict[str, Any]
) -> OrgRecord:
    """Aliases to add: the research's own spelling (on a matched org) and its aliases, less any another
    organisation already answers to. Those are held: a shared spelling resolves neither org."""
    by_name = match.method in NAME_MATCHES
    wanted = [*([record.name] if by_name else []), *record.aliases]
    holders = await org_alias_holders(conn, wanted, match.entity_id)
    for spelling in wanted:
        holder = holders.get(name_key(spelling))
        if holder is not None:
            report["held"].append(
                f"alias {spelling!r} is already the name or an alias of {holder['name']!r} "
                f"[org:{holder['id']}], so it is not added to {record.name!r}. Two organisations "
                f"sharing a spelling is a decision for a person."
            )
    kept = [s for s in wanted if name_key(s) not in holders]
    return record.model_copy(update={"aliases": kept})


async def _reconcile_with_stored(
    conn: Any, record: FunderRecord, match: Match, report: dict[str, Any]
) -> FunderRecord:
    """Drop what the funders row's own constraints would refuse, and say so.

    A constraint violation aborts this funder's whole promotion: funders.cin is UNIQUE and
    funders_grant_band orders the band. A CIN already stored on this row is not overwritten.
    """
    update: dict[str, Any] = {}
    stored = None
    if match.entity_id is not None:
        stored = await (
            await conn.execute(
                "SELECT cin, grant_size_min, grant_size_max FROM funders WHERE id = %s",
                (match.entity_id,),
            )
        ).fetchone()
    if record.cin:
        holder = await cin_holder(conn, record.cin)
        if _is_foundation(record.name):
            report["held"].append(
                f"CIN {record.cin} is not written on {record.name!r}: a CIN names a company, and a "
                f"foundation's research usually carries its parent's. Link the parent by parent_id."
            )
            update["cin"] = None
        elif holder is not None and holder["id"] != match.entity_id:
            report["held"].append(
                f"CIN {record.cin} is already recorded on {holder['name']!r} [funder:{holder['id']}], "
                f"so it is not written on {record.name!r}. One CIN is one company."
            )
            update["cin"] = None
        elif stored and stored["cin"] and stored["cin"] != record.cin:
            report["held"].append(
                f"CIN {record.cin} differs from {stored['cin']} already stored on "
                f"{record.name!r}. Not written — a person decides which is current."
            )
            update["cin"] = None
    one_sided = (record.grant_size_min is None) != (record.grant_size_max is None)
    if stored and one_sided:
        lo = record.grant_size_min if record.grant_size_min is not None else stored["grant_size_min"]
        hi = record.grant_size_max if record.grant_size_max is not None else stored["grant_size_max"]
        if lo is not None and hi is not None and float(hi) < float(lo):
            report["held"].append(
                f"grant band for {record.name!r}: the research inverts the stored band "
                f"({stored['grant_size_min']} to {stored['grant_size_max']}). Not written — a "
                f"person decides which is current."
            )
            update.update(grant_size_min=None, grant_size_max=None)
    return record.model_copy(update=update) if update else record


def _answered(asking: Gate | None, table: str, name: str, match: Match, report: dict[str, Any]) -> Match | None:
    """A name that only resembles a stored one is merged or kept apart on a person's answer; None holds it."""
    top = match.candidates[0]
    choice = asking.on_entity(table, name, top) if asking else "ask"
    if choice == "update":
        return Match("alias", top["id"], top["score"])
    if choice == "new":
        return Match("none")
    names = ", ".join(c["name"] for c in match.candidates)
    report["reasons"].append(f"{name!r} resembles {names} without matching. Not merged — a person decides.")
    return None


async def link_partner_lines(conn: Any, org_id: int) -> int:
    """Funder partner lines that name this NGO but were written before Sangam held it, linked now. No model:
    the line's name, or a variant of it, must be the NGO's name or one of its aliases."""
    org = await (await conn.execute("SELECT name, aliases FROM orgs WHERE id = %s", (org_id,))).fetchone()
    if org is None:
        return 0
    keys = {name_key(n) for n in (org["name"], *(org["aliases"] or []))}
    rows = await (await conn.execute(
        "SELECT id, partner_name, partner_canonical FROM funder_activity "
        "WHERE kind = 'partner' AND partner_org_id IS NULL"
    )).fetchall()
    ids = [r["id"] for r in rows
           if keys & {name_key(n) for raw in (r["partner_name"], r["partner_canonical"]) if raw
                      for n in (raw, *variants(raw))}]
    if ids:
        await conn.execute("UPDATE funder_activity SET partner_org_id = %s WHERE id = ANY(%s)", (org_id, ids))
    return len(ids)


async def _resolved(conn: Any, row: dict[str, Any]) -> Match | None:
    """The entity an earlier save of this slug wrote to, while it still exists: a re-run never matches again.
    An "alias" match, because a person or the matcher already settled that this spelling is that entity."""
    column, table = (("resolved_org_id", "orgs") if row.get("entity_kind") == "org"
                     else ("resolved_funder_id", "funders"))
    found = await (await conn.execute(
        f"SELECT r.{column} AS id FROM entity_research r JOIN {table} t ON t.id = r.{column} "
        "WHERE r.slug = %s ORDER BY r.researched_at DESC LIMIT 1", (row["slug"],),
    )).fetchone()
    return Match("alias", found["id"]) if found else None


async def org_match(conn: Any, row: dict[str, Any], asking: Gate | None = None) -> Match | None:
    """The NGO a save of this research would write to, after any answer to "the same organisation?"; None waits."""
    findings = row["findings"] if isinstance(row.get("findings"), list) else []
    record = org_from(row, findings)
    name = record.name if record else row.get("canonical_name") or row.get("entity_name") or row["slug"]
    match = await _resolved(conn, row) or await resolve_org(
        conn, name, record.identifiers if record else None, record.website if record else None)
    return _answered(asking, "orgs", name, match, {"reasons": []}) if match.method == "trigram" else match


async def _promote_funder(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], report: dict[str, Any],
    asking: Gate | None = None,
) -> None:
    record = funder_from(row, findings, report)
    if record is None:
        report["reasons"].append("no identity finding to build a funder from")
        return

    match = await _resolved(conn, row) or await resolve_funder(conn, record.name, record.cin, record.website)
    if match.method == "trigram":
        match = _answered(asking, "funders", record.name, match, report)
        if match is None:
            return
    if match.resolved:  # the same funder: every spelling the research used becomes an alias
        record = record.model_copy(update={"aliases": [*record.aliases, record.name]})
    record = await _reconcile_with_stored(conn, record, match, report)
    parent_id = await _parent(conn, record, report)
    status, funder_id, _ = await write_funder(conn, record, match, parent_id=parent_id)
    report["entity"] = {
        "kind": "funder", "status": status, "id": funder_id, "name": record.name
    }
    settle_identity(report, findings, "identity", status, f"[funder:{funder_id}]")
    await write_record_tags(conn, "funder_id", funder_id, record, record.name, report)

    owner = Owner.funder(funder_id)
    gate = GATE.get()
    # A plan writes nothing, and archiving moves storage objects, which no rollback undoes.
    docs = {} if gate and gate.plan else await write_documents(conn, row, findings, owner, report)
    if gate and gate.plan:
        for f in findings:
            if f["concept"] == "document":
                settle(report, f, {"state": "written"})
    years = {f["fiscal_year"]: f for f in findings if f["concept"] == "csr_year"}
    for year_record in csr_years_from(row, findings):
        state, _ = await write_csr_year(
            conn, year_record, funder_id, docs.get(year_record.source_url)
        )
        report["csr_years"].append({"fiscal_year": year_record.fiscal_year, "status": state})
        if year_record.fiscal_year in years and state in STATES:
            settle(report, years[year_record.fiscal_year], {"state": STATES[state]})
    programs = await write_programs(conn, row, findings, owner, docs, report)
    findings = [*findings, *legacy_grants(findings, report)]
    await write_facts(conn, row, findings, owner, programs, docs, report)
    if not (gate and gate.plan):
        await write_document_links(conn, findings, owner, programs, docs, report)
        await _link_research(conn, row, funder_id=funder_id)


async def _promote_org(
    conn: Any, row: dict[str, Any], findings: list[dict[str, Any]], report: dict[str, Any],
    asking: Gate | None = None,
) -> None:
    """The NGO path. Same shape as the funder one bar two differences: there is
    no parent link to resolve, and write_org ranks by evidence tier."""
    record = org_from(row, findings, report)
    if record is None:
        report["reasons"].append(
            "no org_identity or org_identifier finding with a source_type and evidence_tier to build an "
            "organisation from (research saved before evidence tiers is re-researched, not promoted)"
        )
        return

    match = await _resolved(conn, row) or await resolve_org(
        conn, record.name, record.identifiers, record.website)
    if match.method == "trigram":
        match = _answered(asking, "orgs", record.name, match, report)
        if match is None:
            return
    record = await _reconcile_org_aliases(conn, record, match, report)
    parent_id = await _org_parent(conn, record, match, report)
    status, org_id, _, conflicts = await write_org(conn, record, match, parent_id=parent_id)
    report["entity"] = {"kind": "org", "status": status, "id": org_id, "name": record.name}
    settle_identity(report, findings, "org_identity", status, f"[org:{org_id}]")
    if linked := await link_partner_lines(conn, org_id):
        report["written"].setdefault("funder_activity (partner link)", collections.Counter())["updated"] += linked
    await write_record_tags(conn, "org_id", org_id, record, record.name, report)
    report["conflicts"].extend(c.describe() for c in conflicts)

    owner = Owner.org(org_id)
    docs = await write_documents(conn, row, findings, owner, report)
    programs = await write_programs(conn, row, findings, owner, docs, report)
    await write_facts(
        conn, row, findings, owner, programs, docs, report, order=ORG_WRITE_ORDER
    )
    await write_document_links(conn, findings, owner, programs, docs, report)
    await _link_research(conn, row, org_id=org_id)


async def promote(conn: Any, row: dict[str, Any], *, gate: Gate | None = None) -> dict[str, Any]:
    """Write what can be written from one research row. Returns a report.

    With a gate, a funder's facts follow the five cases (writer.Gate); an NGO keeps fill-blanks and
    asks only whether a name that resembles a stored NGO's is the same organisation.
    """
    asking = gate
    if row.get("entity_kind") == "org":
        gate = None
    token = GATE.set(gate)
    try:
        report = await _promote(conn, row, asking)
    finally:
        GATE.reset(token)
    if asking and not gate:
        report["questions"] = asking.asked()
        report["held"].extend(
            f"{i['new_name']!r}: waiting for a person to say whether it is {i['stored_name']!r}"
            for i in report["questions"]
        )
    if gate:
        report["questions"] = gate.asked()
        report["changes"] = [i for i in gate.items if i["case"] in (2, 3, 4)
                             and i.get("outcome") in ("written", "planned")]
        report["plan"] = {"same": gate.same, "items": gate.items}
        report["held"].extend(
            f"{i['table']} {i['label']}: waiting for a person ({' / '.join(i['choices'])})"
            for i in report["questions"]
        )
        report["held"].extend(
            f"{i['table']} {i['label']}: {i['reason']}" for i in gate.items if i.get("outcome") == "held"
        )
    return report


async def _promote(conn: Any, row: dict[str, Any], asking: Gate | None = None) -> dict[str, Any]:
    findings = row["findings"] if isinstance(row["findings"], list) else []
    report: dict[str, Any] = {
        "slug": row["slug"], "entity": None, "csr_years": [],
        "written": {}, "held": [], "conflicts": [], "skipped": {}, "reasons": [], "facts": {},
    }
    for concept in sorted({f["concept"] for f in findings}):
        if concept not in PROMOTABLE and concept not in FOLDED:
            report["skipped"][concept] = len([f for f in findings if f["concept"] == concept])

    # Before the kind branch, not after it. An org row researched under the old
    # shape used to be turned away for having no writer, which is a reason that
    # has stopped existing; "re-run the research" is the one that says what to do.
    if findings and row.get("schema_version", 1) < TYPED_SINCE:
        report["reasons"].append(
            f"researched under finding shape v{row.get('schema_version', 1)}, which has no typed "
            f"fields to map. Re-run the research for {row['slug']} and promote that."
        )
        return report

    datasets = await staff_dataset_rows(conn, findings)
    findings = guarded(report, findings, staff_sources.hold_unmarked(
        findings, {u: d["id"] for u, d in datasets.items()}))
    # A marked staff figure is still held unless its cited row prints it, in the unit it was saved in.
    findings = guarded(report, findings, await staff_sources.hold_mismatched(findings, datasets))
    # A vault finding was checked against its org's files at save; here only the funder's general facts pass.
    findings = guarded(report, findings, vault.hold_at_promote(findings, row.get("entity_kind")))
    findings = guarded(report, findings, source_guards.hold_at_promote(findings, row.get("entity_kind")))

    # An NGO is not a funder, and the two kinds reach different tables through
    # different resolvers. Nothing below this line is shared but the report.
    if row.get("entity_kind") == "org":
        await _promote_org(conn, row, findings, report, asking)
    else:
        await _promote_funder(conn, row, findings, report, asking)
    unsettled(report, row["findings"] if isinstance(row["findings"], list) else [])
    report.pop("_raw", None)
    # Ten findings citing the same unresolvable state is one problem, not ten.
    report["held"] = list(dict.fromkeys(report["held"]))
    report["conflicts"] = list(dict.fromkeys(report["conflicts"]))
    return report


def now() -> datetime:
    return datetime.now(UTC)
