"""India CSR, read through the site's own WordPress REST API.

robots.txt disallows only /wp-admin/. Using /wp-json returns the same posts as
JSON, which means no HTML parsing and far fewer requests than crawling pages.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.ingest.adapters._http import content_hash, get_json

API = "https://indiacsr.in/wp-json/wp/v2/posts"
DEFAULT_QUERY = "CSR spend crore"
_TAGS = re.compile(r"<[^>]+>")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub(" ", html or "")).strip()


async def fetch(query: str = DEFAULT_QUERY, limit: int = 10000) -> list[dict[str, Any]]:
    """Raw articles. Extraction into typed records happens in extractor.py."""
    posts = await get_json(
        API,
        {
            "search": query,
            "per_page": min(limit, 20000),
            "orderby": "date",
            "_fields": "id,date,link,title,excerpt,content",
        },
    )
    items = []
    for p in posts:
        title = _text(p.get("title", {}).get("rendered", ""))
        body = _text(p.get("content", {}).get("rendered", ""))[:6000]
        items.append(
            {
                "id": p["id"],
                "title": title,
                "url": p["link"],
                "published": p.get("date"),
                "text": body,
                "content_hash": content_hash(title + body),
                "source_name": "indiacsr",
                "fetched_at": datetime.now(UTC),
            }
        )
    return items
