"""
Attendance Calendar Service
Business logic for monthly attendance calendar functionality
"""

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, text
from typing import Optional, List, Dict, Any
from datetime import datetime, date, time, timedelta
import calendar

from app.models.models import (
    AttendanceRecord, Employee, WorkSchedule, WorkShift, 
    ReceptionShiftAssignment, JobRole, Holiday, DailyAttendanceSummary,
    MonthlyAttendanceStats, AttendanceStatus, HolidayType
)
from app.schemas.attendance_calendar_schemas import (
    MonthlyCalendarResponse, EmployeeCalendarResponse, DailyAttendanceResponse,
    EmployeeDayDetailResponse, CalendarStatisticsResponse, CalendarFilters,
    CalendarConfigResponse, RoleStatistics
)


class AttendanceCalendarService:
    """Service for attendance calendar operations"""
    
    def __init__(self, db: Session):
        self.db = db
        self.violation_threshold_minutes = 15
        self.weekend_days = [5, 6]  # Saturday, Sunday (0=Monday)
    
    async def get_monthly_calendar(
        self, 
        year: int, 
        month: int, 
        filters: CalendarFilters
    ) -> MonthlyCalendarResponse:
        """Get complete monthly calendar data"""
        
        # Get month metadata
        month_name = calendar.month_name[month]
        days_in_month = calendar.monthrange(year, month)[1]
        
        # Get holidays and weekends for the month
        holidays = await self._get_month_holidays(year, month)
        weekends = self._get_weekend_days(year, month)
        working_days = [d for d in range(1, days_in_month + 1) 
                       if d not in holidays and d not in weekends]
        
        # Get employees based on filters
        employees = await self._get_filtered_employees(filters)
        
        # Get or calculate attendance data for each employee
        employee_calendar_data = []
        for employee in employees:
            daily_attendance = await self._get_employee_monthly_attendance(
                employee.badge_number, year, month, holidays, weekends
            )
            
            employee_data = EmployeeCalendarResponse(
                id=employee.badge_number,
                name=employee.thai_name,
                role=employee.job_role.display_name if employee.job_role else None,
                daily_attendance={
                    str(day): daily_data 
                    for day, daily_data in daily_attendance.items()
                }
            )
            employee_calendar_data.append(employee_data)
        
        # Calculate statistics
        statistics = await self._calculate_monthly_statistics(
            year, month, employee_calendar_data, working_days
        )
        
        return MonthlyCalendarResponse(
            year=year,
            month=month,
            month_name=month_name,
            days_in_month=days_in_month,
            employees=employee_calendar_data,
            holidays=holidays,
            weekends=weekends,
            working_days=working_days,
            statistics=statistics
        )
    
    async def get_employee_day_detail(
        self, 
        employee_id: str, 
        target_date: date
    ) -> Optional[EmployeeDayDetailResponse]:
        """Get detailed attendance information for specific employee and day"""
        
        # Get employee info
        employee = self.db.query(Employee).filter(
            Employee.badge_number == employee_id
        ).first()
        
        if not employee:
            return None
        
        # Get attendance records for the day
        attendance_records = self.db.query(AttendanceRecord).filter(
            and_(
                AttendanceRecord.employee_id == employee_id,
                func.date(AttendanceRecord.timestamp) == target_date
            )
        ).order_by(AttendanceRecord.timestamp).all()
        
        # Get schedule for the day
        schedule = await self._get_employee_schedule(employee_id, target_date)
        
        # Check if holiday/weekend
        is_weekend = self._is_weekend(target_date)
        holiday = await self._get_holiday(target_date)
        is_holiday = holiday is not None
        
        # Calculate attendance status and metrics
        check_in, check_out = self._extract_check_in_out(attendance_records)
        status, late_minutes, early_departure_minutes, work_hours = self._calculate_attendance_metrics(
            check_in, check_out, schedule, target_date, is_weekend, is_holiday
        )
        
        # Get additional context
        notes = await self._get_attendance_notes(employee_id, target_date)
        shift_name = await self._get_shift_name(employee_id, target_date)
        
        return EmployeeDayDetailResponse(
            employee_id=employee_id,
            employee_name=employee.thai_name,
            date=target_date.isoformat(),
            status=status,
            check_in=check_in,
            check_out=check_out,
            scheduled_start=schedule.get('start_time') if schedule else None,
            scheduled_end=schedule.get('end_time') if schedule else None,
            late_minutes=late_minutes,
            early_departure_minutes=early_departure_minutes,
            work_hours=work_hours,
            break_duration=schedule.get('break_duration', 60) if schedule else 0,
            overtime_hours=max(0, work_hours - 8) if work_hours and work_hours > 8 else 0,
            is_weekend=is_weekend,
            is_holiday=is_holiday,
            holiday_name=holiday.name if holiday else None,
            job_role=employee.job_role.display_name if employee.job_role else None,
            shift_name=shift_name,
            notes=notes,
            punch_records=[{
                'timestamp': record.timestamp.isoformat(),
                'punch_type': record.punch_type,
                'status': record.status
            } for record in attendance_records]
        )
    
    async def get_monthly_statistics(
        self, 
        year: int, 
        month: int, 
        filters: CalendarFilters
    ) -> CalendarStatisticsResponse:
        """Get detailed monthly statistics"""
        
        # Try to get cached statistics first
        cached_stats = self.db.query(MonthlyAttendanceStats).filter(
            and_(
                MonthlyAttendanceStats.year == year,
                MonthlyAttendanceStats.month == month
            )
        ).first()
        
        if cached_stats and not self._should_recalculate_stats(cached_stats):
            return self._convert_cached_stats_to_response(cached_stats)
        
        # Calculate fresh statistics
        calendar_data = await self.get_monthly_calendar(year, month, filters)
        return calendar_data.statistics
    
    async def get_calendar_config(self) -> CalendarConfigResponse:
        """Get calendar configuration and metadata"""
        
        # Get available roles
        roles = self.db.query(JobRole.display_name).filter(
            JobRole.is_active == True
        ).all()
        role_names = [role[0] for role in roles]
        
        # Get available months with data
        months_with_data = self.db.query(
            func.extract('year', AttendanceRecord.timestamp).label('year'),
            func.extract('month', AttendanceRecord.timestamp).label('month')
        ).distinct().order_by(text('year DESC, month DESC')).limit(12).all()
        
        months = [
            {
                'year': int(row.year),
                'month': int(row.month),
                'month_name': calendar.month_name[int(row.month)]
            }
            for row in months_with_data
        ]
        
        return CalendarConfigResponse(
            violation_threshold_minutes=self.violation_threshold_minutes,
            minor_issue_threshold_minutes=1,
            weekend_days=self.weekend_days,
            status_colors={
                'perfect': '#4CAF50',
                'minor_issue': '#FF9800',
                'violation': '#F44336',
                'absent': '#E0E0E0',
                'non_working': '#2196F3',
                'partial': '#FF5722'
            },
            status_symbols={
                'perfect': '✓',
                'minor_issue': '⚠',
                'violation': '✗',
                'absent': '-',
                'non_working': 'H',
                'partial': '◐'
            },
            roles=role_names,
            months=months
        )
    
    async def recalculate_monthly_attendance(
        self,
        year: int,
        month: int,
        employee_ids: Optional[List[str]] = None,
        force: bool = False
    ):
        """Recalculate attendance status for a month"""
        
        # Get employees to recalculate
        query = self.db.query(Employee).filter(Employee.is_active == True)
        if employee_ids:
            query = query.filter(Employee.badge_number.in_(employee_ids))
        
        employees = query.all()
        days_in_month = calendar.monthrange(year, month)[1]
        
        # Get month context
        holidays = await self._get_month_holidays(year, month)
        weekends = self._get_weekend_days(year, month)
        
        for employee in employees:
            for day in range(1, days_in_month + 1):
                target_date = date(year, month, day)
                
                # Check if summary already exists and is recent (unless forced)
                if not force:
                    existing = self.db.query(DailyAttendanceSummary).filter(
                        and_(
                            DailyAttendanceSummary.employee_badge_number == employee.badge_number,
                            DailyAttendanceSummary.date == target_date
                        )
                    ).first()
                    
                    if existing and (datetime.now() - existing.last_calculated).days < 1:
                        continue
                
                # Calculate attendance for this day
                await self._calculate_and_store_daily_summary(
                    employee.badge_number, target_date, holidays, weekends
                )
        
        # Update monthly statistics
        await self._update_monthly_statistics(year, month)
    
    async def update_attendance_notes(
        self, 
        employee_id: str, 
        target_date: date, 
        notes: str
    ) -> bool:
        """Update notes for attendance record"""
        
        # Find or create daily summary
        summary = self.db.query(DailyAttendanceSummary).filter(
            and_(
                DailyAttendanceSummary.employee_badge_number == employee_id,
                DailyAttendanceSummary.date == target_date
            )
        ).first()
        
        if summary:
            summary.notes = notes
            summary.updated_at = datetime.now()
            self.db.commit()
            return True
        
        return False
    
    async def get_available_months(self, limit: int = 12) -> List[Dict[str, Any]]:
        """Get list of months with attendance data"""
        
        months_data = self.db.query(
            func.extract('year', AttendanceRecord.timestamp).label('year'),
            func.extract('month', AttendanceRecord.timestamp).label('month'),
            func.count(AttendanceRecord.id).label('record_count')
        ).group_by(
            func.extract('year', AttendanceRecord.timestamp),
            func.extract('month', AttendanceRecord.timestamp)
        ).order_by(text('year DESC, month DESC')).limit(limit).all()
        
        return [
            {
                'year': int(row.year),
                'month': int(row.month),
                'month_name': calendar.month_name[int(row.month)],
                'record_count': row.record_count,
                'url': f'/attendance-calendar/{int(row.year)}/{int(row.month)}'
            }
            for row in months_data
        ]
    
    # Private helper methods
    
    async def _get_filtered_employees(self, filters: CalendarFilters) -> List[Employee]:
        """Get employees based on filters"""
        
        query = self.db.query(Employee).join(
            JobRole, Employee.job_role_id == JobRole.id, isouter=True
        )
        
        if not filters.include_inactive:
            query = query.filter(Employee.is_active == True)
        
        if filters.role:
            query = query.filter(JobRole.role_name == filters.role)
        
        if filters.employee_ids:
            query = query.filter(Employee.badge_number.in_(filters.employee_ids))
        
        return query.order_by(Employee.thai_name).all()
    
    async def _get_employee_monthly_attendance(
        self,
        employee_id: str,
        year: int,
        month: int,
        holidays: List[int],
        weekends: List[int]
    ) -> Dict[int, DailyAttendanceResponse]:
        """Get attendance data for employee for entire month"""
        
        days_in_month = calendar.monthrange(year, month)[1]
        daily_attendance = {}
        
        for day in range(1, days_in_month + 1):
            target_date = date(year, month, day)
            
            # Try to get cached summary first
            summary = self.db.query(DailyAttendanceSummary).filter(
                and_(
                    DailyAttendanceSummary.employee_badge_number == employee_id,
                    DailyAttendanceSummary.date == target_date
                )
            ).first()
            
            if summary and self._is_summary_fresh(summary):
                daily_attendance[day] = self._convert_summary_to_response(summary)
            else:
                # Calculate on-the-fly and optionally cache
                daily_data = await self._calculate_daily_attendance(
                    employee_id, target_date, holidays, weekends
                )
                daily_attendance[day] = daily_data
                
                # Store in background for next time
                await self._store_daily_summary_async(employee_id, target_date, daily_data)
        
        return daily_attendance
    
    async def _calculate_daily_attendance(
        self,
        employee_id: str,
        target_date: date,
        holidays: List[int],
        weekends: List[int]
    ) -> DailyAttendanceResponse:
        """Calculate attendance data for specific day"""
        
        # Get attendance records
        attendance_records = self.db.query(AttendanceRecord).filter(
            and_(
                AttendanceRecord.employee_id == employee_id,
                func.date(AttendanceRecord.timestamp) == target_date
            )
        ).order_by(AttendanceRecord.timestamp).all()
        
        # Get schedule
        schedule = await self._get_employee_schedule(employee_id, target_date)
        
        # Check context
        is_weekend = target_date.day in weekends
        holiday = await self._get_holiday(target_date)
        is_holiday = holiday is not None
        
        # Extract check-in/out
        check_in, check_out = self._extract_check_in_out(attendance_records)
        
        # Calculate metrics
        status, late_minutes, early_departure_minutes, work_hours = self._calculate_attendance_metrics(
            check_in, check_out, schedule, target_date, is_weekend, is_holiday
        )
        
        return DailyAttendanceResponse(
            date=target_date.isoformat(),
            status=status,
            check_in=check_in,
            check_out=check_out,
            scheduled_start=schedule.get('start_time') if schedule else None,
            scheduled_end=schedule.get('end_time') if schedule else None,
            late_minutes=late_minutes,
            early_departure_minutes=early_departure_minutes,
            work_hours=work_hours,
            is_weekend=is_weekend,
            is_holiday=is_holiday,
            holiday_name=holiday.name if holiday else None,
            notes=None
        )
    
    def _calculate_attendance_metrics(
        self,
        check_in: Optional[datetime],
        check_out: Optional[datetime],
        schedule: Optional[Dict],
        target_date: date,
        is_weekend: bool,
        is_holiday: bool
    ) -> tuple:
        """Calculate attendance status and metrics"""
        
        # Non-working days
        if is_weekend or is_holiday:
            return AttendanceStatus.NON_WORKING_DAY, 0, 0, None
        
        # No attendance
        if check_in is None and check_out is None:
            return AttendanceStatus.ABSENT, 0, 0, None
        
        # Partial attendance
        if check_in is None or check_out is None:
            return AttendanceStatus.PARTIAL, 0, 0, None
        
        # No schedule
        if not schedule:
            work_hours = (check_out - check_in).total_seconds() / 3600
            return AttendanceStatus.PERFECT, 0, 0, work_hours
        
        # Calculate lateness and early departure
        late_minutes = 0
        early_departure_minutes = 0
        
        scheduled_start_dt = datetime.combine(target_date, schedule['start_time'])
        if check_in > scheduled_start_dt:
            late_minutes = (check_in - scheduled_start_dt).total_seconds() / 60
        
        scheduled_end_dt = datetime.combine(target_date, schedule['end_time'])
        if check_out < scheduled_end_dt:
            early_departure_minutes = (scheduled_end_dt - check_out).total_seconds() / 60
        
        # Calculate work hours
        work_hours = (check_out - check_in).total_seconds() / 3600
        
        # Determine status
        if late_minutes > self.violation_threshold_minutes or early_departure_minutes > self.violation_threshold_minutes:
            status = AttendanceStatus.MAJOR_VIOLATION
        elif late_minutes > 0 or early_departure_minutes > 0:
            status = AttendanceStatus.MINOR_ISSUE
        else:
            status = AttendanceStatus.PERFECT
        
        return status, int(late_minutes), int(early_departure_minutes), work_hours
    
    def _extract_check_in_out(self, records: List[AttendanceRecord]) -> tuple:
        """Extract check-in and check-out from attendance records"""
        
        check_in = None
        check_out = None
        
        for record in records:
            if record.punch_type in [0, 4]:  # Check-in or OT-in
                if check_in is None:
                    check_in = record.timestamp
            elif record.punch_type in [1, 5]:  # Check-out or OT-out
                check_out = record.timestamp
        
        return check_in, check_out
    
    async def _get_employee_schedule(self, employee_id: str, target_date: date) -> Optional[Dict]:
        """Get employee schedule for specific date"""
        
        # Get employee and role
        employee = self.db.query(Employee).filter(
            Employee.badge_number == employee_id
        ).first()
        
        if not employee or not employee.job_role:
            return None
        
        # For reception role, check shift assignments
        if employee.job_role.has_shifts:
            assignment = self.db.query(ReceptionShiftAssignment).filter(
                and_(
                    ReceptionShiftAssignment.employee_badge_number == employee_id,
                    ReceptionShiftAssignment.date == target_date
                )
            ).first()
            
            if assignment and assignment.work_shift:
                return {
                    'start_time': assignment.work_shift.start_time,
                    'end_time': assignment.work_shift.end_time,
                    'break_duration': assignment.work_shift.break_duration_minutes
                }
        
        # For standard roles, get work schedule
        work_schedule = self.db.query(WorkSchedule).filter(
            WorkSchedule.job_role_id == employee.job_role_id
        ).first()
        
        if work_schedule:
            return {
                'start_time': work_schedule.start_time,
                'end_time': work_schedule.end_time,
                'break_duration': work_schedule.break_duration_minutes
            }
        
        return None
    
    async def _get_month_holidays(self, year: int, month: int) -> List[int]:
        """Get holiday days for the month"""
        
        start_date = date(year, month, 1)
        end_date = date(year, month, calendar.monthrange(year, month)[1])
        
        holidays = self.db.query(Holiday).filter(
            and_(
                Holiday.date >= start_date,
                Holiday.date <= end_date,
                Holiday.is_active == True
            )
        ).all()
        
        return [holiday.date.day for holiday in holidays]
    
    def _get_weekend_days(self, year: int, month: int) -> List[int]:
        """Get weekend days for the month"""
        
        days_in_month = calendar.monthrange(year, month)[1]
        weekend_days = []
        
        for day in range(1, days_in_month + 1):
            date_obj = date(year, month, day)
            if date_obj.weekday() in self.weekend_days:
                weekend_days.append(day)
        
        return weekend_days
    
    def _is_weekend(self, target_date: date) -> bool:
        """Check if date is weekend"""
        return target_date.weekday() in self.weekend_days
    
    async def _get_holiday(self, target_date: date) -> Optional[Holiday]:
        """Get holiday for specific date"""
        return self.db.query(Holiday).filter(
            and_(
                Holiday.date == target_date,
                Holiday.is_active == True
            )
        ).first()
    
    async def _calculate_monthly_statistics(
        self,
        year: int,
        month: int,
        employee_data: List[EmployeeCalendarResponse],
        working_days: List[int]
    ) -> CalendarStatisticsResponse:
        """Calculate monthly statistics from employee data"""
        
        total_employees = len(employee_data)
        total_working_days = len(working_days)
        
        # Count statuses
        status_counts = {
            'perfect': 0,
            'minor_issue': 0,
            'violation': 0,
            'absent': 0
        }
        
        total_late_minutes = 0
        late_count = 0
        
        role_stats = {}
        
        for employee in employee_data:
            role = employee.role or 'Unknown'
            if role not in role_stats:
                role_stats[role] = {
                    'employee_count': 0,
                    'perfect_count': 0,
                    'minor_issue_count': 0,
                    'violation_count': 0,
                    'absent_count': 0
                }
            
            role_stats[role]['employee_count'] += 1
            
            for day_str, daily_data in employee.daily_attendance.items():
                day = int(day_str)
                if day in working_days:
                    status = daily_data.status
                    if status in status_counts:
                        status_counts[status] += 1
                        role_stats[role][f'{status}_count'] += 1
                    
                    if daily_data.late_minutes > 0:
                        total_late_minutes += daily_data.late_minutes
                        late_count += 1
        
        # Calculate rates
        total_working_records = sum(status_counts.values())
        perfect_rate = (status_counts['perfect'] / total_working_records * 100) if total_working_records > 0 else 0
        punctuality_rate = ((status_counts['perfect'] + status_counts['minor_issue']) / total_working_records * 100) if total_working_records > 0 else 0
        avg_late_minutes = total_late_minutes / late_count if late_count > 0 else 0
        
        # Convert role stats
        role_statistics = [
            RoleStatistics(
                role_name=role,
                employee_count=stats['employee_count'],
                perfect_count=stats['perfect_count'],
                minor_issue_count=stats['minor_issue_count'],
                violation_count=stats['violation_count'],
                absent_count=stats['absent_count'],
                punctuality_rate=(stats['perfect_count'] + stats['minor_issue_count']) / (stats['perfect_count'] + stats['minor_issue_count'] + stats['violation_count']) * 100 if (stats['perfect_count'] + stats['minor_issue_count'] + stats['violation_count']) > 0 else 0
            )
            for role, stats in role_stats.items()
        ]
        
        return CalendarStatisticsResponse(
            total_employees=total_employees,
            total_working_days=total_working_days,
            perfect_attendance_rate=perfect_rate,
            punctuality_rate=punctuality_rate,
            average_late_minutes=avg_late_minutes,
            violation_count=status_counts['violation'],
            absent_count=status_counts['absent'],
            role_breakdown=role_statistics
        )
    
    # Additional helper methods would go here for:
    # - _get_attendance_notes
    # - _get_shift_name  
    # - _is_summary_fresh
    # - _convert_summary_to_response
    # - _store_daily_summary_async
    # - _calculate_and_store_daily_summary
    # - _update_monthly_statistics
    # - _should_recalculate_stats
    # - _convert_cached_stats_to_response
    
    async def _get_attendance_notes(self, employee_id: str, target_date: date) -> Optional[str]:
        """Get notes for attendance record"""
        summary = self.db.query(DailyAttendanceSummary).filter(
            and_(
                DailyAttendanceSummary.employee_badge_number == employee_id,
                DailyAttendanceSummary.date == target_date
            )
        ).first()
        return summary.notes if summary else None
    
    async def _get_shift_name(self, employee_id: str, target_date: date) -> Optional[str]:
        """Get shift name for employee on specific date"""
        assignment = self.db.query(ReceptionShiftAssignment).filter(
            and_(
                ReceptionShiftAssignment.employee_badge_number == employee_id,
                ReceptionShiftAssignment.date == target_date
            )
        ).first()
        return assignment.work_shift.shift_name if assignment and assignment.work_shift else None