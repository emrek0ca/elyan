"""
Approval History & Audit Log

Persistent record of all approval decisions with full audit trail.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict, field

from core.observability.logger import get_structured_logger

slog = get_structured_logger("approval_history")


@dataclass
class ApprovalHistoryRecord:
    """Single approval history entry."""
    history_id: str
    request_id: str
    action_type: str
    session_id: str
    resolver_id: str
    approved: bool
    resolved_at: float
    reason: str = ""
    risk_level: str = ""
    comments: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ApprovalHistoryManager:
    """Manages approval audit trail and history."""

    def __init__(self, storage_path: Optional[str] = None):
        """Initialize history manager.

        Args:
            storage_path: Path to store history (default: ~/.elyan/approval-history)
        """
        if storage_path is None:
            storage_path = os.path.expanduser("~/.elyan/approval-history")
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _save_history(self, record: ApprovalHistoryRecord) -> None:
        """Save approval history record."""
        try:
            file_path = self.storage_path / f"{record.history_id}.json"
            with open(file_path, "w") as f:
                json.dump(record.to_dict(), f, indent=2)
            slog.log_event("approval_history_saved", {
                "history_id": record.history_id,
                "action": record.action_type,
                "approved": record.approved
            })
        except Exception as e:
            slog.log_event("approval_history_save_error", {
                "error": str(e)
            }, level="error")

    def record_approval(
        self,
        request_id: str,
        action_type: str,
        session_id: str,
        resolver_id: str,
        approved: bool,
        reason: str = "",
        risk_level: str = "",
        comments: str = ""
    ) -> str:
        """Record an approval decision.

        Returns:
            History ID of the recorded entry
        """
        import uuid
        history_id = f"hist_{uuid.uuid4().hex[:8]}"

        record = ApprovalHistoryRecord(
            history_id=history_id,
            request_id=request_id,
            action_type=action_type,
            session_id=session_id,
            resolver_id=resolver_id,
            approved=approved,
            resolved_at=datetime.now().timestamp(),
            reason=reason,
            risk_level=risk_level,
            comments=comments
        )

        self._save_history(record)
        return history_id

    def get_history(self, history_id: str) -> Optional[ApprovalHistoryRecord]:
        """Retrieve a history record by ID."""
        try:
            file_path = self.storage_path / f"{history_id}.json"
            if not file_path.exists():
                return None
            with open(file_path, "r") as f:
                data = json.load(f)
            return ApprovalHistoryRecord(**data)
        except Exception as e:
            slog.log_event("approval_history_get_error", {
                "history_id": history_id,
                "error": str(e)
            }, level="warning")
            return None

    def get_approval_history(
        self,
        action_type: Optional[str] = None,
        resolver_id: Optional[str] = None,
        limit: int = 100,
        approved_only: Optional[bool] = None
    ) -> List[ApprovalHistoryRecord]:
        """Get approval history with optional filters.

        Args:
            action_type: Filter by action type
            resolver_id: Filter by who resolved it
            limit: Maximum records to return
            approved_only: Filter by approved (True) or denied (False)

        Returns:
            List of history records, sorted by date descending
        """
        try:
            records = []
            files = sorted(
                self.storage_path.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )

            for file_path in files[:limit * 2]:
                try:
                    with open(file_path, "r") as f:
                        data = json.load(f)
                    record = ApprovalHistoryRecord(**data)

                    # Apply filters
                    if action_type and record.action_type != action_type:
                        continue
                    if resolver_id and record.resolver_id != resolver_id:
                        continue
                    if approved_only is not None and record.approved != approved_only:
                        continue

                    records.append(record)
                    if len(records) >= limit:
                        break
                except Exception:
                    pass

            return records
        except Exception as e:
            slog.log_event("approval_history_list_error", {
                "error": str(e)
            }, level="error")
            return []

    def get_statistics(self) -> Dict[str, Any]:
        """Get approval statistics."""
        try:
            records = self.get_approval_history(limit=10000)

            total = len(records)
            approved = len([r for r in records if r.approved])
            denied = len([r for r in records if not r.approved])

            approval_rate = (approved / total * 100) if total > 0 else 0

            # Group by action type
            action_stats = {}
            for record in records:
                if record.action_type not in action_stats:
                    action_stats[record.action_type] = {"total": 0, "approved": 0}
                action_stats[record.action_type]["total"] += 1
                if record.approved:
                    action_stats[record.action_type]["approved"] += 1

            return {
                "total_decisions": total,
                "approved": approved,
                "denied": denied,
                "approval_rate_pct": round(approval_rate, 1),
                "by_action_type": action_stats
            }
        except Exception as e:
            slog.log_event("approval_history_stats_error", {
                "error": str(e)
            }, level="error")
            return {}

    def export_audit_report(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
        """Export audit report as JSON.

        Args:
            start_date: ISO format date string
            end_date: ISO format date string

        Returns:
            JSON string of audit trail
        """
        records = self.get_approval_history(limit=10000)

        # Filter by date if provided
        if start_date or end_date:
            try:
                start_ts = datetime.fromisoformat(start_date).timestamp() if start_date else 0
                end_ts = datetime.fromisoformat(end_date).timestamp() if end_date else float('inf')
                records = [r for r in records if start_ts <= r.resolved_at <= end_ts]
            except Exception:
                pass

        report = {
            "generated_at": datetime.now().isoformat(),
            "total_records": len(records),
            "records": [r.to_dict() for r in records]
        }

        return json.dumps(report, indent=2, default=str)


# Global instance
_history_manager: Optional[ApprovalHistoryManager] = None


def get_approval_history_manager(storage_path: Optional[str] = None) -> ApprovalHistoryManager:
    """Get or create approval history manager singleton."""
    global _history_manager
    if _history_manager is None:
        _history_manager = ApprovalHistoryManager(storage_path)
    return _history_manager
