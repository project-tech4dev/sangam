"""Step 1's requirements, read from the saved Funder Match detail so they say what the match judged.

Pure: the caller loads the detail. Text here is shown on screen, so it carries no markers.
"""

from __future__ import annotations

import re
from typing import Any

from app.matching.rules import ITEMS, SECTION_135_TYPES

BAR = "The funder's own bar"
_BAR_HEAD = re.compile(r"^[^:]*:\s*")
CLIP = 240

# match item -> (requirement shown, what the funder asks); CSR Form 1 is law for Section 135 money, so a No stops.
REQUIREMENTS: dict[str, tuple[str, str]] = {
    "12a": ("12A registration", "Registered under section 12A of the Income Tax Act"),
    "80g": ("80G registration", "Registered under section 80G, so donations are tax-exempt"),
    "csr1": ("CSR Form 1", "Registered with the MCA to receive CSR funds (CSR-1)"),
    "audits": ("Audited accounts", "Audited accounts for the last three years"),
}


def _clip(text: str) -> str:
    return text if len(text) <= CLIP else f"{text[:CLIP - 1].rstrip()}…"


def _criterion(detail: dict[str, Any], code: str) -> dict[str, Any] | None:
    return next((c for c in detail.get("criteria") or [] if c.get("code") == code), None)


def _on_record(key: str, parts: list[str], not_judged: list[str]) -> str:
    label = ITEMS[key][0]
    lines = [p for p in [*parts, *not_judged] if (p.startswith(label) if key != "audits" else "audit" in p.lower())]
    return "; ".join(dict.fromkeys(line.rstrip(".") for line in lines)) or "Nothing on record."


def build(detail: dict[str, Any], funder_type: str | None, section_135_bound: bool | None = None) -> dict[str, Any]:
    """{requirements, earlier_phase, cites} for a new proposal; each requirement is answered in step 1."""
    eligibility = _criterion(detail, "eligibility") or {}
    parts = [p for p in (eligibility.get("note") or "").split("; ") if p]
    not_judged = list(detail.get("not_judged") or [])
    csr = funder_type in SECTION_135_TYPES or bool(section_135_bound)

    keys = ["12a", "80g", *(["csr1"] if csr else []), "audits"]
    requirements = [
        {"key": k, "label": REQUIREMENTS[k][0], "rule": REQUIREMENTS[k][1],
         "on_record": _on_record(k, parts, not_judged), "hard": k == "csr1"}
        for k in keys
    ]
    bars = [_clip(_BAR_HEAD.sub("", line)) for line in not_judged if line.startswith(BAR)]
    requirements += [
        {"key": f"bar{i}", "label": "The funder's own requirement", "rule": text,
         "on_record": "Sangam does not check this one.", "hard": False}
        for i, text in enumerate(bars, 1)
    ]
    relationship = _criterion(detail, "relationship") or {}
    return {
        "requirements": requirements,
        "earlier_phase": bool(relationship.get("points")),
        "cites": list(eligibility.get("cites") or []),
    }
