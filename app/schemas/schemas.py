from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# Device schemas
class DeviceBase(BaseModel):
    name: str
    ip_address: str
    port: int = 4370
    password: int = 0
    is_active: bool = True


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None
    password: Optional[int] = None
    is_active: Optional[bool] = None


class Device(DeviceBase):
    id: int
    last_sync: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Employee schemas
class EmployeeBase(BaseModel):
    employee_id: str
    name: str
    department: Optional[str] = None
    position: Optional[str] = None
    is_active: bool = True


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    is_active: Optional[bool] = None


class Employee(EmployeeBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Attendance Record schemas
class AttendanceRecordBase(BaseModel):
    employee_id: str
    device_id: int
    timestamp: datetime
    punch_type: int  # 0=check_in, 1=check_out, 2=break_out, 3=break_in, 4=ot_in, 5=ot_out
    status: int = 0  # 0=normal, 1=late, 2=early


class AttendanceRecordCreate(AttendanceRecordBase):
    pass


class AttendanceRecordUpdate(BaseModel):
    punch_type: Optional[int] = None
    status: Optional[int] = None


class AttendanceRecord(AttendanceRecordBase):
    id: int
    created_at: datetime
    employee: Optional[Employee] = None
    device: Optional[Device] = None

    class Config:
        from_attributes = True


# Sync Log schemas
class SyncLogBase(BaseModel):
    device_id: int
    sync_type: str  # 'employees', 'attendance', 'full'
    status: str  # 'success', 'failed', 'partial'
    records_synced: int = 0
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class SyncLog(SyncLogBase):
    id: int
    device: Optional[Device] = None

    class Config:
        from_attributes = True


# Additional request/response schemas
class SyncRequest(BaseModel):
    device_id: int
    sync_type: str = "full"  # 'employees', 'attendance', 'full'


class SyncResponse(BaseModel):
    message: str
    sync_log_id: Optional[int] = None
    records_synced: Optional[int] = None


class AttendanceFilter(BaseModel):
    employee_id: Optional[str] = None
    device_id: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    punch_type: Optional[int] = None