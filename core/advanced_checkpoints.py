"""
Advanced Checkpoint & Recovery System for Wiqo Bot
===================================================
Enables recovery from any checkpoint in a complex task execution,
with minimal memory overhead and fast resume capability.

Features:
- SQLite-based checkpoint storage
- Automatic step-level checkpointing
- State compression
- Partial state recovery
- Rollback capability
- Progress tracking
- Estimated time remaining
"""

import sqlite3
import json
import time
import logging
import hashlib
import pickle
import gzip
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class CheckpointType(Enum):
    """Types of checkpoints."""
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    GROUP_COMPLETE = "group_complete"
    PHASE_COMPLETE = "phase_complete"
    FULL_STATE = "full_state"


@dataclass
class CheckpointMetadata:
    """Metadata for a checkpoint."""
    checkpoint_id: str
    execution_id: str
    timestamp: float
    checkpoint_type: str
    step_number: int
    task_id: Optional[str]
    group_id: Optional[str]
    progress_percentage: float
    estimated_time_remaining: float
    compressed: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class CheckpointStore:
    """Manages checkpoint storage and retrieval."""

    def __init__(self, db_path: str = "~/.wiqo/checkpoints.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                execution_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                checkpoint_type TEXT NOT NULL,
                step_number INTEGER NOT NULL,
                task_id TEXT,
                group_id TEXT,
                progress_percentage REAL,
                estimated_time_remaining REAL,
                compressed BOOLEAN DEFAULT 0,
                error TEXT,
                state_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (execution_id) REFERENCES executions(execution_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkpoint_data (
                checkpoint_id TEXT PRIMARY KEY,
                state_data BLOB NOT NULL,
                metadata_json TEXT NOT NULL,
                FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(checkpoint_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                execution_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                status TEXT DEFAULT 'active',
                total_steps INTEGER,
                completed_steps INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_execution_id ON checkpoints(execution_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoint_type ON checkpoints(checkpoint_type)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON checkpoints(timestamp)
        """)

        conn.commit()
        conn.close()

    def create_execution(self, execution_id: str, total_steps: int) -> None:
        """Create a new execution record."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO executions (execution_id, total_steps, status)
            VALUES (?, ?, 'active')
        """, (execution_id, total_steps))

        conn.commit()
        conn.close()

    def save_checkpoint(
        self,
        metadata: CheckpointMetadata,
        state: Dict[str, Any],
        compress: bool = True
    ) -> str:
        """Save a checkpoint with metadata and state."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Serialize state
            state_bytes = pickle.dumps(state)
            state_hash = hashlib.sha256(state_bytes).hexdigest()

            if compress:
                state_bytes = gzip.compress(state_bytes)

            # Save checkpoint metadata
            cursor.execute("""
                INSERT INTO checkpoints (
                    checkpoint_id, execution_id, timestamp, checkpoint_type,
                    step_number, task_id, group_id, progress_percentage,
                    estimated_time_remaining, compressed, error, state_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metadata.checkpoint_id,
                metadata.execution_id,
                metadata.timestamp,
                metadata.checkpoint_type,
                metadata.step_number,
                metadata.task_id,
                metadata.group_id,
                metadata.progress_percentage,
                metadata.estimated_time_remaining,
                compress,
                metadata.error,
                state_hash
            ))

            # Save state data
            cursor.execute("""
                INSERT INTO checkpoint_data (checkpoint_id, state_data, metadata_json)
                VALUES (?, ?, ?)
            """, (
                metadata.checkpoint_id,
                state_bytes,
                json.dumps(metadata.to_dict())
            ))

            conn.commit()
            logger.info(f"Saved checkpoint {metadata.checkpoint_id}")
            return metadata.checkpoint_id

        finally:
            conn.close()

    def load_checkpoint(self, checkpoint_id: str) -> Tuple[CheckpointMetadata, Dict[str, Any]]:
        """Load a checkpoint by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get metadata
            cursor.execute("""
                SELECT state_data, metadata_json, compressed
                FROM checkpoint_data
                JOIN checkpoints USING (checkpoint_id)
                WHERE checkpoint_id = ?
            """, (checkpoint_id,))

            row = cursor.fetchone()
            if not row:
                raise KeyError(f"Checkpoint {checkpoint_id} not found")

            state_bytes, metadata_json, compressed = row

            # Decompress if needed
            if compressed:
                state_bytes = gzip.decompress(state_bytes)

            # Deserialize
            state = pickle.loads(state_bytes)
            metadata_dict = json.loads(metadata_json)
            metadata = CheckpointMetadata(**metadata_dict)

            logger.info(f"Loaded checkpoint {checkpoint_id}")
            return metadata, state

        finally:
            conn.close()

    def get_latest_checkpoint(
        self,
        execution_id: str,
        checkpoint_type: Optional[str] = None
    ) -> Optional[str]:
        """Get the latest checkpoint ID for an execution."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            query = "SELECT checkpoint_id FROM checkpoints WHERE execution_id = ?"
            params = [execution_id]

            if checkpoint_type:
                query += " AND checkpoint_type = ?"
                params.append(checkpoint_type)

            query += " ORDER BY timestamp DESC LIMIT 1"

            cursor.execute(query, params)
            row = cursor.fetchone()
            return row[0] if row else None

        finally:
            conn.close()

    def list_checkpoints(
        self,
        execution_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """List checkpoints for an execution."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT checkpoint_id, timestamp, checkpoint_type, step_number,
                       task_id, progress_percentage
                FROM checkpoints
                WHERE execution_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (execution_id, limit))

            checkpoints = []
            for row in cursor.fetchall():
                checkpoints.append({
                    "checkpoint_id": row[0],
                    "timestamp": row[1],
                    "checkpoint_type": row[2],
                    "step_number": row[3],
                    "task_id": row[4],
                    "progress_percentage": row[5]
                })

            return checkpoints

        finally:
            conn.close()

    def delete_old_checkpoints(self, execution_id: str, keep_latest: int = 5) -> int:
        """Delete old checkpoints, keeping only the latest N."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get checkpoints to delete
            cursor.execute("""
                SELECT checkpoint_id FROM checkpoints
                WHERE execution_id = ?
                ORDER BY timestamp DESC
                LIMIT -1 OFFSET ?
            """, (execution_id, keep_latest))

            to_delete = [row[0] for row in cursor.fetchall()]

            # Delete them
            for checkpoint_id in to_delete:
                cursor.execute("DELETE FROM checkpoint_data WHERE checkpoint_id = ?",
                             (checkpoint_id,))
                cursor.execute("DELETE FROM checkpoints WHERE checkpoint_id = ?",
                             (checkpoint_id,))

            conn.commit()
            logger.info(f"Deleted {len(to_delete)} old checkpoints")
            return len(to_delete)

        finally:
            conn.close()

    def cleanup_execution(self, execution_id: str) -> None:
        """Clean up all checkpoints for an execution."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM checkpoint_data WHERE checkpoint_id IN (
                    SELECT checkpoint_id FROM checkpoints WHERE execution_id = ?
                )
            """, (execution_id,))

            cursor.execute("DELETE FROM checkpoints WHERE execution_id = ?",
                         (execution_id,))

            cursor.execute("DELETE FROM executions WHERE execution_id = ?",
                         (execution_id,))

            conn.commit()
            logger.info(f"Cleaned up execution {execution_id}")

        finally:
            conn.close()

    def get_execution_stats(self, execution_id: str) -> Dict[str, Any]:
        """Get statistics for an execution."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT total_steps, completed_steps, status
                FROM executions
                WHERE execution_id = ?
            """, (execution_id,))

            row = cursor.fetchone()
            if not row:
                return {}

            total_steps, completed_steps, status = row

            cursor.execute("""
                SELECT COUNT(*), SUM(progress_percentage), AVG(estimated_time_remaining)
                FROM checkpoints
                WHERE execution_id = ?
            """, (execution_id,))

            checkpoint_row = cursor.fetchone()
            checkpoint_count = checkpoint_row[0] or 0
            avg_progress = checkpoint_row[1] or 0
            avg_time_remaining = checkpoint_row[2]

            return {
                "execution_id": execution_id,
                "total_steps": total_steps,
                "completed_steps": completed_steps,
                "status": status,
                "checkpoint_count": checkpoint_count,
                "avg_progress": avg_progress / checkpoint_count if checkpoint_count > 0 else 0,
                "estimated_time_remaining": avg_time_remaining or 0
            }

        finally:
            conn.close()


class ExecutionRecovery:
    """Manages recovery from checkpoints."""

    def __init__(self, store: CheckpointStore):
        self.store = store

    def get_recovery_point(self, execution_id: str) -> Optional[Tuple[CheckpointMetadata, Dict[str, Any]]]:
        """Get the latest recovery point for an execution."""
        checkpoint_id = self.store.get_latest_checkpoint(execution_id)
        if not checkpoint_id:
            return None

        return self.store.load_checkpoint(checkpoint_id)

    def rollback_to_checkpoint(
        self,
        execution_id: str,
        checkpoint_id: str
    ) -> Tuple[CheckpointMetadata, Dict[str, Any]]:
        """Rollback to a specific checkpoint."""
        metadata, state = self.store.load_checkpoint(checkpoint_id)

        # Delete all checkpoints after this one
        conn = sqlite3.connect(self.store.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM checkpoint_data WHERE checkpoint_id IN (
                    SELECT checkpoint_id FROM checkpoints
                    WHERE execution_id = ? AND timestamp > ?
                )
            """, (execution_id, metadata.timestamp))

            cursor.execute("""
                DELETE FROM checkpoints
                WHERE execution_id = ? AND timestamp > ?
            """, (execution_id, metadata.timestamp))

            conn.commit()
            logger.info(f"Rolled back to checkpoint {checkpoint_id}")

        finally:
            conn.close()

        return metadata, state

    def validate_recovery(
        self,
        checkpoint_id: str,
        state: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """Validate that a checkpoint is valid for recovery."""
        metadata, stored_state = self.store.load_checkpoint(checkpoint_id)

        # Check if state keys match
        if set(state.keys()) != set(stored_state.keys()):
            return False, "State keys don't match stored checkpoint"

        # Check integrity
        state_bytes = pickle.dumps(state)
        state_hash = hashlib.sha256(state_bytes).hexdigest()

        conn = sqlite3.connect(self.store.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT state_hash FROM checkpoints WHERE checkpoint_id = ?",
                         (checkpoint_id,))
            row = cursor.fetchone()

            if row and row[0] != state_hash:
                return False, "State hash mismatch - data may be corrupted"

            return True, "Checkpoint is valid"

        finally:
            conn.close()


class CheckpointManager:
    """High-level manager for checkpointing and recovery."""

    def __init__(self, db_path: str = "~/.wiqo/checkpoints.db"):
        self.store = CheckpointStore(db_path)
        self.recovery = ExecutionRecovery(self.store)
        self.auto_checkpoint_interval = 30.0  # seconds
        self.last_checkpoint_time = 0.0

    def should_checkpoint(self) -> bool:
        """Check if enough time has passed for auto-checkpoint."""
        return time.time() - self.last_checkpoint_time >= self.auto_checkpoint_interval

    def create_checkpoint(
        self,
        execution_id: str,
        state: Dict[str, Any],
        step_number: int,
        checkpoint_type: str = "task_complete",
        task_id: Optional[str] = None,
        group_id: Optional[str] = None,
        progress_percentage: float = 0.0,
        estimated_time_remaining: float = 0.0
    ) -> str:
        """Create a checkpoint."""
        checkpoint_id = f"{execution_id}_{step_number}_{int(time.time() * 1000)}"

        metadata = CheckpointMetadata(
            checkpoint_id=checkpoint_id,
            execution_id=execution_id,
            timestamp=time.time(),
            checkpoint_type=checkpoint_type,
            step_number=step_number,
            task_id=task_id,
            group_id=group_id,
            progress_percentage=progress_percentage,
            estimated_time_remaining=estimated_time_remaining
        )

        self.store.save_checkpoint(metadata, state, compress=True)
        self.last_checkpoint_time = time.time()

        return checkpoint_id

    def get_recovery_state(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest recovery state."""
        recovery_point = self.recovery.get_recovery_point(execution_id)
        if recovery_point:
            return recovery_point[1]
        return None

    def list_checkpoints_for_execution(self, execution_id: str) -> List[Dict[str, Any]]:
        """List all checkpoints for an execution."""
        return self.store.list_checkpoints(execution_id, limit=100)

    def cleanup(self, execution_id: str) -> None:
        """Clean up checkpoints for an execution."""
        self.store.cleanup_execution(execution_id)
