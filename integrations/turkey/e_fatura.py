from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from core.privacy.data_governance import PrivacyEngine
from integrations.turkey.base import ConnectorBase, ConnectorHealth
from security.audit import get_audit_logger


class _RequestSession(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


class _DefaultRequestSession:
    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.request(method, url, **kwargs)


class _EFaturaRequestError(RuntimeError):
    pass


class _EFaturaCredentialError(_EFaturaRequestError):
    pass


@dataclass(slots=True)
class EFaturaConfig:
    production_base_url: str = "https://efatura.gib.gov.tr"
    test_base_url: str = "https://efaturatest.gib.gov.tr"
    use_test_endpoint: bool = True
    timeout_seconds: float = 15.0
    health_path: str = ""
    credential_check_path: str = ""

    def base_url(self) -> str:
        base_url = self.test_base_url if self.use_test_endpoint else self.production_base_url
        return str(base_url or "").strip().rstrip("/")

    def endpoint_url(self, path: str = "") -> str:
        base_url = self.base_url()
        suffix = str(path or "").strip()
        if not suffix:
            return base_url
        return f"{base_url}/{suffix.lstrip('/')}"


@dataclass(slots=True)
class EFaturaCredentials:
    username: str = ""
    password: str = ""
    api_key: str = ""
    integrator_alias: str = ""

    def is_configured(self) -> bool:
        return bool(self.api_key or (self.username and self.password))


class EFaturaConnector(ConnectorBase):
    """
    GIB e-Fatura connector skeleton.

    Production URL: https://efatura.gib.gov.tr
    Test URL: https://efaturatest.gib.gov.tr
    """

    def __init__(
        self,
        *,
        config: EFaturaConfig | None = None,
        credentials: EFaturaCredentials | dict[str, Any] | None = None,
        session: _RequestSession | None = None,
        audit_logger: Any | None = None,
        privacy_engine: PrivacyEngine | None = None,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.5,
        sleeper: Any | None = None,
    ) -> None:
        self.config = config or EFaturaConfig()
        self.credentials = self._coerce_credentials(credentials)
        self.session = session or _DefaultRequestSession()
        self.audit_logger = audit_logger or get_audit_logger()
        self.privacy_engine = privacy_engine or PrivacyEngine()
        self.workspace_id = str(workspace_id or "local-workspace")
        self.user_id = str(user_id or "local-user")
        self.max_attempts = max(1, int(max_attempts or 1))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds or 0.0))
        self._sleeper = sleeper or time.sleep

    @staticmethod
    def _coerce_credentials(credentials: EFaturaCredentials | dict[str, Any] | None) -> EFaturaCredentials:
        if isinstance(credentials, EFaturaCredentials):
            return credentials
        if isinstance(credentials, dict):
            return EFaturaCredentials(
                username=str(credentials.get("username") or "").strip(),
                password=str(credentials.get("password") or "").strip(),
                api_key=str(credentials.get("api_key") or "").strip(),
                integrator_alias=str(credentials.get("integrator_alias") or credentials.get("alias") or "").strip(),
            )
        return EFaturaCredentials()

    def get_name(self) -> str:
        return "e_fatura"

    def health_check(self) -> ConnectorHealth:
        try:
            _, latency_ms = self._perform_request(
                action="health_check",
                url=self.config.endpoint_url(self.config.health_path),
            )
            return ConnectorHealth(is_healthy=True, latency_ms=latency_ms, last_error=None)
        except _EFaturaRequestError as exc:
            return ConnectorHealth(is_healthy=False, latency_ms=0.0, last_error=str(exc))

    def test_credentials(self) -> bool:
        if not self.credentials.is_configured():
            self._audit(
                action="test_credentials",
                success=False,
                duration_ms=0.0,
                result={"error": "e-Fatura kimlik bilgileri eksik"},
            )
            return False
        consent_error = self._consent_error()
        if consent_error:
            self._audit(
                action="test_credentials",
                success=False,
                duration_ms=0.0,
                result={"error": consent_error},
            )
            return False
        try:
            self._perform_request(
                action="test_credentials",
                url=self.config.endpoint_url(self.config.credential_check_path),
                headers=self._credential_headers(),
            )
            return True
        except _EFaturaRequestError:
            return False

    def _consent_error(self) -> str | None:
        consent = self.privacy_engine.get_consent(
            self.user_id,
            workspace_id=self.workspace_id,
            scope="turkey_connector.e_fatura",
        )
        if bool(consent.get("granted")):
            return None
        return "KVKK onayi olmadan e-Fatura kimlik dogrulamasi yapilamaz"

    def _credential_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/plain;q=0.9, */*;q=0.8"}
        if self.credentials.api_key:
            headers["X-API-Key"] = self.credentials.api_key
        if self.credentials.username and self.credentials.password:
            token = base64.b64encode(
                f"{self.credentials.username}:{self.credentials.password}".encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        if self.credentials.integrator_alias:
            headers["X-Integrator-Alias"] = self.credentials.integrator_alias
        return headers

    def _perform_request(
        self,
        *,
        action: str,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> tuple[httpx.Response, float]:
        for attempt in range(1, self.max_attempts + 1):
            started_at = time.perf_counter()
            try:
                response = self.session.request(
                    "GET",
                    url,
                    headers=dict(headers or {}),
                    timeout=self.config.timeout_seconds,
                    follow_redirects=True,
                )
                latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
                if 200 <= response.status_code < 400:
                    self._audit(
                        action=action,
                        success=True,
                        duration_ms=latency_ms,
                        result={"status_code": response.status_code},
                        attempt=attempt,
                        url=url,
                    )
                    return response, latency_ms
                if response.status_code in {401, 403}:
                    error = "e-Fatura kimlik dogrulamasi reddedildi"
                    self._audit(
                        action=action,
                        success=False,
                        duration_ms=latency_ms,
                        result={"status_code": response.status_code, "error": error},
                        attempt=attempt,
                        url=url,
                    )
                    raise _EFaturaCredentialError(error)
                error = f"e-Fatura servisi beklenmeyen durum kodu döndürdü: {response.status_code}"
                self._audit(
                    action=action,
                    success=False,
                    duration_ms=latency_ms,
                    result={"status_code": response.status_code, "error": error},
                    attempt=attempt,
                    url=url,
                )
                if attempt >= self.max_attempts:
                    raise _EFaturaRequestError(error)
            except httpx.HTTPError as exc:
                latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
                error = f"e-Fatura servisine baglanilamadi: {exc}"
                self._audit(
                    action=action,
                    success=False,
                    duration_ms=latency_ms,
                    result={"error": error},
                    attempt=attempt,
                    url=url,
                )
                if attempt >= self.max_attempts:
                    raise _EFaturaRequestError(error) from exc
            if attempt < self.max_attempts:
                self._sleeper(self.retry_backoff_seconds * (2 ** (attempt - 1)))
        raise _EFaturaRequestError("e-Fatura istegi sonucsuz kaldi")

    def _audit(
        self,
        *,
        action: str,
        success: bool,
        duration_ms: float,
        result: dict[str, Any],
        attempt: int = 1,
        url: str = "",
    ) -> None:
        self.audit_logger.log_operation(
            user_id=0,
            operation="turkey_connector.e_fatura",
            action=action,
            params={
                "connector": self.get_name(),
                "workspace_id": self.workspace_id,
                "user_id": self.user_id,
                "environment": "test" if self.config.use_test_endpoint else "production",
                "endpoint": url,
                "attempt": attempt,
                "has_api_key": bool(self.credentials.api_key),
                "has_username": bool(self.credentials.username),
                "has_integrator_alias": bool(self.credentials.integrator_alias),
            },
            result=dict(result or {}),
            success=success,
            duration=duration_ms,
            risk_level="medium",
            approved=True,
        )
