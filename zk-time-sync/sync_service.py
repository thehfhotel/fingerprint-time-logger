#!/usr/bin/env python3
"""
ZK Device Time Sync Service
Minimal service to synchronize ZK biometric device time to Bangkok timezone (GMT+7)
Extracted from main fingerprint-time-logger application
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo

import requests
from zk import ZK


class ZKTimeSyncService:
    """Minimal ZK device time synchronization service"""

    def __init__(self, config_path: str = "config/devices.json"):
        self.config_path = config_path
        self.config = self.load_config()
        self.bangkok_tz = ZoneInfo("Asia/Bangkok")
        self.setup_logging()

    def load_config(self) -> Dict:
        """Load device configuration from JSON file"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            # Default configuration if file doesn't exist
            return {
                "devices": [
                    {
                        "id": 1,
                        "host": "192.168.100.209",
                        "port": 4370,
                        "password": "",
                        "name": "Main Fingerprint Device",
                        "sync_enabled": True
                    }
                ],
                "sync_interval_minutes": 30,
                "bangkok_timezone": "Asia/Bangkok",
                "log_level": "INFO",
                "slack_notifications": {
                    "enabled": False,
                    "webhook_url": "",
                    "notify_on_success": True,
                    "notify_on_error": True,
                    "channel": "#zk-time-sync",
                    "username": "ZK Time Sync Bot"
                }
            }

    def setup_logging(self):
        """Setup logging configuration"""
        log_level = getattr(logging, self.config.get("log_level", "INFO"))

        # Create logs directory if it doesn't exist
        Path("logs").mkdir(exist_ok=True)

        # Main logger
        logging.basicConfig(
            level=log_level,
            format='[%(asctime)s] %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/sync.log'),
                logging.StreamHandler()
            ]
        )

        # Error logger
        error_handler = logging.FileHandler('logs/errors.log')
        error_handler.setLevel(logging.ERROR)
        error_formatter = logging.Formatter('[%(asctime)s] ERROR - %(message)s')
        error_handler.setFormatter(error_formatter)

        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(error_handler)

    def connect_to_device(self, device_config: Dict) -> Optional[Any]:
        """Connect to ZK device"""
        try:
            zk = ZK(
                device_config["host"],
                port=device_config["port"],
                timeout=10,
                password=device_config.get("password", ""),
                ommit_ping=True  # Skip ping check to avoid network issues
            )
            conn = zk.connect()
            self.logger.info(f"Connected to device {device_config['name']} ({device_config['host']}:{device_config['port']})")
            return conn
        except Exception as e:
            self.logger.error(f"Failed to connect to device {device_config['host']}:{device_config['port']} - {str(e)}")
            return None

    def get_bangkok_time(self) -> datetime:
        """Get current Bangkok time (GMT+7)"""
        return datetime.now(self.bangkok_tz)

    def send_slack_notification(self, message: str, is_error: bool = False) -> bool:
        """Send notification to Slack webhook"""
        slack_config = self.config.get("slack_notifications", {})

        if not slack_config.get("enabled", False):
            return True  # Notifications disabled, consider it successful

        webhook_url = slack_config.get("webhook_url", "")
        if not webhook_url:
            self.logger.warning("Slack notifications enabled but no webhook URL configured")
            return False

        # Check if we should notify for this type
        if is_error and not slack_config.get("notify_on_error", True):
            return True
        if not is_error and not slack_config.get("notify_on_success", True):
            return True

        try:
            # Prepare Slack message payload
            color = "#ff0000" if is_error else "#36a64f"  # Red for errors, green for success
            icon = "❌" if is_error else "✅"

            payload = {
                "username": slack_config.get("username", "ZK Time Sync Bot"),
                "channel": slack_config.get("channel", "#zk-time-sync"),
                "attachments": [
                    {
                        "color": color,
                        "title": f"{icon} ZK Time Sync {'Error' if is_error else 'Notification'}",
                        "text": message,
                        "footer": "ZK Time Sync Service",
                        "ts": int(time.time())
                    }
                ]
            }

            # Send the notification
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=10,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200:
                self.logger.info("Slack notification sent successfully")
                return True
            else:
                self.logger.error(f"Failed to send Slack notification: HTTP {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"Error sending Slack notification: {str(e)}")
            return False

    def format_sync_summary(self, results: List[Dict[str, Any]]) -> str:
        """Format sync results for notification - 1-liner format"""
        total_devices = len(results)
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]

        bangkok_time = self.get_bangkok_time().strftime("%H:%M")

        if failed:
            # Error summary - 1-liner with device times
            device_statuses = []
            for result in successful:
                time_diff = result.get("time_diff_after", 0)
                device_time = result.get("new_time", "").split("T")[1][:5] if result.get("new_time") else "??"
                device_statuses.append(f"{result['device']}:✅{device_time}({time_diff:.1f}s)")
            for result in failed:
                device_statuses.append(f"{result['device']}:❌")

            message = f"🚨 ZK Sync {len(successful)}/{total_devices} OK at {bangkok_time} - {', '.join(device_statuses)}"

        else:
            # Success summary - 1-liner with device times
            device_statuses = []
            for result in successful:
                time_diff_before = result.get("time_diff_before", 0)
                time_diff_after = result.get("time_diff_after", 0)
                device_time = result.get("new_time", "").split("T")[1][:5] if result.get("new_time") else "??"
                device_statuses.append(f"{result['device']}:{device_time}({time_diff_before:.1f}s→{time_diff_after:.1f}s)")

            message = f"✅ ZK Sync {total_devices}/{total_devices} OK at {bangkok_time} - {', '.join(device_statuses)}"

        return message

    def sync_device_time(self, device_config: Dict) -> Dict[str, Any]:
        """
        Sync single device time to Bangkok timezone
        Extracted and adapted from app/services/device_service.py
        """
        device_name = device_config["name"]
        device_host = f"{device_config['host']}:{device_config['port']}"

        self.logger.info(f"Starting time sync for device {device_name} ({device_host})")

        try:
            # Connect to device
            conn = self.connect_to_device(device_config)
            if not conn:
                return {
                    "success": False,
                    "error": f"Failed to connect to device {device_host}",
                    "device": device_name
                }

            try:
                # Get current device time
                old_device_time = conn.get_time()
                self.logger.info(f"Current device time: {old_device_time}")

                # Get Bangkok time
                bangkok_time = self.get_bangkok_time()
                # Remove timezone info for device compatibility
                target_time = bangkok_time.replace(tzinfo=None)
                self.logger.info(f"Bangkok time (target): {target_time}")

                # Calculate time difference before sync
                time_diff_before = abs((old_device_time - target_time).total_seconds())
                self.logger.info(f"Time difference before sync: {time_diff_before:.1f} seconds")

                # Set new time
                conn.set_time(target_time)
                self.logger.info(f"Time sync command sent to device")

                # Verify new time
                time.sleep(1)  # Wait for device to process
                new_device_time = conn.get_time()
                time_diff_after = abs((new_device_time - target_time).total_seconds())

                self.logger.info(f"New device time: {new_device_time}")
                self.logger.info(f"Time difference after sync: {time_diff_after:.1f} seconds")

                # Check if sync was successful (within 5 seconds tolerance)
                success = time_diff_after <= 5.0

                if success:
                    self.logger.info(f"Time sync successful for {device_name}")
                else:
                    self.logger.warning(f"Time sync may have failed for {device_name} - difference still {time_diff_after:.1f}s")

                return {
                    "success": success,
                    "device": device_name,
                    "device_host": device_host,
                    "old_time": old_device_time.isoformat(),
                    "new_time": new_device_time.isoformat(),
                    "target_time": target_time.isoformat(),
                    "time_diff_before": time_diff_before,
                    "time_diff_after": time_diff_after
                }

            finally:
                conn.disconnect()
                self.logger.info(f"Disconnected from device {device_name}")

        except Exception as e:
            error_msg = f"Error syncing time for device {device_name}: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "device": device_name,
                "device_host": device_host
            }

    def sync_all_devices(self) -> List[Dict[str, Any]]:
        """Sync time for all enabled devices"""
        results = []
        enabled_devices = [d for d in self.config["devices"] if d.get("sync_enabled", True)]

        self.logger.info(f"Starting sync for {len(enabled_devices)} enabled devices")

        for device_config in enabled_devices:
            result = self.sync_device_time(device_config)
            results.append(result)

        # Log summary
        successful = len([r for r in results if r["success"]])
        total = len(results)
        self.logger.info(f"Sync completed: {successful}/{total} devices successful")

        # Send Slack notification
        try:
            message = self.format_sync_summary(results)
            has_errors = any(not r["success"] for r in results)
            self.send_slack_notification(message, is_error=has_errors)
        except Exception as e:
            self.logger.error(f"Failed to send Slack notification: {str(e)}")

        return results

    def health_check(self) -> Dict[str, Any]:
        """Basic health check"""
        try:
            enabled_devices = [d for d in self.config["devices"] if d.get("sync_enabled", True)]
            bangkok_time = self.get_bangkok_time()

            return {
                "status": "healthy",
                "service": "zk-time-sync",
                "bangkok_time": bangkok_time.isoformat(),
                "enabled_devices": len(enabled_devices),
                "config_loaded": True,
                "logs_directory": "logs/"
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    def run_continuous(self):
        """Run continuous sync service with configured interval"""
        interval_minutes = self.config.get("sync_interval_minutes", 30)
        interval_seconds = interval_minutes * 60

        self.logger.info(f"Starting ZK Time Sync Service")
        self.logger.info(f"Sync interval: {interval_minutes} minutes")
        self.logger.info(f"Bangkok timezone: {self.bangkok_tz}")
        self.logger.info(f"Enabled devices: {len([d for d in self.config['devices'] if d.get('sync_enabled', True)])}")

        # Initial sync
        self.sync_all_devices()

        # Continuous sync loop
        while True:
            try:
                self.logger.info(f"Waiting {interval_minutes} minutes until next sync...")
                time.sleep(interval_seconds)
                self.sync_all_devices()
            except KeyboardInterrupt:
                self.logger.info("Received interrupt signal, shutting down...")
                break
            except Exception as e:
                error_msg = f"🚨 ZK Sync service error at {self.get_bangkok_time().strftime('%H:%M')}: {str(e)} - retrying in 1min"
                self.logger.error(f"Error in main loop: {str(e)}")

                # Send error notification
                try:
                    self.send_slack_notification(error_msg, is_error=True)
                except Exception as notification_error:
                    self.logger.error(f"Failed to send error notification: {str(notification_error)}")

                self.logger.info("Continuing after error...")
                time.sleep(60)  # Wait 1 minute before retrying


def main():
    """Main entry point"""
    service = ZKTimeSyncService()

    # Log health check on startup
    health = service.health_check()
    service.logger.info(f"Health check: {health}")

    try:
        service.run_continuous()
    except Exception as e:
        service.logger.error(f"Service crashed: {str(e)}")
        raise


if __name__ == "__main__":
    main()