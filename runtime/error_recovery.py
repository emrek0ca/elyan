"""Deterministic self-correction for executor step failures.

Bu modül, bir adım başarısız olduğunda *körlemesine replan* yerine önce
DETERMINISTIK ve DAR kapsamlı bir düzeltme denemesi üretir. Amaç:
"hata anında kendini düzeltebilmek" — ama davranışı öngörülebilir tutmak.

Tasarım ilkeleri:
  * Yalnız AÇIKÇA geçici (transient) veya güvenle onarılabilir hatalarda
    yeniden dener. Belirsiz/genel hatalar retryable DEĞİLdir; mevcut replan
    yolu aynen çalışır (regresyon yok).
  * İzin/güvenlik hataları fail-closed: asla otomatik yeniden denenmez.
  * Argüman onarımı yalnız güvenli, tersinir normalizasyonlarla sınırlıdır
    (ör. dosya yolu genişletme). Şema tahmini yapılmaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


# Bir adım için izin verilen toplam deneme (ilk deneme dahil). İkinci denemeden
# sonra düzeltme yerine replan yoluna düşülür.
CORRECTIVE_MAX_ATTEMPTS = 2

_TRANSIENT_CODES = {
    "RATE_LIMITED",
    "RATE_LIMIT",
    "TOO_MANY_REQUESTS",
    "TIMEOUT",
    "TASK_TIMEOUT",
    "NETWORK_ERROR",
    "CONNECTION_ERROR",
    "CONNECTION_RESET",
    "TEMPORARY_FAILURE",
    "SERVICE_UNAVAILABLE",
    "UPSTREAM_UNAVAILABLE",
    "PROVIDER_UNAVAILABLE",
    "SERVER_ERROR",
    "BAD_GATEWAY",
    "GATEWAY_TIMEOUT",
}

# Bu kalıplardan biri hata metninde geçerse geçici sayılır (kod jenerikse bile).
_TRANSIENT_TEXT_MARKERS = (
    "rate limit",
    "rate-limit",
    "too many requests",
    "timed out",
    "timeout",
    "temporarily",
    "temporary",
    "geçici",
    "try again",
    "yeniden dene",
    "connection reset",
    "connection refused",
    "network is unreachable",
    "econnreset",
    "etimedout",
    "503",
    "502",
    "504",
    "429",
)

# İzin / güvenlik: fail-closed. Bu kalıplar görülürse asla otomatik denenmez.
_PERMISSION_CODES = {
    "PERMISSION_DENIED",
    "OS_PERMISSION_DENIED",
    "CAPABILITY_GRANT_DENIED",
    "APPROVAL_REQUIRED",
    "FORBIDDEN",
    "UNAUTHORIZED",
    "DEPENDENCY_PERMISSION_DENIED",
}

_PERMISSION_TEXT_MARKERS = (
    "permission denied",
    "not authorized",
    "unauthorized",
    "forbidden",
    "izin",
    "yetki",
    "erişim engel",
    "operation not permitted",
)

_NOT_FOUND_CODES = {
    "FILE_NOT_FOUND",
    "PATH_NOT_FOUND",
    "NOT_FOUND",
    "NO_SUCH_FILE",
}

# Argümanlarda dosya yolu taşıyabilecek anahtarlar (güvenli normalizasyon için).
_PATH_ARG_KEYS = (
    "path",
    "file",
    "filepath",
    "file_path",
    "filePath",
    "source",
    "src",
    "input",
    "input_path",
    "inputPath",
    "target",
    "output",
    "output_path",
    "outputPath",
)


@dataclass(frozen=True, slots=True)
class CorrectiveAction:
    """Bir başarısız adım için önerilen düzeltme."""

    should_retry: bool
    strategy: str
    reason: str
    category: str
    adjusted_args: dict[str, Any] | None = field(default=None)


def _norm_code(error_code: Any) -> str:
    return str(error_code or "").strip().upper()


def _norm_text(message: Any) -> str:
    return str(message or "").strip().lower()


def classify_failure(error_code: Any, message: Any) -> str:
    """Hata kategorisini döndür: permission | transient | not_found | unknown."""
    code = _norm_code(error_code)
    text = _norm_text(message)

    if code in _PERMISSION_CODES or any(m in text for m in _PERMISSION_TEXT_MARKERS):
        return "permission"
    if code in _TRANSIENT_CODES or any(m in text for m in _TRANSIENT_TEXT_MARKERS):
        return "transient"
    if code in _NOT_FOUND_CODES:
        return "not_found"
    return "unknown"


def _normalize_path_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    # Güvenli, tersinir normalizasyonlar: tırnak kırp, ~ genişlet, çevre değişkeni.
    candidate = raw.strip("'\"").strip()
    candidate = os.path.expanduser(candidate)
    candidate = os.path.expandvars(candidate)
    if candidate and candidate != raw:
        return candidate
    return None


def _repair_paths(args: dict[str, Any]) -> dict[str, Any] | None:
    """Yalnız değişen yol anahtarlarından oluşan dar bir onarım seti döndür."""
    if not isinstance(args, dict):
        return None
    repaired: dict[str, Any] = {}
    for key in _PATH_ARG_KEYS:
        if key not in args:
            continue
        fixed = _normalize_path_value(args.get(key))
        if fixed is not None:
            repaired[key] = fixed
    return repaired or None


def plan_corrective_retry(
    *,
    capability: str,
    args: dict[str, Any],
    error_code: Any,
    message: Any,
    attempt: int,
) -> CorrectiveAction | None:
    """Başarısız bir adım için deterministik düzeltme önerisi (veya None).

    None dönerse çağıran taraf mevcut davranışını (replan/fail) sürdürmelidir.
    ``should_retry=False`` dönmesi ise "bu hata otomatik denenemez" (fail-closed)
    anlamına gelir ve yine mevcut yola düşülür; ancak kategori kayıt altına alınır.
    """
    category = classify_failure(error_code, message)

    if category == "permission":
        # Fail-closed: izin/güvenlik hataları asla sessizce yeniden denenmez.
        return CorrectiveAction(
            should_retry=False,
            strategy="fail_closed_permission",
            reason="permission_or_authorization_error",
            category=category,
        )

    # Deneme bütçesi dolduysa düzeltme yok — replan devralır.
    if attempt >= CORRECTIVE_MAX_ATTEMPTS:
        return None

    if category == "transient":
        return CorrectiveAction(
            should_retry=True,
            strategy="transient_retry",
            reason=str(error_code or "transient").strip() or "transient",
            category=category,
            adjusted_args=None,  # aynı argümanlarla; geçici yarış çözülür
        )

    if category == "not_found":
        repaired = _repair_paths(args)
        if repaired is not None:
            return CorrectiveAction(
                should_retry=True,
                strategy="path_normalize",
                reason="path_not_found_normalized",
                category=category,
                adjusted_args=repaired,
            )
        # Onarılacak yol yoksa otomatik retry yerine replan daha isabetli.
        return None

    # Belirsiz hatalar: deterministik düzeltme yok → replan yolu (regresyon yok).
    return None
