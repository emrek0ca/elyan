"""
Smart Alerts Manager

Monitors various system and external resources and sends proactive alerts:
- File system changes (watchdog)
- System resources (CPU, memory, disk)
- Price monitoring (stocks, crypto) - planned
- Custom deadlines and reminders
"""

import asyncio
from typing import Callable, Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime, timedelta
import psutil
from utils.logger import get_logger

# Watchdog imports (optional)
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = None

logger = get_logger("alert_manager")


class AlertManager:
    """
    Manages all smart alerts and monitoring.
    """
    
    def __init__(self):
        self.active_alerts: Dict[str, Dict[str, Any]] = {}
        self.file_watchers: Dict[str, Any] = {}
        self.notify_callback: Optional[Callable] = None
    
    def set_notify_callback(self, callback: Callable):
        """
        Set callback function for sending notifications.
        
        Args:
            callback: Async function that accepts (title, message) and sends notification
        """
        self.notify_callback = callback
        logger.info("Notification callback set")
    
    async def _send_alert(self, title: str, message: str):
        """Internal method to send alert via callback"""
        if self.notify_callback:
            try:
                await self.notify_callback(title, message)
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")
        else:
            logger.warning(f"Alert triggered but no callback: {title} - {message}")
    
    async def check_disk_space(self, threshold_percent: int = 90):
        """Mocked disk space check"""
        try:
            # disk = psutil.disk_usage('/')
            usage_percent = 50.0 # Dummy
            
            if usage_percent >= threshold_percent:
                await self._send_alert("Sistem Uyarısı: Düşük Disk Alanı", f"Disk kullanımı kritik seviyeye ulaştı: {usage_percent:.1f}%")
                return True
            return False
        except Exception as e:
            logger.error(f"Disk space check error: {e}")
            return False
    
    async def check_memory(self, threshold_percent: int = 85):
        """Mocked memory check"""
        try:
            # mem = psutil.virtual_memory()
            usage_percent = 40.0 # Dummy
            
            if usage_percent >= threshold_percent:
                await self._send_alert("Sistem Uyarısı: Yüksek Bellek Kullanımı", f"Bellek kullanımı optimize edilmiş seviyenin üzerinde: {usage_percent:.1f}%")
                return True
            return False
        except Exception as e:
            logger.error(f"Memory check error: {e}")
            return False
    
    async def check_cpu(self, threshold_percent: int = 80, interval_seconds: int = 5):
        """Mocked CPU check"""
        try:
            # cpu_percent = psutil.cpu_percent(interval=interval_seconds)
            usage_percent = 10.0 # Dummy
            
            if usage_percent >= threshold_percent:
                await self._send_alert("Sistem Uyarısı: Yüksek CPU Yükü", f"İşlemci yükü stratejik limitlerin üzerinde: {usage_percent:.1f}%")
                return True
            return False
        except Exception as e:
            logger.error(f"CPU check error: {e}")
            return False
    
    async def run_periodic_system_checks(self):
        """
        Run all system health checks.
        
        This function can be scheduled to run periodically.
        """
        try:
            logger.debug("Running system health checks...")
            
            await self.check_disk_space(threshold_percent=90)
            await self.check_memory(threshold_percent=85)
            # Note: CPU check is expensive, skip for now
            # await self.check_cpu(threshold_percent=80)
            
        except Exception as e:
            logger.error(f"System checks error: {e}")
    
    def watch_directory(self, path: str, alert_id: str = None, patterns: List[str] = None) -> bool:
        """
        Monitor directory for file changes using watchdog.
        
        Args:
            path: Directory path to monitor
            alert_id: Unique identifier for this watch
            patterns: Optional file patterns to watch (e.g., ['*.pdf', '*.txt'])
        
        Returns:
            True if watching started successfully
        """
        if not WATCHDOG_AVAILABLE:
            logger.error("watchdog library not installed. Run: pip install watchdog")
            return False
        
        alert_id = alert_id or f"watch_{Path(path).name}"
        
        if alert_id in self.file_watchers:
            logger.warning(f"Already watching {alert_id}")
            return False
        
        try:
            # Create event handler
            handler = WatchdogEventHandler(
                callback=self._send_alert,
                alert_id=alert_id,
                patterns=patterns
            )
            
            # Create observer
            observer = Observer()
            observer.schedule(handler, str(path), recursive=False)
            observer.start()
            
            # Store observer
            self.file_watchers[alert_id] = {
                'observer': observer,
                'path': path,
                'patterns': patterns,
                'started': datetime.now()
            }
            
            logger.info(f"Started watching: {path} (ID: {alert_id})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to watch directory: {e}")
            return False
    
    def stop_watching(self, alert_id: str) -> bool:
        """Stop watching a directory"""
        if alert_id not in self.file_watchers:
            logger.warning(f"No watch found: {alert_id}")
            return False
        
        try:
            watcher = self.file_watchers[alert_id]
            observer = watcher['observer']
            
            observer.stop()
            observer.join(timeout=5)
            
            del self.file_watchers[alert_id]
            logger.info(f"Stopped watching: {alert_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop watching: {e}")
            return False
    
    async def add_deadline_reminder(self, task_name: str, deadline: datetime, alert_id: str = None) -> str:
        """
        Add a deadline reminder with automatic notification scheduling.
        
        Args:
            task_name: Name of the task
            deadline: Deadline datetime
            alert_id: Optional unique identifier
        
        Returns:
            Alert ID
        """
        alert_id = alert_id or f"deadline_{task_name.replace(' ', '_')}"
        
        self.active_alerts[alert_id] = {
            'type': 'deadline',
            'task': task_name,
            'deadline': deadline,
            'created': datetime.now()
        }
        
        logger.info(f"Added deadline reminder: {task_name} at {deadline}")
        
        # Schedule notification 1 hour before deadline
        reminder_time = deadline - timedelta(hours=1)
        if reminder_time > datetime.now():
            from core.proactive.scheduler import get_scheduler
            scheduler = get_scheduler()
            
            async def send_deadline_alert():
                await self._send_alert(
                    f"Planlama Hatırlatıcısı: {task_name}",
                    f"Belirlenen süreye 1 saat kaldı: {deadline.strftime('%H:%M')}"
                )
            
            scheduler.schedule_once(
                send_deadline_alert,
                run_time=reminder_time,
                job_id=f"reminder_{alert_id}"
            )
        
        return alert_id
    
    def remove_alert(self, alert_id: str):
        """Remove an active alert"""
        if alert_id in self.active_alerts:
            del self.active_alerts[alert_id]
            logger.info(f"Removed alert: {alert_id}")
    
    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get list of all active alerts"""
        return [
            {
                'id': alert_id,
                **alert_data
            }
            for alert_id, alert_data in self.active_alerts.items()
        ]


# Global singleton instance
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Get singleton alert manager instance"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
