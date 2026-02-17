"""
Session Management and Continuity System
Handles session lifecycle, persistence, and recovery from interruptions
"""

import asyncio
import json
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, asdict, field
from utils.logger import get_logger
from pathlib import Path
import os

logger = get_logger("session_manager")


class SessionStatus(Enum):
    """Session lifecycle states"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"
    CRASHED = "crashed"


@dataclass
class SessionContext:
    """Context of a user session"""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "active"

    # Operation tracking
    operations_count: int = 0
    successful_operations: int = 0
    failed_operations: int = 0

    # Current state
    current_operation: Optional[str] = None
    current_step: int = 0
    total_steps: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContext":
        """Create from dictionary"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.now().isoformat()

    def is_stale(self, timeout_minutes: int = 60) -> bool:
        """Check if session is stale (inactive)"""
        last = datetime.fromisoformat(self.last_activity)
        return datetime.now() - last > timedelta(minutes=timeout_minutes)


class SessionManager:
    """Manages user sessions, persistence, and recovery"""

    def __init__(self, session_dir: Optional[Path] = None):
        self.session_dir = session_dir or Path.home() / ".elyan" / "sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # In-memory sessions
        self.active_sessions: Dict[str, SessionContext] = {}

        # Recovery
        self.max_reconnect_attempts = 5
        self.reconnect_backoff = 1.0  # seconds

        logger.info(f"Session manager initialized: {self.session_dir}")

    async def create_session(self, user_id: Optional[int] = None) -> SessionContext:
        """Create a new session"""
        session = SessionContext(user_id=user_id)
        self.active_sessions[session.session_id] = session

        # Persist to disk
        await self._save_session(session)

        logger.info(f"Session created: {session.session_id} for user {user_id}")
        return session

    async def get_session(self, session_id: str) -> Optional[SessionContext]:
        """Retrieve session by ID"""
        # Check memory first
        if session_id in self.active_sessions:
            return self.active_sessions[session_id]

        # Try to load from disk (recovery)
        session = await self._load_session(session_id)
        if session:
            self.active_sessions[session_id] = session
            logger.info(f"Session loaded from disk: {session_id}")
        return session

    async def get_user_session(self, user_id: int) -> Optional[SessionContext]:
        """Get active session for user (if any)"""
        for session in self.active_sessions.values():
            if session.user_id == user_id and session.status == SessionStatus.ACTIVE.value:
                return session

        # Try to recover last session from disk
        sessions = await self._list_sessions(user_id)
        if sessions:
            # Load most recent
            session = await self._load_session(sessions[-1])
            if session and not session.is_stale():
                self.active_sessions[session.session_id] = session
                return session

        return None

    async def update_session(self, session_id: str, **kwargs) -> bool:
        """Update session fields"""
        session = self.active_sessions.get(session_id)
        if not session:
            return False

        # Update fields
        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)

        session.update_activity()

        # Persist
        await self._save_session(session)
        return True

    async def close_session(self, session_id: str) -> bool:
        """Close a session gracefully"""
        session = self.active_sessions.get(session_id)
        if not session:
            return False

        session.status = SessionStatus.CLOSED.value
        session.update_activity()

        # Persist final state
        await self._save_session(session)

        # Remove from memory
        del self.active_sessions[session_id]

        logger.info(f"Session closed: {session_id}")
        return True

    async def mark_crashed(self, session_id: str) -> bool:
        """Mark session as crashed (for recovery)"""
        session = self.active_sessions.get(session_id)
        if not session:
            return False

        session.status = SessionStatus.CRASHED.value
        session.update_activity()

        # Keep in memory but persist
        await self._save_session(session)

        logger.warning(f"Session marked as crashed: {session_id}")
        return True

    async def recover_session(self, session_id: str) -> bool:
        """Attempt to recover a crashed session"""
        session = self.active_sessions.get(session_id)
        if not session:
            return False

        if session.status != SessionStatus.CRASHED.value:
            return False

        # Try to restore state
        session.status = SessionStatus.ACTIVE.value
        session.update_activity()

        await self._save_session(session)

        logger.info(f"Session recovered: {session_id}")
        return True

    async def handle_reconnection(self, session_id: str) -> bool:
        """Handle user reconnection with automatic retry"""
        session = self.active_sessions.get(session_id)
        if not session:
            return False

        for attempt in range(self.max_reconnect_attempts):
            try:
                session.status = SessionStatus.RECONNECTING.value
                await self._save_session(session)

                # Simulate connection check (actual check would be in connection layer)
                await asyncio.sleep(self.reconnect_backoff * (attempt + 1))

                session.status = SessionStatus.ACTIVE.value
                await self._save_session(session)

                logger.info(f"Session reconnected: {session_id} (attempt {attempt + 1})")
                return True

            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt + 1} failed: {e}")

                if attempt == self.max_reconnect_attempts - 1:
                    session.status = SessionStatus.SUSPENDED.value
                    await self._save_session(session)
                    return False

        return False

    def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a session"""
        session = self.active_sessions.get(session_id)
        if not session:
            return None

        total = session.operations_count
        success_rate = (session.successful_operations / total * 100) if total > 0 else 0

        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "status": session.status,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "operations_total": total,
            "operations_successful": session.successful_operations,
            "operations_failed": session.failed_operations,
            "success_rate": f"{success_rate:.1f}%",
            "current_operation": session.current_operation,
            "progress": f"{session.current_step}/{session.total_steps}" if session.total_steps > 0 else "N/A",
        }

    async def cleanup_stale_sessions(self, timeout_minutes: int = 120):
        """Clean up inactive sessions"""
        to_remove = []

        for session_id, session in list(self.active_sessions.items()):
            if session.is_stale(timeout_minutes):
                to_remove.append(session_id)
                session.status = SessionStatus.CLOSED.value
                await self._save_session(session)
                logger.info(f"Session cleaned up (stale): {session_id}")

        for session_id in to_remove:
            del self.active_sessions[session_id]

        return len(to_remove)

    # Persistence methods
    async def _save_session(self, session: SessionContext):
        """Save session to disk"""
        try:
            session_file = self.session_dir / f"{session.session_id}.json"
            session_data = session.to_dict()

            # Write atomically
            temp_file = session_file.with_suffix('.tmp')
            temp_file.write_text(json.dumps(session_data, indent=2))
            temp_file.replace(session_file)

            logger.debug(f"Session saved: {session.session_id}")
        except Exception as e:
            logger.error(f"Failed to save session {session.session_id}: {e}")

    async def _load_session(self, session_id: str) -> Optional[SessionContext]:
        """Load session from disk"""
        try:
            session_file = self.session_dir / f"{session_id}.json"
            if not session_file.exists():
                return None

            data = json.loads(session_file.read_text())
            session = SessionContext.from_dict(data)

            logger.debug(f"Session loaded: {session_id}")
            return session
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    async def _list_sessions(self, user_id: Optional[int] = None) -> list:
        """List all session files"""
        try:
            sessions = []
            for session_file in sorted(self.session_dir.glob("*.json")):
                try:
                    data = json.loads(session_file.read_text())
                    if user_id is None or data.get("user_id") == user_id:
                        sessions.append(session_file.stem)
                except:
                    pass
            return sessions
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            return []

    async def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Export session state for backup"""
        session = await self.get_session(session_id)
        if not session:
            return None

        return {
            "session": session.to_dict(),
            "exported_at": datetime.now().isoformat(),
        }

    async def import_session(self, session_data: Dict[str, Any]) -> Optional[SessionContext]:
        """Import session from backup"""
        try:
            session_dict = session_data.get("session", {})
            session = SessionContext.from_dict(session_dict)

            # Generate new session ID to avoid conflicts
            session.session_id = str(uuid.uuid4())

            self.active_sessions[session.session_id] = session
            await self._save_session(session)

            logger.info(f"Session imported: {session.session_id}")
            return session
        except Exception as e:
            logger.error(f"Failed to import session: {e}")
            return None


# Global instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get or create session manager"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
