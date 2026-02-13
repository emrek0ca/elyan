"""
Approval System for Dangerous Operations

Provides:
- User approval workflow for risky operations
- Operation risk classification
- Dry-run/simulation mode
- Approval history and audit trail
"""

import asyncio
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
from uuid import uuid4
from utils.logger import get_logger

logger = get_logger("safety.approval")


class RiskLevel(Enum):
    """Risk levels for operations"""
    SAFE = "safe"  # No approval needed
    LOW = "low"  # Auto-approve for trusted users
    MEDIUM = "medium"  # Request approval
    HIGH = "high"  # Require explicit approval
    CRITICAL = "critical"  # Require confirmation + justification


@dataclass
class ApprovalRequest:
    """Represents an approval request"""
    id: str
    operation: str
    risk_level: RiskLevel
    description: str
    params: Dict[str, Any]
    user_id: int
    timestamp: str
    status: str = "pending"  # pending, approved, denied, expired
    response: Optional[str] = None
    response_time: Optional[str] = None


class ApprovalManager:
    """
    Manages approval requests for dangerous operations
    """
    
    def __init__(self, default_timeout: int = 300):
        self.default_timeout = default_timeout
        self.pending_requests: Dict[str, ApprovalRequest] = {}
        self.approval_history: List[ApprovalRequest] = []
        self.approval_callback: Optional[Callable] = None
        
        # Auto-approve settings
        self.auto_approve_low_risk = True
        self.trusted_users: set = set()
    
    def set_approval_callback(self, callback: Callable):
        """
        Set callback function for requesting user approval
        
        The callback should:
        - Display the approval request to user
        - Return True for approved, False for denied
        
        Args:
            callback: async function(request: ApprovalRequest) -> bool
        """
        self.approval_callback = callback
    
    async def request_approval(self, operation: str, risk_level: RiskLevel,
                              description: str, params: Dict[str, Any],
                              user_id: int, timeout: int = None) -> Dict[str, Any]:
        """
        Request approval for an operation
        
        Args:
            operation: Operation name
            risk_level: Risk level
            description: Human-readable description
            params: Operation parameters
            user_id: User ID requesting the operation
            timeout: Approval timeout in seconds
        
        Returns:
            Approval result
        """
        # Check if auto-approval is possible
        if self._can_auto_approve(risk_level, user_id):
            logger.info(f"Auto-approved {operation} for user {user_id} (risk: {risk_level.value})")
            return {
                "approved": True,
                "auto_approved": True,
                "reason": "Low risk operation or trusted user"
            }
        
        # Create approval request
        request_id = f"req_{user_id}_{int(datetime.now().timestamp() * 1000)}_{uuid4().hex[:8]}"
        request = ApprovalRequest(
            id=request_id,
            operation=operation,
            risk_level=risk_level,
            description=description,
            params=params,
            user_id=user_id,
            timestamp=datetime.now().isoformat()
        )
        
        self.pending_requests[request_id] = request
        
        # Request user approval
        if not self.approval_callback:
            logger.error("No approval callback set!")
            return {
                "approved": False,
                "reason": "Approval system not configured"
            }
        
        try:
            # Call approval callback with timeout
            approved = await asyncio.wait_for(
                self.approval_callback(request),
                timeout=timeout or self.default_timeout
            )
            
            request.status = "approved" if approved else "denied"
            request.response_time = datetime.now().isoformat()
            
        except asyncio.TimeoutError:
            request.status = "expired"
            approved = False
            logger.warning(f"Approval request {request_id} expired")
        
        # Move to history
        del self.pending_requests[request_id]
        self.approval_history.append(request)
        
        return {
            "approved": approved,
            "request_id": request_id,
            "status": request.status,
            "auto_approved": False
        }
    
    def _can_auto_approve(self, risk_level: RiskLevel, user_id: int) -> bool:
        """Check if operation can be auto-approved"""
        if risk_level == RiskLevel.SAFE:
            return True
        
        if risk_level == RiskLevel.LOW and self.auto_approve_low_risk:
            return True
        
        if user_id in self.trusted_users and risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM]:
            return True
        
        return False
    
    def add_trusted_user(self, user_id: int):
        """Add a trusted user who gets auto-approval for medium-risk operations"""
        self.trusted_users.add(user_id)
        logger.info(f"Added trusted user: {user_id}")
    
    def remove_trusted_user(self, user_id: int):
        """Remove a trusted user"""
        self.trusted_users.discard(user_id)
        logger.info(f"Removed trusted user: {user_id}")
    
    def get_approval_history(self, user_id: int = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get approval history"""
        history = self.approval_history
        
        if user_id:
            history = [r for r in history if r.user_id == user_id]
        
        return [
            {
                "id": r.id,
                "operation": r.operation,
                "risk_level": r.risk_level.value,
                "description": r.description,
                "timestamp": r.timestamp,
                "status": r.status
            }
            for r in history[-limit:]
        ]
    
    def classify_operation_risk(self, operation: str, params: Dict[str, Any]) -> RiskLevel:
        """
        Classify operation risk level
        
        Args:
            operation: Operation name
            params: Operation parameters
        
        Returns:
            Risk level
        """
        # Critical operations (explicit user confirmation is mandatory)
        critical_ops = {
            "shutdown_system", "restart_system",
        }

        # High risk operations
        high_risk_ops = {
            "delete_file", "delete_folder", "kill_process",
            "execute_safe_command", "execute_script",
            "run_safe_command", "run_command", "execute_command",
            "sleep_system", "lock_screen",
        }
        
        # Medium risk operations
        medium_risk_ops = {
            "write_file", "move_file", "rename_file",
            "execute_python", "run_python_file",
            "close_app"
        }
        
        # Check operation name
        if operation in critical_ops:
            return RiskLevel.CRITICAL

        if operation in high_risk_ops:
            # Further analysis based on params
            if operation == "delete_file":
                # Check if deleting sensitive files
                file_path = str(params.get("file_path") or params.get("path") or "")
                if any(sensitive in file_path.lower() for sensitive in ["/system", "/library", ".app"]):
                    return RiskLevel.CRITICAL
                return RiskLevel.HIGH
            
            elif operation in [
                "execute_safe_command", "execute_script",
                "run_safe_command", "run_command", "execute_command"
            ]:
                # Check command safety
                command = str(params.get("command") or params.get("cmd") or "")
                if any(danger in command.lower() for danger in ["rm -rf", "dd if=", "mkfs"]):
                    return RiskLevel.CRITICAL
                return RiskLevel.HIGH
            
            return RiskLevel.HIGH
        
        elif operation in medium_risk_ops:
            return RiskLevel.MEDIUM
        
        # Default to low risk
        return RiskLevel.LOW


# Global approval manager
_approval_manager = None


def get_approval_manager() -> ApprovalManager:
    """Get or create global approval manager"""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager


# Helper functions

async def require_approval(operation: str, description: str,
                          params: Dict[str, Any], user_id: int) -> bool:
    """
    Request approval for an operation
    
    Returns:
        True if approved, False otherwise
    """
    manager = get_approval_manager()
    
    # Classify risk
    risk_level = manager.classify_operation_risk(operation, params)
    
    # Request approval
    result = await manager.request_approval(
        operation=operation,
        risk_level=risk_level,
        description=description,
        params=params,
        user_id=user_id
    )
    
    return result["approved"]


def classify_risk(operation: str, params: Dict[str, Any]) -> str:
    """Classify operation risk level"""
    manager = get_approval_manager()
    risk = manager.classify_operation_risk(operation, params)
    return risk.value
