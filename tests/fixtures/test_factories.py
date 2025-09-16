"""
Test Data Factories for Fingerprint Time Logger
Provides realistic test data generation using Factory Boy
"""
import factory
from datetime import datetime, timedelta
from factory.alchemy import SQLAlchemyModelFactory
from faker import Faker

from app.models.models import Employee, Device, AttendanceRecord

fake = Faker(['en_US', 'th_TH'])


class EmployeeFactory(SQLAlchemyModelFactory):
    """Factory for creating test Employee records"""

    class Meta:
        model = Employee
        sqlalchemy_session_persistence = "commit"

    badge_number = factory.Sequence(lambda n: f"{n:04d}")
    english_name = factory.Faker('name')
    thai_name = factory.Faker('name', locale='th_TH')
    display_name = factory.LazyAttribute(lambda obj: obj.thai_name or f"พนักงาน {obj.badge_number}")
    department = factory.Faker('company')
    position = factory.Faker('job')
    is_active = True
    is_hidden = False


class DeviceFactory(SQLAlchemyModelFactory):
    """Factory for creating test ZKTeco Device records"""

    class Meta:
        model = Device
        sqlalchemy_session_persistence = "commit"

    name = factory.Faker('company')
    ip_address = factory.Faker('ipv4_private')
    port = 4370
    password = 0
    is_active = True
    last_sync = factory.LazyFunction(datetime.now)


class AttendanceRecordFactory(SQLAlchemyModelFactory):
    """Factory for creating test Attendance records"""

    class Meta:
        model = AttendanceRecord
        sqlalchemy_session_persistence = "commit"

    employee_badge_number = factory.SubFactory(EmployeeFactory)
    device_id = factory.SubFactory(DeviceFactory)
    timestamp = factory.Faker(
        'date_time_between',
        start_date='-30d',
        end_date='now'
    )
    punch_type = factory.Faker('random_element', elements=[0, 1])  # 0=check-in, 1=check-out
    status = 0
    sync_status = 'synced'
    local_id = factory.Faker('uuid4')
    created_locally = False
    validation_status = 'unvalidated'


# Specialized Factories for Common Test Scenarios

class ActiveEmployeeFactory(EmployeeFactory):
    """Factory for active employees with recent attendance"""
    is_active = True
    is_hidden = False


class InactiveEmployeeFactory(EmployeeFactory):
    """Factory for inactive employees"""
    is_active = False


class HiddenEmployeeFactory(EmployeeFactory):
    """Factory for hidden employees"""
    is_hidden = True


class RecentAttendanceFactory(AttendanceRecordFactory):
    """Factory for recent attendance records (last 7 days)"""
    timestamp = factory.Faker(
        'date_time_between',
        start_date='-7d',
        end_date='now'
    )


class CheckInFactory(AttendanceRecordFactory):
    """Factory for check-in records"""
    punch_type = 0


class CheckOutFactory(AttendanceRecordFactory):
    """Factory for check-out records"""
    punch_type = 1


# Trait-based Factories for Complex Scenarios

class EmployeeWithAttendanceFactory(EmployeeFactory):
    """Employee with associated attendance records"""

    @factory.post_generation
    def attendance_records(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted:
            # Create specified number of attendance records
            for _ in range(extracted):
                AttendanceRecordFactory(employee_badge_number=self.badge_number)
        else:
            # Create default 5 attendance records
            for i in range(5):
                AttendanceRecordFactory(
                    employee_badge_number=self.badge_number,
                    timestamp=datetime.now() - timedelta(days=i),
                    punch_type=i % 2  # Alternate check-in/out
                )


class DeviceWithEmployeesFactory(DeviceFactory):
    """Device with associated employees and attendance"""

    @factory.post_generation
    def employees(self, create, extracted, **kwargs):
        if not create:
            return

        employee_count = extracted if extracted else 5

        # Create employees and attendance records
        for i in range(employee_count):
            employee = EmployeeFactory()
            # Create attendance records for this employee on this device
            for day in range(7):  # Last week
                AttendanceRecordFactory(
                    employee_badge_number=employee.badge_number,
                    device_id=self.id,
                    timestamp=datetime.now() - timedelta(days=day),
                    punch_type=day % 2
                )


# Test Data Sets for Common Scenarios

def create_test_company(employee_count=10, device_count=2, days_of_history=30, session=None):
    """Create a complete test company setup"""

    # Set session for factories if provided
    if session:
        EmployeeFactory._meta.sqlalchemy_session = session
        DeviceFactory._meta.sqlalchemy_session = session
        AttendanceRecordFactory._meta.sqlalchemy_session = session
        ActiveEmployeeFactory._meta.sqlalchemy_session = session
        InactiveEmployeeFactory._meta.sqlalchemy_session = session
        HiddenEmployeeFactory._meta.sqlalchemy_session = session

    # Create devices
    devices = [DeviceFactory() for _ in range(device_count)]

    # Create employees with varied characteristics
    employees = []
    for i in range(employee_count):
        if i < employee_count * 0.8:  # 80% active
            employee = ActiveEmployeeFactory()
        elif i < employee_count * 0.9:  # 10% inactive
            employee = InactiveEmployeeFactory()
        else:  # 10% hidden
            employee = HiddenEmployeeFactory()
        employees.append(employee)

    # Create realistic attendance patterns
    attendance_records = []
    for employee in employees:
        if not employee.is_active:
            continue  # Skip attendance for inactive employees

        # Create attendance for each day
        for day in range(days_of_history):
            date = datetime.now() - timedelta(days=day)

            # Skip weekends (basic business logic)
            if date.weekday() >= 5:
                continue

            # Morning check-in (8-9 AM)
            checkin_time = date.replace(
                hour=8,
                minute=fake.random_int(0, 59),
                second=fake.random_int(0, 59)
            )
            attendance_records.append(AttendanceRecordFactory(
                employee_badge_number=employee.badge_number,
                device_id=fake.random_element(devices).id,
                timestamp=checkin_time,
                punch_type=0
            ))

            # Evening check-out (17-18 PM) - 90% probability
            if fake.random_int(1, 100) <= 90:
                checkout_time = date.replace(
                    hour=17,
                    minute=fake.random_int(0, 59),
                    second=fake.random_int(0, 59)
                )
                attendance_records.append(AttendanceRecordFactory(
                    employee_badge_number=employee.badge_number,
                    device_id=fake.random_element(devices).id,
                    timestamp=checkout_time,
                    punch_type=1
                ))

    return {
        'devices': devices,
        'employees': employees,
        'attendance_records': attendance_records
    }


# Quick Test Data Generators

def quick_employee():
    """Generate a single test employee quickly"""
    return EmployeeFactory.build()


def quick_device():
    """Generate a single test device quickly"""
    return DeviceFactory.build()


def quick_attendance(employee_badge=None, device_id=None):
    """Generate a single attendance record quickly"""
    kwargs = {}
    if employee_badge:
        kwargs['employee_badge_number'] = employee_badge
    if device_id:
        kwargs['device_id'] = device_id

    return AttendanceRecordFactory.build(**kwargs)


# Export convenience functions
__all__ = [
    'EmployeeFactory',
    'DeviceFactory',
    'AttendanceRecordFactory',
    'ActiveEmployeeFactory',
    'InactiveEmployeeFactory',
    'HiddenEmployeeFactory',
    'RecentAttendanceFactory',
    'CheckInFactory',
    'CheckOutFactory',
    'EmployeeWithAttendanceFactory',
    'DeviceWithEmployeesFactory',
    'create_test_company',
    'quick_employee',
    'quick_device',
    'quick_attendance'
]