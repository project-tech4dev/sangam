"""Typed application settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import ValidationInfo, field_validator
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

    # For work that needs no reasoning: filling a fixed record shape from one
    # article, and the catalog-writer subagent, which calls two tools and
    # formats their output. Empty falls back to `model`, so an unset value
    # changes nothing. Point it at the cheapest model of the same provider.
    utility_model: str = ""

    # The funder-assessor subagent, run once per candidate funder in a shortlist, so
    # ~25 calls per question. Empty falls back to `model`. A cheaper one cuts the cost.
    assessor_model: str = ""

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

    # Where download_file saves what it fetches, and read_pdf reads from.
    downloads_dir: str = "/tmp/sangam-downloads"

    # Supabase Storage: the provenance archive for fetched documents and the
    # Doc Vault for org uploads. The service-role key bypasses RLS, so it never
    # reaches the browser. Both empty = archiving is skipped and the upload
    # routes return 503; nothing else changes.
    supabase_url: str = ""
    supabase_service_key: str = ""

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
    sql_timeout_ms: int = 5_000
    sql_max_rows: int = 50
    sql_max_attempts: int = 5
    # A cheap second opinion on each SQL answer (grain, filters, false zeros, numbers). Empty disables it;
    # it is a real extra model call per SQL turn, so point it at the cheapest model of a provider you.
    sql_audit_model: str = ""

    # Graph steps per turn, not tool calls: every middleware hook is its own node, so one model-then-tool
    # cycle costs several. Bound in build_agent(); LangGraph's own default is 25, which a SQL turn exceeds.
    # Each subagent gets its OWN budget of this many steps — the counter is per graph invocation, not
    # shared with the parent, so launching more researchers does not eat the supervisor's steps.
    recursion_limit: int = 200

    # How many organisations Sangam Import researches at once. It is not a ceiling on how many you can
    # ASK for: above this the agent works in waves until the list is done. Raise it and raise
    # db_pool_max_size with it — each researcher holds a pooled connection while its tools run.
    # A test pins this number against the one written into app/ingest/instructions.md.
    max_parallel_research: int = 8
    # Connections this process may open. The ceiling is the database's, not ours: the Supabase project
    # allows 60 with 3 reserved, and a deployed backend runs several instances, so 10 leaves room for
    # roughly four of them plus the dashboard. The checkpointer writes on every graph step and shares
    # this pool, which is why the concurrency gates below sit under it rather than at it.
    db_pool_max_size: int = 10
    allowed_origins: str = "http://localhost:3000"
    # Vercel gives every preview deployment a fresh hostname, so an exact-match list cannot cover them. Set
    # a regex to admit them, e.g. ^https://sangam-[a-z0-9-]+\.vercel\.app$ Anchor it: an unanchored pattern.
    allowed_origin_regex: str = ""

    @field_validator("max_parallel_research", "db_pool_max_size", mode="before")
    @classmethod
    def _blank_means_default(cls, v: object, info: ValidationInfo) -> object:
        """An unset variable reaches us as "", not as missing.

        docker-compose forwards `${DB_POOL_MAX_SIZE:-}` as an empty string, and
        a hand-edited .env line with nothing after the `=` does the same. Either
        one made an int field refuse to parse and the container refuse to boot.
        """
        if isinstance(v, str) and not v.strip():
            return cls.model_fields[info.field_name].default
        return v

    @property
    def db_gate_slots(self) -> int:
        """Concurrent DB-holding tasks allowed, under the pool rather than at it.

        The checkpointer writes on every graph step through the same pool, so a
        gate set to the pool size starves it and the whole graph stalls.
        """
        return max(2, self.db_pool_max_size - 3)

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
    def storage_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
