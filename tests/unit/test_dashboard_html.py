"""Desktop-first UI regression tests."""

from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent


def test_react_tauri_routes_are_canonical_product_navigation():
    routes = (_REPO / "apps/desktop/src/app/routes.tsx").read_text(encoding="utf-8")
    assert "/home" in routes
    assert "/command-center" in routes
    assert "/providers" in routes
    assert "/integrations" in routes
    assert "/settings" in routes
    assert "/logs" in routes
    assert 'path: "/dashboard"' not in routes


def test_pyqt_shell_is_marked_as_legacy_compatibility_only():
    ui = (_REPO / "ui/clean_main_app.py").read_text(encoding="utf-8")
    assert "Legacy PyQt desktop compatibility shell." in ui
    assert "Canonical product UX lives in apps/desktop (React/Tauri)." in ui


def test_ops_console_html_contains_admin_panels():
    html = (_REPO / "ui/web/ops_console.html").read_text(encoding="utf-8")

    assert "Elyan Ops Console" in html
    assert 'id="user-list"' in html
    assert 'id="lane-execution"' in html
    assert 'id="selected-plan"' in html
    assert "/ui/web/ops_console.css" in html
    assert "/ui/web/ops_console.js" in html
