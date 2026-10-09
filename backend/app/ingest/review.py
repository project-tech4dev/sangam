"""What the Import review card shows for one researched organisation, in words staff read."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.agent.tools.sql.catalog import CATALOG
from app.ingest.expectations import CONCEPTS
from app.ingest.research_records import to_inr
from app.ingest.staff_sources import SOURCE_URL_PREFIX

# A finding's bookkeeping, as opposed to what it says.
_META = {"concept", "evidence", "source_url", "source_name", "confidence", "basis", "source_type",
         "evidence_tier", "as_of", "aliases", "check_method", "notes", "domain", "theme", "classified_by",
         "classification_note", "designation", "is_ongoing", "fiscal_year"}
_ACRONYMS = {"csr": "CSR", "cin": "CIN", "pan": "PAN", "fcra": "FCRA", "url": "URL", "fy": "FY",
             "rfp": "RFP", "ngo": "NGO", "cso": "CSO", "12a": "12A", "80g": "80G", "inr": "", "id": "ID"}
_NOT_MONEY = ("pct", "percent", "share", "ratio", "lat", "lon", "count", "months", "year")
CHOICE_WORDS = {"keep": "Keep what Sangam has", "update": "Use the new one", "new": "Add it separately",
                "skip": "Skip"}


def words(name: str) -> str:
    """A column or field name as a phrase: `csr_obligation_inr` -> `CSR obligation`."""
    parts = [_ACRONYMS.get(p, p) for p in name.split("_")]
    text = " ".join(p for p in parts if p)
    return text[:1].upper() + text[1:]


_CODE = re.compile(r"^[a-z0-9_]{1,30}$")


def code_words(value: Any) -> Any:
    """An enum's code as words (`corporate_csr` -> `Corporate CSR`); anything else unchanged."""
    return words(value) if isinstance(value, str) and _CODE.match(value) else value


def topic(concept: str) -> str:
    spec = CONCEPTS.get(concept)
    return spec.title if spec else words(concept)


def _topic_of_table(table: str) -> str:
    return next((spec.title for spec in CONCEPTS.values() if spec.table == table), words(table))


def _money_columns(table: str) -> set[str]:
    spec = CATALOG.get(table)
    if spec is None:
        return set()
    return {c.name for c in spec.columns if c.type == "numeric" and not any(w in c.name for w in _NOT_MONEY)}


def _fact(key: str, v: Any) -> dict[str, Any] | None:
    """One value as a labelled fact. Amounts are INR numbers, for the frontend's one formatter."""
    if isinstance(v, dict):
        inr = to_inr(v)
        return {"label": words(key), "value": inr, "money": True} if inr is not None else None
    if isinstance(v, bool) or v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return {"label": words(key), "value": v, "money": False}
    if isinstance(v, list):
        shown = ", ".join(str(x) for x in v if isinstance(x, (str, int, float)))
        return {"label": None, "value": shown, "money": False} if shown else None
    text = code_words(str(v))
    return {"label": None, "value": text if len(text) <= 120 else text[:119] + "…", "money": False}


def facts(finding: dict[str, Any]) -> list[dict[str, Any]]:
    """What a finding says, field by field, without its bookkeeping."""
    return [f for k, v in finding.items() if k not in _META and (f := _fact(k, v))]


def tag(finding: dict[str, Any]) -> str:
    """confirmed: a document or registry states it; self_reported: the organisation's own word, or a listing."""
    tier = finding.get("evidence_tier")
    if tier:
        return "confirmed" if tier == "evidenced" else "self_reported"
    if finding.get("source_type") == "registry":
        return "confirmed"
    # A funder's finding has no tier: a government site, a staff filing export or a published PDF is a document.
    url = urlparse(finding.get("source_url") or "")
    host = url.hostname or ""
    staff = (finding.get("source_url") or "").startswith(SOURCE_URL_PREFIX)
    documented = staff or host.endswith((".gov.in", ".nic.in")) or url.path.lower().endswith(".pdf")
    return "confirmed" if documented else "self_reported"


def answers(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Every finding, the organisation's identity first, then one per topic before any second one."""
    found = [f for f in row.get("findings") or [] if isinstance(f, dict) and f.get("concept")]
    seen: dict[str, int] = {}
    ranked = []
    for i, f in enumerate(found):
        c = f["concept"]
        seen[c] = seen.get(c, 0) + 1
        ranked.append((c not in ("identity", "org_identity"), seen[c], i, f))
    return [
        {"concept": f["concept"], "topic": topic(f["concept"]), "year": f.get("fiscal_year"), "facts": facts(f),
         "tag": tag(f),
         "quote": f.get("evidence") or "", "source_url": f.get("source_url") or "",
         "source_name": f.get("source_name") or urlparse(f.get("source_url") or "").hostname or ""}
        for *_, f in sorted(ranked, key=lambda t: t[:3])
    ]


def missing(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Topics looked for and not got: not mentioned where read, couldn't read where blocked."""
    found = {f.get("concept") for f in row.get("findings") or [] if isinstance(f, dict)}
    out: dict[str, dict[str, Any]] = {}
    for g in row.get("gaps") or []:
        c = g.get("concept")
        if not c or c in found or g.get("field"):
            continue
        blocked = g.get("reason") == "blocked"
        if c in out and not blocked:
            continue
        out[c] = {"concept": c, "topic": topic(c), "tag": "couldnt_read" if blocked else "not_mentioned",
                  "detail": g.get("detail") or ""}
    return list(out.values())


def question(q: dict[str, Any]) -> dict[str, Any]:
    """A promotion question with its table and columns put into words; the id is unchanged."""
    money = _money_columns(q.get("table", ""))
    fields = [
        {"label": words(col), "old": code_words(c.get("old")), "new": code_words(c.get("new")), "money": col in money}
        for col, c in (q.get("changes") or {}).items()
    ]
    return {"id": q["id"], "case": q.get("case"), "topic": _topic_of_table(q.get("table", "")),
            "about": q.get("label") or "", "fields": fields, "stored_as_of": q.get("stored_as_of"),
            "new_as_of": q.get("new_as_of"), "stored_name": q.get("stored_name"), "new_name": q.get("new_name"),
            "choices": [{"value": c, "label": CHOICE_WORDS.get(c, words(c))} for c in q.get("choices", [])]}
