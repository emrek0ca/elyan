"""
Watchdog event handler for file system monitoring
"""

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from typing import Callable, Optional, List
from pathlib import Path
import fnmatch
import asyncio
from utils.logger import get_logger

logger = get_logger("watchdog_handler")


class WatchdogEventHandler(FileSystemEventHandler):
    """Custom event handler for file system changes"""
    
    def __init__(self, callback: Callable, alert_id: str, patterns: Optional[List[str]] = None):
        """
        Initialize handler.
        
        Args:
            callback: Async callback function(title, message)
            alert_id: Identifier for this watcher
            patterns: Optional file patterns (e.g., ['*.pdf', '*.txt'])
        """
        super().__init__()
        self.callback = callback
        self.alert_id = alert_id
        self.patterns = patterns or ['*']  # Default: all files
    
    def _should_process(self, path: str) -> bool:
        """Check if file matches patterns"""
        filename = Path(path).name
        return any(fnmatch.fnmatch(filename, pattern) for pattern in self.patterns)
    
    def _send_alert_sync(self, title: str, message: str):
        """Synchronous wrapper for async callback"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.callback(title, message))
            else:
                loop.run_until_complete(self.callback(title, message))
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
    
    def on_created(self, event: FileSystemEvent):
        """Called when a file/directory is created"""
        if event.is_directory:
            return
        
        if not self._should_process(event.src_path):
            return
        
        filename = Path(event.src_path).name
        self._send_alert_sync(
            "Dosya Sistemi Güncellemesi: Yeni Dosya",
            f"Sistem üzerinde yeni bir dosya algılandı: {filename}\nKonum: {event.src_path}"
        )
        logger.info(f"File created: {event.src_path}")
    
    def on_modified(self, event: FileSystemEvent):
        """Called when a file/directory is modified"""
        if event.is_directory:
            return
        
        if not self._should_process(event.src_path):
            return
        
        filename = Path(event.src_path).name
        self._send_alert_sync(
            "Dosya Sistemi Güncellemesi: Değişiklik",
            f"Dosya içeriğinde bir değişiklik saptandı: {filename}\nKonum: {event.src_path}"
        )
        logger.info(f"File modified: {event.src_path}")
    
    def on_deleted(self, event: FileSystemEvent):
        """Called when a file/directory is deleted"""
        if event.is_directory:
            return
        
        if not self._should_process(event.src_path):
            return
        
        filename = Path(event.src_path).name
        self._send_alert_sync(
            "Dosya Sistemi Güncellemesi: Silinme",
            f"Bir dosya sistemden kaldırıldı: {filename}\nKonum: {event.src_path}"
        )
        logger.info(f"File deleted: {event.src_path}")
    
    def on_moved(self, event: FileSystemEvent):
        """Called when a file/directory is moved/renamed"""
        if event.is_directory:
            return
        
        old_name = Path(event.src_path).name
        new_name = Path(event.dest_path).name
        
        self._send_alert_sync(
            "Dosya Sistemi Güncellemesi: Taşıma/Yeniden Adlandırma",
            f"Dosya konumunda veya isminde değişiklik: {old_name} -> {new_name}\nYeni Konum: {event.dest_path}"
        )
        logger.info(f"File moved: {event.src_path} -> {event.dest_path}")
