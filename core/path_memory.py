"""
Contextual Path Memory - Track recently used file paths for situational awareness
"""

import collections
from typing import List, Optional
from utils.logger import get_logger

logger = get_logger("path_memory")

class ContextualPathMemory:
    """Tracks recently accessed or modified file paths"""
    
    def __init__(self, max_size: int = 20):
        self.paths = collections.deque(maxlen=max_size)
    
    def record_path(self, path: str):
        """Record a file path as being recently used"""
        if not path:
            return
        
        # Normalize/clean path if necessary (optional)
        # Remove if already there to move to front
        if path in self.paths:
            self.paths.remove(path)
        
        self.paths.appendleft(path)
        logger.debug(f"Path recorded: {path}")

    def get_recent_paths(self, limit: int = 10) -> List[str]:
        """Get the most recently used paths"""
        return list(self.paths)[:limit]

    def get_last_path(self) -> Optional[str]:
        """Get the absolute last path used"""
        if self.paths:
            return self.paths[0]
        return None

    def clear(self):
        """Clear all path memory"""
        self.paths.clear()

# Singleton instance
_path_memory = None

def get_path_memory() -> ContextualPathMemory:
    global _path_memory
    if _path_memory is None:
        _path_memory = ContextualPathMemory()
    return _path_memory
