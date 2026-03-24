"""
Encrypted Data Vault

Provides encryption/decryption for sensitive data with:
- AES-256-GCM encryption
- Automatic key derivation
- Authenticated encryption (authenticated with GCM mode)
- Memory-safe operations
"""

import os
import json
import base64
from typing import Any, Optional, Dict
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend
from core.observability.logger import get_structured_logger

slog = get_structured_logger("encrypted_vault")


class EncryptedVault:
    """Encrypts and decrypts sensitive data using AES-256-GCM."""

    def __init__(self, master_key: Optional[bytes] = None):
        """
        Initialize encrypted vault.

        Args:
            master_key: 32-byte key for AES-256. If None, generates from environment.
        """
        if master_key is None:
            master_key = self._load_or_generate_master_key()

        if len(master_key) != 32:
            raise ValueError("Master key must be 32 bytes (256 bits)")

        self.master_key = master_key
        self._backend = default_backend()

    def _load_or_generate_master_key(self) -> bytes:
        """Load master key from env or generate new one."""
        key_env = os.environ.get("ELYAN_ENCRYPTION_KEY")
        if key_env:
            try:
                key_bytes = base64.b64decode(key_env)
                if len(key_bytes) == 32:
                    return key_bytes
            except Exception:
                slog.log_event(
                    "invalid_key_env",
                    {"error": "Could not decode ELYAN_ENCRYPTION_KEY"},
                    level="warning"
                )

        # Generate new key
        new_key = os.urandom(32)
        slog.log_event(
            "generated_new_master_key",
            {"key_b64": base64.b64encode(new_key).decode()},
            level="info"
        )
        return new_key

    def _derive_key(self, salt: bytes, context: str = "vault") -> bytes:
        """Derive encryption key from master key using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=self._backend
        )
        return kdf.derive(self.master_key + context.encode())

    def encrypt(self, data: Any, context: str = "general") -> Dict[str, str]:
        """
        Encrypt data using AES-256-GCM.

        Args:
            data: Object to encrypt (will be JSON-serialized)
            context: Context string for key derivation

        Returns:
            Dict with base64-encoded ciphertext, nonce, salt, tag
        """
        try:
            # Serialize data
            plaintext = json.dumps(data).encode("utf-8")

            # Generate random salt and nonce
            salt = os.urandom(16)
            nonce = os.urandom(12)

            # Derive encryption key
            key = self._derive_key(salt, context)

            # Encrypt with GCM (includes authentication)
            cipher = AESGCM(key)
            ciphertext = cipher.encrypt(nonce, plaintext, None)

            # Return base64-encoded components
            return {
                "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
                "nonce": base64.b64encode(nonce).decode("utf-8"),
                "salt": base64.b64encode(salt).decode("utf-8"),
                "context": context
            }

        except Exception as e:
            slog.log_event(
                "encryption_error",
                {"error": str(e)},
                level="error"
            )
            raise

    def decrypt(self, encrypted_data: Dict[str, str], context: str = "general") -> Any:
        """
        Decrypt data using AES-256-GCM.

        Args:
            encrypted_data: Dict with ciphertext, nonce, salt
            context: Context string for key derivation (must match encryption context)

        Returns:
            Decrypted object
        """
        try:
            # Decode base64 components
            ciphertext = base64.b64decode(encrypted_data["ciphertext"])
            nonce = base64.b64decode(encrypted_data["nonce"])
            salt = base64.b64decode(encrypted_data["salt"])

            # Verify context matches
            stored_context = encrypted_data.get("context", "general")
            if stored_context != context:
                slog.log_event(
                    "context_mismatch",
                    {"expected": context, "got": stored_context},
                    level="warning"
                )

            # Derive key with same context
            key = self._derive_key(salt, context)

            # Decrypt and verify
            cipher = AESGCM(key)
            plaintext = cipher.decrypt(nonce, ciphertext, None)

            # Deserialize
            return json.loads(plaintext.decode("utf-8"))

        except Exception as e:
            slog.log_event(
                "decryption_error",
                {"error": str(e)},
                level="error"
            )
            raise

    def hash_password(self, password: str) -> str:
        """Hash a password using PBKDF2 (for verification)."""
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=self._backend
        )
        hashed = kdf.derive(password.encode())
        return base64.b64encode(salt + hashed).decode()

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash."""
        try:
            decoded = base64.b64decode(hashed)
            salt = decoded[:16]
            stored_hash = decoded[16:]

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=self._backend
            )
            computed_hash = kdf.derive(password.encode())
            return computed_hash == stored_hash
        except Exception as e:
            slog.log_event(
                "password_verify_error",
                {"error": str(e)},
                level="error"
            )
            return False


# Singleton instance
_vault: Optional[EncryptedVault] = None


def get_encrypted_vault(master_key: Optional[bytes] = None) -> EncryptedVault:
    """Get or create encrypted vault singleton."""
    global _vault
    if _vault is None:
        _vault = EncryptedVault(master_key)
    return _vault
