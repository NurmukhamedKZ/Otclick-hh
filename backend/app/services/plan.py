"""Compatibility access policy for the non-commercial self-hosted build.

The database still contains historical plan/payment columns from older migrations,
but runtime features no longer depend on them. Every authenticated user has the
same capabilities and there are no commercial quotas or paid feature gates.

Keep this module temporarily as a small compatibility surface for callers that
still ask for access/limits while the surrounding code is simplified.
"""

from __future__ import annotations

from typing import Literal, TypedDict

Mode = Literal["auto"]


class Limits(TypedDict):
    mode: Mode
    daily: int | None
    total: int | None


_UNLIMITED: Limits = {"mode": "auto", "daily": None, "total": None}


def has_access(profile: dict | None = None) -> bool:
    """All authenticated users have access; profile state is intentionally ignored."""
    return True


def limits_for(profile: dict | None = None) -> Limits:
    """Return the single non-commercial policy: autonomous mode, no quota."""
    return dict(_UNLIMITED)


async def check_access(user_id: str) -> bool:
    """Compatibility helper for legacy callers; user_id is not plan-gated."""
    return True


async def get_limits(user_id: str) -> Limits:
    """Compatibility helper returning the same unlimited policy for every user."""
    return dict(_UNLIMITED)


def filter_paid(user_ids: list[str]) -> list[str]:
    """Legacy name kept temporarily: no paid filtering is performed."""
    return list(user_ids)
