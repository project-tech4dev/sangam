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

    # "provider:model_name", resolved via langchain init_chat_model. Blank or unset always means the default
    # here. Three tiers, by how hard the work is:
    # MODEL reasons (Ask Sangam, the Import supervisor), so it is the strongest.
    model: str = "anthropic:claude-opus-5-5"

    # The entity-researcher: long pages and evidence judgements, up to MAX_PARALLEL_RESEARCH at once,
    # so most of an import's tokens.
    research_model: str = "anthropic:claude-sonnet-5-5"

    # Work that needs no reasoning: a fixed record from one article, the catalog-writer (two tools, a
    # report) and the workbook-reader (one tool, a list of names).
    utility_model: str = "anthropic:claude-haiku-4-5"

    # Local only: also accept `Authorization: Bearer dev` as the seeded dev user. Never set when deployed.
    dev_auth: bool = False

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
    # supabase_url also turns auth on: set, requests must carry a Supabase
    # access token; empty keeps the single seeded dev user.
    supabase_url: str = ""
    supabase_service_key: str = ""

    # Optional tool integrations — all disabled when empty.
    tavily_api_key: str = ""

    # Media & Signals (features-plans/signals/…, D5). The bars decide what is listed and what is public; they live
    # here, never on a screen. Costs are per Tavily advanced search and per Haiku classification.
    news_listed_match: float = 0.6
    news_listed_confidence: float = 0.8
    news_public_match: float = 0.7
    news_public_confidence: float = 0.9
    news_negative_match: float = 0.9
    news_negative_confidence: float = 0.95
    news_topic_match: float = 0.75
    news_search_cost_usd: float = 0.016
    news_classify_cost_usd: float = 0.004
    news_links_per_search: int = 10  # the 11 Oct trial: about 1,020 classifications from 110 searches
    news_parallel_searches: int = 4
    news_parallel_classify: int = 8
    news_max_classify: int = 2000  # per run; the rest wait for the next run
    # The verifier re-reads borderline matches before they are stored. 0 checks means off; 40 is the planned value.
    news_verify_max: int = 0
    news_verify_low: float = 0.35  # below this a match is plainly someone else, not worth a read
    news_parallel_verify: int = 2
    news_verify_seconds: int = 600  # per run, so a pull still ends inside the 1800 s function limit
    news_verify_page_limit: int = 3
    news_verify_call_limit: int = 8
    news_verify_cost_usd: float = 0.08
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
    # A cheap second opinion on each SQL answer (grain, filters, false zeros, numbers). `off` disables it;
    # it is a real extra model call per SQL turn, so it runs on the cheapest tier.
    sql_audit_model: str = "anthropic:claude-haiku-4-5"

    # Graph steps per turn, not tool calls: every middleware hook is its own node, so one model-then-tool
    # cycle costs several. Bound in build_agent(); LangGraph's own default is 25, which a SQL turn exceeds.
    # Each subagent gets its OWN budget of this many steps — the counter is per graph invocation, not
    # shared with the parent, so launching more researchers does not eat the supervisor's steps.
    recursion_limit: int = 200
    # Model calls one Ask question may make before it stops and says so. Trace 5bfdbc85 made 21; the target
    # is under 8. A cap, not a target: it ends a runaway turn long before recursion_limit does.
    ask_model_call_limit: int = 25

    # How many organisations Sangam Import researches at once. It is not a ceiling on how many you can
    # ASK for: above this the agent works in waves until the list is done. Raise it and raise
    # db_pool_max_size with it — each researcher holds a pooled connection while its tools run.
    # A test pins this number against the one written into app/ingest/instructions.md.
    max_parallel_research: int = 8
    # Optional hard stops per researcher run; None means no limit. Set, the reading tools refuse past this many
    # pages and it saves what it has, and the model-call cap ends a run that loops.
    research_page_limit: int | None = None
    research_model_call_limit: int | None = None
    # Connections this process may open. The ceiling is the database's, not ours: the Supabase project
    # allows 60 with 3 reserved, and a deployed backend runs several instances, so 10 leaves room for
    # roughly four of them plus the dashboard. The checkpointer writes on every graph step and shares
    # this pool, which is why the concurrency gates below sit under it rather than at it.
    db_pool_max_size: int = 10
    allowed_origins: str = "http://localhost:3000"
    # Vercel gives every preview deployment a fresh hostname, so an exact-match list cannot cover them. Set
    # a regex to admit them, e.g. ^https://sangam-[a-z0-9-]+\.vercel\.app$ Anchor it: an unanchored pattern.
    allowed_origin_regex: str = ""

    @field_validator(
        "model",
        "research_model",
        "utility_model",
        "sql_audit_model",
        "max_parallel_research", "research_page_limit", "research_model_call_limit", "ask_model_call_limit",
        "db_pool_max_size", mode="before"
    )
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

    @field_validator("sql_audit_model", mode="after")
    @classmethod
    def _off_disables_the_audit(cls, v: str) -> str:
        return "" if v.strip().lower() == "off" else v

    @property
    def db_gate_slots(self) -> int:
        """Concurrent DB-holding tasks allowed, under the pool rather than at it.

        The checkpointer writes on every graph step through the same pool, so a
        gate set to the pool size starves it and the whole graph stalls.
        """
        return max(2, self.db_pool_max_size - 3)

    @field_validator("dev_auth", mode="before")
    @classmethod
    def _empty_dev_auth_is_off(cls, value: object) -> object:
        return False if value == "" else value

    @property
    def github_allowlist(self) -> list[str]:
        if self.github_tool_allowlist.strip():
            return [t.strip() for t in self.github_tool_allowlist.split(",") if t.strip()]
        return DEFAULT_GITHUB_TOOL_ALLOWLIST

    @property
    def auth_enabled(self) -> bool:
        return bool(self.supabase_url)

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
