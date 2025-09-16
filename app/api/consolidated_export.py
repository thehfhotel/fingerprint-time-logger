"""
Consolidated Export API - All data export functionality
Replaces: export.py, employee_export.py, attendance_export.py, report_export.py
"""

from datetime import datetime, date
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io
import logging

from app.core.database import get_db
from app.services.export_service import export_service
from app.services.attendance_service import attendance_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# ATTENDANCE DATA EXPORTS
# ============================================================================

@router.get("/attendance/csv")
async def export_attendance_csv(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    employee_badge: Optional[str] = Query(None, description="Employee filter"),
    filename: Optional[str] = Query(None, description="Custom filename")
):
    """Export attendance records to CSV"""
    try:
        # Generate filename if not provided
        if not filename:
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"attendance_export_{date_str}.csv"
        
        # Generate CSV content directly with filters
        csv_content = export_service.export_attendance_csv(
            start_date=start_date,
            end_date=end_date,
            employee_badge=employee_badge
        )
        
        # Create streaming response
        output = io.StringIO()
        output.write(csv_content)
        output.seek(0)
        
        response = StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/attendance/summary")
async def export_attendance_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    format: str = Query("json", description="Export format: json, csv")
):
    """Export attendance summary report"""
    try:
        summary = attendance_service.get_attendance_summary(
            start_date=start_date,
            end_date=end_date
        )
        
        if format.lower() == "csv":
            # Convert summary to CSV format
            csv_content = export_service.export_summary_csv(summary)
            
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"attendance_summary_{date_str}.csv"
            
            response = StreamingResponse(
                io.BytesIO(csv_content.encode('utf-8')),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            return response
        else:
            return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# EMPLOYEE DATA EXPORTS
# ============================================================================

@router.get("/employees/csv")
async def export_employees_csv(
    include_hidden: bool = Query(False, description="Include hidden employees"),
    format: str = Query("standard", description="Export format: standard, detailed")
):
    """Export employee list to CSV"""
    try:
        csv_content = export_service.export_employees_csv(
            include_hidden=include_hidden
        )
        
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"employees_export_{date_str}.csv"
        
        response = StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employees/thai-names")
async def export_thai_names_mapping():
    """Export employee Thai name mappings"""
    try:
        csv_content = export_service.export_thai_names_csv()
        
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"thai_names_mapping_{date_str}.csv"
        
        response = StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DEVICE DATA EXPORTS
# ============================================================================

@router.get("/devices/config")
async def export_device_config():
    """Export device configuration"""
    try:
        from app.services.device_service import device_service
        
        device = device_service.get_default_device()
        if not device:
            raise HTTPException(status_code=404, detail="No device configured")
        
        config_data = {
            "device_name": device.name,
            "ip_address": device.ip_address,
            "port": device.port,
            "password": device.password,
            "is_active": device.is_active,
            "last_sync": device.last_sync.isoformat() if device.last_sync else None,
            "created_at": device.created_at.isoformat() if device.created_at else None,
            "export_date": datetime.now().isoformat()
        }
        
        return config_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/status-report")
async def export_device_status_report():
    """Export comprehensive device status report"""
    try:
        from app.services.device_service import device_service
        
        device = device_service.get_default_device()
        if not device:
            return {"message": "No device configured"}
        
        # Get device status and diagnostics
        status = device_service.get_device_status()
        
        report = {
            "device_info": {
                "name": device.name,
                "ip_address": device.ip_address,
                "port": device.port,
                "is_active": device.is_active
            },
            "connection_status": status,
            "last_sync": device.last_sync.isoformat() if device.last_sync else None,
            "report_generated": datetime.now().isoformat()
        }
        
        # Try to get additional device info if connected
        try:
            if status.get("connected"):
                users = device_service.get_users(device)
                records = device_service.get_attendance_records(device)
                
                report["device_data"] = {
                    "users_count": len(users),
                    "records_count": len(records)
                }
        except Exception as e:
            report["device_data_error"] = str(e)
        
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# COMPREHENSIVE REPORTS
# ============================================================================

@router.get("/reports/monthly")
async def export_monthly_report(
    year: int = Query(..., description="Year for report"),
    month: int = Query(..., description="Month for report"),
    format: str = Query("json", description="Export format: json, csv")
):
    """Export comprehensive monthly report"""
    try:
        # Calculate date range for the month
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
        
        # Get attendance data for the month
        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            limit=50000
        )
        
        # Generate monthly report
        report = export_service.generate_monthly_report(year, month, records)
        
        if format.lower() == "csv":
            csv_content = export_service.export_monthly_report_csv(report)
            
            filename = f"monthly_report_{year}_{month:02d}.csv"
            
            response = StreamingResponse(
                io.BytesIO(csv_content.encode('utf-8')),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            return response
        else:
            return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/employee-summary")
async def export_employee_summary_report(
    employee_badge: str = Query(..., description="Employee badge number"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    format: str = Query("json", description="Export format: json, csv")
):
    """Export per-employee summary report"""
    try:
        # Get employee attendance records
        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            employee_badge=employee_badge,
            limit=50000
        )

        try:
            report = export_service.generate_employee_summary_report(
                employee_badge=employee_badge,
                records=records
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg:
                raise HTTPException(status_code=404, detail=f"Employee {employee_badge} not found")
            raise HTTPException(status_code=500, detail=str(e))
        
        if format.lower() == "csv":
            csv_content = export_service.export_employee_summary_csv(report)
            
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"employee_summary_{date_str}.csv"
            
            response = StreamingResponse(
                io.BytesIO(csv_content.encode('utf-8')),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            return response
        else:
            return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# EXPORT STATUS & UTILITIES
# ============================================================================

@router.get("/formats")
async def get_supported_export_formats():
    """Get list of supported export formats and their descriptions"""
    return {
        "formats": {
            "csv": {
                "description": "Comma-separated values",
                "content_type": "text/csv",
                "file_extension": ".csv"
            },
            "json": {
                "description": "JavaScript Object Notation",
                "content_type": "application/json",
                "file_extension": ".json"
            }
        },
        "available_exports": [
            {
                "endpoint": "/attendance/csv",
                "description": "Attendance records export",
                "formats": ["csv"]
            },
            {
                "endpoint": "/employees/csv",
                "description": "Employee list export",
                "formats": ["csv"]
            },
            {
                "endpoint": "/reports/monthly",
                "description": "Monthly attendance report",
                "formats": ["json", "csv"]
            },
            {
                "endpoint": "/reports/employee-summary",
                "description": "Per-employee summary report",
                "formats": ["json", "csv"]
            }
        ]
    }


@router.get("/health")
async def export_health_check():
    """Health check for export system"""
    try:
        # Test if export service is working
        test_result = export_service.test_export_capability()
        
        return {
            "status": "healthy" if test_result else "unhealthy",
            "export_service_available": test_result,
            "supported_formats": ["csv", "json"]
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# ============================================================================
# QUICK EXPORTS - Predefined common exports
# ============================================================================

@router.get("/quick/today-attendance")
async def quick_export_today_attendance():
    """Quick export of today's attendance data"""
    try:
        today = date.today()
        csv_content = export_service.export_attendance_csv(
            start_date=today,
            end_date=today
        )
        filename = f"today_attendance_{today.strftime('%Y%m%d')}.csv"
        
        response = StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quick/this-month")
async def quick_export_this_month():
    """Quick export of current month's data"""
    try:
        today = date.today()
        start_date = date(today.year, today.month, 1)
        
        csv_content = export_service.export_attendance_csv(
            start_date=start_date,
            end_date=today
        )
        filename = f"month_attendance_{today.strftime('%Y%m')}.csv"
        
        response = StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quick/all-employees")
async def quick_export_all_employees():
    """Quick export of all active employees"""
    try:
        csv_content = export_service.export_employees_csv(
            include_hidden=False
        )
        
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"all_employees_{date_str}.csv"
        
        response = StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))