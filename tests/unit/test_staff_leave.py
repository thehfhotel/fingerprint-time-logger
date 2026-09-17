"""Leave requests: no LINE calls, real SQL transactions and PNG rendering."""
from datetime import date, timedelta
from io import BytesIO
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.models.models import Employee, EmployeeLeave
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest
from app.services import staff_leave as service
from app.services.staff_leave_image import render_png
from app.api import staff_leave as api

START = date(2026, 9, 17)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(service, 'today', lambda: date(2026, 9, 16))
    monkeypatch.setattr(service.staff_oa_service, 'get_channel_secret', lambda: 'dummy-test-secret')
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def foreign_keys(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Employee(badge_number='TEST-A', display_name='พนักงานทดสอบ ก', thai_name='พนักงานทดสอบ ก',
                     department='ต้อนรับ', location='HF', line_user_id='UtestA',
                     is_active=True, pending_approval=False),
            Employee(badge_number='TEST-B', display_name='พนักงานทดสอบ ข', line_user_id='UtestB',
                     is_active=True, pending_approval=False),
        ])
        session.commit()
        yield session
    engine.dispose()


def employee(db, badge='TEST-A'):
    return db.query(Employee).filter_by(badge_number=badge).one()


def submit(db, **kwargs):
    return service.submit(db, employee(db), kwargs.pop('request_id', uuid4().hex),
                          kwargs.pop('kind', 'personal'), kwargs.pop('start', START),
                          kwargs.pop('end', START + timedelta(days=2)), **kwargs)


def text_event(text, user='UtestA', source='user'):
    return {'type': 'message', 'source': {'type': source, 'userId': user},
            'replyToken': 'test-only', 'message': {'type': 'text', 'text': text}}


def postback(data, selected=None):
    event = {'type': 'postback', 'postback': {'data': data}}
    if selected:
        event['postback']['params'] = {'date': selected}
    return event


def action(message, index=0):
    return message['quickReply']['items'][index]['action']


def test_submit_pending_replay_no_roster(db):
    row = submit(db)
    assert row.status == 'pending' and row.version == 1
    assert db.query(StaffLeaveDay).count() == 3
    assert db.query(EmployeeLeave).count() == 0
    assert submit(db, request_id=row.id).id == row.id
    assert db.query(StaffLeaveRequest).count() == 1


@pytest.mark.parametrize('change', ['employee', 'type', 'date'])
def test_idempotency_key_bound_to_original(db, change):
    row = submit(db)
    with pytest.raises(service.LeaveError):
        service.submit(db, employee(db, 'TEST-B' if change == 'employee' else 'TEST-A'),
                       row.id, 'sick' if change == 'type' else 'personal',
                       START + timedelta(days=1) if change == 'date' else START,
                       START + timedelta(days=2))


@pytest.mark.parametrize('offset', [0, 1, 2, -1])
def test_overlapping_requests_are_atomic(db, offset):
    submit(db)
    with pytest.raises(service.LeaveError):
        submit(db, start=START + timedelta(days=offset), end=START + timedelta(days=offset+2))
    assert db.query(StaffLeaveRequest).count() == 1
    assert db.query(StaffLeaveDay).count() == 3


def test_other_employee_can_request_same_dates(db):
    submit(db)
    service.submit(db, employee(db, 'TEST-B'), uuid4().hex, 'sick', START, START)
    assert db.query(StaffLeaveRequest).count() == 2


@pytest.mark.parametrize('start,end', [
    (START, START-timedelta(days=1)), (START, START+timedelta(days=92)),
    (date(2026, 8, 1), START), (date(2027, 9, 18), date(2027, 9, 18)),
])
def test_invalid_ranges(db, start, end):
    with pytest.raises(service.LeaveError):
        submit(db, start=start, end=end)
    assert db.query(StaffLeaveRequest).count() == 0


@pytest.mark.parametrize('kind', ['public_holiday', 'invalid'])
def test_invalid_types(db, kind):
    with pytest.raises(service.LeaveError):
        submit(db, kind=kind)


@pytest.mark.parametrize('attr', ['is_active', 'pending_approval'])
def test_inactive_or_unapproved_employee_cannot_submit(db, attr):
    setattr(employee(db), attr, attr == 'pending_approval')
    db.commit()
    with pytest.raises(service.LeaveError):
        submit(db)


def test_approval_atomic_roster_and_audit(db):
    row = submit(db)
    result = service.decide(db, row.id, 'approved', 1, 'manager@example.invalid')
    assert result.status == 'approved' and result.version == 2
    assert result.reviewed_by == 'manager@example.invalid' and result.reviewed_at
    assert db.query(EmployeeLeave).count() == 3
    assert {r.note for r in db.query(EmployeeLeave)} == {service.reference(row)}
    with pytest.raises(service.LeaveError):
        service.decide(db, row.id, 'rejected', 1, 'other@example.invalid')
    assert db.get(StaffLeaveRequest, row.id).status == 'approved'


def test_rejection_releases_days(db):
    row = submit(db)
    service.decide(db, row.id, 'rejected', 1, 'manager@example.invalid')
    assert db.query(StaffLeaveDay).count() == 0
    assert db.query(EmployeeLeave).count() == 0
    submit(db)


def test_auto_approve_records_roster_rows_with_auto_reviewer(db):
    row = submit(db)  # personal, 3 calendar days (START..START+2)
    row = service._maybe_auto_approve(db, row)
    assert row.status == 'approved' and row.reviewed_by == service.AUTO_REVIEWER
    rows = db.query(EmployeeLeave).filter_by(employee_badge_number='TEST-A').all()
    assert len(rows) == 3
    assert {r.note for r in rows} == {service.reference(row)}


def test_auto_approve_disabled_keeps_pending_behaviour(db, monkeypatch):
    monkeypatch.setenv('STAFF_LEAVE_AUTO_APPROVE', 'false')
    row = submit(db)
    result = service._maybe_auto_approve(db, row)
    assert result.status == 'pending' and result.reviewed_by is None
    assert db.query(EmployeeLeave).count() == 0


def test_auto_approve_roster_conflict_leaves_request_pending_no_partial_rows(db):
    row = submit(db)
    db.add(EmployeeLeave(employee_badge_number='TEST-A', date=START, leave_type='sick', note='original'))
    db.commit()
    result = service._maybe_auto_approve(db, row)
    assert result.status == 'pending' and result.reviewed_by is None
    assert [r.note for r in db.query(EmployeeLeave)] == ['original']
    assert db.query(StaffLeaveDay).filter_by(request_id=row.id).count() == 3


def test_auto_approve_idempotent_on_already_approved_row(db):
    row = submit(db)
    once = service._maybe_auto_approve(db, row)
    twice = service._maybe_auto_approve(db, once)
    assert twice.status == 'approved' and twice.version == once.version
    assert db.query(EmployeeLeave).count() == 3


def test_cancel_auto_approved_deletes_only_its_own_rows(db):
    unrelated = EmployeeLeave(employee_badge_number='TEST-A', date=START + timedelta(days=30),
                              leave_type='vacation', note='unrelated')
    db.add(unrelated)
    db.commit()
    row = submit(db)
    row = service._maybe_auto_approve(db, row)
    assert row.status == 'approved' and row.reviewed_by == service.AUTO_REVIEWER
    cancelled = service.cancel(db, 'TEST-A', row.id)
    assert cancelled.status == 'cancelled'
    remaining = db.query(EmployeeLeave).all()
    assert [r.note for r in remaining] == ['unrelated']
    assert db.query(StaffLeaveDay).filter_by(request_id=row.id).count() == 0
    submit(db)  # dates are free again


def test_cancel_owner_only_idempotent_and_releases_days(db):
    row = submit(db)
    with pytest.raises(service.LeaveError):
        service.cancel(db, 'TEST-B', row.id)
    assert service.cancel(db, 'TEST-A', row.id).status == 'cancelled'
    assert service.cancel(db, 'TEST-A', row.id).version == 2
    assert db.query(StaffLeaveDay).count() == 0
    submit(db)


def test_cannot_cancel_approved(db):
    row = submit(db)
    service.decide(db, row.id, 'approved', 1, 'manager@example.invalid')
    with pytest.raises(service.LeaveError):
        service.cancel(db, 'TEST-A', row.id)
    assert db.query(EmployeeLeave).count() == 3


def test_roster_conflict_rolls_back_approval_without_overwrite(db):
    row = submit(db)
    db.add(EmployeeLeave(employee_badge_number='TEST-A', date=START, leave_type='sick', note='original'))
    db.commit()
    with pytest.raises(service.LeaveError):
        service.decide(db, row.id, 'approved', 1, 'manager@example.invalid')
    db.expire_all()
    assert row.status == 'pending' and row.version == 1 and row.reviewed_by is None
    assert db.query(EmployeeLeave).one().note == 'original'
    assert db.query(StaffLeaveDay).count() == 3


def test_existing_roster_blocks_submission(db):
    db.add(EmployeeLeave(employee_badge_number='TEST-A', date=START, leave_type='sick'))
    db.commit()
    with pytest.raises(service.LeaveError):
        submit(db)
    assert db.query(StaffLeaveRequest).count() == 0


def test_native_line_flow_needs_explicit_confirmation(db):
    """Auto-record is on by default: the explicit confirmation still gates
    creation, but that same confirmation now also records the leave (no
    separate manager step) — see the auto-approve tests below for the
    off/conflict cases."""
    emp = employee(db)
    first = service._messages(text_event('แจ้งลา'), db, emp)[0]
    choose_start = action(first)
    assert choose_start['type'] == 'datetimepicker' and choose_start['mode'] == 'date'
    assert len(choose_start['data']) <= 300
    second = service._messages(postback(choose_start['data'], START.isoformat()), db, emp)[0]
    review = service._messages(postback(action(second, 1)['data']), db, emp)[0]
    assert db.query(StaffLeaveRequest).count() == 0
    confirmation = action(review)['data']
    receipt = service._messages(postback(confirmation), db, emp)
    assert receipt[1]['type'] == 'image'
    assert 'บันทึกการลาแล้ว' in receipt[0]['text']
    assert 'รออนุมัติ' not in receipt[0]['text']
    row = db.query(StaffLeaveRequest).one()
    assert row.status == 'approved' and row.reviewed_by == service.AUTO_REVIEWER
    assert db.query(EmployeeLeave).count() == 1
    # Replay of the same signed confirmation is idempotent: already approved,
    # so the second call is a no-op rather than a re-approval attempt.
    service._messages(postback(confirmation), db, emp)
    assert db.query(StaffLeaveRequest).count() == 1
    assert db.query(EmployeeLeave).count() == 1
    latest = service._messages(text_event('ใบลาล่าสุด'), db, emp)
    assert 'บันทึกการลาแล้ว' in latest[0]['text']


def test_forwarded_tampered_expired_buttons(db):
    data = service.action_data('review', 'TEST-A', uuid4().hex, 'sick', START.isoformat(), START.isoformat())
    with pytest.raises(service.LeaveError):
        service._parse_action(data, 'TEST-B')
    with pytest.raises(service.LeaveError):
        service._parse_action(data.replace('sick', 'personal'), 'TEST-A')
    expired = service.action_data('review', 'TEST-A', uuid4().hex, expires=1)
    with pytest.raises(service.LeaveError):
        service._parse_action(expired, 'TEST-A')


@pytest.mark.parametrize('source,user', [('group', 'UtestA'), ('user', 'unknown')])
def test_group_or_unknown_gets_no_leave_data(db, monkeypatch, source, user):
    sent = []
    monkeypatch.setattr(service, '_reply', lambda token, messages: sent.extend(messages))
    service.handle_event(text_event('แจ้งลา', user=user, source=source), db)
    assert len(sent) == 1 and sent[0]['type'] == 'text'
    assert 'พนักงานทดสอบ' not in sent[0]['text']
    assert db.query(StaffLeaveRequest).count() == 0


@pytest.mark.parametrize('text,expected', [('แจ้งลา', True), (' ใบลาล่าสุด ', True),
                                         ('วันนี้ลาป่วยนะ', False), ('งานค้าง', False)])
def test_only_explicit_commands_claimed(text, expected):
    assert service.is_leave_event(text_event(text)) is expected


def test_send_failure_preserves_request_for_latest(db, monkeypatch):
    emp = employee(db)
    data = service.action_data('submit', emp.badge_number, uuid4().hex, 'sick', START.isoformat(), START.isoformat())
    event = postback(data)
    event.update(source={'type': 'user', 'userId': 'UtestA'}, replyToken='dummy')
    def fail(*_):
        raise RuntimeError('simulated LINE outage')
    monkeypatch.setattr(service, '_reply', fail)
    with pytest.raises(RuntimeError):
        service.handle_event(event, db)
    assert db.query(StaffLeaveRequest).count() == 1
    assert service._messages(text_event('ใบลาล่าสุด'), db, emp)[1]['type'] == 'image'


@pytest.fixture
def client(db, monkeypatch):
    app = FastAPI()
    app.include_router(api.image_router, prefix='/api/public/staff-oa')
    app.include_router(api.admin_router, prefix='/api/private/leaves/requests')
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(api, 'get_cf_access_email', lambda request: None)
    with TestClient(app) as c:
        yield c


def test_manager_auth_required(client):
    assert client.get('/api/private/leaves/requests').status_code == 403
    assert client.get('/api/private/leaves/requests/manage').status_code == 403
    assert client.get('/api/private/leaves/requests', headers={'Cf-Access-Authenticated-User-Email': 'forged@example.invalid'}).status_code == 403


def test_manager_csrf_version_and_approval(client, db, monkeypatch):
    monkeypatch.setattr(api, 'get_cf_access_email', lambda request: 'manager@example.invalid')
    row = submit(db)
    url = f'/api/private/leaves/requests/{row.id}/decision'
    body = {'decision': 'approved', 'version': 1}
    assert client.post(url, json=body).status_code == 403
    assert client.post(url, json=body, headers={'X-HF-Leave-Action': 'review', 'Origin': 'https://evil.invalid'}).status_code == 403
    result = client.post(url, json=body, headers={'X-HF-Leave-Action': 'review', 'Origin': service.ORIGIN})
    assert result.status_code == 200 and result.json()['status'] == 'approved'
    assert client.post(url, json=body, headers={'X-HF-Leave-Action': 'review'}).status_code == 409


def test_signed_image_private_expiry_and_version(client, db):
    row = submit(db)
    url = urlsplit(service.image_url(row))
    path = url.path + '?' + url.query
    result = client.get(path)
    assert result.status_code == 200 and result.content.startswith(b'\x89PNG')
    assert len(result.content) < 1_000_000 and 'no-store' in result.headers['cache-control']
    assert client.get(path.replace('version=1', 'version=2')).status_code == 404
    assert client.get(url.path + '?version=1&expires=1&signature=bad').status_code == 404
    service.cancel(db, 'TEST-A', row.id)
    assert client.get(path).status_code == 404


@pytest.mark.parametrize('status', ['pending', 'approved', 'rejected', 'cancelled'])
def test_thai_png_layout_long_fields(db, status):
    row = submit(db)
    row.employee_name = 'พนักงานทดสอบชื่อยาว' * 5
    row.department = 'ฝ่ายต้อนรับและงานบริการ' * 4
    row.status = status
    png = render_png(row)
    image = Image.open(BytesIO(png))
    assert image.width == 1080 and image.height <= 2400
    assert len(png) < 1_000_000


def test_date_picker_upper_boundary_never_sends_min_equal_max(db):
    last = service.today() + timedelta(days=366)
    data = service.action_data('from', 'TEST-A', uuid4().hex, 'sick')
    message = service._messages(postback(data, last.isoformat()), db, employee(db))[0]
    actions = [item['action'] for item in message['quickReply']['items']]
    assert [item['label'] for item in actions] == ['ลา 1 วัน', 'ครึ่งวันเช้า', 'ครึ่งวันบ่าย']
    assert all(item['type'] == 'postback' for item in actions)
    assert not any(item['type'] == 'datetimepicker' for item in actions)


def test_image_non_ascii_signature_fails_closed(db):
    row = submit(db)
    assert not service.valid_image_token(row.id, 1, int(service.time.time()) + 100, 'ก' * 64)


def test_loma_font_has_thai_and_latin_not_tofu():
    from app.services.staff_leave_image import _font
    font = _font(32)
    missing = bytes(font.getmask('\U0010ffff'))
    for char in 'HF0123456789/พนักงาน':
        assert bytes(font.getmask(char)) != missing


def test_migration_roundtrip_preserves_foundation_tables():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[2] / 'database/migrations/versions/20260916_000000_staff_leave_requests.py'
    spec = importlib.util.spec_from_file_location('test_leave_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    Employee.__table__.create(engine)
    EmployeeLeave.__table__.create(engine)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert set(inspect(connection).get_table_names()) == {
                'employees', 'employee_leaves', 'staff_leave_requests', 'staff_leave_days'}
            migration.downgrade()
            assert set(inspect(connection).get_table_names()) == {'employees', 'employee_leaves'}
    engine.dispose()