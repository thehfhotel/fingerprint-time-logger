"""
Bangkok timezone helpers.

Storage layer is UTC; user-facing output must be Bangkok-local (UTC+7) per
PLAN.md §1. This module is the single source of truth for the offset constant
and the conversion helper to avoid drift across modules.
"""

from datetime import datetime, timedelta, timezone

# Bangkok timezone (UTC+7). Used for all user-facing date/time output.
BANGKOK_TZ = timezone(timedelta(hours=7))


def to_bangkok(dt: datetime) -> datetime:
    """
    Convert a UTC-stored datetime (naive or aware) to Bangkok timezone.

    Naive datetimes are assumed to be UTC (the storage convention) and
    promoted to UTC-aware before conversion.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BANGKOK_TZ)
