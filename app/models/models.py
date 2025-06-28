from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    ip_address = Column(String(15), nullable=False)
    port = Column(Integer, default=4370)
    password = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    last_sync = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    attendance_records = relationship("AttendanceRecord", back_populates="device")
    sync_logs = relationship("SyncLog", back_populates="device")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    department = Column(String(100), nullable=True)
    position = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    attendance_records = relationship("AttendanceRecord", back_populates="employee")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String(50), ForeignKey("employees.employee_id"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    punch_type = Column(Integer, nullable=False)  # 0=check_in, 1=check_out, 2=break_out, 3=break_in, 4=ot_in, 5=ot_out
    status = Column(Integer, default=0)  # 0=normal, 1=late, 2=early
    created_at = Column(DateTime, default=func.now())

    employee = relationship("Employee", back_populates="attendance_records")
    device = relationship("Device", back_populates="attendance_records")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    sync_type = Column(String(50), nullable=False)  # 'employees', 'attendance', 'full'
    status = Column(String(20), nullable=False)  # 'success', 'failed', 'partial'
    records_synced = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    device = relationship("Device", back_populates="sync_logs")