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

    # Knowledge graph (Graphiti + Neo4j). Graph features activate only when NEO4J_URI is set AND an OpenAI
    # key exists (Graphiti's extraction and embeddings default to OpenAI; Anthropic has no embedding.
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    openai_api_key: str = ""

    # Langfuse tracing (agent runs → traces/generations/costs). Enabled only
    # when both keys are set; the SDK reads LANGFUSE_* from the environment.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Optional tool integrations — all disabled when empty.
    tavily_api_key: str = ""
    github_pat: str = ""
    github_mcp_url: str = "https://api.githubcopilot.com/mcp/"
    playwright_mcp_url: str = ""
    # Extra MCP servers as JSON in langchain-mcp-adapters connection format.
    mcp_servers: dict[str, Any] = {}
    github_tool_allowlist: str = ""

    # Text-to-SQL tool (db_query). See docs/SQL_AGENT.md. sql_reader_role is the NOLOGIN role the query runs
    # as via SET LOCAL ROLE; empty disables that guard and leaves only the validator and the read-only.
    sql_reader_role: str = "sangam_reader"
    sql_timeout_ms: int = 5_000
    sql_max_rows: int = 50
    sql_max_attempts: int = 5
    # A cheap second opinion on each SQL answer (grain, filters, false zeros, numbers). Empty disables it;
    # it is a real extra model call per SQL turn, so point it at the cheapest model of a provider you.
    sql_audit_model: str = ""

    # Graph steps per turn, not tool calls: every middleware hook is its own node, so one model-then-tool
    # cycle costs several. Bound in build_agent(); LangGraph's own default is 25, which a SQL turn exceeds.
    recursion_limit: int = 200
    allowed_origins: str = "http://localhost:3000"
    # Vercel gives every preview deployment a fresh hostname, so an exact-match list cannot cover them. Set
    # a regex to admit them, e.g. ^https://sangam-[a-z0-9-]+\.vercel\.app$ Anchor it: an unanchored pattern.
    allowed_origin_regex: str = ""

    @property
    def github_allowlist(self) -> list[str]:
        if self.github_tool_allowlist.strip():
            return [t.strip() for t in self.github_tool_allowlist.split(",") if t.strip()]
        return DEFAULT_GITHUB_TOOL_ALLOWLIST

    @property
    def graph_enabled(self) -> bool:
        return bool(self.neo4j_uri and self.openai_api_key)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
