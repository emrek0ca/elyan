"""Basic regression tests for dashboard.html."""

from pathlib import Path


def test_dashboard_html_contains_task_center_and_quick_actions():
    html = Path("/Users/emrekoca/Desktop/bot/ui/web/dashboard.html").read_text(encoding="utf-8")

    assert "Task Center" in html
    assert 'data-tab="overview"' in html
    assert 'data-panel="models"' in html
    assert 'id="task-list"' in html
    assert 'id="workflow-preset-list"' in html
    assert 'id="workflow-report"' in html
    assert 'id="benchmark-summary"' in html
    assert 'id="setup-list"' in html
    assert 'id="onboarding-list"' in html
    assert 'id="release-list"' in html
    assert 'id="model-registry-list"' in html
    assert 'id="model-pool-summary"' in html
    assert 'id="model-add-btn"' in html
    assert 'id="collab-save-btn"' in html
    assert 'id="profile-save-btn"' in html
    assert 'id="agent-name-input"' in html
    assert 'id="profile-summary"' in html
    assert "data-quick-prompt=" in html
    assert 'id="status-note"' in html
    assert 'id="status-detail"' in html
    assert "/ui/web/dashboard.css" in html
    assert "/ui/web/dashboard.js" in html


def test_ops_console_html_contains_admin_panels():
    html = Path("/Users/emrekoca/Desktop/bot/ui/web/ops_console.html").read_text(encoding="utf-8")

    assert "Elyan Ops Console" in html
    assert 'id="user-list"' in html
    assert 'id="lane-execution"' in html
    assert 'id="selected-plan"' in html
    assert "/ui/web/ops_console.css" in html
    assert "/ui/web/ops_console.js" in html
