from __future__ import annotations

import sys

from runtime.capability_registry import SafeCapabilityError


_PERMISSION_MARKERS = (
    "permission_denied",
    "permission denied",
    "not authorized",
    "not permitted",
    "screen recording",
    "accessibility",
    "apple events",
    "mach error 4099",
)
_TIMEOUT_MARKERS = (
    "timed out",
    "timeout",
    "zaman asimina ugradi",
    "zaman asimina",
    "zaman asimi",
)


def is_macos() -> bool:
    return sys.platform == "darwin"


def require_macos(feature_name: str) -> None:
    if not is_macos():
        raise unsupported_platform(f"{feature_name} su anda yalnizca macOS'ta destekleniyor.")


def unsupported_platform(message: str) -> SafeCapabilityError:
    return SafeCapabilityError("UNSUPPORTED_PLATFORM", message)


def invalid_argument(message: str) -> SafeCapabilityError:
    return SafeCapabilityError("INVALID_ARGUMENT", message)


def capability_unavailable(message: str) -> SafeCapabilityError:
    return SafeCapabilityError("CAPABILITY_UNAVAILABLE", message)


def permission_required(message: str) -> SafeCapabilityError:
    return SafeCapabilityError("PERMISSION_REQUIRED", message)


def timeout_error(message: str) -> SafeCapabilityError:
    return SafeCapabilityError("TIMEOUT", message)


def is_permission_detail(detail: str) -> bool:
    lowered = str(detail or "").strip().lower()
    return any(marker in lowered for marker in _PERMISSION_MARKERS)


def is_timeout_detail(detail: str) -> bool:
    lowered = str(detail or "").strip().lower()
    return any(marker in lowered for marker in _TIMEOUT_MARKERS)
