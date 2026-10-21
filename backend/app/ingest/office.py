"""Text from Word and Excel files, for an upload's content_md and the vault reader. Pure: bytes in, text out."""

from __future__ import annotations

import io

SHEET_ROWS = 200  # an upload's text keeps this many rows a sheet; the vault reader pages the rest


def docx_paragraphs(data: bytes) -> list[str]:
    """Each paragraph, and each table row as `a | b | c`, in document order; empty ones dropped."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    out: list[str] = []
    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(block, doc).text.strip()
            if text:
                out.append(text)
        elif tag == "tbl":
            for row in Table(block, doc).rows:
                # A merged cell repeats across the row as the same element; keep it once.
                cells = list({id(c._tc): c.text.strip() for c in row.cells}.values())
                if any(cells):
                    out.append(" | ".join(cells))
    return out


def docx_range(data: bytes, start: int = 1, end: int | None = None) -> tuple[str, int]:
    """(paragraphs start..end, each led by [para N]; how many the file has), so a Word file pages like a PDF."""
    paras = docx_paragraphs(data)
    last = min(end or len(paras), len(paras))
    return "\n".join(f"[para {n}] {paras[n - 1]}" for n in range(max(start, 1), last + 1)), len(paras)


def xlsx_markdown(data: bytes) -> str:
    """Every sheet as a heading and its first rows, cells joined by `|`."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for ws in wb.worksheets:
            lines.append(f"## {ws.title}")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= SHEET_ROWS:
                    lines.append(f"… first {SHEET_ROWS} rows only")
                    break
                cells = ["" if v is None else str(v).strip() for v in row]
                if any(cells):
                    lines.append(" | ".join(cells))
    finally:
        wb.close()
    return "\n".join(lines)
