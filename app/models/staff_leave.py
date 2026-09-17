"""Employee-originated leave requests, separate from approved roster leaves."""
from datetime import datetime

from sqlalchemy import (CheckConstraint, Column, Date, DateTime, ForeignKey,
                        Integer, LargeBinary, String)

from app.core.database import Base


class StaffLeaveRequest(Base):
    __tablename__ = "staff_leave_requests"

    id = Column(String(32), primary_key=True)
    employee_badge_number = Column(
        String(50), ForeignKey("employees.badge_number"), nullable=False, index=True
    )
    employee_name = Column(String(100), nullable=False)
    department = Column(String(100), nullable=True)
    location = Column(String(20), nullable=True)
    leave_type = Column(String(20), nullable=False)
    leave_portion = Column(String(20), nullable=False, default="full")
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    version = Column(Integer, nullable=False, default=1)
    medical_certificate = Column(LargeBinary, nullable=True)
    medical_certificate_content_type = Column(String(50), nullable=True)
    medical_certificate_sha256 = Column(String(64), nullable=True)
    medical_certificate_uploaded_at = Column(DateTime, nullable=True)
    # Filled only after HF Family's scheduled slot reply was accepted by LINE.
    # NULL means this leave can still ride the next free reply-token report.
    family_reported_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reviewed_by = Column(String(254), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','cancelled')",
                        name="ck_staff_leave_status"),
        CheckConstraint("leave_type IN ('sick','personal','vacation','day_off')",
                        name="ck_staff_leave_type"),
        CheckConstraint("leave_portion IN ('full','am','pm')",
                        name="ck_staff_leave_portion"),
        CheckConstraint("date_to >= date_from", name="ck_staff_leave_dates"),
        CheckConstraint("leave_portion = 'full' OR date_to = date_from",
                        name="ck_staff_leave_half_day_single_date"),
    )


class StaffLeaveDay(Base):
    """Durable, atomic overlap guard for pending and approved requests."""
    __tablename__ = "staff_leave_days"

    employee_badge_number = Column(
        String(50), ForeignKey("employees.badge_number"), primary_key=True
    )
    date = Column(Date, primary_key=True)
    request_id = Column(
        String(32), ForeignKey("staff_leave_requests.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
