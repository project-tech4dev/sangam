"""A fact's colour comes from where it came from, and nothing else changes it. Pure."""

from __future__ import annotations

from typing import Literal

Origin = Literal["registry", "vault", "web", "you_said", "derived"]
Tier = Literal["green", "amber", "said"]

ORIGINS: tuple[Origin, ...] = ("registry", "vault", "web", "you_said", "derived")

_TIER: dict[str, Tier] = {"registry": "green", "vault": "green", "web": "amber", "you_said": "said", "derived": "amber"}


def tier(origin: str) -> Tier:
    """Registry rows and quoted Doc Vault pages are green; the web and Sangam's own working are amber."""
    if origin not in _TIER:
        raise ValueError(f"no origin {origin!r}")
    return _TIER[origin]


def rank(t: str) -> int:
    """Higher is stronger; two facts disagree only at the same rank."""
    return {"green": 2, "said": 2, "amber": 1}.get(t, 0)
