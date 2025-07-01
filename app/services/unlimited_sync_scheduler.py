"""
Unlimited Sync Scheduler
Automated scheduling for unlimited historical and incremental syncs
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Device, SyncLog
from app.services.unlimited_sync_service import (
    UnlimitedSyncService, 
    SyncConfiguration, 
    ProcessingStrategy
)


class UnlimitedSyncScheduler:
    """
    Scheduler for automated unlimited sync operations
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.is_running = False
        self.active_syncs: Dict[int, asyncio.Task] = {}  # device_id -> task
        self.last_incremental_sync: Dict[int, datetime] = {}
        self.last_full_sync: Dict[int, datetime] = {}
        
        # Configuration
        self.incremental_interval_minutes = 15  # Incremental sync every 15 minutes
        self.full_sync_interval_hours = 24      # Full sync every 24 hours
        self.max_concurrent_syncs = 2           # Maximum concurrent sync operations
    
    async def start_scheduler(self):
        """
        Start the automated sync scheduler
        """
        self.is_running = True
        self.logger.info("Starting unlimited sync scheduler")
        
        while self.is_running:
            try:
                await self._run_scheduled_syncs()
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                self.logger.error(f"Scheduler error: {str(e)}")
                await asyncio.sleep(60)
    
    def stop_scheduler(self):
        """
        Stop the scheduler and cancel active syncs
        """
        self.is_running = False
        
        # Cancel active sync tasks
        for device_id, task in self.active_syncs.items():
            if not task.done():
                task.cancel()
                self.logger.info(f"Cancelled sync task for device {device_id}")
        
        self.active_syncs.clear()
        self.logger.info("Sync scheduler stopped")
    
    async def _run_scheduled_syncs(self):
        """
        Check and run scheduled syncs
        """
        db = next(get_db())
        active_devices = db.query(Device).filter(Device.is_active == True).all()
        
        for device in active_devices:
            try:
                # Skip if device already has an active sync
                if device.id in self.active_syncs and not self.active_syncs[device.id].done():
                    continue
                
                # Check if we can start a new sync (respect concurrency limit)
                active_count = sum(1 for task in self.active_syncs.values() if not task.done())
                if active_count >= self.max_concurrent_syncs:
                    continue
                
                # Determine what type of sync to run
                sync_type = self._determine_sync_type(device)
                
                if sync_type:
                    # Start sync task
                    task = asyncio.create_task(self._run_device_sync(device, sync_type))
                    self.active_syncs[device.id] = task
                    self.logger.info(f"Started {sync_type} sync for device {device.name}")
            
            except Exception as e:
                self.logger.error(f"Error scheduling sync for device {device.name}: {str(e)}")
    
    def _determine_sync_type(self, device: Device) -> Optional[str]:
        """
        Determine what type of sync should be run for a device
        """
        now = datetime.now()
        device_id = device.id
        
        # Check for full sync need
        last_full = self.last_full_sync.get(device_id)
        if not last_full:
            # Check database for last full sync
            last_full_sync = db.query(SyncLog).filter(
                SyncLog.device_id == device_id,
                SyncLog.sync_type.like("unlimited_full%"),
                SyncLog.status == "completed"
            ).order_by(SyncLog.completed_at.desc()).first()
            
            if last_full_sync:
                last_full = last_full_sync.completed_at
                self.last_full_sync[device_id] = last_full
        
        # If no full sync ever, or it's been more than 24 hours
        if not last_full or (now - last_full).total_seconds() > (self.full_sync_interval_hours * 3600):
            return "full_historical"
        
        # Check for incremental sync need
        last_incremental = self.last_incremental_sync.get(device_id)
        if not last_incremental:
            # Check database for last incremental sync
            last_inc_sync = db.query(SyncLog).filter(
                SyncLog.device_id == device_id,
                SyncLog.sync_type.like("unlimited_incremental%"),
                SyncLog.status == "completed"
            ).order_by(SyncLog.completed_at.desc()).first()
            
            if last_inc_sync:
                last_incremental = last_inc_sync.completed_at
                self.last_incremental_sync[device_id] = last_incremental
        
        # If no incremental sync ever, or it's been more than configured interval
        if not last_incremental or (now - last_incremental).total_seconds() > (self.incremental_interval_minutes * 60):
            return "incremental"
        
        return None
    
    async def _run_device_sync(self, device: Device, sync_type: str):
        """
        Run sync for a specific device
        """
        db = next(get_db())
        
        try:
            if sync_type == "full_historical":
                config = SyncConfiguration(
                    chunk_size=100,
                    batch_commit_size=500,
                    processing_strategy=ProcessingStrategy.BALANCED,
                    enable_detailed_logging=False  # Less logging for automated syncs
                )
                
                sync_service = UnlimitedSyncService(device, db, config)
                metrics = await sync_service.sync_full_historical_data()
                
                self.last_full_sync[device.id] = datetime.now()
                self.logger.info(
                    f"Full sync completed for {device.name}: "
                    f"{metrics.new_records_added} new records"
                )
            
            elif sync_type == "incremental":
                config = SyncConfiguration(
                    chunk_size=50,
                    batch_commit_size=200,
                    processing_strategy=ProcessingStrategy.SPEED_OPTIMIZED,
                    enable_detailed_logging=False,
                    stop_on_duplicate_threshold=2
                )
                
                sync_service = UnlimitedSyncService(device, db, config)
                metrics = await sync_service.sync_incremental_updates()
                
                self.last_incremental_sync[device.id] = datetime.now()
                
                if metrics.new_records_added > 0:
                    self.logger.info(
                        f"Incremental sync completed for {device.name}: "
                        f"{metrics.new_records_added} new records"
                    )
        
        except Exception as e:
            self.logger.error(f"Automated sync failed for device {device.name}: {str(e)}")
        
        finally:
            # Clean up completed task
            if device.id in self.active_syncs:
                del self.active_syncs[device.id]
    
    def get_scheduler_status(self) -> Dict:
        """
        Get current scheduler status
        """
        active_syncs = []
        for device_id, task in self.active_syncs.items():
            if not task.done():
                active_syncs.append({
                    "device_id": device_id,
                    "task_name": task.get_name() if hasattr(task, 'get_name') else "sync_task"
                })
        
        return {
            "is_running": self.is_running,
            "active_syncs": active_syncs,
            "last_incremental_sync": {
                device_id: timestamp.isoformat() 
                for device_id, timestamp in self.last_incremental_sync.items()
            },
            "last_full_sync": {
                device_id: timestamp.isoformat() 
                for device_id, timestamp in self.last_full_sync.items()
            },
            "configuration": {
                "incremental_interval_minutes": self.incremental_interval_minutes,
                "full_sync_interval_hours": self.full_sync_interval_hours,
                "max_concurrent_syncs": self.max_concurrent_syncs
            }
        }
    
    def update_configuration(
        self, 
        incremental_interval_minutes: Optional[int] = None,
        full_sync_interval_hours: Optional[int] = None,
        max_concurrent_syncs: Optional[int] = None
    ):
        """
        Update scheduler configuration
        """
        if incremental_interval_minutes is not None:
            self.incremental_interval_minutes = incremental_interval_minutes
            self.logger.info(f"Updated incremental sync interval to {incremental_interval_minutes} minutes")
        
        if full_sync_interval_hours is not None:
            self.full_sync_interval_hours = full_sync_interval_hours
            self.logger.info(f"Updated full sync interval to {full_sync_interval_hours} hours")
        
        if max_concurrent_syncs is not None:
            self.max_concurrent_syncs = max_concurrent_syncs
            self.logger.info(f"Updated max concurrent syncs to {max_concurrent_syncs}")


# Global scheduler instance
_scheduler_instance: Optional[UnlimitedSyncScheduler] = None


def get_scheduler() -> UnlimitedSyncScheduler:
    """
    Get the global scheduler instance
    """
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = UnlimitedSyncScheduler()
    return _scheduler_instance


async def start_scheduler():
    """
    Start the global scheduler
    """
    scheduler = get_scheduler()
    await scheduler.start_scheduler()


def stop_scheduler():
    """
    Stop the global scheduler
    """
    scheduler = get_scheduler()
    scheduler.stop_scheduler()