"""Keyset cursors for lists that grow while you read them (spec section 5): the last row's sort values."""

from __future__ import annotations

import base64
import json


def encode(values: tuple) -> str:
    return base64.urlsafe_b64encode(json.dumps(list(values), default=str).encode()).decode()


def decode(cursor: str) -> tuple:
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("bad cursor") from exc
    if not isinstance(values, list):
        raise ValueError("bad cursor")  # noqa: TRY004 - every bad cursor is one ValueError, a 400 at the route
    return tuple(values)
