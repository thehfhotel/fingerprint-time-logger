"""
Conflict Detection and Resolution for Offline-First Architecture

This service handles data conflicts that may arise when synchronizing
data between local storage and ZKTeco devices, ensuring data integrity
and consistency across offline/online transitions.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple, Union
from enum import Enum
from dataclasses import dataclass
from sqlalchemy.orm import Session
import json

from app.models.models import AttendanceRecord, Employee, Device, SyncQueue
from app.services.cache_service import CacheService


class ConflictType(Enum):
    """Types of data conflicts"""
    DUPLICATE_ATTENDANCE = "duplicate_attendance"
    TIMESTAMP_MISMATCH = "timestamp_mismatch"
    EMPLOYEE_ID_CONFLICT = "employee_id_conflict"
    DEVICE_TIME_DRIFT = "device_time_drift"
    MANUAL_VS_DEVICE = "manual_vs_device"
    CONCURRENT_MODIFICATION = "concurrent_modification"


class ConflictResolution(Enum):
    """Conflict resolution strategies"""
    USE_DEVICE_DATA = "use_device_data"      # Device is source of truth
    USE_LOCAL_DATA = "use_local_data"        # Local data takes precedence
    MERGE_DATA = "merge_data"                # Combine both sources
    MANUAL_REVIEW = "manual_review"          # Requires human intervention
    IGNORE_CONFLICT = "ignore_conflict"      # Accept conflict as-is


@dataclass
class ConflictRecord:
    """Represents a detected conflict"""
    conflict_id: str
    conflict_type: ConflictType
    description: str
    local_record: Optional[Dict]
    device_record: Optional[Dict]
    suggested_resolution: ConflictResolution
    severity: str  # "low", "medium", "high", "critical"
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    resolution_applied: Optional[ConflictResolution] = None
    metadata: Optional[Dict] = None


class ConflictResolver:
    """
    Handles conflict detection and resolution for data synchronization
    
    Features:
    - Automatic conflict detection during sync
    - Intelligent resolution suggestions
    - Manual conflict review interface
    - Conflict resolution audit trail
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.cache_service = CacheService(db)
        
        # Conflict detection thresholds
        self.time_drift_threshold_minutes = 5
        self.duplicate_window_minutes = 2
        
        # Resolution policies
        self.auto_resolve_policies = {
            ConflictType.DUPLICATE_ATTENDANCE: ConflictResolution.USE_DEVICE_DATA,
            ConflictType.DEVICE_TIME_DRIFT: ConflictResolution.MERGE_DATA,
            ConflictType.TIMESTAMP_MISMATCH: ConflictResolution.USE_DEVICE_DATA,
            ConflictType.EMPLOYEE_ID_CONFLICT: ConflictResolution.MANUAL_REVIEW,
            ConflictType.MANUAL_VS_DEVICE: ConflictResolution.MANUAL_REVIEW,
            ConflictType.CONCURRENT_MODIFICATION: ConflictResolution.MANUAL_REVIEW
        }
        
        print("🔍 ConflictResolver initialized")
    
    def detect_conflicts(self, 
                        local_records: List[Dict], 
                        device_records: List[Dict], 
                        device_id: int) -> List[ConflictRecord]:
        """
        Detect conflicts between local and device data
        
        Args:
            local_records: Records from local database
            device_records: Records from ZKTeco device
            device_id: Device ID being synchronized
            
        Returns:
            List of detected conflicts
        """
        conflicts = []
        
        try:
            print(f"🔍 Detecting conflicts for device {device_id}")
            print(f"   Local records: {len(local_records)}, Device records: {len(device_records)}")
            
            # Check for duplicate attendance records
            conflicts.extend(self._detect_duplicate_attendance(local_records, device_records, device_id))
            
            # Check for timestamp mismatches
            conflicts.extend(self._detect_timestamp_mismatches(local_records, device_records, device_id))
            
            # Check for device time drift
            conflicts.extend(self._detect_device_time_drift(device_id))
            
            # Check for manual vs device conflicts
            conflicts.extend(self._detect_manual_vs_device_conflicts(local_records, device_records, device_id))
            
            # Check for concurrent modifications
            conflicts.extend(self._detect_concurrent_modifications(local_records, device_records, device_id))
            
            if conflicts:
                print(f"⚠️  Detected {len(conflicts)} conflicts for device {device_id}")
                self._cache_conflicts(conflicts, device_id)
            else:
                print(f"✅ No conflicts detected for device {device_id}")
            
            return conflicts
            
        except Exception as e:
            print(f"❌ Error detecting conflicts: {e}")
            return []
    
    def _detect_duplicate_attendance(self, 
                                   local_records: List[Dict], 
                                   device_records: List[Dict], 
                                   device_id: int) -> List[ConflictRecord]:
        """Detect duplicate attendance records"""
        conflicts = []
        
        try:
            # Create lookup for local records
            local_lookup = {}
            for record in local_records:
                key = f"{record.get('employee_id')}_{record.get('timestamp')}"
                local_lookup[key] = record
            
            # Check device records against local records
            for device_record in device_records:
                device_key = f"{device_record.get('employee_id')}_{device_record.get('timestamp')}"
                
                # Check for exact matches
                if device_key in local_lookup:
                    local_record = local_lookup[device_key]
                    
                    # Check if there are differences in punch_type or status
                    if (local_record.get('punch_type') != device_record.get('punch_type') or
                        local_record.get('status') != device_record.get('status')):
                        
                        conflict = ConflictRecord(
                            conflict_id=f"dup_{device_id}_{device_key}_{int(datetime.now().timestamp())}",
                            conflict_type=ConflictType.DUPLICATE_ATTENDANCE,
                            description=f"Duplicate attendance with different data for employee {device_record.get('employee_id')}",
                            local_record=local_record,
                            device_record=device_record,
                            suggested_resolution=ConflictResolution.USE_DEVICE_DATA,
                            severity="medium",
                            detected_at=datetime.now(),
                            metadata={"device_id": device_id}
                        )
                        conflicts.append(conflict)
                
                # Check for near-duplicate records (within time window)
                employee_id = device_record.get('employee_id')
                device_timestamp = device_record.get('timestamp')
                
                if isinstance(device_timestamp, str):
                    device_timestamp = datetime.fromisoformat(device_timestamp.replace('Z', '+00:00'))
                
                for local_record in local_records:
                    if local_record.get('employee_id') != employee_id:
                        continue
                    
                    local_timestamp = local_record.get('timestamp')
                    if isinstance(local_timestamp, str):
                        local_timestamp = datetime.fromisoformat(local_timestamp.replace('Z', '+00:00'))
                    
                    # Check if within duplicate window
                    time_diff = abs((device_timestamp - local_timestamp).total_seconds())
                    if time_diff <= (self.duplicate_window_minutes * 60) and time_diff > 0:
                        conflict = ConflictRecord(
                            conflict_id=f"near_dup_{device_id}_{employee_id}_{int(datetime.now().timestamp())}",
                            conflict_type=ConflictType.DUPLICATE_ATTENDANCE,
                            description=f"Near-duplicate attendance within {self.duplicate_window_minutes} minutes",
                            local_record=local_record,
                            device_record=device_record,
                            suggested_resolution=ConflictResolution.MERGE_DATA,
                            severity="low",
                            detected_at=datetime.now(),
                            metadata={"device_id": device_id, "time_diff_seconds": time_diff}
                        )
                        conflicts.append(conflict)
            
            return conflicts
            
        except Exception as e:
            print(f"❌ Error detecting duplicate attendance: {e}")
            return []
    
    def _detect_timestamp_mismatches(self, 
                                   local_records: List[Dict], 
                                   device_records: List[Dict], 
                                   device_id: int) -> List[ConflictRecord]:
        """Detect timestamp mismatches that might indicate clock drift"""
        conflicts = []
        
        try:
            # Get device current time
            device = self.db.query(Device).filter(Device.id == device_id).first()
            if not device:
                return conflicts
            
            # For this implementation, we'll check if timestamps are unreasonably in the future or past
            current_time = datetime.now()
            future_threshold = current_time + timedelta(hours=1)
            past_threshold = current_time - timedelta(days=30)
            
            for record in device_records:
                timestamp = record.get('timestamp')
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                
                if timestamp > future_threshold:
                    conflict = ConflictRecord(
                        conflict_id=f"future_{device_id}_{int(datetime.now().timestamp())}",
                        conflict_type=ConflictType.TIMESTAMP_MISMATCH,
                        description=f"Device timestamp is in the future: {timestamp}",
                        local_record=None,
                        device_record=record,
                        suggested_resolution=ConflictResolution.MANUAL_REVIEW,
                        severity="high",
                        detected_at=datetime.now(),
                        metadata={"device_id": device_id, "future_by_hours": (timestamp - current_time).total_seconds() / 3600}
                    )
                    conflicts.append(conflict)
                
                elif timestamp < past_threshold:
                    conflict = ConflictRecord(
                        conflict_id=f"past_{device_id}_{int(datetime.now().timestamp())}",
                        conflict_type=ConflictType.TIMESTAMP_MISMATCH,
                        description=f"Device timestamp is too far in the past: {timestamp}",
                        local_record=None,
                        device_record=record,
                        suggested_resolution=ConflictResolution.IGNORE_CONFLICT,
                        severity="low",
                        detected_at=datetime.now(),
                        metadata={"device_id": device_id, "past_by_days": (current_time - timestamp).days}
                    )
                    conflicts.append(conflict)
            
            return conflicts
            
        except Exception as e:
            print(f"❌ Error detecting timestamp mismatches: {e}")
            return []
    
    def _detect_device_time_drift(self, device_id: int) -> List[ConflictRecord]:
        """Detect if device clock has drifted from system time"""
        conflicts = []
        
        try:
            # This would require connecting to device to get current time
            # For now, we'll simulate this check
            
            # Get the last known device status
            device_status = self.cache_service.get_device_status(device_id)
            
            if device_status and device_status.get("metadata"):
                metadata = device_status.get("metadata", {})
                if "device_time" in metadata:
                    device_time_str = metadata["device_time"]
                    device_time = datetime.fromisoformat(device_time_str.replace('Z', '+00:00'))
                    current_time = datetime.now()
                    
                    time_diff_minutes = abs((device_time - current_time).total_seconds()) / 60
                    
                    if time_diff_minutes > self.time_drift_threshold_minutes:
                        conflict = ConflictRecord(
                            conflict_id=f"time_drift_{device_id}_{int(datetime.now().timestamp())}",
                            conflict_type=ConflictType.DEVICE_TIME_DRIFT,
                            description=f"Device clock drift detected: {time_diff_minutes:.1f} minutes",
                            local_record={"system_time": current_time.isoformat()},
                            device_record={"device_time": device_time.isoformat()},
                            suggested_resolution=ConflictResolution.MERGE_DATA,
                            severity="medium" if time_diff_minutes < 30 else "high",
                            detected_at=datetime.now(),
                            metadata={"device_id": device_id, "drift_minutes": time_diff_minutes}
                        )
                        conflicts.append(conflict)
            
            return conflicts
            
        except Exception as e:
            print(f"❌ Error detecting device time drift: {e}")
            return []
    
    def _detect_manual_vs_device_conflicts(self, 
                                         local_records: List[Dict], 
                                         device_records: List[Dict], 
                                         device_id: int) -> List[ConflictRecord]:
        """Detect conflicts between manually entered and device-generated records"""
        conflicts = []
        
        try:
            # Get locally created records
            manual_records = [r for r in local_records if r.get('created_locally', False)]
            
            for manual_record in manual_records:
                employee_id = manual_record.get('employee_id')
                manual_timestamp = manual_record.get('timestamp')
                
                if isinstance(manual_timestamp, str):
                    manual_timestamp = datetime.fromisoformat(manual_timestamp.replace('Z', '+00:00'))
                
                # Look for conflicting device records
                for device_record in device_records:
                    if device_record.get('employee_id') != employee_id:
                        continue
                    
                    device_timestamp = device_record.get('timestamp')
                    if isinstance(device_timestamp, str):
                        device_timestamp = datetime.fromisoformat(device_timestamp.replace('Z', '+00:00'))
                    
                    # Check if they're close in time but different punch types
                    time_diff = abs((manual_timestamp - device_timestamp).total_seconds())
                    if (time_diff <= 300 and  # Within 5 minutes
                        manual_record.get('punch_type') != device_record.get('punch_type')):
                        
                        conflict = ConflictRecord(
                            conflict_id=f"manual_vs_device_{device_id}_{employee_id}_{int(datetime.now().timestamp())}",
                            conflict_type=ConflictType.MANUAL_VS_DEVICE,
                            description=f"Manual entry conflicts with device record for employee {employee_id}",
                            local_record=manual_record,
                            device_record=device_record,
                            suggested_resolution=ConflictResolution.MANUAL_REVIEW,
                            severity="high",
                            detected_at=datetime.now(),
                            metadata={"device_id": device_id, "time_diff_seconds": time_diff}
                        )
                        conflicts.append(conflict)
            
            return conflicts
            
        except Exception as e:
            print(f"❌ Error detecting manual vs device conflicts: {e}")
            return []
    
    def _detect_concurrent_modifications(self, 
                                       local_records: List[Dict], 
                                       device_records: List[Dict], 
                                       device_id: int) -> List[ConflictRecord]:
        """Detect concurrent modifications to the same data"""
        conflicts = []
        
        try:
            # Check for records that have been modified both locally and on device
            # This is a simplified implementation
            
            for local_record in local_records:
                if local_record.get('sync_status') == 'pending':  # Was modified locally
                    employee_id = local_record.get('employee_id')
                    local_timestamp = local_record.get('timestamp')
                    
                    # Look for corresponding device record
                    for device_record in device_records:
                        if (device_record.get('employee_id') == employee_id and
                            device_record.get('timestamp') == local_timestamp):
                            
                            # Check if any data differs
                            if (local_record.get('punch_type') != device_record.get('punch_type') or
                                local_record.get('status') != device_record.get('status')):
                                
                                conflict = ConflictRecord(
                                    conflict_id=f"concurrent_{device_id}_{employee_id}_{int(datetime.now().timestamp())}",
                                    conflict_type=ConflictType.CONCURRENT_MODIFICATION,
                                    description=f"Concurrent modification detected for employee {employee_id}",
                                    local_record=local_record,
                                    device_record=device_record,
                                    suggested_resolution=ConflictResolution.MANUAL_REVIEW,
                                    severity="high",
                                    detected_at=datetime.now(),
                                    metadata={"device_id": device_id}
                                )
                                conflicts.append(conflict)
            
            return conflicts
            
        except Exception as e:
            print(f"❌ Error detecting concurrent modifications: {e}")
            return []
    
    def resolve_conflict(self, conflict: ConflictRecord, resolution: ConflictResolution = None) -> bool:
        """
        Resolve a specific conflict
        
        Args:
            conflict: The conflict to resolve
            resolution: Resolution strategy (uses suggested if None)
            
        Returns:
            bool: True if resolution was successful
        """
        try:
            if resolution is None:
                resolution = conflict.suggested_resolution
            
            print(f"🔧 Resolving conflict {conflict.conflict_id} with strategy: {resolution.value}")
            
            success = False
            
            if resolution == ConflictResolution.USE_DEVICE_DATA:
                success = self._apply_device_data_resolution(conflict)
            elif resolution == ConflictResolution.USE_LOCAL_DATA:
                success = self._apply_local_data_resolution(conflict)
            elif resolution == ConflictResolution.MERGE_DATA:
                success = self._apply_merge_resolution(conflict)
            elif resolution == ConflictResolution.IGNORE_CONFLICT:
                success = self._apply_ignore_resolution(conflict)
            elif resolution == ConflictResolution.MANUAL_REVIEW:
                success = self._queue_manual_review(conflict)
            
            if success:
                conflict.resolved_at = datetime.now()
                conflict.resolution_applied = resolution
                self._cache_resolved_conflict(conflict)
                print(f"✅ Conflict {conflict.conflict_id} resolved successfully")
            else:
                print(f"❌ Failed to resolve conflict {conflict.conflict_id}")
            
            return success
            
        except Exception as e:
            print(f"❌ Error resolving conflict {conflict.conflict_id}: {e}")
            return False
    
    def _apply_device_data_resolution(self, conflict: ConflictRecord) -> bool:
        """Apply resolution using device data as source of truth"""
        try:
            if not conflict.device_record:
                return False
            
            device_record = conflict.device_record
            
            # Update or create local record with device data
            if conflict.conflict_type == ConflictType.DUPLICATE_ATTENDANCE:
                # Find and update the local record
                attendance = self.db.query(AttendanceRecord).filter(
                    AttendanceRecord.employee_id == device_record.get('employee_id'),
                    AttendanceRecord.timestamp == device_record.get('timestamp')
                ).first()
                
                if attendance:
                    attendance.punch_type = device_record.get('punch_type')
                    attendance.status = device_record.get('status')
                    attendance.sync_status = 'synced'
                    self.db.commit()
                    return True
            
            return True
            
        except Exception as e:
            print(f"❌ Error applying device data resolution: {e}")
            return False
    
    def _apply_local_data_resolution(self, conflict: ConflictRecord) -> bool:
        """Apply resolution using local data as source of truth"""
        try:
            if not conflict.local_record:
                return False
            
            # Mark local record as authoritative
            # In a full implementation, this might sync back to device
            local_record = conflict.local_record
            
            if conflict.conflict_type == ConflictType.MANUAL_VS_DEVICE:
                # Keep the manually entered data
                attendance = self.db.query(AttendanceRecord).filter(
                    AttendanceRecord.employee_id == local_record.get('employee_id'),
                    AttendanceRecord.timestamp == local_record.get('timestamp'),
                    AttendanceRecord.created_locally == True
                ).first()
                
                if attendance:
                    attendance.sync_status = 'local_authoritative'
                    self.db.commit()
                    return True
            
            return True
            
        except Exception as e:
            print(f"❌ Error applying local data resolution: {e}")
            return False
    
    def _apply_merge_resolution(self, conflict: ConflictRecord) -> bool:
        """Apply resolution by merging local and device data"""
        try:
            if conflict.conflict_type == ConflictType.DEVICE_TIME_DRIFT:
                # Log the time drift but don't modify data
                print(f"⚠️  Device time drift noted: {conflict.description}")
                return True
            
            elif conflict.conflict_type == ConflictType.DUPLICATE_ATTENDANCE:
                # Keep both records but mark them appropriately
                if conflict.local_record and conflict.device_record:
                    # Update local record to note the conflict
                    attendance = self.db.query(AttendanceRecord).filter(
                        AttendanceRecord.employee_id == conflict.local_record.get('employee_id'),
                        AttendanceRecord.timestamp == conflict.local_record.get('timestamp')
                    ).first()
                    
                    if attendance:
                        attendance.sync_status = 'merged_conflict'
                        self.db.commit()
                        return True
            
            return True
            
        except Exception as e:
            print(f"❌ Error applying merge resolution: {e}")
            return False
    
    def _apply_ignore_resolution(self, conflict: ConflictRecord) -> bool:
        """Apply resolution by ignoring the conflict"""
        try:
            # Simply log that we're ignoring this conflict
            print(f"🤷 Ignoring conflict: {conflict.description}")
            return True
            
        except Exception as e:
            print(f"❌ Error applying ignore resolution: {e}")
            return False
    
    def _queue_manual_review(self, conflict: ConflictRecord) -> bool:
        """Queue conflict for manual review"""
        try:
            # Cache conflict for manual review interface
            self.cache_service.set_cache(
                f"manual_review_conflict_{conflict.conflict_id}",
                {
                    "conflict_id": conflict.conflict_id,
                    "conflict_type": conflict.conflict_type.value,
                    "description": conflict.description,
                    "local_record": conflict.local_record,
                    "device_record": conflict.device_record,
                    "severity": conflict.severity,
                    "detected_at": conflict.detected_at.isoformat(),
                    "metadata": conflict.metadata
                },
                expires_in_hours=168  # Keep for a week
            )
            
            print(f"📋 Conflict {conflict.conflict_id} queued for manual review")
            return True
            
        except Exception as e:
            print(f"❌ Error queueing conflict for manual review: {e}")
            return False
    
    def _cache_conflicts(self, conflicts: List[ConflictRecord], device_id: int) -> None:
        """Cache detected conflicts for later review"""
        try:
            conflicts_data = []
            for conflict in conflicts:
                conflicts_data.append({
                    "conflict_id": conflict.conflict_id,
                    "conflict_type": conflict.conflict_type.value,
                    "description": conflict.description,
                    "severity": conflict.severity,
                    "detected_at": conflict.detected_at.isoformat(),
                    "suggested_resolution": conflict.suggested_resolution.value
                })
            
            self.cache_service.set_cache(
                f"conflicts_device_{device_id}",
                {
                    "device_id": device_id,
                    "conflict_count": len(conflicts),
                    "conflicts": conflicts_data,
                    "detected_at": datetime.now().isoformat()
                },
                expires_in_hours=48
            )
            
        except Exception as e:
            print(f"❌ Error caching conflicts: {e}")
    
    def _cache_resolved_conflict(self, conflict: ConflictRecord) -> None:
        """Cache resolved conflict for audit trail"""
        try:
            self.cache_service.set_cache(
                f"resolved_conflict_{conflict.conflict_id}",
                {
                    "conflict_id": conflict.conflict_id,
                    "conflict_type": conflict.conflict_type.value,
                    "description": conflict.description,
                    "resolution_applied": conflict.resolution_applied.value if conflict.resolution_applied else None,
                    "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
                    "severity": conflict.severity
                },
                expires_in_hours=168  # Keep for a week
            )
            
        except Exception as e:
            print(f"❌ Error caching resolved conflict: {e}")
    
    def get_pending_conflicts(self, device_id: int = None) -> List[Dict]:
        """Get conflicts pending manual review"""
        try:
            # This is a simplified implementation
            # In practice, you'd query a conflicts table or cache
            
            if device_id:
                cached_conflicts = self.cache_service.get_cache(f"conflicts_device_{device_id}")
                if cached_conflicts:
                    return cached_conflicts.get("conflicts", [])
            
            return []
            
        except Exception as e:
            print(f"❌ Error getting pending conflicts: {e}")
            return []
    
    def auto_resolve_conflicts(self, conflicts: List[ConflictRecord]) -> Tuple[int, int]:
        """
        Automatically resolve conflicts based on policies
        
        Returns:
            Tuple of (resolved_count, failed_count)
        """
        resolved_count = 0
        failed_count = 0
        
        for conflict in conflicts:
            try:
                # Check if this conflict type can be auto-resolved
                auto_resolution = self.auto_resolve_policies.get(conflict.conflict_type)
                
                if auto_resolution and auto_resolution != ConflictResolution.MANUAL_REVIEW:
                    if self.resolve_conflict(conflict, auto_resolution):
                        resolved_count += 1
                    else:
                        failed_count += 1
                else:
                    # Queue for manual review
                    if self._queue_manual_review(conflict):
                        resolved_count += 1
                    else:
                        failed_count += 1
                        
            except Exception as e:
                print(f"❌ Error auto-resolving conflict {conflict.conflict_id}: {e}")
                failed_count += 1
        
        print(f"🔧 Auto-resolved {resolved_count} conflicts, {failed_count} failed")
        return resolved_count, failed_count


# Convenience function
def get_conflict_resolver(db: Session) -> ConflictResolver:
    """Get a conflict resolver instance"""
    return ConflictResolver(db)