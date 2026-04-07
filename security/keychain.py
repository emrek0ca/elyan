import subprocess
import logging
import os
import platform
import json
from pathlib import Path
from typing import Optional
from utils.logger import get_logger

logger = get_logger("keychain")

# Canonical env->keychain mapping for Elyan secrets.
ENV_TO_KEYCHAIN = {
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "DISCORD_BOT_TOKEN": "discord_bot_token",
    "SLACK_BOT_TOKEN": "slack_bot_token",
    "SLACK_APP_TOKEN": "slack_app_token",
    "TWILIO_AUTH_TOKEN": "twilio_auth_token",
    "WHATSAPP_BOT_TOKEN": "whatsapp_bot_token",
    "WHATSAPP_BRIDGE_TOKEN": "whatsapp_bridge_token",
    "WHATSAPP_ACCESS_TOKEN": "whatsapp_access_token",
    "WHATSAPP_VERIFY_TOKEN": "whatsapp_verify_token",
    "SIGNAL_BOT_TOKEN": "signal_bot_token",
    "OPENAI_API_KEY": "openai_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "GOOGLE_API_KEY": "google_api_key",
    "GROQ_API_KEY": "groq_api_key",
}

class KeychainManager:
    """macOS Keychain interface using the 'security' command line tool."""
    SERVICE_NAME = "ai.elyan.keys"

    @staticmethod
    def set_key(key_name: str, secret: str) -> bool:
        if not secret: return False
        if not KeychainManager.is_available():
            return False
        try:
            # -U: update if exists, -a: account (key name), -s: service, -w: password (secret)
            proc = subprocess.run(
                ["security", "add-generic-password", "-a", key_name, "-s", KeychainManager.SERVICE_NAME, "-w", secret, "-U"],
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                logger.error(f"Keychain write error for {key_name}: return_code={proc.returncode}")
                return False
            logger.info(f"Secret stored in Keychain: {key_name}")
            return True
        except Exception as e:
            logger.error(f"Keychain write error for {key_name}: {type(e).__name__}")
            return False

    @staticmethod
    def get_key(key_name: str) -> Optional[str]:
        if not KeychainManager.is_available():
            return None
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-a", key_name, "-s", KeychainManager.SERVICE_NAME, "-w"],
                capture_output=True, text=True, check=False
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()
        except Exception:
            return None

    @staticmethod
    def delete_key(key_name: str):
        if not KeychainManager.is_available():
            return
        try:
            subprocess.run(
                ["security", "delete-generic-password", "-a", key_name, "-s", KeychainManager.SERVICE_NAME],
                capture_output=True, check=False
            )
            logger.info(f"Secret deleted from Keychain: {key_name}")
        except:
            pass

    @staticmethod
    def is_available() -> bool:
        return platform.system() == "Darwin" and shutil_which("security") is not None

    @staticmethod
    def key_for_env(env_key: str) -> Optional[str]:
        return ENV_TO_KEYCHAIN.get(env_key)

    @staticmethod
    def audit_env_plaintext(env_path: str | Path = ".env") -> dict:
        """
        Detect plaintext secrets in .env.
        Returns metadata and findings without printing secret values.
        """
        path = Path(env_path).expanduser()
        if not path.exists():
            return {"exists": False, "findings": []}

        findings = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            keychain_key = KeychainManager.key_for_env(key)
            if keychain_key and value and not value.startswith("$"):
                findings.append({"env_key": key, "keychain_key": keychain_key})

        return {"exists": True, "findings": findings}

    @staticmethod
    def migrate_from_env(env_path: str | Path = ".env", clear_env: bool = False) -> dict:
        """
        Migrate plaintext .env secrets to Keychain.
        If clear_env=True, migrated values are blanked in .env.
        """
        audit = KeychainManager.audit_env_plaintext(env_path)
        if not audit.get("exists"):
            return {"migrated": 0, "updated_env": False, "findings": [], "reason": ".env not found"}
        if not KeychainManager.is_available():
            return {"migrated": 0, "updated_env": False, "findings": audit["findings"], "reason": "Keychain unavailable"}

        path = Path(env_path).expanduser()
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        migrated = 0
        migrated_keys = set()
        for finding in audit["findings"]:
            env_key = finding["env_key"]
            keychain_key = finding["keychain_key"]
            secret = os.getenv(env_key, "")
            if not secret:
                # fallback to file value
                for line in lines:
                    if line.strip().startswith(f"{env_key}="):
                        secret = line.split("=", 1)[1].strip()
                        break
            if secret and KeychainManager.set_key(keychain_key, secret):
                migrated += 1
                migrated_keys.add(env_key)

        updated = False
        if clear_env and migrated_keys:
            new_lines = []
            for line in lines:
                if "=" in line and not line.strip().startswith("#"):
                    key = line.split("=", 1)[0].strip()
                    if key in migrated_keys:
                        new_lines.append(f"{key}=\n")
                        updated = True
                        continue
                new_lines.append(line)
            path.write_text("".join(new_lines), encoding="utf-8")

        return {"migrated": migrated, "updated_env": updated, "findings": audit["findings"]}

    @staticmethod
    def audit_config_plaintext(config_path: str | Path) -> dict:
        """
        Detect plaintext channel tokens in elyan.json.
        Checks channels[*].token/bridge_token/access_token/verify_token.
        """
        path = Path(config_path).expanduser()
        if not path.exists():
            return {"exists": False, "findings": []}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"exists": True, "findings": [], "reason": "invalid_json"}

        channels = data.get("channels", []) if isinstance(data, dict) else []
        findings = []
        for idx, ch in enumerate(channels):
            if not isinstance(ch, dict):
                continue
            ctype = str(ch.get("type", "") or "").lower()
            token_fields = [
                ("token", str(ch.get("token", "") or "").strip()),
                ("bridge_token", str(ch.get("bridge_token", "") or "").strip()),
                ("access_token", str(ch.get("access_token", "") or "").strip()),
                ("verify_token", str(ch.get("verify_token", "") or "").strip()),
            ]
            for field_name, token in token_fields:
                if not token or token.startswith("$"):
                    continue

                env_key = {
                    ("telegram", "token"): "TELEGRAM_BOT_TOKEN",
                    ("discord", "token"): "DISCORD_BOT_TOKEN",
                    ("slack", "token"): "SLACK_BOT_TOKEN",
                    ("whatsapp", "token"): "WHATSAPP_BOT_TOKEN",
                    ("whatsapp", "bridge_token"): "WHATSAPP_BRIDGE_TOKEN",
                    ("whatsapp", "access_token"): "WHATSAPP_ACCESS_TOKEN",
                    ("whatsapp", "verify_token"): "WHATSAPP_VERIFY_TOKEN",
                    ("signal", "token"): "SIGNAL_BOT_TOKEN",
                }.get((ctype, field_name))
                keychain_key = KeychainManager.key_for_env(env_key) if env_key else None
                if env_key and keychain_key:
                    findings.append(
                        {
                            "channel_type": ctype,
                            "index": idx,
                            "field": field_name,
                            "env_key": env_key,
                            "keychain_key": keychain_key,
                        }
                    )

        return {"exists": True, "findings": findings}

    @staticmethod
    def migrate_config_channel_tokens(config_path: str | Path, clear_config: bool = True) -> dict:
        """
        Migrate plaintext channel tokens in config channels[*].token to Keychain.
        If clear_config=True, replace token with $ENV_KEY reference after migration.
        """
        path = Path(config_path).expanduser()
        audit = KeychainManager.audit_config_plaintext(path)
        if not audit.get("exists"):
            return {"migrated": 0, "updated_config": False, "findings": [], "reason": "config not found"}
        if not KeychainManager.is_available():
            return {"migrated": 0, "updated_config": False, "findings": audit["findings"], "reason": "Keychain unavailable"}
        if audit.get("reason") == "invalid_json":
            return {"migrated": 0, "updated_config": False, "findings": [], "reason": "invalid_json"}

        data = json.loads(path.read_text(encoding="utf-8"))
        channels = data.get("channels", [])
        migrated = 0
        updated = False

        for finding in audit["findings"]:
            idx = finding["index"]
            env_key = finding["env_key"]
            keychain_key = finding["keychain_key"]
            field_name = str(finding.get("field") or "token")
            token = str(channels[idx].get(field_name, "") or "")
            if token and KeychainManager.set_key(keychain_key, token):
                migrated += 1
                if clear_config:
                    channels[idx][field_name] = f"${env_key}"
                    updated = True

        if updated:
            data["channels"] = channels
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        return {"migrated": migrated, "updated_config": updated, "findings": audit["findings"]}


def shutil_which(cmd: str) -> Optional[str]:
    try:
        import shutil
        return shutil.which(cmd)
    except Exception:
        return None

# Global instance
keychain = KeychainManager()
