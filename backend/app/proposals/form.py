"""The funder's form as headings to fill: one model call reads it, code keeps only what it can check."""

from __future__ import annotations

import asyncio
import base64
import io
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.integrations import storage
from app.proposals import rubric
from app.repositories import proposals as repo

PROMPT = (Path(__file__).parent / "prompts" / "form_reader.md").read_text(encoding="utf-8")
MAX_PAGES = 100  # the most PDF pages Anthropic reads as pages
MAX_BYTES = 32 * 1024 * 1024
LABEL, ASK, NUMBER = 200, 1000, 20
_BRACKETS = str.maketrans("[]", "()")  # a form's words must not close an [Add: …] or [You fill: …] mark


class Unreadable(Exception):
    """The chosen form can't be read: said to the person as it is."""


class Limit(BaseModel):
    n: int = Field(gt=0, description="The number the form gives, such as 1500.")
    unit: Literal["chars", "words", "pages"]


class Heading(BaseModel):
    number: str | None = Field(None, description='The form\'s own numbering, such as "5", "3(b)" or "Annex 3".')
    label: str = Field(description="The heading as the form writes it, without its number or limit.")
    ask: str = Field("", description="What the form asks under the heading, in its own words, shortened if long.")
    kind: Literal["prose", "field", "table", "attach", "skip"] = Field(
        description="prose: written paragraphs. field: a short fact such as a PAN number. table: a grid to fill. "
                    "attach: a document to attach or sign. skip: instructions, terms, covers.")
    limit: Limit | None = Field(None, description="The length the form allows, or null when it states none.")
    uses: list[str] = Field(default_factory=list, description="Codes of Sangam's parts that answer it; [] if none.")
    only_if: Literal["earlier_phase"] | None = Field(
        None, description='"earlier_phase" when only a second-phase applicant answers it.')


class Outline(BaseModel):
    headings: list[Heading] = Field(description="Every heading, in the form's order.")


def _clean(text: str | None, cap: int) -> str:
    return " ".join((text or "").translate(_BRACKETS).split())[:cap].strip()


def check(outline: Outline, codes: set[str]) -> list[dict[str, Any]]:
    """The headings as kept: coded T1…Tn in order, capped, only prose drawing on this proposal's parts. Pure."""
    out: list[dict[str, Any]] = []
    for h in outline.headings:
        label = _clean(h.label, LABEL)
        if not label:
            if out:
                out[-1]["ask"] = _clean(f"{out[-1]['ask']} {h.ask}", ASK)
            continue
        out.append({"code": f"T{len(out) + 1}", "number": _clean(h.number, NUMBER).rstrip(".:") or None,
                    "label": label, "ask": _clean(h.ask, ASK), "kind": h.kind,
                    "limit": h.limit.model_dump() if h.limit else None,
                    "uses": [c for c in dict.fromkeys(h.uses) if c in codes] if h.kind == "prose" else [],
                    "only_if": h.only_if})
    return out


def _first_pages(data: bytes) -> tuple[bytes, bool]:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) <= MAX_PAGES:
        return data, False
    writer = PdfWriter()
    for page in reader.pages[:MAX_PAGES]:
        writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue(), True


def content(title: str, suffix: str, data: bytes) -> list[dict[str, Any]]:
    """The message holding the form: a PDF as a document, so pages that are only images are read too."""
    intro = {"type": "text", "text": f"The funder's form, {title}:"}
    if suffix == ".pdf":
        return [intro, {"type": "file", "base64": base64.b64encode(data).decode(), "mime_type": "application/pdf"}]
    if suffix == ".docx":
        from app.ingest import office

        return [intro, {"type": "text", "text": "\n".join(office.docx_paragraphs(data))}]
    raise Unreadable("The funder's form must be a PDF or Word file.")


async def read(pool: Any, template: dict[str, Any], org_id: int, sections: list[rubric.Section],
               model: Any) -> dict[str, Any]:
    """The form's outline as `work.template.outline` keeps it. Raises Unreadable; a model failure propagates."""
    doc = await repo.form_file(pool, template["document_id"], org_id)
    parts = storage.split((doc or {}).get("storage_path") or "")
    if parts is None:
        raise Unreadable("Sangam has no copy of the funder's form. Upload it again in step 2.")
    suffix = Path(parts[1]).suffix.lower()
    data = await storage.download(*parts, max_bytes=MAX_BYTES)
    if data is None:
        raise Unreadable("The funder's form could not be downloaded. Try again.")
    cut = False
    if suffix == ".pdf":
        data, cut = await asyncio.to_thread(_first_pages, data)
    title = doc.get("title") or "the funder's form"
    listed = "\n".join(f"- {s.code} {s.label}: {s.question}" for s in sections)
    found = await model.with_structured_output(Outline).ainvoke(
        [SystemMessage(PROMPT.replace("{{PARTS}}", listed)), HumanMessage(content(title, suffix, data))])
    headings = check(found, {s.code for s in sections})
    if not any(h["kind"] == "prose" for h in headings):
        raise Unreadable(f"{title} has no questions to answer in writing.")
    return {"document_id": template["document_id"],
            "title": re.sub(r"\.(pdf|docx)$", "", title, flags=re.IGNORECASE), "headings": headings, "pages_cut": cut, "read_at": datetime.now(UTC).isoformat()}
