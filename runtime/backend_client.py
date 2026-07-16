from __future__ import annotations

import json
import os
import datetime as dt
import threading
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable
from urllib.parse import quote, urlencode, urljoin, urlparse

from app_config import get_app_config_value
from runtime.capability_registry import capability_names
from runtime import state_store

AUTH_ENDPOINTS = {
    "/v1/auth/login",
    "/v1/auth/register",
    "/v1/auth/refresh",
    "/v1/auth/logout",
}
_PAIRING_FALLBACK_TTL_MINUTES = 10


def _safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text


def _request_id() -> str:
    import time
    from uuid import uuid4

    return f"req_{int(time.time() * 1000)}_{uuid4().hex[:8]}"


def _is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    normalized = hostname.lower()
    return normalized in {"localhost", "127.0.0.1", "::1"}


def _is_loopback_base_url(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    return _is_loopback(parsed.hostname)


def _map_from(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_error_message(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("message", "error", "detail", "description"):
            normalized = _normalize_error_message(value.get(key))
            if normalized:
                return normalized
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            normalized = _normalize_error_message(item)
            if normalized:
                return normalized
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text[:1] in {"[", "{"}:
        try:
            parsed = json.loads(text)
        except Exception:
            return text
        normalized = _normalize_error_message(parsed)
        if normalized:
            return normalized
    return text


def _safe_error_code(value: Any, fallback: str) -> str:
    text = _normalize_error_message(value).strip().lower()
    if not text:
        return fallback
    normalized = "".join(char if char.isalnum() else "_" for char in text)
    normalized = normalized.strip("_")
    if not normalized:
        return fallback
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized[:80]


@lru_cache(maxsize=1)
def _requests_module() -> Any | None:
    try:
        import requests as requests_module
    except Exception:
        return None
    return requests_module


def _is_uuid_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        uuid.UUID(text)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _runtime_identity_repair_error_code(value: Any) -> str:
    text = str(value or "").strip()
    if text == "RUNTIME_REGISTER_INVALID_IDENTITY":
        return "runtime_register_invalid_identity"
    if text:
        return _safe_error_code(text, "runtime_register_invalid_identity")
    return "runtime_register_invalid_identity"


# Backend register "cihaz bulunamadı" (DESKTOP_RUNTIME_DEVICE_NOT_FOUND) yanıtı
# tek başına belirsizdir: deploy penceresi, geçici proxy 404'ü, yanlış DB'ye
# bağlanma ya da cihazın gerçekten silinmiş olması — hepsi aynı kodu döndürür.
# Kalıcı eşleşmeyi tek bir belirsiz yanıtla yok etmemek için, bu hata KESİNTİSİZ
# olarak bu kadar saniye sürerse yerel kimliği siliyoruz (yeniden eşleştirme
# gerekir). Daha kısa kesintilerde kayıt-yeniden-deneme döngüsü aynı kimlikle
# devam eder ve backend toparlanınca kendini iyileştirir.
_DEVICE_NOT_FOUND_WIPE_GRACE_SECONDS = 900.0


def _runtime_registration_identity_error(result: "BackendResult") -> str:
    values: list[str] = [str(result.error or "")]
    if isinstance(result.data, dict):
        values.extend(str(result.data.get(key, "") or "") for key in ("error", "code", "message"))
        nested = result.data.get("error")
        if isinstance(nested, dict):
            values.extend(str(nested.get(key, "") or "") for key in ("code", "message"))
    normalized = " ".join(values).upper()
    for code in ("RUNTIME_REGISTER_INVALID_IDENTITY", "DESKTOP_RUNTIME_DEVICE_NOT_FOUND"):
        if code in normalized:
            return code
    if result.status_code == 404 and "DESKTOP RUNTIME DEVICE NOT FOUND" in normalized:
        return "DESKTOP_RUNTIME_DEVICE_NOT_FOUND"
    return ""


def _request_exception_code(exc: Any) -> str:
    requests_mod = _requests_module()
    if requests_mod is not None and isinstance(exc, requests_mod.Timeout):
        return "network_timeout"
    if requests_mod is not None and isinstance(exc, requests_mod.ConnectionError):
        return "network_unreachable"
    return "request_failed"


def _pairing_expiry_fallback_iso() -> str:
    return (dt.datetime.utcnow() + dt.timedelta(minutes=_PAIRING_FALLBACK_TTL_MINUTES)).replace(
        microsecond=0
    ).isoformat() + "Z"


def _pairing_qr_text(session_id: str, pairing_code: str) -> str:
    if not session_id or not pairing_code:
        return ""
    return f"elyan://pair?sessionId={session_id}&pairingCode={pairing_code}"


def _pairing_expired(expires_at: Any, *, skew_seconds: int = 15) -> bool:
    text = str(expires_at or "").strip()
    if not text:
        return False
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        expires = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    return expires <= now - dt.timedelta(seconds=skew_seconds)


def _terminal_auth_failure(result: "BackendResult") -> bool:
    if result.status_code not in {401, 403}:
        return False
    values: list[str] = []
    for value in (result.error, result.data):
        if isinstance(value, dict):
            values.extend(str(value.get(key, "") or "").strip().lower() for key in ("error", "code", "message"))
        else:
            values.append(str(value or "").strip().lower())
    text = " ".join(item for item in values if item)
    if not text:
        return False
    terminal_markers = (
        "invalid_refresh",
        "refresh_token_invalid",
        "refresh token invalid",
        "refresh_token_revoked",
        "refresh token revoked",
        "session_expired",
        "token_expired",
        "session_revoked",
        "refresh_revoked",
    )
    return any(marker in text for marker in terminal_markers)


def _capability_list_from_payload(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = sorted(
        {
            str(item or "").strip()
            for item in value
            if str(item or "").strip()
        }
    )
    return normalized


def _payload_capabilities(*payloads: dict[str, Any] | None) -> list[str]:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for candidate in (
            payload.get("capabilities"),
            _map_from(payload.get("runtime")).get("capabilities"),
            _map_from(payload.get("runtimeInfo")).get("capabilities"),
            _map_from(payload.get("connection")).get("capabilities"),
            _map_from(payload.get("readiness")).get("capabilities"),
        ):
            normalized = _capability_list_from_payload(candidate)
            if normalized:
                return normalized
    return []


def _payload_capability_states(*payloads: dict[str, Any] | None) -> dict[str, Any]:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for candidate in (
            payload.get("capabilityStates"),
            _map_from(payload.get("runtime")).get("capabilityStates"),
            _map_from(payload.get("runtimeInfo")).get("capabilityStates"),
            _map_from(payload.get("connection")).get("capabilityStates"),
            _map_from(payload.get("readiness")).get("capabilityStates"),
            _map_from(_map_from(payload.get("readiness")).get("runtime")).get("capabilityStates"),
        ):
            if isinstance(candidate, dict):
                return dict(candidate)
    return {}


def _ws_url_from_http(base_url: str | None) -> str | None:
    value = str(base_url or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme == "https":
        scheme = "wss"
    elif parsed.scheme == "http":
        scheme = "ws"
    else:
        return None
    return parsed._replace(scheme=scheme).geturl().rstrip("/")


@dataclass(slots=True)
class BackendResult:
    ok: bool
    request_id: str
    status_code: int | None
    data: Any
    error: str | None = None
    x_request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "requestId": self.request_id,
            "statusCode": self.status_code,
            "data": self.data,
            "error": self.error,
            "xRequestId": self.x_request_id,
        }


class BackendClient:
    def __init__(
        self,
        base_url: str | None,
        timeout: float = 8.0,
        capabilities_provider: Callable[[], list[str]] | None = None,
    ):
        self.base_url = self._normalize_base_url(base_url)
        self.timeout = timeout
        self.connect_timeout = min(float(timeout), 4.0) if float(timeout) > 0 else 4.0
        self.read_timeout = max(float(timeout), self.connect_timeout)
        self._capabilities_provider = capabilities_provider
        self._session_local = threading.local()
        self._user_refresh_lock = threading.Lock()
        self._runtime_unauthorized_lock = threading.Lock()

    @staticmethod
    def _normalize_base_url(base_url: str | None) -> str | None:
        # Constructor argümanı açık operatör seçimidir. Özellikle yerel backend
        # geliştirmesinde APP_BASE_URL=localhost değerini kullanıcı config'indeki
        # production URL ile sessizce ezme.
        explicit = BackendClient._canonicalize_base_url(base_url)
        if explicit:
            return explicit
        candidates = (
            os.environ.get("APP_BASE_URL"),
            os.environ.get("ELYAN_BACKEND_BASE_URL"),
            get_app_config_value("backend_base_url", ""),
        )
        fallback = ""
        for candidate in candidates:
            value = BackendClient._canonicalize_base_url(candidate)
            if value:
                if not fallback:
                    fallback = value
                if not _is_loopback_base_url(value):
                    return value
        return fallback or None

    @staticmethod
    def _canonicalize_base_url(value: Any) -> str:
        text = str(value or "").strip().rstrip("/")
        if not text:
            return ""
        parsed = urlparse(text)
        if parsed.hostname == "84.247.172.213" and (parsed.port in {None, 4000}):
            return "https://api.elyan.dev"
        return text

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @property
    def loopback(self) -> bool:
        if not self.base_url:
            return False
        parsed = urlparse(self.base_url)
        return _is_loopback(parsed.hostname)

    def _session_for_thread(self) -> Any | None:
        requests_mod = _requests_module()
        if requests_mod is None:
            return None
        session = getattr(self._session_local, "session", None)
        if isinstance(session, requests_mod.Session):
            return session
        session = requests_mod.Session()
        self._session_local.session = session
        return session

    def _advertised_capabilities(self) -> list[str]:
        provider = self._capabilities_provider
        if callable(provider):
            try:
                provided = provider()
            except Exception:
                provided = []
            if isinstance(provided, list):
                normalized = sorted(
                    {
                        str(item or "").strip()
                        for item in provided
                        if str(item or "").strip()
                    }
                )
                if normalized:
                    return normalized
        return sorted(capability_names())

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        request_id: str | None = None,
    ) -> BackendResult:
        request_id = request_id or _request_id()
        if not self.base_url:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=None,
                data=None,
                error="backend_unconfigured",
            )
        requests_mod = _requests_module()
        if requests_mod is None:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=None,
                data=None,
                error="requests_unavailable",
            )

        url = urljoin(self.base_url + "/", path.lstrip("/"))
        request_headers = {
            "Accept": "application/json",
            "X-Request-Id": request_id,
            "X-Elyan-Client-Capabilities": "blocks_v1",
        }
        if headers:
            request_headers.update(headers)
        try:
            session = self._session_for_thread()
            if session is None:
                return BackendResult(
                    ok=False,
                    request_id=request_id,
                    status_code=None,
                    data=None,
                    error="requests_unavailable",
                )
            response = session.request(
                method,
                url,
                json=json_body,
                headers=request_headers,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests_mod.RequestException as exc:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=None,
                data=None,
                error=_request_exception_code(exc),
            )

        text = response.text or ""
        payload = _safe_json(text) if text else {}
        return BackendResult(
            ok=response.ok,
            request_id=request_id,
            status_code=response.status_code,
            data=payload,
            error=(
                None
                if response.ok
                else (
                    _normalize_error_message(payload.get("message"))
                    if isinstance(payload, dict)
                    else ""
                )
                or (
                    _normalize_error_message(payload.get("error"))
                    if isinstance(payload, dict)
                    else ""
                )
                or _normalize_error_message(payload)
                or text[:200]
                or response.reason
            ),
            x_request_id=response.headers.get("x-request-id")
            or response.headers.get("X-Request-Id"),
        )

    def _runtime_binary_request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        _retry_after_rotation: bool = True,
    ) -> BackendResult:
        request_id = _request_id()
        token = self._runtime_token()
        requests_mod = _requests_module()
        if not self.base_url:
            return BackendResult(False, request_id, None, None, "backend_unconfigured")
        if not token:
            return BackendResult(False, request_id, None, None, "runtime_token_missing")
        if requests_mod is None:
            return BackendResult(False, request_id, None, None, "requests_unavailable")
        request_headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-Id": request_id,
            "Accept": "application/json" if method.upper() != "GET" else "*/*",
            **(headers or {}),
        }
        try:
            session = self._session_for_thread()
            if session is None:
                return BackendResult(False, request_id, None, None, "requests_unavailable")
            response = session.request(
                method,
                urljoin(self.base_url + "/", path.lstrip("/")),
                data=body,
                headers=request_headers,
                timeout=(self.connect_timeout, max(self.read_timeout, 90)),
            )
        except requests_mod.RequestException as exc:
            return BackendResult(False, request_id, None, None, _request_exception_code(exc))
        if response.status_code == 401:
            retry_with_rotated_token = False
            with self._runtime_unauthorized_lock:
                current_runtime_token = self._runtime_token()
                if current_runtime_token and current_runtime_token != token:
                    retry_with_rotated_token = method.upper() in {"GET", "HEAD"}
                elif current_runtime_token == token:
                    self._clear_runtime_session(error_code="runtime_unauthorized")
            if retry_with_rotated_token and _retry_after_rotation:
                return self._runtime_binary_request(
                    method,
                    path,
                    body=body,
                    headers=headers,
                    _retry_after_rotation=False,
                )
        if response.ok and method.upper() == "GET":
            payload: Any = bytes(response.content or b"")
        else:
            text = response.text or ""
            payload = _safe_json(text) if text else {}
        return BackendResult(
            ok=response.ok,
            request_id=request_id,
            status_code=response.status_code,
            data=payload,
            error=None if response.ok else _normalize_error_message(payload) or response.reason,
            x_request_id=response.headers.get("x-request-id"),
        )

    def _user_access_token(self) -> str:
        account = _map_from(state_store.snapshot().get("account"))
        return _first_nonempty(account.get("accessToken"))

    def _refresh_token(self) -> str:
        account = _map_from(state_store.snapshot().get("account"))
        return _first_nonempty(account.get("refreshToken"))

    def _runtime_token(self) -> str:
        runtime = _map_from(state_store.snapshot().get("runtime"))
        return _first_nonempty(runtime.get("runtimeToken"))

    def _pairing_token(self) -> str:
        pairing = _map_from(state_store.snapshot().get("pairing"))
        return _first_nonempty(pairing.get("pairingToken"), pairing.get("lastPairingToken"))

    def _apply_subscription_truth(self, payload: dict[str, Any]) -> None:
        subscription = _map_from(payload.get("subscription"))
        if not subscription:
            user = _map_from(payload.get("user"))
            subscription = _map_from(user.get("subscription"))
        if not subscription and not _map_from(payload.get("usage")):
            return

        billing_patch: dict[str, Any] = {}
        account_patch: dict[str, Any] = {}
        if subscription:
            brain_profile = _map_from(subscription.get("brainProfile"))
            normalized = {
                "planCode": _first_nonempty(subscription.get("planCode")),
                "status": _first_nonempty(subscription.get("status")),
                "aiCreditsMonthly": int(subscription.get("aiCreditsMonthly") or 0),
                "taskLimitMonthly": int(subscription.get("taskLimitMonthly") or 0),
                "periodEndsAt": _first_nonempty(subscription.get("periodEndsAt")),
            }
            if brain_profile:
                normalized["brainProfile"] = brain_profile
            for key in (
                "billingProvider",
                "subscriptionSource",
                "manageSubscriptionHint",
                "creditBalance",
                "creditGrantedThisPeriod",
                "creditPeriodEndsAt",
                "creditStatus",
                "trialEndsAt",
            ):
                value = subscription.get(key)
                if isinstance(value, dict):
                    normalized[key] = dict(value)
                else:
                    text = _first_nonempty(value)
                    if text:
                        normalized[key] = text
            billing_patch.update(normalized)
            account_patch["subscription"] = normalized
        usage = _map_from(payload.get("usage"))
        if usage:
            billing_patch["usage"] = usage
        if billing_patch:
            state_store.update_state({"billing": billing_patch})
        if account_patch:
            state_store.update_state({"account": account_patch})

    def _apply_control_plane_truth(self, key: str, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        state_store.update_state({"controlPlane": {key: payload}})

    def _apply_health_truth(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        dependencies = _map_from(payload.get("dependencies"))
        billing = _map_from(dependencies.get("billing"))
        if billing:
            billing_patch: dict[str, Any] = {
                "iyzicoStatus": _first_nonempty(billing.get("status")) or "unavailable",
            }
            if "checkoutEnabled" in billing:
                billing_patch["checkoutEnabled"] = bool(billing.get("checkoutEnabled"))
            if billing_patch:
                state_store.update_state({"billing": billing_patch})
        self._apply_control_plane_truth("health", payload)

    def _apply_user_truth(
        self,
        payload: dict[str, Any],
        *,
        include_tokens: bool,
    ) -> None:
        user = _map_from(payload.get("user"))
        account_patch: dict[str, Any] = {}
        email = _first_nonempty(user.get("email"), payload.get("email"))
        display_name = _first_nonempty(
            user.get("displayName"),
            user.get("name"),
            payload.get("displayName"),
        )
        if email:
            account_patch["email"] = email
        if display_name:
            account_patch["displayName"] = display_name
        avatar_url = _first_nonempty(
            user.get("avatarUrl"),
            user.get("avatar_url"),
            user.get("photoUrl"),
            user.get("photo_url"),
            user.get("picture"),
            user.get("image"),
            payload.get("avatarUrl"),
            payload.get("photoUrl"),
        )
        avatar_path = _first_nonempty(
            user.get("avatarPath"),
            user.get("avatar_path"),
            user.get("photoPath"),
            user.get("photo_path"),
            payload.get("avatarPath"),
            payload.get("photoPath"),
        )
        if avatar_url:
            account_patch["avatarUrl"] = avatar_url
        if avatar_path:
            account_patch["avatarPath"] = avatar_path
        if "hasAvatar" in user or "hasAvatar" in payload:
            account_patch["hasAvatar"] = bool(user.get("hasAvatar", payload.get("hasAvatar", False)))
        if "avatarVersion" in user or "avatarVersion" in payload:
            try:
                account_patch["avatarVersion"] = max(0, int(user.get("avatarVersion", payload.get("avatarVersion", 0)) or 0))
            except (TypeError, ValueError):
                account_patch["avatarVersion"] = 0
        if include_tokens:
            tokens = _map_from(payload.get("tokens"))
            access_token = _first_nonempty(
                tokens.get("accessToken"),
                tokens.get("access_token"),
                payload.get("accessToken"),
                payload.get("access_token"),
                payload.get("access"),
            )
            refresh_token = _first_nonempty(
                tokens.get("refreshToken"),
                tokens.get("refresh_token"),
                payload.get("refreshToken"),
                payload.get("refresh_token"),
                payload.get("refresh"),
            )
            if access_token:
                account_patch["accessToken"] = access_token
            if refresh_token:
                account_patch["refreshToken"] = refresh_token
        if account_patch:
            account_patch["onboardingCompleted"] = True
            state_store.update_state({"account": account_patch})
        self._apply_subscription_truth(payload)

    def _apply_runtime_truth(self, payload: dict[str, Any]) -> None:
        runtime = _map_from(payload.get("runtime"))
        runtime_auth = _map_from(payload.get("runtimeAuth"))
        if not runtime:
            runtime = dict(runtime_auth)
        runtime_patch: dict[str, Any] = {}
        runtime_token = _first_nonempty(
            runtime.get("runtimeToken"),
            runtime.get("token"),
            _map_from(payload.get("tokens")).get("accessToken"),
            _map_from(payload.get("tokens")).get("access_token"),
            payload.get("runtimeToken"),
            payload.get("token"),
        )
        device_id = _first_nonempty(
            runtime_auth.get("deviceId"),
            runtime.get("deviceId"),
            payload.get("deviceId"),
        )
        device_secret = _first_nonempty(
            runtime_auth.get("deviceSecret"),
            runtime.get("deviceSecret"),
            payload.get("deviceSecret"),
        )
        connection_id = _first_nonempty(
            runtime.get("connectionId"),
            payload.get("connectionId"),
        )
        if runtime_token:
            runtime_patch["runtimeToken"] = runtime_token
        if device_id:
            runtime_patch["deviceId"] = device_id
        if device_secret:
            runtime_patch["deviceSecret"] = device_secret
        if connection_id:
            runtime_patch["connectionId"] = connection_id
        if "targetStatus" in payload:
            runtime_patch["targetStatus"] = _first_nonempty(payload.get("targetStatus"))
        if "targetErrorCode" in payload:
            runtime_patch["targetErrorCode"] = _first_nonempty(payload.get("targetErrorCode"))
        if "currentTaskId" in payload:
            runtime_patch["currentTaskId"] = _first_nonempty(payload.get("currentTaskId"))
        if "ready" in payload:
            runtime_patch["ready"] = bool(payload.get("ready"))
        if "lifecycleState" in payload:
            runtime_patch["lifecycleState"] = _first_nonempty(payload.get("lifecycleState")) or "offline"
        if "websocketConnected" in payload:
            runtime_patch["websocketConnected"] = bool(payload.get("websocketConnected"))
        if "lastErrorCode" in payload:
            runtime_patch["lastErrorCode"] = _first_nonempty(payload.get("lastErrorCode"))
        if "xRequestId" in payload:
            runtime_patch["lastXRequestId"] = _first_nonempty(payload.get("xRequestId"))
        capabilities = _payload_capabilities(payload)
        if capabilities:
            runtime_patch["capabilities"] = capabilities
        capability_states = _payload_capability_states(payload)
        if capability_states:
            runtime_patch["capabilityStates"] = capability_states
        if runtime_patch:
            state_store.update_state({"runtime": runtime_patch})

    def _apply_pairing_truth(self, payload: dict[str, Any]) -> None:
        pairing_patch: dict[str, Any] = {}
        session_id = _first_nonempty(payload.get("sessionId"), payload.get("id"))
        pairing_token = _first_nonempty(payload.get("pairingToken"), payload.get("token"))
        qr_payload = _map_from(payload.get("qrPayload"))
        desktop_device = _map_from(payload.get("desktopDevice"))
        desktop_device_id = _first_nonempty(
            payload.get("desktopDeviceId"),
            desktop_device.get("id"),
        )
        pairing_code = _first_nonempty(
            payload.get("pairingCode"),
            payload.get("pairing_code"),
            payload.get("code"),
            qr_payload.get("pairingCode"),
            qr_payload.get("pairing_code"),
            qr_payload.get("code"),
        )
        manual_entry_code = _first_nonempty(
            payload.get("manualEntryCode"),
            payload.get("manual_entry_code"),
            qr_payload.get("manualEntryCode"),
            qr_payload.get("manual_entry_code"),
        )
        qr_text = _first_nonempty(payload.get("qrText"))
        qr_data_url = _first_nonempty(payload.get("qrDataUrl"))
        expires_at = _first_nonempty(payload.get("expiresAt"))
        status = _first_nonempty(payload.get("status"))
        if session_id:
            pairing_patch["lastSessionId"] = session_id
        if desktop_device_id:
            pairing_patch["desktopDeviceId"] = desktop_device_id
        if pairing_token:
            pairing_patch["pairingToken"] = pairing_token
        if pairing_code:
            pairing_patch["pairingCode"] = pairing_code
        if manual_entry_code:
            pairing_patch["manualEntryCode"] = manual_entry_code
        if not qr_text and session_id and pairing_code:
            qr_text = _pairing_qr_text(session_id, pairing_code)
        if qr_text:
            pairing_patch["qrText"] = qr_text
        if qr_data_url:
            pairing_patch["qrDataUrl"] = qr_data_url
        if not expires_at and session_id and (pairing_code or qr_text):
            expires_at = _pairing_expiry_fallback_iso()
        if expires_at:
            pairing_patch["expiresAt"] = expires_at
        if status:
            pairing_patch["lastSessionStatus"] = status
            pairing_patch["lastErrorCode"] = ""
        if status == "pending":
            pairing_patch["lastClaimedAt"] = ""
            pairing_patch["lastHeartbeatAt"] = ""
            pairing_patch["realtimeReady"] = False
        if status == "claimed":
            pairing_patch["lastClaimedAt"] = _first_nonempty(payload.get("claimedAt"))
        if pairing_patch:
            state_store.update_state({"pairing": pairing_patch})
        if status == "claimed":
            self._apply_runtime_truth(
                {
                    "ready": False,
                    "lifecycleState": "claimed_registering",
                    "websocketConnected": False,
                }
            )
        self._apply_runtime_truth(payload)

    def _paired_runtime_identity(self) -> dict[str, str]:
        runtime = _map_from(state_store.snapshot().get("runtime"))
        return {
            "deviceId": _first_nonempty(runtime.get("deviceId")),
            "deviceSecret": _first_nonempty(runtime.get("deviceSecret")),
        }

    def _clear_active_pairing_session(self, *, error_code: str = "") -> None:
        state_store.update_state(
            {
                "pairing": {
                    "lastSessionId": "",
                    "desktopDeviceId": "",
                    "pairingToken": "",
                    "pairingCode": "",
                    "manualEntryCode": "",
                    "qrText": "",
                    "qrDataUrl": "",
                    "expiresAt": "",
                    "lastSessionStatus": "",
                    "lastErrorCode": error_code,
                    "realtimeReady": False,
                    "lastClaimedAt": "",
                    "lastHeartbeatAt": "",
                }
            }
        )

    def _clear_session(self) -> None:
        paired = self._paired_runtime_identity()
        state_store.update_state(
            {
                "account": {
                    "displayName": "Elyan",
                    "email": "",
                    "avatarUrl": "",
                    "avatarPath": "",
                    "hasAvatar": False,
                    "avatarVersion": 0,
                    "accessToken": "",
                    "refreshToken": "",
                    "onboardingCompleted": False,
                    "subscription": {
                        "planCode": "offline",
                        "status": "offline",
                        "aiCreditsMonthly": 0,
                        "taskLimitMonthly": 0,
                        "periodEndsAt": "",
                    },
                },
                "runtime": {
                    "runtimeToken": "",
                    "deviceId": paired["deviceId"],
                    "deviceSecret": paired["deviceSecret"],
                    "connectionId": "",
                    "currentTaskId": "",
                    "ready": False,
                    "lifecycleState": "offline",
                    "websocketConnected": False,
                    "lastErrorCode": "",
                    "lastXRequestId": "",
                },
                "pairing": {
                    "realtimeReady": False,
                    "lastSessionId": "",
                    "desktopDeviceId": "",
                    "pairingToken": "",
                    "pairingCode": "",
                    "manualEntryCode": "",
                    "qrText": "",
                    "qrDataUrl": "",
                    "expiresAt": "",
                    "lastSessionStatus": "",
                    "lastErrorCode": "",
                    "connectedDevices": [],
                    "lastHeartbeatAt": "",
                    "lastClaimedAt": "",
                },
                "billing": {
                    "planCode": "offline",
                    "status": "offline",
                    "aiCreditsMonthly": 0,
                    "taskLimitMonthly": 0,
                    "periodEndsAt": "",
                    "usage": {},
                    "paymentMethod": "",
                    "cards": [],
                    "billingInfo": {},
                    "taxInfo": {},
                    "iyzicoStatus": "unavailable",
                    "invoices": [],
                    "limits": {},
                    "limitBehavior": "fail_closed",
                    "features": [],
                },
                "conversation": {
                    "activeId": "",
                    "items": [],
                },
                "controlPlane": {
                    "authMe": None,
                    "mobileBootstrap": None,
                    "brainProfile": None,
                    "runtimeSession": None,
                },
            }
        )

    def _clear_runtime_session(self, *, error_code: str = "") -> None:
        state_store.update_state(
            {
                "runtime": {
                    "runtimeToken": "",
                    "connectionId": "",
                    "currentTaskId": "",
                    "ready": False,
                    "lifecycleState": "offline",
                    "websocketConnected": False,
                    "targetStatus": "",
                    "targetErrorCode": "",
                    "lastErrorCode": error_code,
                    "lastXRequestId": "",
                },
                "pairing": {
                    "realtimeReady": False,
                    "lastHeartbeatAt": "",
                },
                "controlPlane": {
                    "runtimeSession": None,
                },
            }
        )

    def _expire_user_session(self) -> None:
        # User auth and the paired runtime are separate lifecycles. A terminal
        # refresh failure clears only user tokens; the QR-paired daemon keeps
        # its runtime identity and can continue receiving desktop tasks.
        state_store.update_state(
            {
                "account": {
                    "accessToken": "",
                    "refreshToken": "",
                }
            }
        )
        import sys
        import json
        event_id = _request_id()
        sys.stdout.write(json.dumps({
            "id": event_id,
            "taskId": event_id,
            "ok": True,
            "capability": "backend.auth_refresh_needed",
            "result": {},
            "events": [],
            "artifacts": [],
            "error": None,
            "durationMs": 0,
            "requestId": event_id
        }) + "\n")
        sys.stdout.flush()

    def _refresh_user_session_after_unauthorized(self, stale_access_token: str) -> BackendResult:
        with self._user_refresh_lock:
            current_access_token = self._user_access_token()
            if current_access_token and current_access_token != stale_access_token:
                return BackendResult(
                    ok=True,
                    request_id=_request_id(),
                    status_code=200,
                    data={"reusedRotatedSession": True},
                )
            return self.refresh_session()

    def _authorized_request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        request_id = _request_id()
        token = self._user_access_token() if token_kind == "user" else self._runtime_token()
        if not token:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=None,
                data=None,
                error="user_token_missing" if token_kind == "user" else "runtime_token_missing",
            )
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
        result = self._request(
            method,
            path,
            json_body,
            headers=headers,
            request_id=request_id,
        )
        if token_kind == "runtime" and result.status_code == 401:
            with self._runtime_unauthorized_lock:
                current_runtime_token = self._runtime_token()
                if current_runtime_token and current_runtime_token != token:
                    # Another request already rotated/re-registered the runtime.
                    # Retry this stale response once with the new token instead
                    # of clearing the fresh session.
                    headers["Authorization"] = f"Bearer {current_runtime_token}"
                    result = self._request(
                        method,
                        path,
                        json_body,
                        headers=headers,
                        request_id=request_id,
                    )
                    if result.status_code == 401 and self._runtime_token() == current_runtime_token:
                        self._clear_runtime_session()
                elif current_runtime_token == token:
                    self._clear_runtime_session()
        if token_kind != "user" or not refresh_on_401 or result.status_code != 401:
            return result

        refresh_result = self._refresh_user_session_after_unauthorized(token)
        if not refresh_result.ok:
            if _terminal_auth_failure(refresh_result):
                self._expire_user_session()
                error_code = "session_expired"
                status_code = 401
            else:
                error_code = refresh_result.error or "auth_refresh_failed"
                status_code = refresh_result.status_code
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=status_code,
                data=refresh_result.data if refresh_result.data is not None else result.data,
                error=error_code,
                x_request_id=refresh_result.x_request_id or result.x_request_id,
            )

        refreshed_token = self._user_access_token()
        if not refreshed_token:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=401,
                data=result.data,
                error="auth_refresh_token_missing",
                x_request_id=result.x_request_id,
            )

        headers["Authorization"] = f"Bearer {refreshed_token}"
        return self._request(
            method,
            path,
            json_body,
            headers=headers,
            request_id=request_id,
        )

    def _authorized_binary_request(
        self,
        method: str,
        path: str,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        request_id = _request_id()
        token = self._user_access_token() if token_kind == "user" else self._runtime_token()
        if not self.base_url:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=None,
                data=None,
                error="backend_unconfigured",
            )
        requests_mod = _requests_module()
        if requests_mod is None:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=None,
                data=None,
                error="requests_unavailable",
            )
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        headers: dict[str, str] = {
            "Accept": "*/*",
            "X-Request-Id": request_id,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            session = self._session_for_thread()
            if session is None:
                return BackendResult(
                    ok=False,
                    request_id=request_id,
                    status_code=None,
                    data=None,
                    error="requests_unavailable",
                )
            response = session.request(
                method,
                url,
                headers=headers,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests_mod.RequestException as exc:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=None,
                data=None,
                error=_request_exception_code(exc),
            )
        if token_kind == "user" and refresh_on_401 and response.status_code == 401:
            refresh_result = self._refresh_user_session_after_unauthorized(token)
            if not refresh_result.ok:
                if _terminal_auth_failure(refresh_result):
                    self._expire_user_session()
                    error_code = "session_expired"
                    status_code = 401
                else:
                    error_code = refresh_result.error or "auth_refresh_failed"
                    status_code = refresh_result.status_code
                return BackendResult(
                    ok=False,
                    request_id=request_id,
                    status_code=status_code,
                    data=refresh_result.data,
                    error=error_code,
                    x_request_id=refresh_result.x_request_id
                    or response.headers.get("x-request-id")
                    or response.headers.get("X-Request-Id"),
                )
            return self._authorized_binary_request(method, path, token_kind=token_kind, refresh_on_401=False)
        if not response.ok:
            text = response.text or ""
            payload = _safe_json(text) if text else {}
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=response.status_code,
                data=payload if payload else None,
                error=(
                    _normalize_error_message(payload.get("message")) if isinstance(payload, dict) else ""
                )
                or (_normalize_error_message(payload.get("error")) if isinstance(payload, dict) else "")
                or _normalize_error_message(payload)
                or text[:200]
                or response.reason,
                x_request_id=response.headers.get("x-request-id") or response.headers.get("X-Request-Id"),
            )
        import base64

        mime_type = str(response.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()
        return BackendResult(
            ok=True,
            request_id=request_id,
            status_code=response.status_code,
            data={
                "mimeType": mime_type,
                "dataBase64": base64.b64encode(response.content).decode("ascii"),
            },
            x_request_id=response.headers.get("x-request-id") or response.headers.get("X-Request-Id"),
        )

    def auth_login(self, email: str, password: str) -> BackendResult:
        result = self._request(
            "POST",
            "/v1/auth/login",
            {"email": email, "password": password},
        )
        if result.ok and isinstance(result.data, dict):
            self._apply_user_truth(result.data, include_tokens=True)
        return result

    def auth_oauth_login(
        self,
        provider: str,
        id_token: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        authorization_code: str | None = None,
    ) -> BackendResult:
        normalized_provider = str(provider or "").strip().lower()
        if normalized_provider not in {"google", "apple"}:
            return BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=None,
                data=None,
                error="unsupported_auth_provider",
            )
        payload: dict[str, Any] = {
            "idToken": str(id_token or "").strip(),
        }
        normalized_email = _first_nonempty(email)
        normalized_display_name = _first_nonempty(display_name)
        normalized_authorization_code = _first_nonempty(authorization_code)
        if normalized_email:
            payload["email"] = normalized_email
        if normalized_display_name:
            payload["displayName"] = normalized_display_name
        if normalized_authorization_code:
            payload["authorizationCode"] = normalized_authorization_code
        result = self._request("POST", f"/v1/auth/oauth/{normalized_provider}", payload)
        if result.ok and isinstance(result.data, dict):
            self._apply_user_truth(result.data, include_tokens=True)
        return result

    def runtime_register_identity_error(self) -> dict[str, str] | None:
        state = state_store.snapshot()
        pairing = _map_from(state.get("pairing"))
        runtime = _map_from(state.get("runtime"))
        device_id = _first_nonempty(runtime.get("deviceId"))
        device_secret = _first_nonempty(runtime.get("deviceSecret"))
        desktop_device_id = _first_nonempty(pairing.get("desktopDeviceId"))

        if not device_id or not device_secret:
            return {
                "code": "RUNTIME_AUTH_MISSING",
                "message": "Runtime eşleştirmesi tamamlanmamış.",
            }
        if len(device_secret) < 16:
            return {
                "code": "RUNTIME_REGISTER_INVALID_IDENTITY",
                "message": "Runtime kimliği geçersiz.",
            }
        if not _is_uuid_value(device_id):
            return {
                "code": "RUNTIME_REGISTER_INVALID_IDENTITY",
                "message": "Runtime kimliği geçersiz.",
            }
        if desktop_device_id:
            if not _is_uuid_value(desktop_device_id) or desktop_device_id != device_id:
                return {
                    "code": "RUNTIME_REGISTER_INVALID_IDENTITY",
                    "message": "Runtime kimliği geçersiz.",
                }
        return None

    def repair_invalid_runtime_identity(self, error_code: str = "RUNTIME_REGISTER_INVALID_IDENTITY") -> None:
        safe_error_code = _runtime_identity_repair_error_code(error_code)
        state_store.update_state(
            {
                "runtime": {
                    "runtimeToken": "",
                    "deviceId": "",
                    "deviceSecret": "",
                    "connectionId": "",
                    "currentTaskId": "",
                    "ready": False,
                    "lifecycleState": "offline",
                    "websocketConnected": False,
                    "lastErrorCode": safe_error_code,
                    "lastXRequestId": "",
                },
                "pairing": {
                    "lastSessionId": "",
                    "desktopDeviceId": "",
                    "pairingToken": "",
                    "pairingCode": "",
                    "manualEntryCode": "",
                    "qrText": "",
                    "expiresAt": "",
                    "lastSessionStatus": "",
                    "lastErrorCode": safe_error_code,
                    "realtimeReady": False,
                    "lastHeartbeatAt": "",
                },
            }
        )

    def _clear_device_not_found_streak(self) -> None:
        runtime = state_store.snapshot().get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        if str(runtime.get("deviceNotFoundSince", "") or "").strip():
            state_store.update_state({"runtime": {"deviceNotFoundSince": ""}})

    def _device_not_found_wipe_due(self) -> bool:
        """Kesintisiz 'cihaz bulunamadı' süresi eşiği aştıysa True.

        İlk gözlemde zaman damgasını kaydeder ve False döner (kimliği koru,
        yeniden dene). Ancak süre eşiği aşınca True döner ki çağıran gerçekten
        silinmiş cihaz için kimliği temizlesin.
        """
        now = dt.datetime.now(dt.timezone.utc)
        runtime = state_store.snapshot().get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        since_raw = str(runtime.get("deviceNotFoundSince", "") or "").strip()
        since: dt.datetime | None = None
        if since_raw:
            try:
                since = dt.datetime.fromisoformat(since_raw)
            except ValueError:
                since = None
            if since is not None and since.tzinfo is None:
                since = since.replace(tzinfo=dt.timezone.utc)
        if since is None:
            state_store.update_state(
                {"runtime": {"deviceNotFoundSince": now.isoformat()}}
            )
            return False
        elapsed = (now - since).total_seconds()
        return elapsed >= _DEVICE_NOT_FOUND_WIPE_GRACE_SECONDS

    def auth_register(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
        legal_acceptance: dict[str, Any] | None = None,
    ) -> BackendResult:
        payload: dict[str, Any] = {"email": email, "password": password}
        if display_name:
            payload["displayName"] = display_name
        if isinstance(legal_acceptance, dict):
            payload["legalAcceptance"] = {
                "termsAccepted": legal_acceptance.get("termsAccepted") is True,
                "privacyAccepted": legal_acceptance.get("privacyAccepted") is True,
            }
        result = self._request("POST", "/v1/auth/register", payload)
        if result.ok and isinstance(result.data, dict):
            self._apply_user_truth(result.data, include_tokens=True)
        return result

    def auth_update_profile(self, display_name: str) -> BackendResult:
        result = self._authorized_request(
            "PATCH",
            "/v1/auth/me",
            {"displayName": display_name},
            token_kind="user",
            refresh_on_401=True,
        )
        if result.ok and isinstance(result.data, dict):
            self._apply_user_truth(result.data, include_tokens=False)
            self._apply_control_plane_truth("authMe", result.data)
        return result

    def auth_change_password(self, current_password: str, next_password: str) -> BackendResult:
        return self._authorized_request(
            "POST",
            "/v1/auth/password",
            {
                "currentPassword": current_password,
                "nextPassword": next_password,
            },
            token_kind="user",
            refresh_on_401=True,
        )

    def auth_avatar_upload(self, mime_type: str, data_base64: str) -> BackendResult:
        result = self._authorized_request(
            "POST",
            "/v1/auth/avatar",
            {
                "mimeType": mime_type,
                "dataBase64": data_base64,
            },
            token_kind="user",
            refresh_on_401=True,
        )
        if result.ok and isinstance(result.data, dict):
            self._apply_user_truth(result.data, include_tokens=False)
            self._apply_control_plane_truth("authMe", result.data)
        return result

    def auth_avatar_delete(self) -> BackendResult:
        result = self._authorized_request(
            "DELETE",
            "/v1/auth/avatar",
            token_kind="user",
            refresh_on_401=True,
        )
        if result.ok and isinstance(result.data, dict):
            self._apply_user_truth(result.data, include_tokens=False)
            self._apply_control_plane_truth("authMe", result.data)
        return result

    def auth_avatar_get(self) -> BackendResult:
        request_id = _request_id()
        if not self.base_url:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=None,
                data=None,
                error="backend_unconfigured",
            )
        token = self._user_access_token()
        headers: dict[str, str] = {
            "Accept": "*/*",
            "X-Request-Id": request_id,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = urljoin(self.base_url + "/", "/v1/auth/avatar".lstrip("/"))
        try:
            requests_mod = _requests_module()
            if requests_mod is None:
                return BackendResult(
                    ok=False,
                    request_id=request_id,
                    status_code=None,
                    data=None,
                    error="requests_unavailable",
                )
            session = self._session_for_thread()
            if session is None:
                return BackendResult(
                    ok=False,
                    request_id=request_id,
                    status_code=None,
                    data=None,
                    error="requests_unavailable",
                )
            response = session.request(
                "GET",
                url,
                headers=headers,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests_mod.RequestException as exc:
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=None,
                data=None,
                error=_request_exception_code(exc),
            )
        if response.status_code == 401:
            refresh_result = self._refresh_user_session_after_unauthorized(token)
            if not refresh_result.ok:
                if _terminal_auth_failure(refresh_result):
                    self._expire_user_session()
                    error_code = "session_expired"
                    status_code = 401
                else:
                    error_code = refresh_result.error or "auth_refresh_failed"
                    status_code = refresh_result.status_code
                return BackendResult(
                    ok=False,
                    request_id=request_id,
                    status_code=status_code,
                    data=refresh_result.data,
                    error=error_code,
                    x_request_id=refresh_result.x_request_id
                    or response.headers.get("x-request-id")
                    or response.headers.get("X-Request-Id"),
                )
            return self.auth_avatar_get()
        if not response.ok:
            text = response.text or ""
            payload = _safe_json(text) if text else {}
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=response.status_code,
                data=payload if payload else None,
                error=(
                    _normalize_error_message(payload.get("message")) if isinstance(payload, dict) else ""
                )
                or (_normalize_error_message(payload.get("error")) if isinstance(payload, dict) else "")
                or _normalize_error_message(payload)
                or text[:200]
                or response.reason,
                x_request_id=response.headers.get("x-request-id") or response.headers.get("X-Request-Id"),
            )
        import base64

        mime_type = str(response.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()
        return BackendResult(
            ok=True,
            request_id=request_id,
            status_code=response.status_code,
            data={
                "mimeType": mime_type,
                "dataBase64": base64.b64encode(response.content).decode("ascii"),
            },
            x_request_id=response.headers.get("x-request-id") or response.headers.get("X-Request-Id"),
        )

    def auth_refresh(self) -> BackendResult:
        refresh_token = self._refresh_token()
        if not refresh_token:
            return BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=None,
                data=None,
                error="refresh_token_missing",
            )
        result = self._request(
            "POST",
            "/v1/auth/refresh",
            {"refreshToken": refresh_token},
        )
        if result.ok and isinstance(result.data, dict):
            self._apply_user_truth(result.data, include_tokens=True)
        elif _terminal_auth_failure(result):
            self._expire_user_session()
        return result

    def refresh_session(self) -> BackendResult:
        return self.auth_refresh()

    def auth_logout(self) -> BackendResult:
        if self._runtime_token():
            self.disconnect_runtime()
        result = self._authorized_request(
            "POST",
            "/v1/auth/logout",
            token_kind="user",
            refresh_on_401=True,
        )
        self._clear_session()
        return result

    def auth_delete_account(self) -> BackendResult:
        if self._runtime_token():
            self.disconnect_runtime()
        result = self._authorized_request(
            "DELETE",
            "/v1/auth/me",
            token_kind="user",
            refresh_on_401=True,
        )
        if result.ok:
            self._clear_session()
        return result

    def auth_me(self) -> BackendResult:
        result = self._authorized_request(
            "GET",
            "/v1/auth/me",
            token_kind="user",
            refresh_on_401=True,
        )
        if result.ok and isinstance(result.data, dict):
            self._apply_user_truth(result.data, include_tokens=False)
            self._apply_control_plane_truth("authMe", result.data)
        elif not result.ok:
            state_store.update_state({"controlPlane": {"authMe": None}})
        return result

    def device_deactivate(self, device_id: str) -> BackendResult:
        return self._authorized_request(
            "POST",
            f"/v1/devices/{device_id.strip()}/deactivate",
            token_kind="user",
            refresh_on_401=True,
        )

    def mobile_bootstrap(self) -> BackendResult:
        result = self._authorized_request(
            "GET",
            "/v1/mobile/bootstrap",
            token_kind="user",
            refresh_on_401=True,
        )
        if result.ok and isinstance(result.data, dict):
            self._apply_user_truth(result.data, include_tokens=False)
            self._apply_control_plane_truth("mobileBootstrap", result.data)
        elif not result.ok:
            state_store.update_state({"controlPlane": {"mobileBootstrap": None}})
        return result

    def health(self) -> BackendResult:
        result = self._request("GET", "/healthz")
        if result.ok and isinstance(result.data, dict):
            self._apply_health_truth(result.data)
        elif not result.ok:
            state_store.update_state({"controlPlane": {"health": None}})
        return result

    def tasks_list(
        self,
        *,
        limit: int = 20,
        target_device_id: str = "",
        status: str = "",
    ) -> BackendResult:
        query_parts = [f"limit={max(1, min(int(limit or 20), 100))}"]
        normalized_target_device_id = _first_nonempty(target_device_id)
        normalized_status = _first_nonempty(status)
        if normalized_target_device_id:
            query_parts.append(f"targetDeviceId={normalized_target_device_id}")
        if normalized_status:
            query_parts.append(f"status={normalized_status}")
        path = "/v1/tasks"
        if query_parts:
            path = f"{path}?{'&'.join(query_parts)}"
        return self._authorized_request(
            "GET",
            path,
            token_kind="user",
            refresh_on_401=True,
        )

    def task_detail(self, task_id: str) -> BackendResult:
        return self._authorized_request(
            "GET",
            f"/v1/tasks/{task_id}",
            token_kind="user",
            refresh_on_401=True,
        )

    def task_approval(self, task_id: str, approved: bool, notes: str | None = None) -> BackendResult:
        payload: dict[str, Any] = {"approved": bool(approved)}
        normalized_notes = str(notes or "").strip()
        if normalized_notes:
            payload["notes"] = normalized_notes[:500]
        # Backend bu rotada runtime token da kabul eder (sub = cihaz sahibi):
        # QR eşleşmiş masaüstünde kullanıcı token'ı yoktur; tepsiden onay/iptal
        # runtime token ile çalışmalı.
        return self._authorized_request(
            "POST",
            f"/v1/tasks/{task_id}/approval",
            payload,
            token_kind=self._user_scoped_token_kind(),
            refresh_on_401=True,
        )

    def _user_scoped_token_kind(self) -> str:
        """Kullanıcı-kapsamlı ama runtime token'la da çağrılabilen rotalar
        (chat/brain) için token seçimi. Anonim (QR) eşleşmiş masaüstünde hiç
        kullanıcı token'ı olmaz; backend bu rotalarda runtime token kabul eder
        (sub = cihaz sahibinin userId'si)."""
        return "user" if self._user_access_token() else "runtime"

    def brain_profile(self) -> BackendResult:
        result = self._authorized_request(
            "GET",
            "/v1/brain/profile",
            token_kind=self._user_scoped_token_kind(),
            refresh_on_401=True,
        )
        if result.ok and isinstance(result.data, dict):
            self._apply_control_plane_truth("brainProfile", result.data)
        elif not result.ok:
            state_store.update_state({"controlPlane": {"brainProfile": None}})
        return result

    def desktop_plan(self, payload: dict[str, Any]) -> BackendResult:
        """Yapılandırılmış planlama (elyan.plan.v2): planlama zarfını sohbet
        pipeline'ına sokmadan doğrudan sunucu planlayıcısına gönderir; saf plan
        JSON'u döner. Eski backend'lerde 404 döner — çağıran chat yoluna düşer."""
        return self._authorized_request(
            "POST",
            "/v1/brain/desktop/plan",
            dict(payload),
            token_kind=self._user_scoped_token_kind(),
            refresh_on_401=True,
        )

    def chat_messages(self, payload: dict[str, Any]) -> BackendResult:
        return self._authorized_request(
            "POST",
            "/v1/chat/messages",
            dict(payload),
            token_kind=self._user_scoped_token_kind(),
            refresh_on_401=True,
        )

    def chat_sessions(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> BackendResult:
        query: dict[str, Any] = {"limit": max(1, min(int(limit or 20), 20))}
        normalized_status = str(status or "").strip().lower()
        if normalized_status:
            query["status"] = normalized_status
        path = "/v1/chat/sessions"
        if query:
            path = f"{path}?{urlencode(query)}"
        return self._authorized_request(
            "GET",
            path,
            token_kind="user",
            refresh_on_401=True,
        )

    def chat_session_detail(self, session_id: str) -> BackendResult:
        return self._authorized_request(
            "GET",
            f"/v1/chat/sessions/{session_id}",
            token_kind=self._user_scoped_token_kind(),
            refresh_on_401=True,
        )

    def chat_session_create(self, payload: dict[str, Any]) -> BackendResult:
        return self._authorized_request(
            "POST",
            "/v1/chat/sessions",
            dict(payload),
            token_kind=self._user_scoped_token_kind(),
            refresh_on_401=True,
        )

    def chat_session_update(self, session_id: str, payload: dict[str, Any]) -> BackendResult:
        return self._authorized_request(
            "PATCH",
            f"/v1/chat/sessions/{session_id}",
            dict(payload),
            token_kind="user",
            refresh_on_401=True,
        )

    def chat_session_delete(self, session_id: str) -> BackendResult:
        return self._authorized_request(
            "DELETE",
            f"/v1/chat/sessions/{session_id}",
            token_kind="user",
            refresh_on_401=True,
        )

    def chat_sessions_clear(self, before: dt.datetime | None = None) -> BackendResult:
        query: dict[str, Any] = {}
        if before is not None:
            query["before"] = before.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()
        path = "/v1/chat/sessions"
        if query:
            path = f"{path}?{urlencode(query)}"
        return self._authorized_request(
            "DELETE",
            path,
            token_kind="user",
            refresh_on_401=True,
        )

    def brain_retrieval_search(self, payload: dict[str, Any]) -> BackendResult:
        return self._authorized_request(
            "POST",
            "/v1/brain/retrieval/search",
            dict(payload),
            token_kind=self._user_scoped_token_kind(),
            refresh_on_401=True,
        )

    def brain_knowledge_document(self, payload: dict[str, Any]) -> BackendResult:
        return self._authorized_request(
            "POST",
            "/v1/brain/knowledge/documents",
            dict(payload),
            token_kind="user",
            refresh_on_401=True,
        )

    def realtime_runtime(self) -> BackendResult:
        return self.runtime_session()

    def register_runtime(self, payload: dict[str, Any]) -> BackendResult:
        request_id = _request_id()
        identity_error = self.runtime_register_identity_error()
        if identity_error is not None:
            error_code = str(identity_error.get("code", "") or "").strip() or "RUNTIME_AUTH_MISSING"
            if error_code == "RUNTIME_REGISTER_INVALID_IDENTITY":
                self.repair_invalid_runtime_identity(error_code)
            else:
                self._apply_runtime_truth(
                    {
                        "ready": False,
                        "lifecycleState": "offline",
                        "websocketConnected": False,
                        "lastErrorCode": _runtime_identity_repair_error_code(error_code),
                        "xRequestId": "",
                    }
                )
            return BackendResult(
                ok=False,
                request_id=request_id,
                status_code=400,
                data={"error": identity_error},
                error=_runtime_identity_repair_error_code(error_code),
            )

        request_payload = dict(payload)
        runtime_identity = self._paired_runtime_identity()
        if runtime_identity["deviceId"]:
            request_payload["deviceId"] = runtime_identity["deviceId"]
        if runtime_identity["deviceSecret"]:
            request_payload["deviceSecret"] = runtime_identity["deviceSecret"]
        runtime_version = _first_nonempty(request_payload.get("runtimeVersion"))
        if runtime_version:
            request_payload["runtimeVersion"] = runtime_version
        else:
            request_payload.pop("runtimeVersion", None)
        if not isinstance(request_payload.get("capabilities"), list) or not request_payload.get("capabilities"):
            request_payload["capabilities"] = self._advertised_capabilities()
        result = self._request(
            "POST",
            "/v1/runtime/register",
            request_payload,
            request_id=request_id,
        )
        if result.ok and isinstance(result.data, dict):
            self._clear_device_not_found_streak()
            state_store.update_state(
                {
                    "runtime": {
                        "runtimeToken": "",
                        "connectionId": "",
                        "currentTaskId": "",
                        "ready": False,
                        "websocketConnected": False,
                        "targetStatus": "",
                        "targetErrorCode": "",
                    }
                }
            )
            self._apply_runtime_truth(
                {
                    **result.data,
                    "ready": False,
                    "lifecycleState": "runtime_connecting",
                    "websocketConnected": False,
                    "xRequestId": result.x_request_id or "",
                    "capabilities": _payload_capabilities(request_payload),
                    "capabilityStates": _payload_capability_states(request_payload),
                }
            )
        elif not result.ok:
            identity_error_code = _runtime_registration_identity_error(result)
            if identity_error_code == "DESKTOP_RUNTIME_DEVICE_NOT_FOUND":
                # Belirsiz tek yanıt: kimliği hemen silme. Yalnızca hata
                # kesintisiz olarak grace süresini aşarsa (gerçekten silinmiş
                # cihaz) sil; aksi halde kimliği koru ki yeniden-deneme döngüsü
                # backend toparlanınca kendini iyileştirsin.
                if self._device_not_found_wipe_due():
                    self.repair_invalid_runtime_identity(identity_error_code)
                    return BackendResult(
                        ok=False,
                        request_id=result.request_id,
                        status_code=result.status_code,
                        data=result.data,
                        error=_runtime_identity_repair_error_code(identity_error_code),
                        x_request_id=result.x_request_id,
                    )
                self._apply_runtime_truth(
                    {
                        "ready": False,
                        "lifecycleState": "offline",
                        "websocketConnected": False,
                        "lastErrorCode": _runtime_identity_repair_error_code(identity_error_code),
                        "xRequestId": result.x_request_id or "",
                    }
                )
                return BackendResult(
                    ok=False,
                    request_id=result.request_id,
                    status_code=result.status_code,
                    data=result.data,
                    error=_runtime_identity_repair_error_code(identity_error_code),
                    x_request_id=result.x_request_id,
                )
            if identity_error_code:
                self.repair_invalid_runtime_identity(identity_error_code)
                return BackendResult(
                    ok=False,
                    request_id=result.request_id,
                    status_code=result.status_code,
                    data=result.data,
                    error=_runtime_identity_repair_error_code(identity_error_code),
                    x_request_id=result.x_request_id,
                )
            self._apply_runtime_truth(
                {
                    "ready": False,
                    "lifecycleState": "offline",
                    "websocketConnected": False,
                    "lastErrorCode": _safe_error_code(result.error, "runtime_register_failed"),
                    "xRequestId": result.x_request_id or "",
                }
            )
        return result

    def heartbeat(self, payload: dict[str, Any]) -> BackendResult:
        heartbeat_payload = dict(payload)
        if not isinstance(heartbeat_payload.get("capabilities"), list) or not heartbeat_payload.get("capabilities"):
            heartbeat_payload["capabilities"] = self._advertised_capabilities()
        current_task_id = _first_nonempty(heartbeat_payload.get("currentTaskId"))
        result = self._authorized_request(
            "POST",
            "/v1/runtime/heartbeat",
            heartbeat_payload,
            token_kind="runtime",
        )
        if result.ok:
            state_store.update_state(
                {
                    "runtime": {
                        "ready": True,
                        "lifecycleState": "ready",
                        "currentTaskId": current_task_id,
                        "capabilities": _payload_capabilities(heartbeat_payload),
                        "capabilityStates": _payload_capability_states(heartbeat_payload),
                        "lastErrorCode": "",
                        "lastXRequestId": result.x_request_id or "",
                    },
                    "pairing": {
                        "realtimeReady": True,
                        "lastHeartbeatAt": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                    },
                }
            )
        elif result.status_code == 401:
            self._clear_runtime_session(error_code="runtime_unauthorized")
        elif not result.ok:
            self._apply_runtime_truth(
                {
                    "ready": False,
                    "lifecycleState": "reconnecting"
                    if self._paired_runtime_identity()["deviceId"]
                    and self._paired_runtime_identity()["deviceSecret"]
                    else "offline",
                    "websocketConnected": False,
                    "currentTaskId": current_task_id,
                    "lastErrorCode": _safe_error_code(result.error, "runtime_heartbeat_failed"),
                    "xRequestId": result.x_request_id or "",
                }
            )
            state_store.update_state(
                {
                    "pairing": {
                        "realtimeReady": False,
                    }
                }
            )
        return result

    def gmail_send_message(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        connection_id: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
    ) -> BackendResult:
        payload: dict[str, Any] = {
            "to": [item for item in to if str(item or "").strip()],
            "subject": subject,
            "body": body,
        }
        if connection_id:
            payload["connectionId"] = connection_id
        if cc:
            payload["cc"] = [item for item in cc if str(item or "").strip()]
        if bcc:
            payload["bcc"] = [item for item in bcc if str(item or "").strip()]
        if reply_to:
            payload["replyTo"] = reply_to
        return self._authorized_request(
            "POST",
            "/v1/integrations/gmail/send",
            payload,
            token_kind="user",
            refresh_on_401=True,
        )

    def integration_apps(self) -> BackendResult:
        return self._authorized_request(
            "GET",
            "/v1/integrations/apps",
            token_kind="user",
            refresh_on_401=True,
        )

    def start_integration_app_oauth(
        self,
        app_id: str,
        *,
        redirect_uri: str | None = None,
    ) -> BackendResult:
        payload: dict[str, Any] = {}
        normalized_redirect = str(redirect_uri or "").strip()
        if normalized_redirect:
            payload["redirectUri"] = normalized_redirect
        return self._authorized_request(
            "POST",
            f"/v1/integrations/apps/{str(app_id or '').strip()}/oauth/start",
            payload,
            token_kind="user",
            refresh_on_401=True,
        )

    def disconnect_integration_app(self, app_id: str) -> BackendResult:
        return self._authorized_request(
            "DELETE",
            f"/v1/integrations/apps/{str(app_id or '').strip()}",
            token_kind="user",
            refresh_on_401=True,
        )

    def runtime_mcp_connections(self) -> BackendResult:
        return self._authorized_request(
            "GET",
            "/v1/integrations/runtime/mcp",
            token_kind="runtime",
        )

    def runtime_session(self) -> BackendResult:
        result = self._authorized_request(
            "GET",
            "/v1/runtime/session",
            token_kind="runtime",
        )
        if result.ok and isinstance(result.data, dict):
            readiness = _map_from(result.data.get("readiness"))
            connection = _map_from(result.data.get("connection"))
            target_status = _first_nonempty(readiness.get("targetStatus")).lower()
            target_error_code = _first_nonempty(readiness.get("targetErrorCode"))
            can_receive_tasks = readiness.get("canReceiveTasks") is True
            connected = _first_nonempty(connection.get("status")).lower() == "online"
            realtime_ready = readiness.get("realtimeReady")
            if not isinstance(realtime_ready, bool):
                realtime_ready = can_receive_tasks and target_status == "ready"
            heartbeat_at = _first_nonempty(
                connection.get("lastHeartbeatAt"),
                _map_from(readiness.get("runtime")).get("lastHeartbeatAt"),
            )
            current_task_id = _first_nonempty(connection.get("currentTaskId"))
            self._apply_runtime_truth(
                {
                    "currentTaskId": current_task_id,
                    "ready": realtime_ready,
                    "lifecycleState": "ready" if realtime_ready else "reconnecting",
                    "targetStatus": target_status,
                    "targetErrorCode": target_error_code,
                    "websocketConnected": connected,
                    "capabilities": _payload_capabilities(result.data) or self._advertised_capabilities(),
                    "capabilityStates": _payload_capability_states(result.data),
                    "lastErrorCode": "",
                    "xRequestId": result.x_request_id or "",
                }
            )
            self._apply_control_plane_truth("runtimeSession", result.data)
            pairing_patch: dict[str, Any] = {
                "realtimeReady": realtime_ready,
            }
            if heartbeat_at:
                pairing_patch["lastHeartbeatAt"] = heartbeat_at
            state_store.update_state({"pairing": pairing_patch})
        elif result.status_code == 401:
            self._clear_runtime_session(error_code="runtime_unauthorized")
        elif not result.ok:
            runtime_state = _map_from(state_store.snapshot().get("runtime"))
            has_runtime_identity = bool(
                _first_nonempty(runtime_state.get("deviceId"))
                and _first_nonempty(runtime_state.get("deviceSecret"))
            )
            lifecycle_state = "reconnecting" if has_runtime_identity else "offline"
            self._apply_runtime_truth(
                {
                    "ready": False,
                    "lifecycleState": lifecycle_state,
                    "websocketConnected": False,
                    "lastErrorCode": _safe_error_code(result.error, "runtime_session_failed"),
                    "xRequestId": result.x_request_id or result.request_id,
                }
            )
            state_store.update_state({"controlPlane": {"runtimeSession": None}})
            state_store.update_state({"pairing": {"realtimeReady": False, "lastHeartbeatAt": ""}})
        return result

    def runtime_tasks_assigned(self) -> BackendResult:
        result = self._authorized_request(
            "GET",
            "/v1/runtime/tasks/assigned",
            token_kind="runtime",
        )
        if result.status_code == 401:
            self._clear_runtime_session(error_code="runtime_unauthorized")
        return result

    def runtime_task_status(self, task_id: str, payload: dict[str, Any]) -> BackendResult:
        result = self._authorized_request(
            "POST",
            f"/v1/runtime/tasks/{task_id}/status",
            payload,
            token_kind="runtime",
        )
        if result.status_code == 401:
            self._clear_runtime_session(error_code="runtime_unauthorized")
        return result

    def runtime_task_artifacts(self, task_id: str, payload: dict[str, Any]) -> BackendResult:
        result = self._authorized_request(
            "POST",
            f"/v1/runtime/tasks/{task_id}/artifacts",
            payload,
            token_kind="runtime",
        )
        if result.status_code == 401:
            self._clear_runtime_session(error_code="runtime_unauthorized")
        return result

    def runtime_task_binary_artifact(
        self,
        task_id: str,
        body: bytes,
        *,
        name: str,
        content_type: str,
        sha256: str,
    ) -> BackendResult:
        return self._runtime_binary_request(
            "POST",
            f"/v1/runtime/tasks/{task_id}/artifacts/binary",
            body=body,
            headers={
                "Content-Type": content_type,
                "X-Elyan-File-Name": name,
                "X-Content-Sha256": sha256,
            },
        )

    def runtime_task_input_content(self, task_id: str, input_ref: str) -> BackendResult:
        return self._runtime_binary_request(
            "GET",
            f"/v1/runtime/tasks/{task_id}/inputs/{quote(input_ref, safe='')}/content",
        )

    def disconnect_runtime(self) -> BackendResult:
        result = self._authorized_request(
            "POST",
            "/v1/runtime/disconnect",
            token_kind="runtime",
        )
        self._clear_runtime_session()
        return result

    def pairing_create_session(self, payload: dict[str, Any]) -> BackendResult:
        request_payload = dict(payload)
        pairing = _map_from(state_store.snapshot().get("pairing"))
        current_session_id = _first_nonempty(pairing.get("lastSessionId"))
        current_status = _first_nonempty(pairing.get("lastSessionStatus")).lower()
        current_pairing_token = _first_nonempty(pairing.get("pairingToken"))
        current_pairing_code = _first_nonempty(pairing.get("pairingCode"))
        current_qr_text = _first_nonempty(pairing.get("qrText"))
        force_new = bool(request_payload.pop("forceNew", False) or request_payload.pop("force_new", False))
        if (
            not force_new
            and current_status == "pending"
            and current_session_id
            and current_pairing_token
            and (current_pairing_code or current_qr_text)
            and not _pairing_expired(pairing.get("expiresAt"))
        ):
            return BackendResult(
                ok=True,
                request_id=_request_id(),
                status_code=200,
                data={
                    "sessionId": current_session_id,
                    "desktopDeviceId": _first_nonempty(pairing.get("desktopDeviceId")),
                    "status": "pending",
                    "pairingToken": current_pairing_token,
                    "pairingCode": current_pairing_code,
                    "manualEntryCode": _first_nonempty(pairing.get("manualEntryCode")),
                    "qrText": current_qr_text,
                    "qrDataUrl": _first_nonempty(pairing.get("qrDataUrl")),
                    "expiresAt": _first_nonempty(pairing.get("expiresAt")),
                    "reused": True,
                },
            )
        external_device_id = _first_nonempty(
            request_payload.get("externalDeviceId"),
            request_payload.get("external_device_id"),
            pairing.get("externalDeviceId"),
        )
        if external_device_id:
            request_payload["externalDeviceId"] = external_device_id
        # Girişsiz masaüstü de oturum açabilir (anonim eşleştirme) — token
        # varsa gönderilir, yoksa istek yetkisiz gider ve backend kabul eder.
        if self._user_access_token():
            result = self._authorized_request(
                "POST",
                "/v1/pairing/sessions",
                request_payload,
                token_kind="user",
                refresh_on_401=True,
            )
        else:
            result = self._request("POST", "/v1/pairing/sessions", request_payload)
        if result.ok and isinstance(result.data, dict):
            self._apply_pairing_truth(result.data)
            self._apply_runtime_truth(
                {
                    "ready": False,
                    "lifecycleState": "waiting_claim",
                    "websocketConnected": False,
                    "lastErrorCode": "",
                    "xRequestId": result.x_request_id or "",
                }
            )
        return result

    def pairing_claim_session(self, session_id: str, payload: dict[str, Any]) -> BackendResult:
        # Claim, oturum sahibinin user token'ıyla yetkilendirilir. Mobil kendi
        # token'ıyla claim eder; masaüstü self-pairing'de aynı hesabın token'ı
        # kullanılır (backend canlı olarak doğrulandı: aynı kullanıcı kendi
        # oturumunu claim edebiliyor).
        if self._user_access_token():
            return self._authorized_request(
                "POST",
                f"/v1/pairing/sessions/{session_id}/claim",
                payload,
                token_kind="user",
                refresh_on_401=True,
            )
        return self._request(
            "POST",
            f"/v1/pairing/sessions/{session_id}/claim",
            payload,
        )

    def pairing_get_session(self, session_id: str, pairing_token: str | None = None) -> BackendResult:
        current_pairing = _map_from(state_store.snapshot().get("pairing"))
        if (
            session_id
            and session_id == _first_nonempty(current_pairing.get("lastSessionId"))
            and _pairing_expired(current_pairing.get("expiresAt"))
        ):
            self._clear_active_pairing_session(error_code="PAIRING_SESSION_EXPIRED")
            self._apply_runtime_truth(
                {
                    "ready": False,
                    "lifecycleState": "waiting_claim",
                    "websocketConnected": False,
                    "lastErrorCode": "pairing_session_expired",
                    "xRequestId": "",
                }
            )
            return BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=409,
                data={"error": "PAIRING_SESSION_EXPIRED"},
                error="Pair session has expired",
            )
        token = _first_nonempty(pairing_token, self._pairing_token())
        headers = {"x-pairing-token": token} if token else {}
        result = self._request("GET", f"/v1/pairing/sessions/{session_id}", headers=headers)
        if result.ok and isinstance(result.data, dict):
            self._apply_pairing_truth(result.data)
            if _first_nonempty(result.data.get("status")).lower() == "claimed":
                state_store.update_state(
                    {
                        "pairing": {
                            "realtimeReady": False,
                        },
                        "runtime": {
                            "ready": False,
                            "lifecycleState": "claimed_registering",
                            "websocketConnected": False,
                            "lastErrorCode": "",
                            "lastXRequestId": result.x_request_id or "",
                        },
                    }
                )
        elif result.status_code in {404, 409}:
            error_text = str(result.error or "").lower()
            error_code = (
                "PAIRING_SESSION_EXPIRED"
                if "expired" in error_text
                else "PAIRING_SESSION_INVALID"
            )
            self._clear_active_pairing_session(error_code=error_code)
            self._apply_runtime_truth(
                {
                    "ready": False,
                    "lifecycleState": "waiting_claim",
                    "websocketConnected": False,
                    "lastErrorCode": error_code.lower(),
                    "xRequestId": result.x_request_id or "",
                }
            )
        return result

    def runtime_websocket_url(self) -> str | None:
        base = _ws_url_from_http(self.base_url)
        if not base:
            return None
        return urljoin(base + "/", "v1/realtime/runtime")
