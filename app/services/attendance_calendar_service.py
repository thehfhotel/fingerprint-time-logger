"""
Stub for removed attendance calendar service - minimal implementation
"""

class AttendanceCalendarService:
    """Minimal attendance calendar service stub"""
    
    def __init__(self, db=None):
        self.db = db
    
    def get_calendar_data(self, year, month):
        return {
            "year": year,
            "month": month,
            "employees": [],
            "holidays": [],
            "weekends": []
        }
    
    async def get_monthly_calendar(self, year, month, filters=None):
        """Get monthly calendar data with actual attendance records"""
        import calendar as cal
        from datetime import datetime, date
        from sqlalchemy import and_, func, desc
        from app.models.models import Employee, AttendanceRecord, JobRole
        from collections import defaultdict
        
        # Get days in month and basic structure
        days_in_month = cal.monthrange(year, month)[1]
        month_name = cal.month_name[month]
        
        if not self.db:
            # Fallback if no database connection
            return self._get_empty_calendar(year, month, month_name, days_in_month)
        
        try:
            # Get maid role employees (role_name = 'maid', job_role_id = 1)
            maid_employees = self.db.query(Employee).join(JobRole).filter(
                and_(
                    JobRole.role_name == 'maid',
                    Employee.is_active == True,
                    Employee.is_hidden == False
                )
            ).all()
            
            if not maid_employees:
                return self._get_empty_calendar(year, month, month_name, days_in_month)
            
            # Handle potential date issues (2065 vs 2025)
            # Try the requested year first, then try with +40 years if no data found
            search_years = [year, year + 40] if year < 2030 else [year]
            attendance_records = []
            
            maid_badges = [emp.badge_number for emp in maid_employees]
            
            for search_year in search_years:
                start_date = datetime(search_year, month, 1)
                if month == 12:
                    end_date = datetime(search_year + 1, 1, 1)
                else:
                    end_date = datetime(search_year, month + 1, 1)
                
                # Query attendance records for maid employees
                year_records = self.db.query(AttendanceRecord).filter(
                    and_(
                        AttendanceRecord.employee_badge_number.in_(maid_badges),
                        AttendanceRecord.timestamp >= start_date,
                        AttendanceRecord.timestamp < end_date
                    )
                ).order_by(AttendanceRecord.timestamp).all()
                
                if year_records:
                    attendance_records = year_records
                    print(f"Found {len(attendance_records)} attendance records for year {search_year}")
                    break
            
            # Process attendance data by employee and day
            employee_calendar_data = []
            total_violations = 0
            total_perfect_days = 0
            
            for employee in maid_employees:
                # Get this employee's records
                emp_records = [r for r in attendance_records if r.employee_badge_number == employee.badge_number]
                
                # Group by day
                daily_records = defaultdict(list)
                for record in emp_records:
                    day = record.timestamp.day
                    daily_records[day].append(record)
                
                # Build daily attendance data
                daily_attendance = {}
                for day in range(1, days_in_month + 1):
                    day_records = daily_records.get(day, [])
                    status = self._calculate_day_status(day_records, year, month, day)
                    daily_attendance[str(day)] = status
                    
                    # Count for statistics
                    if status["status"] == "perfect":
                        total_perfect_days += 1
                    elif status["status"] == "violation":
                        total_violations += 1
                
                employee_calendar_data.append({
                    "badge_number": employee.badge_number,
                    "name": employee.display_name or employee.thai_name or f"พนักงาน {employee.badge_number}",
                    "role": "maid",
                    "daily_attendance": daily_attendance
                })
            
            # Calculate statistics
            working_days = [i for i in range(1, days_in_month + 1) if cal.weekday(year, month, i) < 5]
            total_working_days = len(working_days)
            total_possible_days = len(maid_employees) * total_working_days
            
            statistics = {
                "total_employees": len(maid_employees),
                "total_working_days": total_working_days,
                "perfect_attendance_count": total_perfect_days,
                "violation_count": total_violations,
                "absent_count": max(0, total_possible_days - total_perfect_days - total_violations),
                "average_attendance_rate": (total_perfect_days / total_possible_days * 100) if total_possible_days > 0 else 0.0,
                "perfect_attendance_rate": (total_perfect_days / total_possible_days * 100) if total_possible_days > 0 else 0.0,
                "punctuality_rate": (total_perfect_days / total_possible_days * 100) if total_possible_days > 0 else 0.0,
                "average_late_minutes": 0.0  # Would need more complex calculation
            }
            
            result = {
                "year": year,
                "month": month,
                "month_name": month_name,
                "days_in_month": days_in_month,
                "employees": employee_calendar_data,
                "holidays": [],
                "weekends": [i for i in range(1, days_in_month + 1) if cal.weekday(year, month, i) >= 5],
                "working_days": working_days,
                "statistics": statistics
            }
            print(f"Returning calendar data: {len(employee_calendar_data)} employees, {len(attendance_records)} total records")
            return result
            
        except Exception as e:
            print(f"Error fetching calendar data: {e}")
            import traceback
            traceback.print_exc()
            return self._get_empty_calendar(year, month, month_name, days_in_month)
    
    def _get_empty_calendar(self, year, month, month_name, days_in_month):
        """Return empty calendar structure"""
        import calendar as cal
        working_days = [i for i in range(1, days_in_month + 1) if cal.weekday(year, month, i) < 5]
        
        return {
            "year": year,
            "month": month,
            "month_name": month_name,
            "days_in_month": days_in_month,
            "employees": [],
            "holidays": [],
            "weekends": [i for i in range(1, days_in_month + 1) if cal.weekday(year, month, i) >= 5],
            "working_days": working_days,
            "statistics": {
                "total_employees": 0,
                "total_working_days": len(working_days),
                "perfect_attendance_count": 0,
                "violation_count": 0,
                "absent_count": 0,
                "average_attendance_rate": 0.0,
                "perfect_attendance_rate": 0.0,
                "punctuality_rate": 0.0,
                "average_late_minutes": 0.0
            }
        }
    
    def _calculate_day_status(self, day_records, year, month, day):
        """Calculate attendance status for a specific day"""
        import calendar as cal
        from datetime import time
        
        # Check if it's a weekend
        if cal.weekday(year, month, day) >= 5:  # Saturday or Sunday
            return {
                "status": "non_working",
                "check_in": None,
                "check_out": None,
                "notes": "Weekend"
            }
        
        if not day_records:
            return {
                "status": "absent",
                "check_in": None,
                "check_out": None,
                "notes": "No attendance record"
            }
        
        # Find check-in and check-out records
        check_in_record = None
        check_out_record = None
        
        for record in day_records:
            if record.punch_type == 0:  # Check-in
                if not check_in_record or record.timestamp > check_in_record.timestamp:
                    check_in_record = record
            elif record.punch_type == 1:  # Check-out
                if not check_out_record or record.timestamp > check_out_record.timestamp:
                    check_out_record = record
        
        # Maid standard schedule: 07:00 - 16:00
        standard_start = time(7, 0)  # 7:00 AM
        standard_end = time(16, 0)   # 4:00 PM
        
        status = "perfect"
        notes = []
        
        check_in_time = check_in_record.timestamp.time() if check_in_record else None
        check_out_time = check_out_record.timestamp.time() if check_out_record else None
        
        # Check lateness (more than 15 minutes late is violation)
        if check_in_record and check_in_time > time(7, 15):  # More than 15 min late
            status = "violation"
            minutes_late = (check_in_time.hour - 7) * 60 + check_in_time.minute - 15
            notes.append(f"Late by {minutes_late} minutes")
        elif check_in_record and check_in_time > standard_start:  # 1-15 minutes late
            status = "minor_issue"
            minutes_late = (check_in_time.hour - 7) * 60 + check_in_time.minute
            notes.append(f"Late by {minutes_late} minutes")
        
        # Check early departure
        if check_out_record and check_out_time < time(15, 45):  # More than 15 min early
            status = "violation"
            notes.append("Left early")
        elif check_out_record and check_out_time < standard_end:  # Left slightly early
            if status == "perfect":
                status = "minor_issue"
            notes.append("Left slightly early")
        
        # Missing check-out
        if check_in_record and not check_out_record:
            if status == "perfect":
                status = "minor_issue"
            notes.append("No check-out record")
        
        return {
            "status": status,
            "check_in": check_in_time.strftime("%H:%M") if check_in_time else None,
            "check_out": check_out_time.strftime("%H:%M") if check_out_time else None,
            "notes": "; ".join(notes) if notes else "On time"
        }
    
    async def get_calendar_config(self):
        """Get calendar configuration"""
        return {
            "violation_threshold_minutes": 15,
            "status_colors": {
                "perfect": "#22c55e",
                "minor_issue": "#eab308", 
                "violation": "#ef4444",
                "absent": "#9ca3af",
                "non_working": "#3b82f6"
            },
            "working_days": [1, 2, 3, 4, 5],  # Monday to Friday
            "weekend_days": [6, 7],  # Saturday and Sunday
            "symbol_mappings": {
                "perfect": "✓",
                "minor_issue": "⚠",
                "violation": "✗", 
                "absent": "○",
                "non_working": "—"
            },
            "time_format": "24h",
            "timezone": "Asia/Bangkok"
        }
    
    async def get_employee_day_detail(self, employee_id, target_date):
        """Get detailed attendance information for specific employee and day"""
        # Stub implementation - would normally query actual attendance data
        return {
            "employee_id": employee_id,
            "date": target_date.isoformat(),
            "status": "absent",
            "check_in_time": None,
            "check_out_time": None,
            "total_hours": 0,
            "late_minutes": 0,
            "early_departure_minutes": 0,
            "break_duration": 0,
            "overtime_hours": 0,
            "notes": "No attendance data available (stub implementation)"
        }