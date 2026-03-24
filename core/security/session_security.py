"""
Session Security & Token Management

Provides:
- Encrypted session tokens
- Session metadata encryption
- In-memory session store
- Token lifecycle management (issuance, validation, revocation)
"""

import uuid
import time
import json
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from core.observability.logger import get_structured_logger
from core.security.encrypted_vault import get_encrypted_vault

slog = get_structured_logger("session_security")


@dataclass
class SessionToken:
    """Encrypted session token metadata."""
    token_id: str
    user_id: str
    created_at: float
    expires_at: float
    encrypted_payload: Dict[str, str]  # Encrypted session data
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if token is expired."""
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict (for logging)."""
        return {
            "token_id": self.token_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "expired": self.is_expired(),
            "metadata": self.metadata
        }


class SessionManager:
    """Manages encrypted session tokens."""

    def __init__(self, token_ttl_seconds: int = 3600):
        """
        Initialize session manager.

        Args:
            token_ttl_seconds: Token time-to-live in seconds (default 1 hour)
        """
        self.token_ttl = token_ttl_seconds
        self._sessions: Dict[str, SessionToken] = {}
        self._vault = get_encrypted_vault()

    def issue_token(
        self,
        user_id: str,
        session_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Issue a new encrypted session token.

        Args:
            user_id: User identifier
            session_data: Session data to encrypt
            metadata: Unencrypted metadata (for logging)

        Returns:
            Token ID (client stores this, not the full token)
        """
        try:
            token_id = f"tok_{uuid.uuid4().hex[:16]}"
            now = time.time()
            expires_at = now + self.token_ttl

            # Encrypt session data
            encrypted = self._vault.encrypt(
                session_data,
                context=f"session_{token_id}"
            )

            # Create token record
            token = SessionToken(
                token_id=token_id,
                user_id=user_id,
                created_at=now,
                expires_at=expires_at,
                encrypted_payload=encrypted,
                metadata=metadata or {}
            )

            self._sessions[token_id] = token

            slog.log_event("token_issued", {
                "token_id": token_id,
                "user_id": user_id,
                "ttl_seconds": self.token_ttl
            })

            return token_id

        except Exception as e:
            slog.log_event("token_issue_error", {
                "error": str(e),
                "user_id": user_id
            }, level="error")
            raise

    def validate_token(self, token_id: str) -> Optional[Dict[str, Any]]:
        """
        Validate and decrypt session token.

        Args:
            token_id: Token ID to validate

        Returns:
            Decrypted session data if valid, None otherwise
        """
        try:
            token = self._sessions.get(token_id)
            if not token:
                slog.log_event("token_not_found", {
                    "token_id": token_id
                }, level="warning")
                return None

            if token.is_expired():
                self._sessions.pop(token_id, None)
                slog.log_event("token_expired", {
                    "token_id": token_id,
                    "user_id": token.user_id
                }, level="warning")
                return None

            # Decrypt session data
            session_data = self._vault.decrypt(
                token.encrypted_payload,
                context=f"session_{token_id}"
            )

            return session_data

        except Exception as e:
            slog.log_event("token_validation_error", {
                "error": str(e),
                "token_id": token_id
            }, level="error")
            return None

    def revoke_token(self, token_id: str) -> bool:
        """Revoke a session token."""
        try:
            if token_id in self._sessions:
                token = self._sessions.pop(token_id)
                slog.log_event("token_revoked", {
                    "token_id": token_id,
                    "user_id": token.user_id
                })
                return True
            return False
        except Exception as e:
            slog.log_event("token_revoke_error", {
                "error": str(e),
                "token_id": token_id
            }, level="error")
            return False

    def cleanup_expired(self) -> int:
        """Remove expired tokens. Returns count of removed tokens."""
        expired = [
            tid for tid, token in self._sessions.items()
            if token.is_expired()
        ]
        for tid in expired:
            self._sessions.pop(tid, None)

        if expired:
            slog.log_event("cleanup_expired_tokens", {
                "count": len(expired)
            })

        return len(expired)

    def get_active_sessions(self, user_id: str) -> list:
        """Get active sessions for a user."""
        return [
            token.to_dict() for token in self._sessions.values()
            if token.user_id == user_id and not token.is_expired()
        ]

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        total = len(self._sessions)
        expired = sum(1 for t in self._sessions.values() if t.is_expired())
        active = total - expired

        users = set(t.user_id for t in self._sessions.values() if not t.is_expired())

        return {
            "total_tokens": total,
            "active_tokens": active,
            "expired_tokens": expired,
            "unique_users": len(users),
            "ttl_seconds": self.token_ttl
        }


# Singleton instance
_session_manager: Optional[SessionManager] = None


def get_session_manager(token_ttl_seconds: int = 3600) -> SessionManager:
    """Get or create session manager singleton."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(token_ttl_seconds)
    return _session_manager
