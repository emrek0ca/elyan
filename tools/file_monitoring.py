"""
File Monitoring and Watching Tools

Features:
- Watch directories for changes
- Monitor file modifications
- Trigger actions on file events
- Directory synchronization tracking
"""

import asyncio
import time
from typing import Dict, Any, Optional, Callable, List
from pathlib import Path
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("tools.file_monitor")


class FileMonitor:
    """
    Monitor files and directories for changes
    
    Uses polling (cross-platform) instead of OS-specific APIs
    """
    
    def __init__(self, check_interval: float = 1.0):
        self.check_interval = check_interval
        self.watched_files: Dict[str, Dict[str, Any]] = {}
        self.is_monitoring = False
        self.monitor_task: Optional[asyncio.Task] = None
    
    async def watch_file(self, file_path: str, 
                        on_change: Callable = None,
                        on_delete: Callable = None,
                        on_create: Callable = None) -> Dict[str, Any]:
        """
        Start watching a file for changes
        
        Args:
            file_path: Path to file to watch
            on_change: Callback when file is modified
            on_delete: Callback when file is deleted
            on_create: Callback when file is created
        
        Returns:
            Watch status
        """
        path = Path(file_path).expanduser().resolve()
        
        # Get initial state
        if path.exists():
            stat = path.stat()
            initial_state = {
                "exists": True,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "last_check": time.time()
            }
        else:
            initial_state = {
                "exists": False,
                "last_check": time.time()
            }
        
        self.watched_files[str(path)] = {
            "path": path,
            "state": initial_state,
            "callbacks": {
                "on_change": on_change,
                "on_delete": on_delete,
                "on_create": on_create
            }
        }
        
        # Start monitoring if not already running
        if not self.is_monitoring:
            await self.start_monitoring()
        
        return {
            "success": True,
            "file": str(path),
            "watching": True,
            "initial_state": initial_state
        }
    
    async def watch_directory(self, dir_path: str,
                             pattern: str = "*",
                             on_change: Callable = None,
                             recursive: bool = False) -> Dict[str, Any]:
        """
        Watch a directory for file changes
        
        Args:
            dir_path: Directory to watch
            pattern: File pattern to watch (glob)
            on_change: Callback when files change
            recursive: Watch subdirectories
        
        Returns:
            Watch status with file count
        """
        path = Path(dir_path).expanduser().resolve()
        
        if not path.exists() or not path.is_dir():
            return {
                "success": False,
                "error": "Directory not found or not a directory"
            }
        
        # Get all matching files
        if recursive:
            files = list(path.rglob(pattern))
        else:
            files = list(path.glob(pattern))
        
        # Watch each file
        for file_path in files:
            if file_path.is_file():
                await self.watch_file(str(file_path), on_change=on_change)
        
        return {
            "success": True,
            "directory": str(path),
            "files_watched": len([f for f in files if f.is_file()]),
            "pattern": pattern,
            "recursive": recursive
        }
    
    async def start_monitoring(self):
        """Start the monitoring loop"""
        if self.is_monitoring:
            return
        
        self.is_monitoring = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("File monitoring started")
    
    async def stop_monitoring(self):
        """Stop the monitoring loop"""
        self.is_monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("File monitoring stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self.is_monitoring:
            try:
                await self._check_all_files()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
    
    async def _check_all_files(self):
        """Check all watched files for changes"""
        for file_path, watch_info in list(self.watched_files.items()):
            await self._check_file(file_path, watch_info)
    
    async def _check_file(self, file_path: str, watch_info: Dict[str, Any]):
        """Check a single file for changes"""
        path = watch_info["path"]
        old_state = watch_info["state"]
        callbacks = watch_info["callbacks"]
        
        # Check current state
        if path.exists():
            stat = path.stat()
            new_state = {
                "exists": True,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "last_check": time.time()
            }
            
            # File created
            if not old_state["exists"]:
                if callbacks.get("on_create"):
                    await self._safe_callback(callbacks["on_create"], str(path), "created")
            
            # File modified
            elif old_state["mtime"] != new_state["mtime"]:
                if callbacks.get("on_change"):
                    await self._safe_callback(callbacks["on_change"], str(path), "modified")
        
        else:
            new_state = {
                "exists": False,
                "last_check": time.time()
            }
            
            # File deleted
            if old_state["exists"]:
                if callbacks.get("on_delete"):
                    await self._safe_callback(callbacks["on_delete"], str(path), "deleted")
        
        # Update state
        watch_info["state"] = new_state
    
    async def _safe_callback(self, callback: Callable, file_path: str, event_type: str):
        """Safely execute a callback"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(file_path, event_type)
            else:
                callback(file_path, event_type)
        except Exception as e:
            logger.error(f"Callback error for {file_path}: {e}")
    
    def get_watched_files(self) -> List[str]:
        """Get list of watched files"""
        return list(self.watched_files.keys())
    
    def unwatch_file(self, file_path: str) -> bool:
        """Stop watching a file"""
        path = str(Path(file_path).expanduser().resolve())
        if path in self.watched_files:
            del self.watched_files[path]
            return True
        return False


# Global monitor instance
_file_monitor = None


def get_file_monitor() -> FileMonitor:
    """Get or create the global file monitor"""
    global _file_monitor
    if _file_monitor is None:
        _file_monitor = FileMonitor()
    return _file_monitor


# Tool functions

async def watch_file_changes(file_path: str) -> Dict[str, Any]:
    """
    Start watching a file for changes
    
    Args:
        file_path: Path to file to watch
    
    Returns:
        Watch status
    """
    monitor = get_file_monitor()
    
    # Simple change logger
    def on_change(path, event):
        logger.info(f"File changed: {path} ({event})")
    
    return await monitor.watch_file(file_path, on_change=on_change)


async def watch_directory_changes(directory: str, pattern: str = "*", recursive: bool = False) -> Dict[str, Any]:
    """
    Watch a directory for file changes
    
    Args:
        directory: Directory to watch
        pattern: File pattern (glob)
        recursive: Watch subdirectories
    
    Returns:
        Watch status
    """
    monitor = get_file_monitor()
    return await monitor.watch_directory(directory, pattern=pattern, recursive=recursive)


async def list_watched_files() -> Dict[str, Any]:
    """
    List all currently watched files
    
    Returns:
        List of watched files
    """
    monitor = get_file_monitor()
    watched = monitor.get_watched_files()
    
    return {
        "success": True,
        "watched_files": watched,
        "count": len(watched),
        "monitoring_active": monitor.is_monitoring
    }


async def stop_watching_file(file_path: str) -> Dict[str, Any]:
    """
    Stop watching a file
    
    Args:
        file_path: Path to file
    
    Returns:
        Success status
    """
    monitor = get_file_monitor()
    success = monitor.unwatch_file(file_path)
    
    return {
        "success": success,
        "file": file_path,
        "message": "Stopped watching" if success else "File was not being watched"
    }


async def get_file_changes_summary(directory: str, since_minutes: int = 60) -> Dict[str, Any]:
    """
    Get summary of file changes in a directory
    
    Args:
        directory: Directory to check
        since_minutes: Look back this many minutes
    
    Returns:
        Summary of changes
    """
    path = Path(directory).expanduser().resolve()
    
    if not path.exists() or not path.is_dir():
        return {
            "success": False,
            "error": "Directory not found"
        }
    
    since_time = time.time() - (since_minutes * 60)
    
    modified_files = []
    new_files = []
    
    for file_path in path.rglob("*"):
        if file_path.is_file():
            stat = file_path.stat()
            
            # Recently modified
            if stat.st_mtime > since_time:
                # Check if created or modified
                if stat.st_ctime > since_time:
                    new_files.append({
                        "path": str(file_path.relative_to(path)),
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_ctime).isoformat()
                    })
                else:
                    modified_files.append({
                        "path": str(file_path.relative_to(path)),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
    
    return {
        "success": True,
        "directory": str(path),
        "time_window_minutes": since_minutes,
        "new_files": new_files,
        "modified_files": modified_files,
        "total_changes": len(new_files) + len(modified_files)
    }
