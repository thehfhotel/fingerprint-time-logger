"""
Health Calculator Service for Error Classification Integration

This service calculates system health using error classification data
instead of raw queue statistics, providing intelligent health assessment.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.models.models import ErrorEvent
from app.services.error_classifier import ErrorSeverity


class HealthCalculator:
    """Calculate health scores using error classification intelligence"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def calculate_system_health(self, time_window_hours: int = 1) -> Dict[str, Any]:
        """
        Calculate overall system health using error classification data
        
        Args:
            time_window_hours: Time window to analyze (default 1 hour)
            
        Returns:
            Dictionary with health score and detailed metrics
        """
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        
        # Get recent error events
        recent_errors = self.db.query(ErrorEvent).filter(
            ErrorEvent.timestamp >= cutoff_time
        ).all()
        
        if not recent_errors:
            return {
                "overall_health": "healthy",
                "health_score": 1.0,
                "error_analysis": {
                    "total_events": 0,
                    "informational_count": 0,
                    "recoverable_count": 0,
                    "critical_count": 0,
                    "false_positive_rate": 0.0
                },
                "recommendation": "No recent events - system operating normally"
            }
        
        # Analyze errors by severity
        error_analysis = self._analyze_error_distribution(recent_errors)
        
        # Calculate health score
        health_score = self._calculate_health_score(error_analysis)
        overall_health = self._determine_health_state(error_analysis)
        
        return {
            "overall_health": overall_health,
            "health_score": health_score,
            "error_analysis": error_analysis,
            "recommendation": self._get_health_recommendation(overall_health, error_analysis),
            "time_window_hours": time_window_hours,
            "assessment_time": datetime.now().isoformat()
        }
    
    def _analyze_error_distribution(self, error_events: List[ErrorEvent]) -> Dict[str, Any]:
        """Analyze distribution of errors by severity and type"""
        
        # Count by severity
        informational_count = sum(1 for e in error_events if e.severity == ErrorSeverity.INFORMATIONAL)
        warning_count = sum(1 for e in error_events if e.severity == ErrorSeverity.WARNING)
        recoverable_count = sum(1 for e in error_events if e.severity == ErrorSeverity.RECOVERABLE)
        critical_count = sum(1 for e in error_events if e.severity == ErrorSeverity.CRITICAL)
        fatal_count = sum(1 for e in error_events if e.severity == ErrorSeverity.FATAL)
        
        total_events = len(error_events)
        real_failures = recoverable_count + critical_count + fatal_count
        
        # Calculate false positive rate
        false_positive_rate = (informational_count / total_events * 100) if total_events > 0 else 0
        
        # Count by category
        category_counts = {}
        for event in error_events:
            category = event.category
            category_counts[category] = category_counts.get(category, 0) + 1
        
        return {
            "total_events": total_events,
            "informational_count": informational_count,
            "warning_count": warning_count,
            "recoverable_count": recoverable_count,
            "critical_count": critical_count,
            "fatal_count": fatal_count,
            "real_failures": real_failures,
            "false_positive_rate": round(false_positive_rate, 1),
            "category_distribution": category_counts
        }
    
    def _calculate_health_score(self, error_analysis: Dict[str, Any]) -> float:
        """
        Calculate numeric health score (0.0 - 1.0)
        
        Args:
            error_analysis: Error distribution analysis
            
        Returns:
            Health score between 0.0 (critical) and 1.0 (perfect)
        """
        fatal_count = error_analysis["fatal_count"]
        critical_count = error_analysis["critical_count"]
        recoverable_count = error_analysis["recoverable_count"]
        total_events = error_analysis["total_events"]
        
        # Fatal errors = 0.0 score
        if fatal_count > 0:
            return 0.0
        
        # Critical errors significantly impact score
        if critical_count >= 5:
            return 0.1  # Multiple critical errors
        elif critical_count >= 3:
            return 0.3  # Several critical errors
        elif critical_count >= 1:
            return 0.6  # Some critical errors
        
        # Recoverable errors moderately impact score
        if recoverable_count >= 20:
            return 0.4  # Many recoverable errors
        elif recoverable_count >= 10:
            return 0.7  # Some recoverable errors
        elif recoverable_count >= 5:
            return 0.8  # Few recoverable errors
        
        # Mostly informational = excellent health
        return 1.0
    
    def _determine_health_state(self, error_analysis: Dict[str, Any]) -> str:
        """
        Determine health state for dashboard display
        
        Args:
            error_analysis: Error distribution analysis
            
        Returns:
            Health state: healthy, warning, degraded, critical
        """
        fatal_count = error_analysis["fatal_count"]
        critical_count = error_analysis["critical_count"]
        recoverable_count = error_analysis["recoverable_count"]
        
        # Fatal errors = critical state
        if fatal_count > 0:
            return "critical"
        
        # Multiple critical errors = critical state
        if critical_count >= 3:
            return "critical"
        
        # Some critical errors = degraded state
        if critical_count >= 1:
            return "degraded"
        
        # Many recoverable errors = warning state
        if recoverable_count >= 15:
            return "warning"
        
        # Some recoverable errors = degraded state
        if recoverable_count >= 5:
            return "degraded"
        
        # Mostly informational = healthy state
        return "healthy"
    
    def _get_health_recommendation(self, health_state: str, error_analysis: Dict[str, Any]) -> str:
        """Get human-readable health recommendation"""
        
        if health_state == "healthy":
            return "System operating normally with minimal issues"
        elif health_state == "warning":
            return f"Minor issues detected ({error_analysis['recoverable_count']} recoverable errors) - monitoring recommended"
        elif health_state == "degraded":
            if error_analysis["critical_count"] > 0:
                return f"System degraded with {error_analysis['critical_count']} critical errors requiring attention"
            else:
                return f"Performance degraded with {error_analysis['recoverable_count']} recoverable errors"
        else:  # critical
            return f"Critical system issues detected - immediate action required ({error_analysis['critical_count']} critical, {error_analysis['fatal_count']} fatal errors)"
    
    def get_device_health(self, device_id: int, time_window_hours: int = 1) -> Dict[str, Any]:
        """Calculate health for specific device"""
        
        cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
        
        device_errors = self.db.query(ErrorEvent).filter(
            ErrorEvent.device_id == device_id,
            ErrorEvent.timestamp >= cutoff_time
        ).all()
        
        if not device_errors:
            return {
                "device_id": device_id,
                "overall_health": "healthy",
                "health_score": 1.0,
                "error_count": 0,
                "recommendation": "No recent errors for this device"
            }
        
        error_analysis = self._analyze_error_distribution(device_errors)
        health_score = self._calculate_health_score(error_analysis)
        overall_health = self._determine_health_state(error_analysis)
        
        return {
            "device_id": device_id,
            "overall_health": overall_health,
            "health_score": health_score,
            "error_analysis": error_analysis,
            "recommendation": self._get_health_recommendation(overall_health, error_analysis)
        }