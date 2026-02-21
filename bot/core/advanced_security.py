"""
Advanced Security & Permission System
Enhanced validation, threat detection, audit logging
"""

import re
import time
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from enum import Enum
from collections import Counter, deque

from utils.logger import get_logger

logger = get_logger("advanced_security")


class ThreatLevel(Enum):
    """Threat severity levels"""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionLevel(Enum):
    """User permission levels"""
    RESTRICTED = 0  # Can only run safe commands
    NORMAL = 1  # Can run most commands
    ELEVATED = 2  # Can run system commands
    ADMIN = 3  # Full access


@dataclass
class SecurityEvent:
    """Security event record"""
    event_type: str
    threat_level: ThreatLevel
    user_id: str
    description: str
    timestamp: float
    blocked: bool
    details: Dict[str, Any]


@dataclass
class Permission:
    """Permission definition"""
    name: str
    level: PermissionLevel
    description: str
    allowed_tools: Set[str]


class AdvancedSecurity:
    """
    Advanced Security & Permission System
    - Input validation and sanitization
    - Threat detection
    - Permission management
    - Security audit logging
    - Sensitive data protection
    """

    def __init__(self):
        self.security_events: deque = deque(maxlen=1000)
        self.blocked_patterns: List[str] = []
        self.user_permissions: Dict[str, PermissionLevel] = {}
        self.threat_score_threshold = 75  # 0-100

        # Sensitive patterns to detect
        self.sensitive_patterns = [
            # API Keys and tokens
            r'(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*["\']?[\w\-]+["\']?',
            # Credit cards
            r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b',
            # Social security numbers
            r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b',
            # Email addresses (for PII detection)
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        ]

        # Command injection patterns
        self.injection_patterns = [
            r';\s*rm\s+-rf',
            r'&&\s*rm\s+',
            r'\|\s*bash',
            r'\$\(.*\)',
            r'`.*`',
            r'>\s*/dev/',
            r'curl.*\|.*sh',
            r'wget.*\|.*sh'
        ]

        # Path traversal patterns
        self.traversal_patterns = [
            r'\.\./.*',
            r'/etc/passwd',
            r'/etc/shadow',
            r'%2e%2e',
            r'\.\.\\',
        ]

        # Dangerous tools requiring elevated permissions
        self.restricted_tools = {
            "run_safe_command",
            "kill_process",
            "delete_file",
            "move_file"
        }

        logger.info("Advanced Security System initialized")

    def validate_input(self, user_input: str, user_id: str) -> Dict[str, Any]:
        """
        Comprehensive input validation
        Returns: {valid: bool, threat_level: ThreatLevel, issues: List[str]}
        """
        issues = []
        threat_score = 0

        # Check for command injection
        for pattern in self.injection_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                issues.append(f"Command injection pattern detected: {pattern}")
                threat_score += 30

        # Check for path traversal
        for pattern in self.traversal_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                issues.append(f"Path traversal pattern detected")
                threat_score += 25

        # Check for sensitive data exposure
        for pattern in self.sensitive_patterns:
            if re.search(pattern, user_input):
                issues.append("Potential sensitive data detected")
                threat_score += 15

        # Check for SQL injection (if applicable)
        sql_patterns = [r"'\s*OR\s*'1'\s*=\s*'1", r";\s*DROP\s+TABLE"]
        for pattern in sql_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                issues.append("SQL injection pattern detected")
                threat_score += 30

        # Determine threat level
        if threat_score >= 75:
            threat_level = ThreatLevel.CRITICAL
        elif threat_score >= 50:
            threat_level = ThreatLevel.HIGH
        elif threat_score >= 25:
            threat_level = ThreatLevel.MEDIUM
        elif threat_score > 0:
            threat_level = ThreatLevel.LOW
        else:
            threat_level = ThreatLevel.NONE

        # Log security event
        if threat_level != ThreatLevel.NONE:
            self._log_security_event(
                event_type="input_validation",
                threat_level=threat_level,
                user_id=user_id,
                description=f"Threat detected in user input",
                blocked=threat_score >= self.threat_score_threshold,
                details={"issues": issues, "threat_score": threat_score}
            )

        return {
            "valid": threat_score < self.threat_score_threshold,
            "threat_level": threat_level,
            "threat_score": threat_score,
            "issues": issues
        }

    def sanitize_input(self, user_input: str) -> str:
        """Sanitize user input by removing dangerous patterns"""
        sanitized = user_input

        # Remove null bytes
        sanitized = sanitized.replace('\0', '')

        # Remove control characters
        sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)

        # Limit length
        max_length = 10000
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]

        return sanitized

    def check_permission(
        self,
        user_id: str,
        tool_name: str
    ) -> Dict[str, Any]:
        """
        Check if user has permission to use tool
        Returns: {allowed: bool, reason: str}
        """
        user_level = self.user_permissions.get(user_id, PermissionLevel.NORMAL)

        # Admin has full access
        if user_level == PermissionLevel.ADMIN:
            return {"allowed": True, "reason": "Admin access"}

        # Check if tool is restricted
        if tool_name in self.restricted_tools:
            if user_level.value < PermissionLevel.ELEVATED.value:
                self._log_security_event(
                    event_type="permission_denied",
                    threat_level=ThreatLevel.MEDIUM,
                    user_id=user_id,
                    description=f"Attempted to use restricted tool: {tool_name}",
                    blocked=True,
                    details={"tool": tool_name, "user_level": user_level.name}
                )
                return {
                    "allowed": False,
                    "reason": f"Tool '{tool_name}' requires elevated permissions"
                }

        return {"allowed": True, "reason": "Permission granted"}

    def validate_file_access(
        self,
        file_path: str,
        operation: str,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Validate file access operations
        operation: read, write, delete, execute
        """
        path = Path(file_path).resolve()

        # Blocked directories
        blocked_dirs = [
            "/etc",
            "/bin",
            "/sbin",
            "/usr/bin",
            "/usr/sbin",
            "/System",
            "/Library/System"
        ]

        # Check if in blocked directory
        for blocked in blocked_dirs:
            if str(path).startswith(blocked):
                self._log_security_event(
                    event_type="file_access_denied",
                    threat_level=ThreatLevel.HIGH,
                    user_id=user_id,
                    description=f"Attempted access to restricted directory: {blocked}",
                    blocked=True,
                    details={"path": str(path), "operation": operation}
                )
                return {
                    "allowed": False,
                    "reason": f"Access to {blocked} is restricted"
                }

        # Check for path traversal
        if ".." in str(path):
            return {
                "allowed": False,
                "reason": "Path traversal not allowed"
            }

        # Check if trying to access sensitive files
        sensitive_files = ["id_rsa", "id_ecdsa", "id_ed25519", ".ssh/", "credentials"]
        for sensitive in sensitive_files:
            if sensitive in str(path):
                self._log_security_event(
                    event_type="sensitive_file_access",
                    threat_level=ThreatLevel.CRITICAL,
                    user_id=user_id,
                    description=f"Attempted access to sensitive file",
                    blocked=True,
                    details={"path": str(path), "operation": operation}
                )
                return {
                    "allowed": False,
                    "reason": "Access to sensitive files is restricted"
                }

        return {"allowed": True, "reason": "File access permitted"}

    def detect_anomaly(
        self,
        user_id: str,
        action: str,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Detect anomalous behavior patterns"""
        # Get recent actions by user
        recent_events = [
            e for e in self.security_events
            if e.user_id == user_id
            and time.time() - e.timestamp < 300  # Last 5 minutes
        ]

        # Rapid fire detection
        if len(recent_events) > 50:
            return {
                "anomaly": "rapid_fire",
                "severity": ThreatLevel.HIGH,
                "description": "Unusually high activity rate detected"
            }

        # Repeated failures
        failures = [e for e in recent_events if "failed" in e.description.lower()]
        if len(failures) > 10:
            return {
                "anomaly": "repeated_failures",
                "severity": ThreatLevel.MEDIUM,
                "description": "Multiple failed attempts detected"
            }

        # Unusual tool usage
        restricted_access = [e for e in recent_events if e.event_type == "permission_denied"]
        if len(restricted_access) > 5:
            return {
                "anomaly": "privilege_escalation_attempt",
                "severity": ThreatLevel.CRITICAL,
                "description": "Potential privilege escalation attempt"
            }

        return None

    def _log_security_event(
        self,
        event_type: str,
        threat_level: ThreatLevel,
        user_id: str,
        description: str,
        blocked: bool,
        details: Dict[str, Any]
    ):
        """Log security event"""
        event = SecurityEvent(
            event_type=event_type,
            threat_level=threat_level,
            user_id=user_id,
            description=description,
            timestamp=time.time(),
            blocked=blocked,
            details=details
        )

        self.security_events.append(event)

        # Log critical events
        if threat_level in [ThreatLevel.HIGH, ThreatLevel.CRITICAL]:
            logger.warning(f"SECURITY: [{threat_level.value.upper()}] {description} (User: {user_id})")

    def get_security_report(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get security report"""
        events = list(self.security_events)

        if user_id:
            events = [e for e in events if e.user_id == user_id]

        # Count by threat level
        threat_counts = Counter([e.threat_level.value for e in events])

        # Count by event type
        event_type_counts = Counter([e.event_type for e in events])

        # Recent critical events
        critical_events = [
            {
                "type": e.event_type,
                "description": e.description,
                "user_id": e.user_id,
                "timestamp": e.timestamp,
                "blocked": e.blocked
            }
            for e in events
            if e.threat_level == ThreatLevel.CRITICAL
        ][-10:]

        return {
            "total_events": len(events),
            "threat_levels": dict(threat_counts),
            "event_types": dict(event_type_counts),
            "critical_events": critical_events,
            "blocked_count": sum(1 for e in events if e.blocked)
        }

    def set_user_permission(self, user_id: str, level: PermissionLevel):
        """Set user permission level"""
        self.user_permissions[user_id] = level
        logger.info(f"User {user_id} permission set to {level.name}")

    def get_user_permission(self, user_id: str) -> PermissionLevel:
        """Get user permission level"""
        return self.user_permissions.get(user_id, PermissionLevel.NORMAL)

    def add_blocked_pattern(self, pattern: str):
        """Add a pattern to block list"""
        self.blocked_patterns.append(pattern)
        logger.info(f"Added blocked pattern: {pattern}")

    def check_rate_limit(self, user_id: str, action: str) -> Dict[str, Any]:
        """Advanced rate limiting"""
        # Get recent actions
        recent = [
            e for e in self.security_events
            if e.user_id == user_id
            and time.time() - e.timestamp < 60  # Last minute
        ]

        max_per_minute = 60
        if len(recent) > max_per_minute:
            self._log_security_event(
                event_type="rate_limit_exceeded",
                threat_level=ThreatLevel.MEDIUM,
                user_id=user_id,
                description="Rate limit exceeded",
                blocked=True,
                details={"action_count": len(recent)}
            )
            return {
                "allowed": False,
                "reason": "Rate limit exceeded",
                "retry_after": 60
            }

        return {"allowed": True, "reason": "Within rate limit"}

    def get_summary(self) -> Dict[str, Any]:
        """Get security summary"""
        critical = sum(1 for e in self.security_events if e.threat_level == ThreatLevel.CRITICAL)
        high = sum(1 for e in self.security_events if e.threat_level == ThreatLevel.HIGH)
        blocked = sum(1 for e in self.security_events if e.blocked)

        return {
            "total_events": len(self.security_events),
            "critical_threats": critical,
            "high_threats": high,
            "blocked_actions": blocked,
            "active_users": len(set(e.user_id for e in self.security_events))
        }


# Global instance
_advanced_security: Optional[AdvancedSecurity] = None


def get_advanced_security() -> AdvancedSecurity:
    """Get or create global advanced security instance"""
    global _advanced_security
    if _advanced_security is None:
        _advanced_security = AdvancedSecurity()
    return _advanced_security
