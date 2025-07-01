"""
Unlimited Historical Data Sync Service
Handles complete dataset synchronization without record limits
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Generator, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from app.models.models import Device, AttendanceRecord, EmployeeThaiName, SyncLog
from app.services.device_service import DeviceService


class SyncMode(Enum):
    FULL_HISTORICAL = "full_historical"    # Complete historical data
    INCREMENTAL = "incremental"            # Only new records since last sync
    DATE_RANGE = "date_range"              # Specific date range
    RECOVERY = "recovery"                  # Recovery from failed sync


class ProcessingStrategy(Enum):
    MEMORY_EFFICIENT = "memory_efficient"  # Process in chunks to save memory
    SPEED_OPTIMIZED = "speed_optimized"    # Load more data for faster processing
    BALANCED = "balanced"                  # Balance between memory and speed


@dataclass
class SyncConfiguration:
    """Configuration for sync operations"""
    chunk_size: int = 100                     # Records per processing chunk
    max_memory_records: int = 10000           # Max records in memory at once
    batch_commit_size: int = 500              # Database commit batch size
    connection_timeout: int = 30              # Device connection timeout
    retry_attempts: int = 3                   # Retry failed operations
    progress_update_interval: int = 100       # Progress update frequency
    enable_detailed_logging: bool = True      # Detailed operation logging
    stop_on_duplicate_threshold: int = 50     # Stop after N consecutive duplicates (incremental)
    processing_strategy: ProcessingStrategy = ProcessingStrategy.BALANCED


@dataclass
class SyncMetrics:
    """Comprehensive sync operation metrics"""
    # Progress tracking
    total_device_records: int = 0
    processed_records: int = 0
    new_records_added: int = 0
    duplicate_records_skipped: int = 0
    error_records: int = 0
    
    # Performance metrics
    start_time: datetime = None
    last_update_time: datetime = None
    estimated_completion_time: datetime = None
    records_per_second: float = 0.0
    
    # Memory and processing
    current_memory_usage_mb: float = 0.0
    peak_memory_usage_mb: float = 0.0
    chunks_processed: int = 0
    database_commits: int = 0
    
    # Status
    is_running: bool = False
    is_completed: bool = False
    error_message: Optional[str] = None
    completion_percentage: float = 0.0
    
    # Additional info
    last_processed_timestamp: Optional[datetime] = None
    sync_mode: Optional[str] = None
    device_name: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for JSON serialization"""
        result = asdict(self)
        # Convert datetime objects to ISO strings
        for key, value in result.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat() if value else None
        return result


class UnlimitedSyncService:
    """
    Enhanced sync service for unlimited historical data retrieval
    Handles large datasets with memory-efficient processing
    """
    
    def __init__(self, device: Device, db: Session, config: SyncConfiguration = None):
        self.device = device
        self.db = db
        self.config = config or SyncConfiguration()
        self.logger = logging.getLogger(__name__)
        self.device_service = DeviceService(device)
        self.metrics = SyncMetrics()
        self._sync_log_id: Optional[int] = None
        
    async def sync_full_historical_data(self) -> SyncMetrics:
        """
        Synchronize complete historical dataset from device
        Handles unlimited records with memory-efficient processing
        """
        self.logger.info(f"Starting full historical sync for device: {self.device.name}")
        
        return await self._execute_sync(
            mode=SyncMode.FULL_HISTORICAL,
            start_date=None,
            end_date=None
        )
    
    async def sync_incremental_updates(self) -> SyncMetrics:
        """
        Synchronize only new records since last successful sync
        """
        last_sync_time = self._get_last_successful_sync_time()
        self.logger.info(f"Starting incremental sync from: {last_sync_time}")
        
        return await self._execute_sync(
            mode=SyncMode.INCREMENTAL,
            start_date=last_sync_time
        )
    
    async def sync_date_range(self, start_date: datetime, end_date: datetime) -> SyncMetrics:
        """
        Synchronize records within specific date range
        """
        self.logger.info(f"Starting date range sync: {start_date} to {end_date}")
        
        return await self._execute_sync(
            mode=SyncMode.DATE_RANGE,
            start_date=start_date,
            end_date=end_date
        )
    
    async def _execute_sync(
        self, 
        mode: SyncMode, 
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> SyncMetrics:
        """
        Core sync execution with unlimited data handling
        """
        self._initialize_sync(mode)
        
        try:
            # Connect to device
            if not self.device_service.connect():
                raise Exception("Failed to connect to ZK device")
            
            self.logger.info("Successfully connected to device")
            
            # Get all attendance records from device
            self.logger.info("Retrieving all attendance records from device...")
            device_records = self._get_all_device_records()
            
            self.metrics.total_device_records = len(device_records)
            self.logger.info(f"Retrieved {self.metrics.total_device_records} total records from device")
            
            # Filter records by date range if specified
            if start_date or end_date:
                device_records = self._filter_records_by_date(device_records, start_date, end_date)
                self.logger.info(f"Filtered to {len(device_records)} records within date range")
            
            # Process records in memory-efficient chunks
            await self._process_records_in_chunks(device_records, mode)
            
            # Mark sync as completed
            self._complete_sync()
            
        except Exception as e:
            self._handle_sync_error(e)
            raise
        finally:
            self.device_service.disconnect()
            self._update_sync_log()
        
        return self.metrics
    
    def _get_all_device_records(self) -> List[Dict[str, Any]]:
        """
        Retrieve ALL attendance records from device without limitations
        """
        try:
            # Get attendance records using device service
            raw_records = self.device_service.get_attendance()
            
            # Convert to standardized format
            standardized_records = []
            for record in raw_records:
                standardized_record = {
                    'user_id': str(record.get('user_id', '')),
                    'timestamp': record.get('timestamp'),
                    'punch_type': record.get('punch', 0),
                    'status': record.get('status', 0),
                    'device_user_id': record.get('user_id'),  # Keep original for reference
                }
                standardized_records.append(standardized_record)
            
            # Sort by timestamp (oldest first for historical sync)
            standardized_records.sort(key=lambda x: x['timestamp'] or datetime.min)
            
            self.logger.info(f"Successfully retrieved and standardized {len(standardized_records)} records")
            return standardized_records
            
        except Exception as e:
            self.logger.error(f"Failed to retrieve device records: {str(e)}")
            raise Exception(f"Device communication error: {str(e)}")
    
    def _filter_records_by_date(
        self, 
        records: List[Dict[str, Any]], 
        start_date: Optional[datetime], 
        end_date: Optional[datetime]
    ) -> List[Dict[str, Any]]:
        """
        Filter records by date range
        """
        filtered_records = []
        
        for record in records:
            record_time = record['timestamp']
            if not record_time:
                continue
                
            # Apply date filters
            if start_date and record_time < start_date:
                continue
            if end_date and record_time > end_date:
                continue
                
            filtered_records.append(record)
        
        return filtered_records
    
    async def _process_records_in_chunks(self, records: List[Dict[str, Any]], mode: SyncMode):
        """
        Process records in memory-efficient chunks
        """
        total_records = len(records)
        chunk_size = self.config.chunk_size
        chunks_total = (total_records + chunk_size - 1) // chunk_size
        
        self.logger.info(f"Processing {total_records} records in {chunks_total} chunks of {chunk_size}")
        
        consecutive_duplicates = 0
        records_batch = []
        
        for i in range(0, total_records, chunk_size):
            chunk_end = min(i + chunk_size, total_records)
            chunk = records[i:chunk_end]
            
            self.metrics.chunks_processed += 1
            
            # Process chunk
            chunk_result = await self._process_record_chunk(chunk, mode)
            
            # Update metrics
            self._update_metrics_from_chunk(chunk_result)
            
            # Handle incremental sync stopping condition
            if mode == SyncMode.INCREMENTAL:
                if chunk_result['all_duplicates']:
                    consecutive_duplicates += 1
                    if consecutive_duplicates >= 3:  # Stop after 3 consecutive duplicate chunks
                        self.logger.info("Stopping incremental sync - found consecutive duplicate chunks")
                        break
                else:
                    consecutive_duplicates = 0
            
            # Batch database commits for better performance
            records_batch.extend(chunk_result['new_records'])
            if len(records_batch) >= self.config.batch_commit_size:
                await self._commit_records_batch(records_batch)
                records_batch = []
            
            # Update progress
            progress_percentage = (chunk_end / total_records) * 100
            self.metrics.completion_percentage = progress_percentage
            
            if self.metrics.chunks_processed % 10 == 0:  # Log every 10 chunks
                self.logger.info(
                    f"Progress: {progress_percentage:.1f}% "
                    f"({chunk_end}/{total_records} records, "
                    f"{self.metrics.new_records_added} new, "
                    f"{self.metrics.duplicate_records_skipped} duplicates)"
                )
            
            # Brief pause to prevent overwhelming the system
            await asyncio.sleep(0.01)
        
        # Commit any remaining records
        if records_batch:
            await self._commit_records_batch(records_batch)
    
    async def _process_record_chunk(self, chunk: List[Dict[str, Any]], mode: SyncMode) -> Dict[str, Any]:
        """
        Process a single chunk of records
        """
        chunk_result = {
            'processed': 0,
            'new_records': [],
            'duplicates': 0,
            'errors': 0,
            'all_duplicates': True
        }
        
        for record in chunk:
            try:
                # Check if record already exists
                existing_record = self._find_existing_record(record)
                
                if existing_record:
                    chunk_result['duplicates'] += 1
                else:
                    # Prepare new record for batch insert
                    new_record = self._create_attendance_record_object(record)
                    if new_record:
                        chunk_result['new_records'].append(new_record)
                        chunk_result['all_duplicates'] = False
                    else:
                        chunk_result['errors'] += 1
                
                chunk_result['processed'] += 1
                
                # Update last processed timestamp
                if record['timestamp']:
                    self.metrics.last_processed_timestamp = record['timestamp']
                
            except Exception as e:
                self.logger.error(f"Error processing record: {str(e)}")
                chunk_result['errors'] += 1
        
        return chunk_result
    
    async def _commit_records_batch(self, records_batch: List[AttendanceRecord]):
        """
        Commit a batch of records to database
        """
        try:
            self.db.add_all(records_batch)
            self.db.commit()
            self.metrics.database_commits += 1
            self.logger.debug(f"Committed batch of {len(records_batch)} records")
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Failed to commit records batch: {str(e)}")
            raise
    
    def _find_existing_record(self, device_record: Dict[str, Any]) -> Optional[AttendanceRecord]:
        """
        Check if record already exists in database
        Enhanced duplicate detection with multiple strategies
        """
        # Strategy 1: Exact match
        exact_match = self.db.query(AttendanceRecord).filter(
            AttendanceRecord.employee_id == device_record['user_id'],
            AttendanceRecord.device_id == self.device.id,
            AttendanceRecord.timestamp == device_record['timestamp']
        ).first()
        
        if exact_match:
            return exact_match
        
        # Strategy 2: Near-time match (within 1 minute window)
        if device_record['timestamp']:
            time_window_start = device_record['timestamp'] - timedelta(minutes=1)
            time_window_end = device_record['timestamp'] + timedelta(minutes=1)
            
            near_match = self.db.query(AttendanceRecord).filter(
                AttendanceRecord.employee_id == device_record['user_id'],
                AttendanceRecord.device_id == self.device.id,
                AttendanceRecord.timestamp >= time_window_start,
                AttendanceRecord.timestamp <= time_window_end,
                AttendanceRecord.punch_type == device_record['punch_type']
            ).first()
            
            if near_match:
                return near_match
        
        return None
    
    def _create_attendance_record_object(self, device_record: Dict[str, Any]) -> Optional[AttendanceRecord]:
        """
        Create AttendanceRecord object from device record
        """
        try:
            # Validate required fields
            if not device_record['user_id'] or not device_record['timestamp']:
                return None
            
            # Create new attendance record
            attendance_record = AttendanceRecord(
                employee_id=device_record['user_id'],
                device_id=self.device.id,
                timestamp=device_record['timestamp'],
                punch_type=device_record['punch_type'],
                status=device_record['status'],
                sync_status='synced',
                created_locally=False
            )
            
            return attendance_record
            
        except Exception as e:
            self.logger.error(f"Failed to create attendance record: {str(e)}")
            return None
    
    def _initialize_sync(self, mode: SyncMode):
        """
        Initialize sync operation and metrics
        """
        self.metrics = SyncMetrics(
            start_time=datetime.now(),
            last_update_time=datetime.now(),
            is_running=True,
            sync_mode=mode.value,
            device_name=self.device.name
        )
        
        # Create sync log entry
        sync_log = SyncLog(
            device_id=self.device.id,
            sync_type=f"unlimited_{mode.value}",
            status="in_progress",
            started_at=self.metrics.start_time
        )
        self.db.add(sync_log)
        self.db.commit()
        self._sync_log_id = sync_log.id
        
        self.logger.info(f"Initialized sync operation: {mode.value}")
    
    def _update_metrics_from_chunk(self, chunk_result: Dict[str, Any]):
        """
        Update metrics from chunk processing result
        """
        self.metrics.processed_records += chunk_result['processed']
        self.metrics.new_records_added += len(chunk_result['new_records'])
        self.metrics.duplicate_records_skipped += chunk_result['duplicates']
        self.metrics.error_records += chunk_result['errors']
        
        # Calculate performance metrics
        now = datetime.now()
        self.metrics.last_update_time = now
        
        if self.metrics.start_time:
            elapsed_seconds = (now - self.metrics.start_time).total_seconds()
            if elapsed_seconds > 0:
                self.metrics.records_per_second = self.metrics.processed_records / elapsed_seconds
    
    def _complete_sync(self):
        """
        Mark sync as completed
        """
        self.metrics.is_running = False
        self.metrics.is_completed = True
        self.metrics.completion_percentage = 100.0
        
        # Update device last_sync timestamp
        self.device.last_sync = datetime.now()
        self.db.commit()
        
        self.logger.info(
            f"Sync completed successfully: "
            f"{self.metrics.new_records_added} new records added, "
            f"{self.metrics.duplicate_records_skipped} duplicates skipped, "
            f"{self.metrics.error_records} errors"
        )
    
    def _handle_sync_error(self, error: Exception):
        """
        Handle sync operation error
        """
        self.metrics.is_running = False
        self.metrics.error_message = str(error)
        self.logger.error(f"Sync failed with error: {str(error)}")
    
    def _update_sync_log(self):
        """
        Update sync log with final results
        """
        if self._sync_log_id:
            sync_log = self.db.query(SyncLog).filter(SyncLog.id == self._sync_log_id).first()
            if sync_log:
                sync_log.status = "completed" if self.metrics.is_completed else "failed"
                sync_log.completed_at = datetime.now()
                sync_log.records_synced = self.metrics.new_records_added
                sync_log.error_message = self.metrics.error_message
                self.db.commit()
    
    def _get_last_successful_sync_time(self) -> Optional[datetime]:
        """
        Get timestamp of last successful sync for incremental updates
        """
        last_sync = self.db.query(SyncLog).filter(
            SyncLog.device_id == self.device.id,
            SyncLog.status == "completed"
        ).order_by(desc(SyncLog.completed_at)).first()
        
        return last_sync.completed_at if last_sync else None
    
    def get_sync_progress(self) -> Dict[str, Any]:
        """
        Get current sync progress as dictionary
        """
        return self.metrics.to_dict()


# Convenience functions for easy usage
async def sync_device_full_historical(device_id: int, db: Session) -> SyncMetrics:
    """
    Convenience function to sync all historical data for a device
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise ValueError(f"Device {device_id} not found")
    
    sync_service = UnlimitedSyncService(device, db)
    return await sync_service.sync_full_historical_data()


async def sync_device_incremental(device_id: int, db: Session) -> SyncMetrics:
    """
    Convenience function to sync incremental updates for a device
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise ValueError(f"Device {device_id} not found")
    
    sync_service = UnlimitedSyncService(device, db)
    return await sync_service.sync_incremental_updates()