"""One text per version of a page, so a re-spaced or re-encoded copy fingerprints the same."""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Zero-width space, non-joiner, joiner, word joiner, byte-order mark, and the soft hyphen.
_INVISIBLE = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD))
_WHITESPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """NFC, invisible characters dropped, whitespace collapsed; case is kept, since it can carry meaning."""
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    return _WHITESPACE.sub(" ", text).strip()


def text_hash(text: str) -> str:
    return bytes_hash(normalise(text).encode())


def bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
