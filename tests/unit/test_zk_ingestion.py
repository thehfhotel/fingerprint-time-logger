"""
Regression suite for fix/zk-ingestion-loss ("missing fingerprint punches").

Locked spec: /private/tmp/claude-501/-Users-nut-fingerprint-time-logger/
a34fcde6-ec0f-4580-9761-7c64b1e43eef/scratchpad/fix-interfaces.md

Asserts the FIXED contracts CORE implements in app/services/zk_session.py:
  - `catch_up_now(full: bool = False) -> int` (module-level, locked entry point)
  - per-device (not global), now-capped watermark minus
    `zk_catchup_lookback_hours`; `full=True` bypasses the floor entirely
    (dedup only)
  - dedup/exists key is `(employee_badge_number, timestamp, punch_type)` on
    BOTH the catch-up and realtime (`_handle_punch`) paths
  - sanity rule (`ts.year < 2010` or `ts > now_bangkok + 1 day`) rejects with
    a logged `[zk_session.sanity] rejected badge=... ts=... reason=...`
    warning on BOTH paths — never a bare `continue`
  - `get_status_and_time() -> {"status": ..., "time": ...}` opens exactly
    one device connection

Adapted from the proven offline repro harness (fake pyzk conn objects,
temp-sqlite SessionLocal monkeypatching, frozen clock via patching
`zk_session.datetime`) at .../scratchpad/repro/. Drives catch-up scenarios
through the LOCKED module-level functions (`catch_up_now`, ``
get_status_and_time`) via the one-shot connect path (patching `zk_session.ZK`)
rather than private methods, so these tests don't depend on how CORE splits
`_catch_up`'s internals. `_stream`/`_handle_punch` are called directly since
their call signature is unaffected by the fix.

NOTE: at the time these tests were written, CORE's contracts were still
in-flight (parallel agent). Failures here that stem from
`catch_up_now`/`get_status_and_time` not yet accepting the new signature, or
from the old buggy watermark/dedup logic still being in place, are EXPECTED
until CORE's changes land — see the TESTS agent's report for the current
pass/fail breakdown.

Never touches a real device: `_no_real_device` (autouse, below) makes any
unpatched `zk_session.ZK(...)` construction raise immediately.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

BANGKOK = timezone(timedelta(hours=7))
UTC = timezone.utc


# ---------------------------------------------------------------------------
# fake pyzk objects — shapes match what zk_session.py reads
#   _handle_punch: att.timestamp, att.user_id, att.punch, att.status
#   _catch_up:     record.timestamp, record.user_id, record.punch, record.status
# ---------------------------------------------------------------------------
class FakeAtt:
    """One device attendance record (device stamps Bangkok-naive time)."""

    def __init__(self, user_id, timestamp: datetime, punch: int = 0, status: int = 1):
        self.user_id = user_id
        self.timestamp = timestamp
        self.punch = punch
        self.status = status

    def __repr__(self):
        return f"FakeAtt(user_id={self.user_id!r}, ts={self.timestamp}, punch={self.punch})"


class ExplodingAtt(FakeAtt):
    """Punch whose first timestamp read raises — simulates a transient error
    mid-processing in the realtime path (DB hiccup, decode error, ...). The
    device's own flash copy (a fresh FakeAtt with the same data) is
    unaffected — that's what catch-up re-reads."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._boom = True

    @property
    def timestamp(self):
        if self._boom:
            self._boom = False
            raise RuntimeError("simulated transient failure mid-punch-processing")
        return self._ts

    @timestamp.setter
    def timestamp(self, value):
        self._ts = value


class FakeConn:
    """Stand-in for a pyzk connection."""

    def __init__(self, attendance=None, live_events=None, device_time=None):
        self.attendance = list(attendance or [])
        self.live_events = list(live_events or [])
        self.device_time = device_time or datetime(2026, 1, 1, 12, 0, 0)
        self.disconnected = False
        self.end_live_capture = False

    def get_attendance(self):
        return list(self.attendance)

    def live_capture(self, new_timeout=2):
        for ev in self.live_events:
            yield ev

    def get_time(self):
        return self.device_time

    def get_firmware_version(self):
        return "Ver 6.60 Jun 18 2018"

    def disconnect(self):
        self.disconnected = True


def bkk_to_utc(ts: datetime) -> datetime:
    """Bangkok-naive -> UTC-naive, the same conversion zk_session does."""
    return ts.replace(tzinfo=BANGKOK).astimezone(UTC).replace(tzinfo=None)


def make_frozen_datetime(local_naive: datetime, local_offset_hours: int = 7):
    """Return a datetime subclass whose now()/utcnow() are frozen to
    `local_naive` (the container's wall clock — prod runs TZ=Asia/Bangkok)."""
    tzinfo = timezone(timedelta(hours=local_offset_hours))
    aware = local_naive.replace(tzinfo=tzinfo)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return local_naive
            return aware.astimezone(tz)

        @classmethod
        def utcnow(cls):
            return aware.astimezone(UTC).replace(tzinfo=None)

    return _Frozen


# ---------------------------------------------------------------------------
# fixtures (self-contained — no dependency on tests/conftest.py fixtures)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_real_device(monkeypatch):
    """Hard guardrail: any attempt to construct a real pyzk ZK() blows up.
    Tests that need a device op override this locally via monkeypatch."""
    from app.services import zk_session as zk_session_module

    def _boom(*a, **kw):
        raise AssertionError("test_zk_ingestion tried to open a REAL device connection")

    monkeypatch.setattr(zk_session_module, "ZK", _boom)


@pytest.fixture
def freeze_now(monkeypatch):
    """freeze_now(datetime(...), offset_hours=7) -> patches zk_session.datetime."""
    from app.services import zk_session as zk_session_module

    def _apply(local_naive: datetime, local_offset_hours: int = 7):
        monkeypatch.setattr(
            zk_session_module,
            "datetime",
            make_frozen_datetime(local_naive, local_offset_hours),
        )

    return _apply


@pytest.fixture
def db(monkeypatch, tmp_path):
    """Throwaway SQLite DB wired into app.core.database.SessionLocal — the
    same pattern zk_session's `_handle_punch`/`_catch_up` use
    (`next(get_db())`), so nothing needs a FastAPI dependency override."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.core.database as db_module
    from app.core.database import Base
    from app.models.models import AttendanceRecord, Device, Employee  # noqa: F401

    engine = create_engine(
        f"sqlite:///{tmp_path}/zk-ingestion.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestingSessionLocal)

    # seed: one active fingerprint device, id=1 (the default device
    # `.filter(is_active==True).order_by(Device.id).first()` resolves to).
    s = TestingSessionLocal()
    s.add(Device(name="K40", ip_address="192.168.100.209", port=4370, is_active=True,
                 device_type="fingerprint"))
    s.commit()
    s.close()

    class Handle:
        Session = TestingSessionLocal

        def add_employee(self, badge, name=None):
            ses = TestingSessionLocal()
            ses.add(Employee(badge_number=str(badge), english_name=name or f"Emp {badge}",
                             display_name=name or f"Emp {badge}", is_active=True))
            ses.commit()
            ses.close()

        def add_device(self, name, device_type="qr_terminal", is_active=True):
            """A second device — e.g. a QR kiosk — whose rows must NOT feed
            device 1's watermark (proves per-device scoping, not a global MAX)."""
            ses = TestingSessionLocal()
            d = Device(name=name, device_type=device_type, is_active=is_active)
            ses.add(d)
            ses.commit()
            ses.refresh(d)
            device_id = d.id
            ses.close()
            return device_id

        def insert_raw(self, badge, utc_ts, punch_type=0, device_id=1, status=0):
            """Directly insert an AttendanceRecord, bypassing zk_session
            entirely — used to seed pre-existing rows (prior imports, or a
            poison future-dated row already sitting in the DB)."""
            ses = TestingSessionLocal()
            ses.add(AttendanceRecord(
                employee_badge_number=str(badge),
                device_id=device_id,
                timestamp=utc_ts,
                punch_type=punch_type,
                status=status,
                sync_status="synced",
            ))
            ses.commit()
            ses.close()

        def rows(self):
            ses = TestingSessionLocal()
            try:
                return [
                    (r.employee_badge_number, r.timestamp, r.punch_type, r.device_id)
                    for r in ses.query(AttendanceRecord)
                    .order_by(AttendanceRecord.timestamp).all()
                ]
            finally:
                ses.close()

        def has(self, badge, utc_ts, punch_type=None):
            return any(
                b == str(badge) and t == utc_ts and (punch_type is None or p == punch_type)
                for b, t, p, _ in self.rows()
            )

        def count(self):
            return len(self.rows())

    return Handle()


@pytest.fixture
def session():
    """A fresh (unstarted) ZkSession — device I/O only via a fake conn passed
    directly to `_stream`/`_catch_up`. Nothing here spins up the daemon
    thread, so no real ZK() construction is possible via this fixture."""
    from app.services.zk_session import ZkSession

    return ZkSession(host="127.0.0.1", port=1, password=0, timeout=1)


def run_catch_up(monkeypatch, records, full: bool = False):
    """Drive the REAL, LOCKED `catch_up_now(full=...)` entry point through
    the one-shot connect path (the session daemon isn't running in these
    tests, so `submit()` falls back to `_run_op_one_shot`, which constructs
    `ZK(...)` — patched here to hand back a FakeConn)."""
    from app.services import zk_session as zk_session_module

    conn = FakeConn(attendance=records)
    zk_instance = MagicMock()
    zk_instance.connect.return_value = conn
    monkeypatch.setattr(zk_session_module, "ZK", lambda *a, **kw: zk_instance)
    return zk_session_module.catch_up_now(full=full)


# ===========================================================================
# 1. Gap backfill: record older than newer rows (incl. a newer QR row on
#    another device_id) but within lookback -> inserted by catch-up.
# ===========================================================================
def test_1_gap_backfill_within_lookback_ignores_other_device_rows(db, freeze_now, monkeypatch):
    db.add_employee("1001")
    db.add_employee("1002")
    qr_device_id = db.add_device("QR Kiosk", device_type="qr_terminal")
    freeze_now(datetime(2026, 8, 1, 12, 0, 0))

    # Device 1's own watermark: its newest row, only 2h old.
    db.insert_raw("1001", bkk_to_utc(datetime(2026, 8, 1, 10, 0, 0)), punch_type=0, device_id=1)
    # A QR check-in on a DIFFERENT device, only 10min old — much newer than
    # device 1's own watermark. This is the layout that actually
    # discriminates per-device vs. global scoping (a QR row merely newer
    # than the gap punch, as in a naive seed, still leaves the gap punch
    # above even a global floor and doesn't prove anything):
    #   - per-device floor = device 1's watermark (now-2h) - 48h = now-50h
    #     -> the gap punch (now-49h) is ABOVE the floor -> inserted.
    #   - global floor (if `.filter(device_id==...)` were dropped from the
    #     watermark query) = MAX(this QR row, now-10min) - 48h
    #     = now-48h10min -> the gap punch (now-49h) is BELOW that floor ->
    #     silently dedup-skipped instead of inserted.
    # So this layout goes RED under global scoping and GREEN only under
    # correct per-device scoping.
    db.insert_raw("1002", bkk_to_utc(datetime(2026, 8, 1, 11, 50, 0)), punch_type=0,
                  device_id=qr_device_id)

    # The GAP punch: missed by live_capture, ~49h old — inside device 1's
    # own 48h lookback floor, still on the device.
    gap_ts = datetime(2026, 7, 30, 11, 0, 0)
    already_imported = FakeAtt("1001", datetime(2026, 8, 1, 10, 0, 0), punch=0)
    gap = FakeAtt("1001", gap_ts, punch=1)

    inserted = run_catch_up(monkeypatch, [already_imported, gap])

    assert inserted == 1, f"gap punch not backfilled; rows={db.rows()}"
    assert db.has("1001", bkk_to_utc(gap_ts), punch_type=1), f"rows={db.rows()}"


# ===========================================================================
# 2. Same-second cross-employee (old watermark-equality RED) -> both inserted.
# ===========================================================================
def test_2_same_second_cross_employee_both_inserted(db, freeze_now, monkeypatch):
    db.add_employee("1001")
    db.add_employee("1002")
    freeze_now(datetime(2026, 8, 1, 9, 0, 0))

    ts = datetime(2026, 8, 1, 8, 0, 0)
    first = FakeAtt("1001", ts, punch=0)
    assert run_catch_up(monkeypatch, [first]) == 1

    same_second = FakeAtt("1002", ts, punch=0)
    run_catch_up(monkeypatch, [first, same_second])

    assert db.has("1002", bkk_to_utc(ts)), (
        f"same-second punch by another employee eaten by an inclusive/equal "
        f"watermark comparison; rows={db.rows()}"
    )
    assert db.count() == 2


# ===========================================================================
# 3. Future-drift + backwards resync -> recovered by a later sweep via lookback.
# ===========================================================================
def test_3_future_drift_then_backwards_resync_recovered(db, freeze_now, monkeypatch):
    db.add_employee("1001")
    db.add_employee("1002")
    freeze_now(datetime(2026, 8, 1, 14, 0, 0))

    # (a) device is 5 min fast: punch made ~now, stamped a few minutes ahead.
    drifted = FakeAtt("1001", datetime(2026, 8, 1, 14, 5, 0), punch=0)
    assert run_catch_up(monkeypatch, [drifted]) == 1, f"rows={db.rows()}"

    # (b) scheduler resyncs the device clock backwards -> subsequent REAL
    #     punches now carry timestamps earlier than the just-imported watermark.
    freeze_now(datetime(2026, 8, 1, 14, 20, 0))
    after_resync = [
        FakeAtt("1002", datetime(2026, 8, 1, 14, 3, 0), punch=0),
        FakeAtt("1001", datetime(2026, 8, 1, 14, 4, 30), punch=1),
    ]
    run_catch_up(monkeypatch, [drifted] + after_resync)

    missing = [r for r in after_resync if not db.has(r.user_id, bkk_to_utc(r.timestamp))]
    assert not missing, (
        f"punches made AFTER a backwards clock resync were not recovered by "
        f"the lookback-scoped sweep: {missing}; rows={db.rows()}"
    )


# ===========================================================================
# 4a. Same badge, same second, different punch_type via CATCH-UP -> the
#     catch-up exists-check dedup key is now (badge, timestamp) ONLY
#     (punch_type dropped), so the second record in the batch is treated as
#     a duplicate of the first and conservatively dedup-SKIPPED, not
#     inserted. (Realtime keeps the 3-column key — see 4b.)
# ===========================================================================
def test_4a_same_second_double_punch_catchup_dedup_skips_second(db, freeze_now, monkeypatch):
    db.add_employee("1001")
    freeze_now(datetime(2026, 8, 1, 18, 0, 0))

    ts = datetime(2026, 8, 1, 17, 0, 0)
    recs = [FakeAtt("1001", ts, punch=1), FakeAtt("1001", ts, punch=0)]
    inserted = run_catch_up(monkeypatch, recs)

    assert inserted == 1, (
        f"catch-up dedup key should be (badge, timestamp) ONLY — the second "
        f"same-(badge,ts) record with a different punch_type must be "
        f"conservatively dedup-skipped, not inserted (got inserted={inserted}); "
        f"rows={db.rows()}"
    )
    rows = [r for r in db.rows() if r[0] == "1001"]
    assert len(rows) == 1, f"expected exactly one surviving row; rows={db.rows()}"
    assert rows[0][2] == 1, (
        f"expected the FIRST-processed record (punch=1) to survive the dedup "
        f"skip of the second; rows={db.rows()}"
    )


# ===========================================================================
# 4b. Same badge, same second, different punch_type via REALTIME -> dedup
#     key stays (badge, timestamp, punch_type) on `_handle_punch`, so BOTH
#     rows persist (contrast with 4a's catch-up behavior).
# ===========================================================================
def test_4b_same_second_double_punch_realtime_both_persist(db, freeze_now, monkeypatch, session):
    db.add_employee("1003")
    freeze_now(datetime(2026, 8, 1, 18, 0, 0))

    ts2 = datetime(2026, 8, 1, 17, 30, 0)
    session._stream(
        FakeConn(live_events=[FakeAtt("1003", ts2, punch=1), FakeAtt("1003", ts2, punch=0)])
    )
    n1003 = len([r for r in db.rows() if r[0] == "1003"])
    assert n1003 == 2, (
        f"realtime _handle_punch dedup key should stay (badge, timestamp, "
        f"punch_type) — merged two distinct punch_types; rows={db.rows()}"
    )


# ===========================================================================
# 5. Unknown badge, employee created later -> recovered by next catch-up
#    within lookback.
# ===========================================================================
def test_5_unknown_badge_recovered_after_enrollment(db, freeze_now, monkeypatch, session):
    db.add_employee("1002")  # 1001 not yet enrolled
    freeze_now(datetime(2026, 8, 1, 10, 0, 0))

    # An existing device-1 row so a REAL watermark floor exists (an empty
    # table gives floor=None, which trivially lets every record through and
    # doesn't exercise the lookback logic at all).
    db.insert_raw("1002", bkk_to_utc(datetime(2026, 8, 1, 9, 0, 0)), punch_type=0, device_id=1)

    # Unknown badge, well inside the lookback (floor = now-1h - 48h).
    unknown_ts = datetime(2026, 8, 1, 9, 30, 0)  # now - 30min
    unknown = FakeAtt("1001", unknown_ts, punch=0)
    session._stream(FakeConn(live_events=[unknown]))
    assert not db.has("1001", bkk_to_utc(unknown_ts)), "should not exist before enrollment"

    db.add_employee("1001")
    inserted = run_catch_up(monkeypatch, [unknown])

    assert inserted == 1, f"unknown-badge punch not recovered after enrollment; rows={db.rows()}"
    assert db.has("1001", bkk_to_utc(unknown_ts))


# ===========================================================================
# 6. `_handle_punch` exception -> recovered by catch-up.
# ===========================================================================
def test_6_handle_punch_exception_recovered_by_catchup(db, freeze_now, monkeypatch, session):
    db.add_employee("1002")
    freeze_now(datetime(2026, 8, 1, 10, 0, 0))

    punch_ts = datetime(2026, 8, 1, 8, 30, 0)
    boom = ExplodingAtt("1002", punch_ts, punch=0)  # raises once on first .timestamp read

    session._stream(FakeConn(live_events=[boom]))
    assert not db.has("1002", bkk_to_utc(punch_ts)), "punch should not exist after the exception"

    # Device's own flash copy is unaffected by our processing exception.
    device_copy = FakeAtt("1002", punch_ts, punch=0)
    inserted = run_catch_up(monkeypatch, [device_copy])

    assert inserted == 1, f"punch lost to a realtime exception not recovered by catch-up; rows={db.rows()}"
    assert db.has("1002", bkk_to_utc(punch_ts))


# ===========================================================================
# 7. Sanity rejects are logged (caplog), not silent; far-future realtime
#    punch rejected on realtime path too.
# ===========================================================================
def test_7_sanity_rejects_are_logged_not_silent(db, freeze_now, monkeypatch, session, caplog):
    db.add_employee("1001")
    freeze_now(datetime(2026, 8, 1, 12, 0, 0))

    # catch-up path: pre-2010 record.
    bad_year = FakeAtt("1001", datetime(2009, 1, 1, 0, 0, 0), punch=0)
    with caplog.at_level(logging.WARNING):
        inserted = run_catch_up(monkeypatch, [bad_year])

    assert inserted == 0
    assert not any(r[0] == "1001" for r in db.rows()), f"bad-year record was inserted; rows={db.rows()}"
    assert "[zk_session.sanity] rejected" in caplog.text and "badge=1001" in caplog.text, (
        f"sanity rejection on the catch-up path wasn't logged (bare `continue`?); "
        f"log=\n{caplog.text}"
    )

    caplog.clear()

    # realtime path: far-future punch (> now + 1 day).
    far_future_ts = datetime(2026, 8, 5, 12, 0, 0)  # +4 days
    far_future = FakeAtt("1001", far_future_ts, punch=0)
    with caplog.at_level(logging.WARNING):
        session._stream(FakeConn(live_events=[far_future]))

    assert not db.has("1001", bkk_to_utc(far_future_ts)), "far-future realtime punch was inserted"
    assert "[zk_session.sanity] rejected" in caplog.text and "badge=1001" in caplog.text, (
        f"sanity rejection on the realtime (_handle_punch) path wasn't logged; "
        f"log=\n{caplog.text}"
    )


# ===========================================================================
# 8. Watermark capped at now (a far-future row in DB does not kill catch-up).
# ===========================================================================
def test_8_watermark_capped_at_now_survives_poison_future_row(db, freeze_now, monkeypatch):
    db.add_employee("1001")
    now = datetime(2026, 8, 1, 12, 0, 0)
    freeze_now(now)

    # Poison row already sitting in the DB (corrupt import, manual edit, a
    # sanity-check regression before this fix, ...) with a wildly future
    # timestamp. Without capping MAX(timestamp) at utcnow, `watermark -
    # lookback` would ALSO be in the future, and the normal record below
    # (2h old) would look "older than the floor" and get skipped.
    poison_utc = bkk_to_utc(datetime(2026, 11, 1, 12, 0, 0))  # +3 months
    db.insert_raw("1001", poison_utc, punch_type=0, device_id=1)

    normal_ts = datetime(2026, 8, 1, 10, 0, 0)  # 2h ago
    normal = FakeAtt("1001", normal_ts, punch=1)

    inserted = run_catch_up(monkeypatch, [normal])

    assert inserted == 1, (
        f"a poisoned future watermark row blocked catch-up from recovering a "
        f"normal recent punch — MAX(timestamp) must be capped at utcnow; rows={db.rows()}"
    )
    assert db.has("1001", bkk_to_utc(normal_ts))


# ===========================================================================
# 9. `full=True` reconciles the entire device log (dedup-only).
# ===========================================================================
def test_9_full_true_bypasses_lookback_floor(db, freeze_now, monkeypatch):
    db.add_employee("1001")
    now = datetime(2026, 8, 1, 12, 0, 0)
    freeze_now(now)

    # Recent watermark so the non-full floor sits well inside the last 48h.
    db.insert_raw("1001", bkk_to_utc(datetime(2026, 8, 1, 9, 0, 0)), punch_type=0, device_id=1)

    old_ts = datetime(2026, 7, 25, 9, 0, 0)  # ~7 days ago — outside the 48h lookback
    old = FakeAtt("1001", old_ts, punch=1)

    inserted_default = run_catch_up(monkeypatch, [old], full=False)
    assert inserted_default == 0, (
        f"non-full catch-up reached past the lookback floor; rows={db.rows()}"
    )
    assert not db.has("1001", bkk_to_utc(old_ts))

    inserted_full = run_catch_up(monkeypatch, [old], full=True)
    assert inserted_full == 1, f"full=True should dedup-only reconcile the whole device log; rows={db.rows()}"
    assert db.has("1001", bkk_to_utc(old_ts))


# ===========================================================================
# 10. CONTROL: normal punch -> row (both paths). Must stay GREEN throughout —
#     proves the harness drives the real code paths.
# ===========================================================================
def test_10_control_normal_punch_both_paths(db, freeze_now, monkeypatch, session):
    db.add_employee("1001")
    db.add_employee("1002")
    freeze_now(datetime(2026, 8, 1, 12, 0, 0))

    punch = datetime(2026, 8, 1, 9, 15, 0)  # 09:15 Bangkok, catch-up path
    inserted = run_catch_up(monkeypatch, [FakeAtt("1001", punch, punch=0)])
    assert inserted == 1, f"catch_up reported {inserted} inserts"
    assert db.has("1001", bkk_to_utc(punch)), f"rows={db.rows()}"

    live_ts = datetime(2026, 8, 1, 11, 0, 0)  # realtime path
    session._stream(FakeConn(live_events=[FakeAtt("1002", live_ts, punch=1)]))
    assert db.has("1002", bkk_to_utc(live_ts)), f"rows={db.rows()}"

    # and it is visible through the read path the UI uses
    from app.services.attendance_service import attendance_service

    got = attendance_service.get_attendance_records(
        start_date=datetime(2026, 8, 1).date(), end_date=datetime(2026, 8, 1).date()
    )
    assert len(got) == 2, "punches in DB but invisible to the Bangkok-date read path"


# ===========================================================================
# 11. `get_status_and_time()` submits exactly ONE op.
# ===========================================================================
def test_11_get_status_and_time_submits_one_op(monkeypatch, freeze_now):
    from app.services import zk_session as zk_session_module

    freeze_now(datetime(2026, 8, 1, 12, 0, 0))

    conn = FakeConn(device_time=datetime(2026, 8, 1, 12, 0, 5))
    zk_instance = MagicMock()
    zk_instance.connect.return_value = conn
    zk_ctor = MagicMock(return_value=zk_instance)
    monkeypatch.setattr(zk_session_module, "ZK", zk_ctor)

    result = zk_session_module.get_status_and_time()

    assert zk_ctor.call_count == 1, (
        f"get_status_and_time() must open exactly one device connection for "
        f"both status and time (one submitted op), got {zk_ctor.call_count} "
        f"ZK() construction(s)"
    )
    assert zk_instance.connect.call_count == 1
    assert conn.disconnected is True

    assert "status" in result and "time" in result, f"unexpected shape: {result!r}"
    assert result["status"]["connected"] is True
    assert result["status"]["firmware"] == "Ver 6.60 Jun 18 2018"
    assert result["time"]["success"] is True
    assert "time_difference_seconds" in result["time"]


# ===========================================================================
# 12. Catch-up summary log line reports `unknown_badge=N` separately from
#     dedup/sanity skips.
# ===========================================================================
def test_12_catchup_summary_log_reports_unknown_badge_count(db, freeze_now, monkeypatch, caplog):
    db.add_employee("1001")
    freeze_now(datetime(2026, 8, 1, 12, 0, 0))

    known = FakeAtt("1001", datetime(2026, 8, 1, 9, 0, 0), punch=0)
    unenrolled = FakeAtt("9999", datetime(2026, 8, 1, 9, 5, 0), punch=0)

    with caplog.at_level(logging.INFO):
        inserted = run_catch_up(monkeypatch, [known, unenrolled])

    assert inserted == 1, f"rows={db.rows()}"
    assert "unknown_badge=1" in caplog.text, (
        f"catch-up summary log line ('device_records=... new=... "
        f"dedup_skipped=... sanity_skipped=... unknown_badge=... full=...') "
        f"should report unknown_badge=N for records with no matching "
        f"Employee row; log=\n{caplog.text}"
    )


# ===========================================================================
# 13. `_op_get_status_and_time` isolates the time read: a get_time() failure
#     must not take down the status half.
# ===========================================================================
def test_13_op_get_status_and_time_isolates_time_failure(freeze_now):
    from app.services import zk_session as zk_session_module

    freeze_now(datetime(2026, 8, 1, 12, 0, 0))

    conn = FakeConn()

    def _boom_get_time():
        raise RuntimeError("simulated get_time failure")

    conn.get_time = _boom_get_time

    result = zk_session_module._op_get_status_and_time(conn)

    assert result["status"]["connected"] is True, (
        f"a get_time() failure must not take down the status half; result={result!r}"
    )
    assert result["status"]["firmware"] == "Ver 6.60 Jun 18 2018"
    assert result["time"]["success"] is False, (
        f"time half must report success=False when get_time() raises, not "
        f"propagate the exception up through the merged op; result={result!r}"
    )


# ===========================================================================
# 14. `run_attendance_import_now(full=True)` schedules a one-shot job and
#     returns immediately instead of running the import inline.
# ===========================================================================
def test_14_run_attendance_import_now_full_true_schedules_not_inline(monkeypatch):
    import asyncio

    from app.services.background_scheduler import BackgroundSchedulerService
    from app.services import zk_session as zk_session_module

    scheduler = BackgroundSchedulerService()
    scheduler._running = True  # in case scheduling is gated on the scheduler being up

    def _boom(*a, **kw):
        raise AssertionError(
            "run_attendance_import_now(full=True) must schedule a one-shot "
            "job, not call catch_up_now() inline on the request path"
        )

    monkeypatch.setattr(zk_session_module, "catch_up_now", _boom)

    result = asyncio.run(scheduler.run_attendance_import_now(full=True))

    assert result.get("success") is True, f"unexpected result: {result!r}"
    assert result.get("scheduled") is True, (
        f"full=True must return scheduled=True instead of running the "
        f"full reconcile inline; result={result!r}"
    )


# ===========================================================================
# 15. `_handle_punch` guards its commit against an IntegrityError (rollback
#     + debug log, no raise) — e.g. a race with catch-up inserting the same
#     (badge, timestamp, punch_type) row first.
# ===========================================================================
def test_15_handle_punch_integrity_error_guard_no_exception_escapes(
    db, freeze_now, monkeypatch, session
):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as SASession

    db.add_employee("1001")
    freeze_now(datetime(2026, 8, 1, 12, 0, 0))

    original_commit = SASession.commit
    state = {"raised": False}

    def _commit_raises_once(self, *a, **kw):
        if not state["raised"]:
            state["raised"] = True
            raise IntegrityError(
                "INSERT INTO attendance_records ...", {}, Exception("UNIQUE constraint failed")
            )
        return original_commit(self, *a, **kw)

    monkeypatch.setattr(SASession, "commit", _commit_raises_once)

    punch_ts = datetime(2026, 8, 1, 11, 0, 0)
    att = FakeAtt("1001", punch_ts, punch=0)

    # Call `_handle_punch` directly (not via `_stream`) — `_stream`'s own
    # outer try/except would swallow an unguarded IntegrityError too and
    # mask a regression in `_handle_punch`'s own guard.
    try:
        session._handle_punch(att)
    except Exception as exc:
        pytest.fail(
            f"_handle_punch must guard db.commit()'s IntegrityError (rollback "
            f"+ debug log, no raise) — got an escaped exception instead: {exc!r}"
        )

    assert state["raised"] is True, "guard test didn't actually exercise commit()"
    assert not db.has("1001", bkk_to_utc(punch_ts)), (
        f"row should not exist after a genuinely-failed commit; rows={db.rows()}"
    )


# ===========================================================================
# 16. `GET /api/private/employees/?from_device=true` serves the
#     `device_users` cache; it must never open a live device connection
#     (`zk_client.get_users()`) on the request path — that goes through the
#     same locked `zk_session` queue as live_capture and the K40 only
#     tolerates one TCP session at a time.
# ===========================================================================
def test_16_employees_from_device_never_calls_get_users_serves_cache(
    test_client, test_db, monkeypatch
):
    from app.models.models import Device, Employee
    from app.services import zk_client as zk_client_module
    from app.services.device_cache_service import device_cache_service

    test_db.add(
        Device(
            name="K40", ip_address="192.168.100.209", port=4370, is_active=True,
            device_type="fingerprint",
        )
    )
    test_db.add(
        Employee(
            badge_number="1001", english_name="Alice", display_name="Alice",
            is_active=True, is_hidden=False,
        )
    )
    test_db.commit()

    def _boom():
        raise AssertionError(
            "GET ?from_device=true must serve the device_users cache, not "
            "call zk_client.get_users() on the request path"
        )

    monkeypatch.setattr(zk_client_module.zk_client, "get_users", _boom)

    device_cache_service.set(
        "device_users",
        [{"user_id": "1001", "name": "Alice", "privilege": 0, "password": "", "group_id": ""}],
    )

    response = test_client.get("/api/private/employees/?from_device=true")

    assert response.status_code == 200, response.text
    badges = {emp["badge_number"] for emp in response.json()["employees"]}
    assert "1001" in badges, f"cached device user missing from response: {response.json()}"
