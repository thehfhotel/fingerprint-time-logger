"""
Unit tests for the monthly report's lateness helpers.

Pins the tier thresholds the UI legend and payroll rely on:
  < 5   → tier 0 (on-time / grace)
  5–14  → tier 1 (late)
  15–29 → tier 2 (late, minutes surfaced)
  >= 30 → tier 3 (severe)
"""

from datetime import datetime

from app.api.consolidated_attendance import (
    LATE_GRACE_MINUTES,
    LATE_NOTE_MINUTES,
    LATE_SEVERE_MINUTES,
    _late_minutes,
    _late_tier,
)
from app.utils.timezone import BANGKOK_TZ


def _bkk(hour, minute, second=0):
    return datetime(2026, 5, 14, hour, minute, second, tzinfo=BANGKOK_TZ)


SHIFT_START = _bkk(8, 0)


class TestLateMinutes:
    def test_no_punch_is_zero(self):
        assert _late_minutes(None, SHIFT_START) == 0

    def test_early_punch_is_zero(self):
        assert _late_minutes(_bkk(7, 55), SHIFT_START) == 0

    def test_exactly_on_start_is_zero(self):
        assert _late_minutes(_bkk(8, 0), SHIFT_START) == 0

    def test_floors_to_whole_minutes(self):
        # 08:08:59 is 8 minutes and change after start → floor to 8.
        assert _late_minutes(_bkk(8, 8, 59), SHIFT_START) == 8

    def test_counts_full_minutes(self):
        assert _late_minutes(_bkk(8, 45), SHIFT_START) == 45


class TestLateTier:
    def test_grace_band(self):
        assert _late_tier(0) == 0
        assert _late_tier(4) == 0

    def test_late_band(self):
        assert _late_tier(5) == 1
        assert _late_tier(14) == 1

    def test_late_with_minutes_band(self):
        assert _late_tier(15) == 2
        assert _late_tier(29) == 2

    def test_severe_band(self):
        assert _late_tier(30) == 3
        assert _late_tier(180) == 3

    def test_thresholds_are_stable(self):
        assert (LATE_GRACE_MINUTES, LATE_NOTE_MINUTES, LATE_SEVERE_MINUTES) == (5, 15, 30)
