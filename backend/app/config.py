"""Typed application settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

# GitHub MCP tools the agent may use when no explicit allowlist is configured.
# Kept from deep-agent-app: read/inspect + propose-PR only, never merge/delete.
DEFAULT_GITHUB_TOOL_ALLOWLIST = [
    "get_me",
    "search_repositories",
    "search_code",
    "search_issues",
    "get_file_contents",
    "list_branches",
    "list_commits",
    "list_issues",
    "issue_read",
    "list_pull_requests",
    "pull_request_read",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "provider:model_name", resolved via langchain init_chat_model.
    model: str = "anthropic:claude-sonnet-5"

    # Postgres connection string; holds app data AND LangGraph checkpoints.
    database_url: str = "postgresql://sangam:sangam@localhost:5433/sangam"

    # Knowledge graph (Graphiti + FalkorDB). Graph features activate only when
    # FALKORDB_HOST is set AND an OpenAI key exists (Graphiti's extraction and
    # embeddings default to OpenAI; Anthropic has no embedding models).
    falkordb_host: str = ""
    falkordb_port: int = 6379
    openai_api_key: str = ""

    # Optional tool integrations — all disabled when empty.
    tavily_api_key: str = ""
    github_pat: str = ""
    github_mcp_url: str = "https://api.githubcopilot.com/mcp/"
    playwright_mcp_url: str = ""
    # Extra MCP servers as JSON in langchain-mcp-adapters connection format.
    mcp_servers: dict[str, Any] = {}
    github_tool_allowlist: str = ""

    downloads_dir: str = "downloads"
    recursion_limit: int = 100
    allowed_origins: str = "http://localhost:3000"

    @property
    def github_allowlist(self) -> list[str]:
        if self.github_tool_allowlist.strip():
            return [t.strip() for t in self.github_tool_allowlist.split(",") if t.strip()]
        return DEFAULT_GITHUB_TOOL_ALLOWLIST

    @property
    def graph_enabled(self) -> bool:
        return bool(self.falkordb_host and self.openai_api_key)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
