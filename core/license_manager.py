"""
License Manager for Wiqo v12.0

Handles Lifetime Executive License validation.
Offline verification using cryptographic signatures.

License Format:
{
    "license_key": "WIQO-XXXX-XXXX-XXXX-XXXX",
    "license_type": "Lifetime Executive",
    "issued_to": "User Name",
    "issued_date": "2026-02-07",
    "machine_id": "unique-machine-hash",
    "signature": "cryptographic-signature"
}
"""

import hashlib
import hmac
import json
import platform
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("license_manager")


@dataclass
class License:
    """License information"""
    license_key: str
    license_type: str
    issued_to: str
    issued_date: str
    machine_id: str
    signature: str

    def is_valid(self) -> bool:
        """Check if license is structurally valid"""
        return (
            self.license_key.startswith("WIQO-") and
            len(self.license_key) == 24 and
            self.license_type == "Lifetime Executive" and
            bool(self.issued_to) and
            bool(self.signature)
        )


class LicenseManager:
    """
    Manages license validation for Wiqo.

    Without valid license:
    - Task planning: Allowed
    - Task execution: Blocked
    """

    # Secret key for HMAC (in production, this should be obfuscated/encrypted)
    _SECRET_KEY = b"wiqo_lifetime_executive_2026_secret_key_v1"

    def __init__(self):
        self.license_file = Path.home() / ".wiqo" / "license.json"
        self._license: Optional[License] = None
        self._is_licensed = False
        self._load_license()

    def _load_license(self):
        """Load license from file"""
        if not self.license_file.exists():
            logger.info("No license file found")
            return

        try:
            with open(self.license_file, 'r') as f:
                data = json.load(f)

            self._license = License(
                license_key=data.get("license_key", ""),
                license_type=data.get("license_type", ""),
                issued_to=data.get("issued_to", ""),
                issued_date=data.get("issued_date", ""),
                machine_id=data.get("machine_id", ""),
                signature=data.get("signature", "")
            )

            # Validate license
            if self._validate_license(self._license):
                self._is_licensed = True
                logger.info(f"License validated: {self._license.license_key}")
            else:
                logger.warning("License validation failed")
                self._license = None

        except Exception as e:
            logger.error(f"License load error: {e}")
            self._license = None

    def _validate_license(self, license: License) -> bool:
        """Validate license cryptographically"""

        # 1. Structure check
        if not license.is_valid():
            logger.warning("License structure invalid")
            return False

        # 2. Machine binding check
        current_machine_id = self._get_machine_id()
        if license.machine_id != current_machine_id:
            logger.warning(f"Machine ID mismatch: {license.machine_id} != {current_machine_id}")
            return False

        # 3. Signature verification
        expected_signature = self._generate_signature(
            license.license_key,
            license.issued_to,
            license.issued_date,
            license.machine_id
        )

        if license.signature != expected_signature:
            logger.warning("License signature invalid")
            return False

        logger.info("License validation passed")
        return True

    def _get_machine_id(self) -> str:
        """Get unique machine identifier"""
        try:
            # Combine multiple hardware identifiers
            mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff)
                           for elements in range(0, 2*6, 2)][::-1])

            system = platform.system()
            node = platform.node()

            combined = f"{mac}:{system}:{node}"
            machine_hash = hashlib.sha256(combined.encode()).hexdigest()[:32]

            return machine_hash

        except Exception as e:
            logger.error(f"Machine ID generation error: {e}")
            return "unknown"

    def _generate_signature(
        self,
        license_key: str,
        issued_to: str,
        issued_date: str,
        machine_id: str
    ) -> str:
        """Generate HMAC signature for license"""

        data = f"{license_key}:{issued_to}:{issued_date}:{machine_id}"
        signature = hmac.new(
            self._SECRET_KEY,
            data.encode(),
            hashlib.sha256
        ).hexdigest()

        return signature

    def is_licensed(self) -> bool:
        """Check if system is licensed"""
        return self._is_licensed

    def get_license_info(self) -> Optional[Dict[str, Any]]:
        """Get license information"""
        if not self._license:
            return None

        return {
            "license_key": self._license.license_key,
            "license_type": self._license.license_type,
            "issued_to": self._license.issued_to,
            "issued_date": self._license.issued_date,
            "is_valid": self._is_licensed
        }

    def get_trial_info(self) -> Dict[str, Any]:
        """Get trial/unlicensed mode information"""
        return {
            "mode": "Trial Mode",
            "limitations": [
                "Task planning: Available",
                "Task execution: Blocked",
                "All features visible but not executable"
            ],
            "upgrade_message": (
                "Upgrade to Lifetime Executive License for full access.\n"
                "Contact: license@wiqo.ai"
            )
        }

    def generate_license_request(self) -> str:
        """Generate license request string for users"""
        machine_id = self._get_machine_id()
        system_info = f"{platform.system()} {platform.release()}"

        request = (
            f"Wiqo License Request\n"
            f"====================\n\n"
            f"Machine ID: {machine_id}\n"
            f"System: {system_info}\n"
            f"Request Date: {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"Please send this information to: license@wiqo.ai\n"
            f"You will receive your Lifetime Executive License key."
        )

        return request

    def install_license(
        self,
        license_key: str,
        issued_to: str,
        issued_date: str
    ) -> bool:
        """
        Install a new license (for internal use / license generation)

        Returns:
            bool: True if license installed successfully
        """

        machine_id = self._get_machine_id()
        signature = self._generate_signature(
            license_key,
            issued_to,
            issued_date,
            machine_id
        )

        license_data = {
            "license_key": license_key,
            "license_type": "Lifetime Executive",
            "issued_to": issued_to,
            "issued_date": issued_date,
            "machine_id": machine_id,
            "signature": signature
        }

        try:
            # Ensure directory exists
            self.license_file.parent.mkdir(parents=True, exist_ok=True)

            # Write license file
            with open(self.license_file, 'w') as f:
                json.dump(license_data, f, indent=2)

            logger.info(f"License installed: {license_key}")

            # Reload license
            self._load_license()

            return self._is_licensed

        except Exception as e:
            logger.error(f"License installation error: {e}")
            return False


# Singleton instance
_license_manager: Optional[LicenseManager] = None


def get_license_manager() -> LicenseManager:
    """Get singleton license manager instance"""
    global _license_manager
    if _license_manager is None:
        _license_manager = LicenseManager()
    return _license_manager
