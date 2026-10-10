"""Where one Import run may read from: the person's answer to choose_sources, enforced on every tool that pulls."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage

CHOOSE = "choose_sources"
WEB_TOOLS = frozenset({"search_public_sources", "read_page", "fetch_document"})
STAFF_TOOLS = frozenset({"read_source_rows", "read_workbook"})
VAULT_TOOLS = frozenset({"list_vault_documents", "read_vault_document"})
LIBRARY_TOOLS = frozenset({"list_library_documents", "read_library_document"})
PULLING = WEB_TOOLS | STAFF_TOOLS | VAULT_TOOLS | LIBRARY_TOOLS


@dataclass(frozen=True)
class Sources:
    web: bool = True
    library: bool = False
    vault_org: int | None = None
    vault_docs: frozenset[int] = field(default_factory=frozenset)
    staff_docs: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def of(cls, artifact: dict[str, Any]) -> Sources:
        return cls(web=bool(artifact.get("web")), library=bool(artifact.get("library")),
                   vault_org=artifact.get("vault_org"), vault_docs=frozenset(artifact.get("vault_docs") or ()),
                   staff_docs=frozenset(artifact.get("staff_docs") or ()))

    def artifact(self) -> dict[str, Any]:
        return {"web": self.web, "library": self.library, "vault_org": self.vault_org,
                "vault_docs": sorted(self.vault_docs), "staff_docs": sorted(self.staff_docs)}


# A person who turns the card down still wants the research: public websites only.
WEB_ONLY = Sources(web=True)
# Set by the supervisor around each subagent it launches; a subagent outside one reads nothing.
CURRENT: ContextVar[Sources | None] = ContextVar("import_run_sources", default=None)


def chosen(messages: list[BaseMessage]) -> Sources | None:
    """The run's latest answered choose_sources, or None while it has not been answered."""
    for m in reversed(messages):
        if not isinstance(m, ToolMessage) or m.name != CHOOSE:
            continue
        if isinstance(m.artifact, dict):
            return Sources.of(m.artifact)
        if m.status == "error":  # the person rejected the card
            return WEB_ONLY
    return None


def _ids(value: Any) -> set[int] | None:
    if value is None:
        return None
    try:
        return {int(v) for v in (value if isinstance(value, list | tuple | set) else [value])}
    except (TypeError, ValueError):
        return set()


def refusal(sources: Sources | None, name: str, args: dict[str, Any]) -> str | None:
    """Why this run may not make this call, or None. Only PULLING tools are ever refused."""
    if name not in PULLING:
        return None
    if sources is None:
        return "REFUSED: no sources were chosen for this run. Read nothing; report that back."
    if name in WEB_TOOLS and not sources.web:
        return "REFUSED: the person chose not to read public websites in this run. Use the sources it allows."
    if name in LIBRARY_TOOLS and not sources.library:
        return "REFUSED: Sangam's library is not among this run's sources."
    if name in STAFF_TOOLS:
        asked = _ids(args.get("documents"))
        if not sources.staff_docs:
            return "REFUSED: no team spreadsheets were picked for this run."
        if not asked or not asked <= sources.staff_docs:
            return (f"REFUSED: pass documents= with the picked spreadsheets only: {sorted(sources.staff_docs)}.")
    if name == "list_vault_documents" and not sources.vault_docs:
        return "REFUSED: no Doc Vault files were picked for this run."
    if name == "read_vault_document" and int(args.get("document_id") or 0) not in sources.vault_docs:
        return f"REFUSED: only the picked Doc Vault files may be read: {sorted(sources.vault_docs)}."
    return None
