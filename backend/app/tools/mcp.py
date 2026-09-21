"""MCP tool loading via langchain-mcp-adapters.

GitHub is configured from GITHUB_PAT; arbitrary extra servers come from the
MCP_SERVERS setting so new integrations need zero code changes.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools as tools_from_session

CONNECT_ATTEMPTS = 3
CONNECT_RETRY_SECONDS = 3

# Servers whose tools share state between calls (an open browser, a logged-in
# session). These need ONE persistent MCP session for the app's lifetime;
# the default get_tools() path opens a fresh session per tool call, which
# would give the browser amnesia between navigate and snapshot.
STATEFUL_SERVERS = {"playwright"}

# Tools excluded per server regardless of other settings. run_code_unsafe
# executes arbitrary code in the playwright container — far more power than
# the agent needs to browse.
SERVER_DENYLIST: dict[str, set[str]] = {
    "playwright": {"browser_run_code_unsafe"},
}

from app.config import Settings

logger = logging.getLogger(__name__)


def build_server_config(settings: Settings) -> dict[str, dict[str, Any]]:
    servers: dict[str, dict[str, Any]] = {}
    if settings.github_pat:
        servers["github"] = {
            "transport": "streamable_http",
            "url": settings.github_mcp_url,
            "headers": {"Authorization": f"Bearer {settings.github_pat}"},
        }
    if settings.playwright_mcp_url:
        servers["playwright"] = {
            "transport": "streamable_http",
            "url": settings.playwright_mcp_url,
        }
    servers.update(settings.mcp_servers)
    return servers


async def load_mcp_tools(settings: Settings, stack: AsyncExitStack) -> list[Any]:
    """Load tools from all configured MCP servers.

    Persistent sessions for stateful servers are opened on `stack`, which the
    caller (the FastAPI lifespan) keeps alive for the life of the app.
    """
    servers = build_server_config(settings)
    if not servers:
        return []

    client = MultiServerMCPClient(servers)
    tools: list[Any] = []
    github_allowlist = set(settings.github_allowlist)

    for name in servers:
        server_tools = None
        # Retry: sibling containers (e.g. the playwright service) may still be
        # starting when the backend boots.
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                if name in STATEFUL_SERVERS:
                    session = await stack.enter_async_context(client.session(name))
                    server_tools = await tools_from_session(session)
                else:
                    server_tools = await client.get_tools(server_name=name)
                break
            except Exception:
                if attempt == CONNECT_ATTEMPTS:
                    logger.exception("Failed to load MCP tools from server %r; skipping", name)
                else:
                    logger.warning(
                        "MCP server %r not reachable (attempt %d/%d), retrying in %ds",
                        name, attempt, CONNECT_ATTEMPTS, CONNECT_RETRY_SECONDS,
                    )
                    await asyncio.sleep(CONNECT_RETRY_SECONDS)
        if server_tools is None:
            continue
        if name == "github":
            skipped = [t.name for t in server_tools if t.name not in github_allowlist]
            server_tools = [t for t in server_tools if t.name in github_allowlist]
            if skipped:
                logger.info("GitHub MCP: %d tools excluded by allowlist", len(skipped))
        denied = SERVER_DENYLIST.get(name, set())
        if denied:
            server_tools = [t for t in server_tools if t.name not in denied]
        tools.extend(server_tools)
        logger.info("MCP server %r: loaded %d tools", name, len(server_tools))

    return tools
