from __future__ import annotations

import base64
import json
import time
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from core.dependencies import get_dependency_runtime

from ..auth import oauth_broker
from ..base import AuthStrategy, BaseConnector, ConnectorResult, ConnectorSnapshot, ConnectorState, OAuthAccount


class GoogleConnector(BaseConnector):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._services: dict[str, Any] = {}
        self._browser_fallback = None

    def _ensure_runtime(self) -> bool:
        runtime = get_dependency_runtime()
        deps = [
            ("google-api-python-client", "google-api-python-client", []),
            ("google-auth", "google-auth", []),
            ("google-auth-oauthlib", "google-auth-oauthlib", []),
            ("httplib2", "httplib2", []),
        ]
        ok = True
        for module_name, install_spec, post_install in deps:
            record = runtime.ensure_module(
                module_name,
                install_spec=install_spec,
                source="pypi",
                trust_level="trusted",
                post_install=post_install,
                skill_name=self.capability.name or "google",
                tool_name="google_runtime",
                allow_install=True,
            )
            ok = ok and str(record.status).lower() in {"installed", "ready"}
        return ok

    def _credential_obj(self):
        if not isinstance(self.auth_account, OAuthAccount):
            return None
        if not self.auth_account.access_token:
            return None
        try:
            from google.oauth2.credentials import Credentials
        except Exception:
            return None

        cfg = oauth_broker.provider_config("google")
        token_uri = str(cfg.get("token_url") or "https://oauth2.googleapis.com/token")
        try:
            return Credentials(
                token=self.auth_account.access_token or None,
                refresh_token=self.auth_account.refresh_token or None,
                token_uri=token_uri,
                client_id=str(cfg.get("client_id") or ""),
                client_secret=str(cfg.get("client_secret") or ""),
                scopes=list(self.auth_account.granted_scopes or self.capability.required_scopes or []),
            )
        except Exception:
            return None

    def _service(self, name: str, version: str):
        key = f"{name}:{version}"
        if key in self._services:
            return self._services[key]
        creds = self._credential_obj()
        if creds is None:
            return None
        try:
            from googleapiclient.discovery import build

            service = build(name, version, credentials=creds, cache_discovery=False)
            self._services[key] = service
            return service
        except Exception:
            return None

    async def connect(self, app_name_or_url: str, **kwargs: Any) -> ConnectorResult:
        started = time.perf_counter()
        if not self._ensure_runtime():
            return self._result(
                success=False,
                status="blocked",
                error="google_runtime_missing",
                message="google_api_runtime_missing",
                retryable=True,
                fallback_reason="google_runtime_missing",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
            )
        if isinstance(self.auth_account, OAuthAccount) and self.auth_account.is_ready:
            snapshot = await self.snapshot()
            return self._result(
                success=True,
                status="ready",
                message="google_connected",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                snapshot=snapshot,
                auth_state=self.auth_account.status,
            )
        account = oauth_broker.authorize("google", self.capability.required_scopes or ["email.read"], mode=str(kwargs.get("mode") or "auto"))
        self.auth_account = account
        if account.is_ready:
            snapshot = await self.snapshot()
            return self._result(
                success=True,
                status="ready",
                message="google_authorized",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                snapshot=snapshot,
                auth_state=account.status,
            )
        return self._result(
            success=False,
            status="needs_input",
            message="oauth_required",
            fallback_used=True,
            fallback_reason="oauth_required",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            auth_state=account.status,
            metadata={"auth_url": account.auth_url, "fallback_mode": account.fallback_mode.value if hasattr(account.fallback_mode, "value") else str(account.fallback_mode)},
        )

    async def execute(self, action: dict[str, Any]) -> ConnectorResult:
        started = time.perf_counter()
        payload = dict(action or {})
        kind = str(payload.get("kind") or payload.get("action") or "").strip().lower()
        service_name = str(payload.get("service") or payload.get("product") or "").strip().lower()
        if not (self.auth_account and self.auth_account.is_ready):
            account = oauth_broker.authorize("google", self.capability.required_scopes or ["google.read"], mode=str(payload.get("mode") or "auto"))
            self.auth_account = account
            if not account.is_ready:
                return self._result(
                    success=False,
                    status="needs_input",
                    message="oauth_required",
                    fallback_used=True,
                    fallback_reason="oauth_required",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    auth_state=account.status,
                    metadata={"auth_url": account.auth_url, "fallback_mode": account.fallback_mode.value if hasattr(account.fallback_mode, "value") else str(account.fallback_mode)},
                )
        service = None
        if service_name in {"gmail", "mail", "email"} or any(token in kind for token in ("mail", "email", "gmail")):
            service = self._service("gmail", "v1")
            if service is None:
                return await self._browser_fallback_action(payload, started, service_url="https://mail.google.com")
            if kind in {"gmail_list", "list_mail", "read_email"}:
                count = int(payload.get("limit", 10) or 10)
                data = service.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=count).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="gmail_listed",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "gmail_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            if kind in {"gmail_send", "send_email", "draft_email"}:
                to = str(payload.get("to") or payload.get("recipient") or "")
                subject = str(payload.get("subject") or "")
                body = str(payload.get("body") or payload.get("text") or "")
                msg = MIMEText(body, "plain", "utf-8")
                msg["to"] = to
                msg["subject"] = subject
                raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
                data = service.users().messages().send(userId="me", body={"raw": raw}).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="gmail_sent",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "gmail_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
        if service_name in {"calendar", "event", "schedule", "reminder"} or any(token in kind for token in ("calendar", "event", "remind")):
            service = self._service("calendar", "v3")
            if service is None:
                return await self._browser_fallback_action(payload, started, service_url="https://calendar.google.com")
            if kind in {"calendar_create", "create_event", "reminder"}:
                event = dict(payload.get("event") or {})
                if not event:
                    event = {
                        "summary": str(payload.get("summary") or payload.get("title") or "Elyan Event"),
                        "description": str(payload.get("description") or payload.get("body") or ""),
                    }
                    if payload.get("start") and payload.get("end"):
                        event["start"] = {"dateTime": str(payload.get("start"))}
                        event["end"] = {"dateTime": str(payload.get("end"))}
                data = service.events().insert(calendarId="primary", body=event).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="calendar_event_created",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "calendar_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            if kind in {"calendar_list", "today", "list_events"}:
                max_results = int(payload.get("limit", 10) or 10)
                data = service.events().list(calendarId="primary", maxResults=max_results, singleEvents=True, orderBy="startTime").execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="calendar_listed",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "calendar_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
        if service_name in {"drive", "files"} or any(token in kind for token in ("drive", "file", "document", "upload")):
            service = self._service("drive", "v3")
            if service is None:
                return await self._browser_fallback_action(payload, started, service_url="https://drive.google.com")
            if kind in {"drive_list", "list_drive", "files_list"}:
                data = service.files().list(pageSize=int(payload.get("limit", 10) or 10), fields="files(id,name,mimeType)").execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="drive_listed",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "drive_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            if kind in {"drive_upload", "upload_drive", "upload_file"}:
                file_path = str(payload.get("file_path") or payload.get("path") or "").strip()
                if not file_path:
                    return self._result(
                        success=False,
                        status="failed",
                        message="file_path_missing",
                        error="file_path_missing",
                        auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                    )
                try:
                    from googleapiclient.http import MediaFileUpload
                except Exception:
                    return self._result(
                        success=False,
                        status="blocked",
                        message="google_drive_upload_dependency_missing",
                        error="google_drive_upload_dependency_missing",
                        retryable=True,
                        auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                    )
                metadata: dict[str, Any] = {"name": str(payload.get("name") or Path(file_path).name)}
                parent_id = str(payload.get("parent_id") or payload.get("folder_id") or "").strip()
                if parent_id:
                    metadata["parents"] = [parent_id]
                media = MediaFileUpload(file_path, resumable=True)
                data = service.files().create(body=metadata, media_body=media, fields="id,name,webViewLink,mimeType").execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="drive_uploaded",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "drive_api", "action": kind, "file_path": file_path}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
        if service_name in {"docs", "document", "workspace_docs"} or any(token in kind for token in ("docs", "document", "word", "doc")):
            service = self._service("docs", "v1")
            if service is None:
                return await self._browser_fallback_action(payload, started, service_url="https://docs.google.com")
            document_id = str(payload.get("document_id") or payload.get("id") or "").strip()
            if kind in {"docs_get", "document_get", "read_doc"} and document_id:
                data = service.documents().get(documentId=document_id).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="docs_fetched",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "docs_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            if kind in {"docs_update", "update_doc", "append_doc", "write_doc"} and document_id:
                body = dict(payload.get("body") or {})
                if not body:
                    body = {
                        "requests": payload.get("requests") or [],
                    }
                data = service.documents().batchUpdate(documentId=document_id, body=body).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="docs_updated",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "docs_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            return await self._browser_fallback_action(payload, started, service_url="https://docs.google.com")
        if service_name in {"sheets", "sheet", "spreadsheet"} or any(token in kind for token in ("sheet", "spreadsheet", "table")):
            service = self._service("sheets", "v4")
            if service is None:
                return await self._browser_fallback_action(payload, started, service_url="https://sheets.google.com")
            spreadsheet_id = str(payload.get("spreadsheet_id") or payload.get("sheet_id") or "").strip()
            if kind in {"sheets_get", "sheet_get", "read_sheet"} and spreadsheet_id:
                data = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="sheets_fetched",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "sheets_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            if kind in {"sheets_get_values", "sheet_values_get", "read_sheet_values"} and spreadsheet_id:
                range_name = str(payload.get("range") or payload.get("sheet_range") or "A1:Z100").strip()
                data = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="sheets_values_fetched",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "sheets_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            if kind in {"sheets_update", "sheet_values_update", "write_sheet"} and spreadsheet_id:
                range_name = str(payload.get("range") or payload.get("sheet_range") or "A1").strip()
                body = dict(payload.get("body") or {"values": payload.get("values") or []})
                value_input = str(payload.get("value_input_option") or "USER_ENTERED")
                data = service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption=value_input,
                    body=body,
                ).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="sheets_values_updated",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "sheets_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            return await self._browser_fallback_action(payload, started, service_url="https://sheets.google.com")
        if service_name in {"slides", "presentation", "deck"} or any(token in kind for token in ("slide", "presentation", "deck")):
            service = self._service("slides", "v1")
            if service is None:
                return await self._browser_fallback_action(payload, started, service_url="https://slides.google.com")
            presentation_id = str(payload.get("presentation_id") or payload.get("deck_id") or "").strip()
            if kind in {"slides_get", "presentation_get", "read_slides"} and presentation_id:
                data = service.presentations().get(presentationId=presentation_id).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="slides_fetched",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "slides_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            if kind in {"slides_update", "presentation_update", "write_slides"} and presentation_id:
                body = dict(payload.get("body") or {"requests": payload.get("requests") or []})
                data = service.presentations().batchUpdate(presentationId=presentation_id, body=body).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="slides_updated",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "slides_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            return await self._browser_fallback_action(payload, started, service_url="https://slides.google.com")
        if service_name in {"chat", "workspace_chat"} or any(token in kind for token in ("chat", "message_space")):
            service = self._service("chat", "v1")
            if service is None:
                return await self._browser_fallback_action(payload, started, service_url="https://chat.google.com")
            space = str(payload.get("space") or payload.get("space_id") or "").strip()
            message = str(payload.get("message") or payload.get("text") or "").strip()
            if kind in {"chat_list", "list_spaces"}:
                data = service.spaces().list(pageSize=int(payload.get("limit", 10) or 10)).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="chat_spaces_listed",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "chat_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            if kind in {"chat_post", "send_chat", "send_message"} and space and message:
                data = service.spaces().messages().create(parent=space, body={"text": message}).execute()
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="success",
                    message="chat_message_sent",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    result=dict(data),
                    evidence=[{"kind": "chat_api", "action": kind}],
                    auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                )
            return await self._browser_fallback_action(payload, started, service_url="https://chat.google.com")
        return await self._browser_fallback_action(payload, started)

    async def _browser_fallback_action(self, payload: dict[str, Any], started: float, *, service_url: str = "") -> ConnectorResult:
        from .browser import BrowserConnector

        if self._browser_fallback is None:
            self._browser_fallback = BrowserConnector(
                capability=self.capability,
                auth_account=self.auth_account,
                platform=self.platform,
                provider="browser",
                connector_name="browser",
            )
        if service_url:
            await self._browser_fallback.connect(service_url)
        result = await self._browser_fallback.execute(payload)
        data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        data["fallback_used"] = True
        data["fallback_reason"] = "google_api_fallback_browser"
        data["latency_ms"] = float((time.perf_counter() - started) * 1000.0)
        return ConnectorResult.model_validate({
            **data,
            "connector_name": self.connector_name,
            "provider": self.provider,
            "integration_type": self.capability.integration_type,
            "platform": self.platform,
            "auth_state": self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
            "fallback_used": True,
            "fallback_reason": "google_api_fallback_browser",
            "latency_ms": float((time.perf_counter() - started) * 1000.0),
        })

    async def snapshot(self) -> ConnectorSnapshot:
        state = "ready" if self.auth_account and self.auth_account.is_ready else "needs_input"
        return self._snapshot(
            state=state,
            metadata={
                "services_ready": list(self._services.keys()),
                "fallback_active": bool(self._browser_fallback is not None),
            },
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
        )
