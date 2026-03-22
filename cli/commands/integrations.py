"""integrations.py - OAuth/account/trace management CLI."""
from __future__ import annotations

import json
from typing import Any

from integrations import integration_registry, oauth_broker
from core.integration_trace import get_integration_trace_store


def handle_integrations(args) -> int:
    action = getattr(args, "action", None) or "accounts"
    provider = str(getattr(args, "provider", "") or "").strip().lower()
    alias = str(getattr(args, "account_alias", "") or "default").strip() or "default"

    if action in {"accounts", "list", "status"}:
        _list_accounts(provider, as_json=bool(getattr(args, "json", False)))
        return 0

    if action == "connect":
        app_name = str(getattr(args, "app_name", "") or "").strip()
        scopes = _split_scopes(getattr(args, "scopes", []))
        plan = integration_registry.resolve_connection_plan(
            app_name=app_name,
            provider=provider,
            scopes=scopes,
            mode=str(getattr(args, "mode", "auto") or "auto"),
            account_alias=alias,
            extra={
                "display_name": str(getattr(args, "display_name", "") or "").strip(),
                "email": str(getattr(args, "email", "") or "").strip(),
            },
        )
        provider = str(plan.get("provider") or provider or "").strip().lower()
        scopes = list(plan.get("required_scopes") or scopes or [])
        alias = str(getattr(args, "account_alias", "") or plan.get("account_alias") or "default").strip() or "default"
        redirect_uri = str(getattr(args, "redirect_uri", "") or "").strip() or "http://localhost:8765/callback"
        account = oauth_broker.authorize(
            provider,
            scopes,
            mode=str(getattr(args, "mode", "auto") or "auto"),
            account_alias=alias,
            authorization_code=str(getattr(args, "authorization_code", "") or ""),
            redirect_uri=redirect_uri,
            extra={
                "display_name": str(getattr(args, "display_name", "") or "").strip(),
                "email": str(getattr(args, "email", "") or "").strip(),
                "app_name": app_name,
            },
        )
        payload = account.public_dump()
        payload["ok"] = True
        payload["resolved_app_name"] = plan.get("app_name") or app_name or provider
        payload["resolved_provider"] = provider
        payload["resolved_scopes"] = scopes
        payload["resolved_account_alias"] = alias
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            prefix = "✅" if account.is_ready else "⚠️"
            state = "bağlandı" if account.is_ready else "needs_input"
            print(f"{prefix}  {payload['resolved_app_name']} -> {provider}:{alias} {state}")
            if payload.get("auth_url"):
                print(f"    auth_url: {payload.get('auth_url')}")
            if payload.get("granted_scopes"):
                print(f"    scopes: {', '.join(payload.get('granted_scopes') or [])}")
        return 0

    if action == "revoke":
        ok = oauth_broker.delete_account(provider, alias)
        payload = {"ok": ok, "provider": provider, "account_alias": alias}
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            prefix = "✅" if ok else "❌"
            state = "kaldırıldı" if ok else "kaldırılamadı"
            print(f"{prefix}  {provider}:{alias} {state}")
        return 0 if ok else 1

    if action == "traces":
        _list_traces(args)
        return 0

    if action == "summary":
        _print_summary(provider, as_json=bool(getattr(args, "json", False)))
        return 0

    print(f"Bilinmeyen integrations eylemi: {action}")
    print("Usage: elyan integrations [accounts|connect|revoke|traces|summary]")
    return 1


def _split_scopes(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _print_payload(payload: dict[str, Any], *, prefix: str = "") -> None:
    if prefix:
        print(prefix, end=" ")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _list_accounts(provider: str, *, as_json: bool = False) -> None:
    accounts = [item.public_dump() for item in oauth_broker.list_accounts(provider or None)]
    counts: dict[str, int] = {}
    for item in accounts:
        state = str(item.get("status") or "unknown").strip().lower()
        counts[state] = int(counts.get(state, 0)) + 1
    payload = {
        "ok": True,
        "provider": provider,
        "total": len(accounts),
        "counts": counts,
        "accounts": accounts,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"Hesaplar: {len(accounts)}")
    for item in accounts:
        status = str(item.get("status") or "-")
        alias = str(item.get("account_alias") or "default")
        email = str(item.get("email") or "")
        scopes = ", ".join(item.get("granted_scopes") or [])
        auth = str(item.get("auth_url") or "")
        print(f"  • {item.get('provider','-')}:{alias} [{status}] {item.get('display_name') or email or '-'}")
        if email:
            print(f"    email: {email}")
        if scopes:
            print(f"    scopes: {scopes}")
        if auth and status != "ready":
            print(f"    auth_url: {auth}")


def _list_traces(args) -> None:
    store = get_integration_trace_store()
    try:
        limit = int(getattr(args, "limit", 50) or 50)
    except Exception:
        limit = 50
    traces = store.list_traces(
        limit=limit,
        provider=str(getattr(args, "provider", "") or "").strip().lower(),
        user_id=str(getattr(args, "user_id", "") or "").strip(),
        operation=str(getattr(args, "operation", "") or "").strip().lower(),
        connector_name=str(getattr(args, "connector_name", "") or "").strip().lower(),
        integration_type=str(getattr(args, "integration_type", "") or "").strip().lower(),
    )
    payload = {"ok": True, "total": len(traces), "summary": store.summary(limit=limit), "traces": traces}
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"Trace sayısı: {len(traces)}")
    for item in traces[:20]:
        provider = item.get("provider") or "-"
        connector = item.get("connector_name") or "-"
        operation = item.get("operation") or "connector"
        status = item.get("status") or ("success" if item.get("success") else "failed")
        latency = item.get("latency_ms")
        fallback = " fallback" if item.get("fallback_used") else ""
        print(f"  • {provider}:{connector} {operation} [{status}] {latency or 0:.0f}ms{fallback}")


def _print_summary(provider: str, *, as_json: bool = False) -> None:
    store = get_integration_trace_store()
    traces = store.summary(limit=200)
    accounts = [item.public_dump() for item in oauth_broker.list_accounts(provider or None)]
    counts: dict[str, int] = {}
    for item in accounts:
        state = str(item.get("status") or "unknown").strip().lower()
        counts[state] = int(counts.get(state, 0)) + 1
    payload = {
        "ok": True,
        "accounts": {"total": len(accounts), "counts": counts, "provider": provider, "items": accounts[:20]},
        "traces": traces,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"Hesaplar: {len(accounts)}")
    for key, value in counts.items():
        print(f"  - {key}: {value}")
    print(f"Trace toplam: {traces.get('total', 0)}")
    print(f"Fallback: {traces.get('fallback_count', 0)}")
