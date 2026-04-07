"""
Session Security & Token Management

Provides:
- Encrypted session tokens
- Session metadata encryption
- In-memory session store
- Token lifecycle management (issuance, validation, revocation)
"""

import json
import os
import time
import uuid
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path

from config.elyan_config import elyan_config
from core.observability.logger import get_structured_logger
from core.security.encrypted_vault import get_encrypted_vault
from core.storage_paths import resolve_elyan_data_dir

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

    def __init__(self, token_ttl_seconds: int = 3600, *, storage_path: Optional[str] = None, persistence_enabled: Optional[bool] = None):
        """
        Initialize session manager.

        Args:
            token_ttl_seconds: Token time-to-live in seconds (default 1 hour)
        """
        self.token_ttl = token_ttl_seconds
        self._sessions: Dict[str, SessionToken] = {}
        self._vault = get_encrypted_vault()
        configured_path = str(elyan_config.get("security.sessionSecurity.path", "") or "").strip()
        self._persistence_enabled = (
            bool(persistence_enabled)
            if persistence_enabled is not None
            else (
                bool(elyan_config.get("security.sessionSecurity.persist", True))
                and os.environ.get("ELYAN_SESSION_SECURITY_PERSIST", "1").strip().lower() not in {"0", "false", "off"}
            )
            and "PYTEST_CURRENT_TEST" not in os.environ
        )
        self._storage_path = self._resolve_storage_path(storage_path=storage_path, configured_path=configured_path)
        if self._persistence_enabled:
            try:
                self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                self._disable_persistence("session_storage_unavailable", exc)
            else:
                self._restore_sessions()

    def _resolve_storage_path(self, *, storage_path: Optional[str], configured_path: str) -> Path:
        if storage_path:
            return Path(storage_path).expanduser()
        if configured_path:
            return Path(configured_path).expanduser()
        if self._persistence_enabled:
            return (resolve_elyan_data_dir() / "security" / "sessions.json").expanduser()

        data_root = str(os.getenv("ELYAN_DATA_DIR", "") or "").strip()
        if data_root:
            return (Path(data_root).expanduser() / "security" / "sessions.json").expanduser()
        return (Path.home() / ".elyan" / "security" / "sessions.json").expanduser()

    def _disable_persistence(self, event_name: str, exc: Exception) -> None:
        self._persistence_enabled = False
        slog.log_event(
            event_name,
            {"error": str(exc), "storage_path": str(self._storage_path)},
            level="warning",
        )

    @staticmethod
    def _record_security_event(event_name: str, payload: Dict[str, Any]) -> None:
        try:
            from core.elyan_runtime import get_elyan_runtime
            from core.events.event_store import EventType

            event_type = getattr(EventType, event_name, None)
            if event_type is None:
                return
            get_elyan_runtime().record_event(
                event_type=event_type,
                aggregate_id=str(payload.get("token_id") or payload.get("user_id") or "security"),
                aggregate_type="security",
                payload=dict(payload or {}),
            )
        except Exception:
            return

    def _persist_sessions(self) -> None:
        if not self._persistence_enabled:
            return
        try:
            payload = {
                "ttl_seconds": self.token_ttl,
                "tokens": [
                    {
                        "token_id": token.token_id,
                        "user_id": token.user_id,
                        "created_at": token.created_at,
                        "expires_at": token.expires_at,
                        "encrypted_payload": token.encrypted_payload,
                        "metadata": token.metadata,
                    }
                    for token in self._sessions.values()
                ],
            }
            tmp = self._storage_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._storage_path)
        except Exception as exc:
            slog.log_event("session_persist_error", {"error": str(exc)}, level="warning")

    def _restore_sessions(self) -> None:
        try:
            if not self._storage_path.exists():
                return
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            rows = payload.get("tokens") if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                return
            restored = 0
            now = time.time()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                token = SessionToken(
                    token_id=str(row.get("token_id") or f"tok_{uuid.uuid4().hex[:16]}"),
                    user_id=str(row.get("user_id") or "unknown"),
                    created_at=float(row.get("created_at") or now),
                    expires_at=float(row.get("expires_at") or now),
                    encrypted_payload=dict(row.get("encrypted_payload") or {}),
                    metadata=dict(row.get("metadata") or {}),
                )
                if token.expires_at <= now:
                    continue
                self._sessions[token.token_id] = token
                restored += 1
            if restored:
                slog.log_event("session_tokens_restored", {"count": restored, "path": str(self._storage_path)})
        except Exception as exc:
            self._disable_persistence("session_restore_error", exc)

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
            self._persist_sessions()

            slog.log_event("token_issued", {
                "token_id": token_id,
                "user_id": user_id,
                "ttl_seconds": self.token_ttl
            })
            self._record_security_event(
                "TOKEN_ISSUED",
                {"token_id": token_id, "user_id": user_id, "ttl_seconds": self.token_ttl},
            )

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
                self._persist_sessions()
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
                self._persist_sessions()
                slog.log_event("token_revoked", {
                    "token_id": token_id,
                    "user_id": token.user_id
                })
                self._record_security_event(
                    "TOKEN_REVOKED",
                    {"token_id": token_id, "user_id": token.user_id},
                )
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
            self._persist_sessions()
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
            "ttl_seconds": self.token_ttl,
            "persistence_enabled": self._persistence_enabled,
            "storage_path": str(self._storage_path),
        }


# Singleton instance
_session_manager: Optional[SessionManager] = None


def get_session_manager(token_ttl_seconds: int = 3600) -> SessionManager:
    """Get or create session manager singleton."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(token_ttl_seconds)
    return _session_manager
