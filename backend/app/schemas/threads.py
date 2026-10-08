from __future__ import annotations

from datetime import datetime
from typing import Any

from app.schemas.common import ReadModel


class ThreadOut(ReadModel):
    thread_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class ThreadMessagesOut(ReadModel):
    thread_id: str
    # AG-UI messages, camelCase as the chat client reads them (toolCalls, toolCallId).
    messages: list[dict[str, Any]]
