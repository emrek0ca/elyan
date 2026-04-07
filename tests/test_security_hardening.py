"""
Security Hardening Tests (Phase 5.2.2)

Test:
- Encrypted Vault (encryption/decryption, key derivation)
- Session Manager (token issuance, validation, revocation)
- Approval Audit Log (action logging, encrypted storage)
"""

import pytest
import time
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from core.security.encrypted_vault import EncryptedVault, get_encrypted_vault
from core.security.session_security import SessionManager, get_session_manager
from core.security.audit_approval import ApprovalAuditLog, get_approval_audit_log


class TestEncryptedVault:
    """Test encrypted data vault."""

    @pytest.fixture
    def vault(self):
        """Create vault with test key."""
        test_key = os.urandom(32)  # Generate 32 random bytes
        return EncryptedVault(test_key)

    def test_vault_initialization(self, vault):
        """Test vault initialization."""
        assert vault.master_key is not None
        assert len(vault.master_key) == 32

    def test_encrypt_decrypt_simple(self, vault):
        """Test encrypt and decrypt simple data."""
        data = {"user": "test", "action": "approve"}
        encrypted = vault.encrypt(data)

        assert "ciphertext" in encrypted
        assert "nonce" in encrypted
        assert "salt" in encrypted

        decrypted = vault.decrypt(encrypted)
        assert decrypted == data

    def test_encrypt_decrypt_complex(self, vault):
        """Test with complex nested data."""
        data = {
            "request_id": "req_123",
            "metadata": {
                "risk_level": "high",
                "timestamp": 1234567890,
                "nested": {
                    "deep": "value"
                }
            },
            "items": [1, 2, 3, 4, 5]
        }
        encrypted = vault.encrypt(data)
        decrypted = vault.decrypt(encrypted)
        assert decrypted == data

    def test_encrypt_with_context(self, vault):
        """Test encryption with context."""
        data = {"sensitive": "data"}
        encrypted = vault.encrypt(data, context="user_session")

        # Should fail to decrypt with different context
        with pytest.raises(Exception):
            vault.decrypt(encrypted, context="different_context")

    def test_different_encryptions_different_results(self, vault):
        """Test that same data encrypts differently (due to random salt/nonce)."""
        data = {"test": "data"}
        enc1 = vault.encrypt(data)
        enc2 = vault.encrypt(data)

        # Ciphertexts should be different
        assert enc1["ciphertext"] != enc2["ciphertext"]
        # But both should decrypt to same data
        assert vault.decrypt(enc1) == data
        assert vault.decrypt(enc2) == data

    def test_password_hashing(self, vault):
        """Test password hashing and verification."""
        password = "test_password_123"
        hashed = vault.hash_password(password)

        assert vault.verify_password(password, hashed)
        assert not vault.verify_password("wrong_password", hashed)

    def test_tamper_detection(self, vault):
        """Test that tampering with ciphertext is detected."""
        data = {"important": "data"}
        encrypted = vault.encrypt(data)

        # Tamper with ciphertext
        tampered = encrypted.copy()
        tampered_ct = list(encrypted["ciphertext"])
        tampered_ct[0] = 'Z'  # Change first character
        tampered["ciphertext"] = ''.join(tampered_ct)

        # Should fail to decrypt
        with pytest.raises(Exception):
            vault.decrypt(tampered)


class TestSessionManager:
    """Test session token management."""

    @pytest.fixture
    def manager(self):
        """Create session manager with short TTL for testing."""
        return SessionManager(token_ttl_seconds=10)

    def test_token_issuance(self, manager):
        """Test issuing a session token."""
        session_data = {"user_id": "user_123", "permissions": ["read", "write"]}
        token_id = manager.issue_token("user_123", session_data)

        assert token_id.startswith("tok_")
        assert len(token_id) > 10

    def test_token_validation(self, manager):
        """Test token validation and decryption."""
        session_data = {"user_id": "user_123", "action": "list_files"}
        token_id = manager.issue_token("user_123", session_data)

        validated_data = manager.validate_token(token_id)
        assert validated_data == session_data

    def test_invalid_token(self, manager):
        """Test validation of non-existent token."""
        result = manager.validate_token("invalid_token_id")
        assert result is None

    def test_token_expiration(self, manager):
        """Test token expiration."""
        session_data = {"test": "data"}
        token_id = manager.issue_token("user_123", session_data)

        # Token should be valid immediately
        assert manager.validate_token(token_id) is not None

        # Manually set expiration to past
        manager._sessions[token_id].expires_at = time.time() - 1

        # Should now be expired
        assert manager.validate_token(token_id) is None
        assert token_id not in manager._sessions

    def test_token_revocation(self, manager):
        """Test token revocation."""
        session_data = {"test": "data"}
        token_id = manager.issue_token("user_123", session_data)

        assert manager.validate_token(token_id) is not None

        # Revoke token
        assert manager.revoke_token(token_id) is True

        # Should no longer be valid
        assert manager.validate_token(token_id) is None
        assert manager.revoke_token(token_id) is False  # Already revoked

    def test_cleanup_expired(self, manager):
        """Test cleanup of expired tokens."""
        token_ids = []
        for i in range(5):
            token_id = manager.issue_token(f"user_{i}", {"data": i})
            token_ids.append(token_id)

        # Expire some tokens
        manager._sessions[token_ids[0]].expires_at = time.time() - 1
        manager._sessions[token_ids[1]].expires_at = time.time() - 1
        manager._sessions[token_ids[2]].expires_at = time.time() - 1

        # Cleanup
        removed = manager.cleanup_expired()
        assert removed == 3
        assert len(manager._sessions) == 2

    def test_active_sessions_for_user(self, manager):
        """Test getting active sessions for a user."""
        # Issue multiple tokens for same user
        token_ids = []
        for i in range(3):
            token_id = manager.issue_token("user_123", {"session": i})
            token_ids.append(token_id)

        # Issue tokens for different user
        manager.issue_token("user_456", {"session": "other"})

        # Get active sessions for user_123
        active = manager.get_active_sessions("user_123")
        assert len(active) == 3

        # Get active sessions for user_456
        active_456 = manager.get_active_sessions("user_456")
        assert len(active_456) == 1

    def test_session_stats(self, manager):
        """Test session statistics."""
        for i in range(5):
            manager.issue_token(f"user_{i}", {"data": i})

        stats = manager.get_session_stats()
        assert stats["total_tokens"] == 5
        assert stats["active_tokens"] == 5
        assert stats["expired_tokens"] == 0
        assert stats["unique_users"] == 5
        assert stats["ttl_seconds"] == 10

    def test_token_metadata(self, manager):
        """Test token with metadata."""
        metadata = {"source": "api", "ip": "192.168.1.1"}
        token_id = manager.issue_token(
            "user_123",
            {"test": "data"},
            metadata=metadata
        )

        token = manager._sessions[token_id]
        assert token.metadata == metadata

    def test_token_persistence_roundtrip(self):
        """Disk-backed sessions survive process-local manager restart."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = str(Path(tmpdir) / "sessions.json")
            manager = SessionManager(token_ttl_seconds=30, storage_path=storage_path, persistence_enabled=True)
            token_id = manager.issue_token("user_123", {"scope": "local_first"})

            restored = SessionManager(token_ttl_seconds=30, storage_path=storage_path, persistence_enabled=True)
            assert restored.validate_token(token_id) == {"scope": "local_first"}

    def test_persistence_disabled_skips_writable_data_dir_resolution(self, monkeypatch):
        monkeypatch.setattr(
            "core.security.session_security.resolve_elyan_data_dir",
            lambda: (_ for _ in ()).throw(AssertionError("should not resolve writable dir")),
        )
        manager = SessionManager(token_ttl_seconds=30, persistence_enabled=False)

        assert manager.get_session_stats()["persistence_enabled"] is False

    def test_unwritable_storage_falls_back_to_memory_only(self, monkeypatch, tmp_path):
        blocked_dir = tmp_path / "blocked"
        storage_path = blocked_dir / "sessions.json"
        original_mkdir = Path.mkdir

        def _mkdir(self, *args, **kwargs):
            if Path(self) == blocked_dir:
                raise PermissionError("blocked")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", _mkdir)

        manager = SessionManager(token_ttl_seconds=30, storage_path=str(storage_path), persistence_enabled=True)

        assert manager.get_session_stats()["persistence_enabled"] is False
        token_id = manager.issue_token("user_123", {"scope": "memory_only"})
        assert manager.validate_token(token_id) == {"scope": "memory_only"}


class TestApprovalAuditLog:
    """Test approval action audit trail."""

    @pytest.fixture
    def audit_log(self):
        """Create audit log with temp database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_approval.db")
            yield ApprovalAuditLog(db_path)

    def test_log_request_created(self, audit_log):
        """Test logging request creation."""
        success = audit_log.log_request_created(
            entry_id="entry_001",
            request_id="req_123",
            user_id="user_123",
            session_id="sess_456",
            action_type="execute_script",
            risk_level="high",
            action_data={"script": "rm -rf /", "target": "/home"}
        )

        assert success is True
        entries = audit_log.get_entries(request_id="req_123")
        assert len(entries) == 1
        assert entries[0]["action_type"] == "request_created"

    def test_log_request_resolved(self, audit_log):
        """Test logging request resolution."""
        # Log creation first
        audit_log.log_request_created(
            entry_id="entry_001",
            request_id="req_123",
            user_id="user_123",
            session_id="sess_456",
            action_type="execute_script",
            risk_level="high",
            action_data={"script": "test"}
        )

        # Log resolution
        success = audit_log.log_request_resolved(
            entry_id="entry_002",
            request_id="req_123",
            approved=True,
            resolver_id="admin_001",
            user_id="user_123",
            session_id="sess_456",
            risk_level="high"
        )

        assert success is True
        entries = audit_log.get_entries(request_id="req_123")
        assert len(entries) == 2
        assert entries[0]["action_type"] == "request_resolved"
        assert entries[0]["approved"] == 1

    def test_log_bulk_resolve(self, audit_log):
        """Test logging bulk approval."""
        request_ids = ["req_001", "req_002", "req_003"]
        success = audit_log.log_bulk_resolve(
            entry_id="entry_bulk_001",
            request_ids=request_ids,
            approved=True,
            resolver_id="admin_001",
            user_id="user_123",
            session_id="sess_456"
        )

        assert success is True
        entries = audit_log.get_entries()
        assert len(entries) == 1
        assert entries[0]["action_type"] == "bulk_resolve"

    def test_get_entries_by_user(self, audit_log):
        """Test filtering entries by user."""
        # Log entries for different users
        for i in range(3):
            audit_log.log_request_created(
                entry_id=f"entry_{i}",
                request_id=f"req_{i}",
                user_id="user_123",
                session_id="sess_456",
                action_type="test",
                risk_level="low",
                action_data={"index": i}
            )

        for i in range(2):
            audit_log.log_request_created(
                entry_id=f"entry_other_{i}",
                request_id=f"req_other_{i}",
                user_id="user_456",
                session_id="sess_789",
                action_type="test",
                risk_level="low",
                action_data={"index": i}
            )

        # Query by user
        entries_123 = audit_log.get_entries(user_id="user_123")
        entries_456 = audit_log.get_entries(user_id="user_456")

        assert len(entries_123) == 3
        assert len(entries_456) == 2

    def test_duplicate_entry_rejection(self, audit_log):
        """Test that duplicate entry IDs are rejected."""
        success1 = audit_log.log_request_created(
            entry_id="entry_dup",
            request_id="req_001",
            user_id="user_123",
            session_id="sess_456",
            action_type="test",
            risk_level="low",
            action_data={}
        )

        # Try to insert same entry ID again
        success2 = audit_log.log_request_created(
            entry_id="entry_dup",
            request_id="req_002",
            user_id="user_123",
            session_id="sess_456",
            action_type="test",
            risk_level="low",
            action_data={}
        )

        assert success1 is True
        assert success2 is False

    def test_get_stats(self, audit_log):
        """Test audit statistics."""
        # Log some actions
        audit_log.log_request_created(
            entry_id="entry_001",
            request_id="req_001",
            user_id="user_123",
            session_id="sess_456",
            action_type="execute",
            risk_level="high",
            action_data={}
        )

        audit_log.log_request_resolved(
            entry_id="entry_002",
            request_id="req_001",
            approved=True,
            resolver_id="admin",
            user_id="user_123",
            session_id="sess_456",
            risk_level="high"
        )

        audit_log.log_request_resolved(
            entry_id="entry_003",
            request_id="req_002",
            approved=False,
            resolver_id="admin",
            user_id="user_123",
            session_id="sess_456",
            risk_level="low"
        )

        stats = audit_log.get_stats()
        assert stats["total_entries"] == 3
        assert "request_created" in stats["by_action_type"]
        assert stats["by_action_type"]["request_resolved"] == 2
        assert stats["approval_rate_percent"] == 50.0
