"""Keyset cursors round-trip; a tampered cursor is refused, not guessed at."""

import pytest

from app.repositories import keyset


def test_round_trip():
    values = (0.9, 0.95, "2026-10-01", 42)
    assert keyset.decode(keyset.encode(values)) == values


def test_a_bad_cursor_raises():
    with pytest.raises(ValueError):
        keyset.decode("not-a-cursor")


def test_a_cursor_that_is_not_a_list_is_a_bad_cursor():
    import base64

    with pytest.raises(ValueError):
        keyset.decode(base64.urlsafe_b64encode(b"5").decode())
