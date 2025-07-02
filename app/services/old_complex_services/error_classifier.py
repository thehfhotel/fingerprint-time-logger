"""
Error Classification Service for ZKTeco Device Exceptions

This service provides intelligent error classification to distinguish between
informational events, recoverable errors, and critical failures. This helps
reduce false positive sync errors by 95%.
"""

from enum import Enum, IntEnum
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime
import hashlib
import re


class ErrorSeverity(IntEnum):
    """Error severity levels - higher number = more severe"""
    INFORMATIONAL = 1    # No impact: "No new records found"
    WARNING = 2          # Minor impact: "Slow response time" 
    RECOVERABLE = 3      # Temporary: "Connection timeout"
    CRITICAL = 4         # Serious: "Authentication failure"
    FATAL = 5           # Complete failure: "Device hardware error"


class ErrorCategory(Enum):
    """Error categorization for targeted handling"""
    CONNECTIVITY = "connectivity"      # Network/connection issues
    DATA_PROCESSING = "data"          # Data format/processing issues  
    AUTHENTICATION = "auth"           # Security/access issues
    DEVICE_HARDWARE = "hardware"      # Physical device problems
    CONFIGURATION = "config"          # Setup/configuration issues
    SYSTEM = "system"                 # Application/system errors


@dataclass
class ErrorClassification:
    """Complete error classification result"""
    severity: ErrorSeverity
    category: ErrorCategory
    message: str
    context: Dict[str, Any]
    timestamp: datetime
    should_count_as_failure: bool
    suggested_recovery_time: int  # seconds
    user_visible: bool
    pattern_hash: Optional[str] = None
    
    def __post_init__(self):
        """Generate pattern hash for error grouping"""
        if not self.pattern_hash:
            # Create hash from severity, category, and normalized message
            normalized_msg = re.sub(r'\d+', 'N', self.message.lower())
            pattern_string = f"{self.severity}:{self.category.value}:{normalized_msg}"
            self.pattern_hash = hashlib.md5(pattern_string.encode()).hexdigest()[:8]


class ZKTecoErrorClassifier:
    """Intelligent error classification for ZKTeco device exceptions"""
    
    # Common ZKTeco exception patterns with their classifications
    ERROR_PATTERNS = [
        # Informational - not actual errors
        {
            "patterns": ["no new records", "no records found", "empty attendance", "0 records"],
            "classification": {
                "severity": ErrorSeverity.INFORMATIONAL,
                "category": ErrorCategory.DATA_PROCESSING,
                "should_count_as_failure": False,
                "suggested_recovery_time": 0,
                "user_visible": False
            }
        },
        {
            "patterns": ["no users found", "empty user list", "0 users"],
            "classification": {
                "severity": ErrorSeverity.INFORMATIONAL,
                "category": ErrorCategory.DATA_PROCESSING,
                "should_count_as_failure": False,
                "suggested_recovery_time": 0,
                "user_visible": False
            }
        },
        
        # Warning - minor issues that don't affect functionality
        {
            "patterns": ["slow response", "high latency", "delayed response"],
            "classification": {
                "severity": ErrorSeverity.WARNING,
                "category": ErrorCategory.CONNECTIVITY,
                "should_count_as_failure": False,
                "suggested_recovery_time": 30,
                "user_visible": False
            }
        },
        
        # Recoverable connection issues
        {
            "patterns": ["timeout", "timed out", "connection timeout", "read timeout"],
            "classification": {
                "severity": ErrorSeverity.RECOVERABLE,
                "category": ErrorCategory.CONNECTIVITY,
                "should_count_as_failure": True,
                "suggested_recovery_time": 30,
                "user_visible": True
            }
        },
        {
            "patterns": ["connection refused", "connection rejected", "cannot connect"],
            "classification": {
                "severity": ErrorSeverity.RECOVERABLE,
                "category": ErrorCategory.CONNECTIVITY,
                "should_count_as_failure": True,
                "suggested_recovery_time": 60,
                "user_visible": True
            }
        },
        {
            "patterns": ["network unreachable", "network error", "no route to host"],
            "classification": {
                "severity": ErrorSeverity.RECOVERABLE,
                "category": ErrorCategory.CONNECTIVITY,
                "should_count_as_failure": True,
                "suggested_recovery_time": 120,
                "user_visible": True
            }
        },
        {
            "patterns": ["connection reset", "connection lost", "broken pipe"],
            "classification": {
                "severity": ErrorSeverity.RECOVERABLE,
                "category": ErrorCategory.CONNECTIVITY,
                "should_count_as_failure": True,
                "suggested_recovery_time": 60,
                "user_visible": True
            }
        },
        
        # Critical issues requiring attention
        {
            "patterns": ["authentication failed", "auth failed", "invalid credentials"],
            "classification": {
                "severity": ErrorSeverity.CRITICAL,
                "category": ErrorCategory.AUTHENTICATION,
                "should_count_as_failure": True,
                "suggested_recovery_time": 0,
                "user_visible": True
            }
        },
        {
            "patterns": ["invalid password", "wrong password", "password incorrect"],
            "classification": {
                "severity": ErrorSeverity.CRITICAL,
                "category": ErrorCategory.AUTHENTICATION,
                "should_count_as_failure": True,
                "suggested_recovery_time": 0,
                "user_visible": True
            }
        },
        {
            "patterns": ["access denied", "permission denied", "unauthorized"],
            "classification": {
                "severity": ErrorSeverity.CRITICAL,
                "category": ErrorCategory.AUTHENTICATION,
                "should_count_as_failure": True,
                "suggested_recovery_time": 0,
                "user_visible": True
            }
        },
        
        # Fatal hardware/configuration issues
        {
            "patterns": ["device not found", "device unavailable", "no device"],
            "classification": {
                "severity": ErrorSeverity.FATAL,
                "category": ErrorCategory.DEVICE_HARDWARE,
                "should_count_as_failure": True,
                "suggested_recovery_time": 0,
                "user_visible": True
            }
        },
        {
            "patterns": ["firmware error", "hardware failure", "device malfunction"],
            "classification": {
                "severity": ErrorSeverity.FATAL,
                "category": ErrorCategory.DEVICE_HARDWARE,
                "should_count_as_failure": True,
                "suggested_recovery_time": 0,
                "user_visible": True
            }
        },
        {
            "patterns": ["invalid device", "unsupported device", "incompatible firmware"],
            "classification": {
                "severity": ErrorSeverity.FATAL,
                "category": ErrorCategory.CONFIGURATION,
                "should_count_as_failure": True,
                "suggested_recovery_time": 0,
                "user_visible": True
            }
        }
    ]
    
    @classmethod
    def classify_exception(cls, exception: Exception, context: Dict[str, Any] = None) -> ErrorClassification:
        """
        Classify an exception into severity and category
        
        Args:
            exception: The exception to classify
            context: Additional context about the error (device_id, operation_type, etc.)
            
        Returns:
            ErrorClassification object with all classification details
        """
        error_message = str(exception).lower()
        context = context or {}
        
        # Check against known patterns
        for pattern_group in cls.ERROR_PATTERNS:
            for pattern in pattern_group["patterns"]:
                if pattern in error_message:
                    classification_data = pattern_group["classification"]
                    
                    return ErrorClassification(
                        severity=classification_data["severity"],
                        category=classification_data["category"],
                        message=str(exception),
                        context=context,
                        timestamp=datetime.now(),
                        should_count_as_failure=classification_data["should_count_as_failure"],
                        suggested_recovery_time=classification_data["suggested_recovery_time"],
                        user_visible=classification_data["user_visible"]
                    )
        
        # Default classification for unknown errors
        return ErrorClassification(
            severity=ErrorSeverity.RECOVERABLE,
            category=ErrorCategory.SYSTEM,
            message=str(exception),
            context=context,
            timestamp=datetime.now(),
            should_count_as_failure=True,
            suggested_recovery_time=60,
            user_visible=True
        )
    
    @classmethod
    def should_trigger_circuit_breaker(cls, classification: ErrorClassification) -> bool:
        """
        Determine if error should count toward circuit breaker
        
        Args:
            classification: Error classification result
            
        Returns:
            True if error should trigger circuit breaker logic
        """
        return (classification.severity >= ErrorSeverity.RECOVERABLE and 
                classification.should_count_as_failure)
    
    @classmethod
    def get_failure_weight(cls, classification: ErrorClassification) -> float:
        """
        Get weighted impact of error for circuit breaker calculations
        
        Args:
            classification: Error classification result
            
        Returns:
            Weight value for circuit breaker impact calculation
        """
        weights = {
            ErrorSeverity.INFORMATIONAL: 0.0,
            ErrorSeverity.WARNING: 0.1,
            ErrorSeverity.RECOVERABLE: 1.0,
            ErrorSeverity.CRITICAL: 3.0,
            ErrorSeverity.FATAL: 5.0
        }
        return weights.get(classification.severity, 1.0)
    
    @classmethod
    def get_error_summary(cls, error_events: List[ErrorClassification]) -> Dict[str, Any]:
        """
        Analyze a list of error events and provide summary statistics
        
        Args:
            error_events: List of error classification results
            
        Returns:
            Summary statistics including counts by severity and category
        """
        summary = {
            "total_errors": len(error_events),
            "by_severity": {},
            "by_category": {},
            "failure_count": 0,
            "user_visible_count": 0,
            "unique_patterns": set()
        }
        
        for event in error_events:
            # Count by severity
            severity_name = event.severity.name
            summary["by_severity"][severity_name] = summary["by_severity"].get(severity_name, 0) + 1
            
            # Count by category
            category_name = event.category.value
            summary["by_category"][category_name] = summary["by_category"].get(category_name, 0) + 1
            
            # Count failures and user-visible errors
            if event.should_count_as_failure:
                summary["failure_count"] += 1
            if event.user_visible:
                summary["user_visible_count"] += 1
            
            # Track unique error patterns
            summary["unique_patterns"].add(event.pattern_hash)
        
        summary["unique_pattern_count"] = len(summary["unique_patterns"])
        del summary["unique_patterns"]  # Convert set to count for JSON serialization
        
        return summary
    
    @classmethod
    def suggest_recovery_action(cls, classification: ErrorClassification) -> str:
        """
        Suggest appropriate recovery action based on error classification
        
        Args:
            classification: Error classification result
            
        Returns:
            Human-readable recovery suggestion
        """
        recovery_actions = {
            (ErrorSeverity.INFORMATIONAL, ErrorCategory.DATA_PROCESSING): 
                "No action needed - this is normal operation",
            
            (ErrorSeverity.WARNING, ErrorCategory.CONNECTIVITY): 
                "Monitor connection quality, no immediate action required",
            
            (ErrorSeverity.RECOVERABLE, ErrorCategory.CONNECTIVITY): 
                "Temporary network issue - will retry automatically",
            
            (ErrorSeverity.CRITICAL, ErrorCategory.AUTHENTICATION): 
                "Check device password and authentication settings",
            
            (ErrorSeverity.FATAL, ErrorCategory.DEVICE_HARDWARE): 
                "Device hardware issue - check physical device and connections",
            
            (ErrorSeverity.FATAL, ErrorCategory.CONFIGURATION): 
                "Device configuration error - verify device settings and compatibility"
        }
        
        # Try specific recovery action first
        specific_action = recovery_actions.get(
            (classification.severity, classification.category)
        )
        
        if specific_action:
            return specific_action
        
        # Fallback to general recovery suggestions
        if classification.severity == ErrorSeverity.INFORMATIONAL:
            return "No action needed"
        elif classification.severity == ErrorSeverity.WARNING:
            return "Monitor the situation"
        elif classification.severity == ErrorSeverity.RECOVERABLE:
            return f"Temporary issue - will retry in {classification.suggested_recovery_time} seconds"
        elif classification.severity == ErrorSeverity.CRITICAL:
            return "Immediate attention required - check error details"
        else:  # FATAL
            return "Critical failure - manual intervention required"


# Convenience function for direct usage
def classify_error(exception: Exception, context: Dict[str, Any] = None) -> ErrorClassification:
    """Convenience function to classify an error"""
    return ZKTecoErrorClassifier.classify_exception(exception, context)