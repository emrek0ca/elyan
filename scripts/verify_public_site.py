from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]


def _require(path: str) -> Path:
    candidate = ROOT / path
    if not candidate.exists():
        raise SystemExit(f"missing required asset: {path}")
    return candidate


def _read(path: str) -> str:
    return _require(path).read_text(encoding="utf-8")


def _assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"missing {label}: {needle}")


def main() -> int:
    files = [
        "site/index.html",
        "site/auth.html",
        "site/panel.html",
        "site/pricing.html",
        "docs/index.html",
        "assets/public.css",
    ]
    for path in files:
        _require(path)

    home = _read("site/index.html")
    docs = _read("docs/index.html")
    panel = _read("site/panel.html")
    auth = _read("site/auth.html")
    pricing = _read("site/pricing.html")
    server = _read("core/gateway/server.py")

    for needle in [
        "local-first",
        "hosted control plane",
        "Register / Login",
        "Install locally",
        "Docs",
    ]:
        _assert_contains(home, needle, "home content")

    for needle in [
        "Getting Started",
        "Hosted Account / Billing",
        "Privacy / Boundaries",
        "Optional MCP",
    ]:
        _assert_contains(docs, needle, "docs content")

    for needle in [
        "/api/v1/public/auth/me",
        "/api/v1/billing/workspace",
        "/api/v1/billing/ledger",
        "/api/v1/billing/events",
        "/api/v1/notifications",
        "Mark seen",
    ]:
        _assert_contains(panel, needle, "panel content")

    for needle in [
        "/api/v1/billing/plans",
        "Local runtime first",
        "No fake upgrade flow",
    ]:
        _assert_contains(pricing, needle, "pricing content")

    for needle in [
        "handle_v1_public_auth_register",
        "handle_v1_public_auth_login",
        "handle_v1_notifications",
        "handle_public_panel_page",
        "handle_public_docs_page",
    ]:
        _assert_contains(server, needle, "gateway routes")

    route_count = len(re.findall(r"add_get\('/panel", server))
    if route_count == 0:
        raise SystemExit("panel route registration missing")
    print("public site verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
