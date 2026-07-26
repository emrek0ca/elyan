from __future__ import annotations

import sys

from runtime.capability_registry import SafeCapabilityError


_PERMISSION_MARKERS = (
    "permission_denied",
    "permission denied",
    "not authorized",
    "not permitted",
    "screen recording",
    "ekran kaydi izni",
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


def require_screen_capture_platform(feature_name: str) -> None:
    """Ekran okuma için platform kapısı.

    Ekran yakalama artık macOS'a özel DEĞİL: Windows'ta yerel bir arka uç
    (ctypes + Pillow) aynı sözleşmeyi üretiyor. Bu kapı `require_macos`ten
    ayrıldı, çünkü o kapı Windows'u yakalama denenmeden reddediyordu — yani
    çalışabilecek bir yetenek platform adına kapatılıyordu.

    Linux hâlâ dışarıda: orada yakalama arka ucu yok ve olmayan bir şeyi
    "destekleniyor" saymak, sessizce boş görüntü döndürmekten daha kötüdür.
    """
    import sys

    if sys.platform not in {"darwin", "win32"}:
        raise unsupported_platform(
            f"{feature_name} su anda yalnizca macOS ve Windows'ta destekleniyor."
        )


def unsupported_platform(message: str) -> SafeCapabilityError:
    return SafeCapabilityError("UNSUPPORTED_PLATFORM", message)


def invalid_argument(message: str) -> SafeCapabilityError:
    return SafeCapabilityError("INVALID_ARGUMENT", message)


def capability_unavailable(message: str) -> SafeCapabilityError:
    return SafeCapabilityError("CAPABILITY_UNAVAILABLE", message)


def app_not_found(message: str) -> SafeCapabilityError:
    # "Uygulama bulunamadı" bir yetenek arızası DEĞİLDİR — replanner bu kodla
    # uygulama adını düzeltmeyi/alternatif önermeyi deneyebilir;
    # CAPABILITY_UNAVAILABLE ise "bu yetenek bu kurulumda bozuk" demektir.
    return SafeCapabilityError("APP_NOT_FOUND", message)


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
