from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.contracts.failure_taxonomy import FailureCode
from core.contracts.verification_result import VerificationCheck, VerificationResult
from core.storage_paths import resolve_elyan_data_dir

from .services import BrowserRuntimeServices, PLAYWRIGHT_AVAILABLE, default_browser_runtime_services


ScreenOperatorRunner = Callable[..., Awaitable[dict[str, Any]]]

DOM_UNAVAILABLE = "DOM_UNAVAILABLE"
NATIVE_DIALOG_REQUIRED = "NATIVE_DIALOG_REQUIRED"
UNCONTROLLED_BROWSER_CHROME = "UNCONTROLLED_BROWSER_CHROME"


def _normalize_url(url: str) -> str:
    raw = str(url or "").strip()
    if raw and not raw.startswith(("http://", "https://")):
        return "https://" + raw
    return raw


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


def _artifact_root() -> Path:
    root = resolve_elyan_data_dir() / "browser_runtime" / str(int(time.time() * 1000))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _materialize_artifacts(
    *,
    root: Path,
    dom_snapshot: dict[str, Any],
    screenshot_path: str,
    action_logs: list[dict[str, Any]],
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    html_path = root / "dom_snapshot.html"
    json_path = root / "dom_snapshot.json"
    nav_path = root / "navigation.json"
    action_path = root / "action_log.json"
    verify_path = root / "verification.json"

    _write_json(json_path, dom_snapshot)
    _write_text(html_path, str(dom_snapshot.get("html") or ""))
    _write_json(nav_path, {"url": dom_snapshot.get("url"), "title": dom_snapshot.get("title"), "dom_hash": dom_snapshot.get("dom_hash")})
    _write_json(action_path, action_logs)
    _write_json(verify_path, verification)

    for path in (json_path, html_path, nav_path, action_path, verify_path):
        artifacts.append({"path": str(path), "type": "json" if path.suffix == ".json" else "text"})
    if screenshot_path and Path(screenshot_path).exists():
        target = root / "page.png"
        if Path(screenshot_path).resolve() != target.resolve():
            shutil.copyfile(screenshot_path, target)
        else:
            target = Path(screenshot_path)
        artifacts.append({"path": str(target), "type": "image"})
    return artifacts


def _verify_browser_result(
    *,
    action: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    action_result: dict[str, Any],
    extracted_text: str,
    typed_value: str,
    expected_text: str,
    expected_url: str,
    expected_title: str,
    screenshot_path: str,
) -> dict[str, Any]:
    before_url = str(before_state.get("url") or "")
    after_url = str(after_state.get("url") or "")
    before_title = str(before_state.get("title") or "")
    after_title = str(after_state.get("title") or "")
    before_hash = str(before_state.get("dom_hash") or "")
    after_hash = str(after_state.get("dom_hash") or "")
    text_blob = " ".join([str(after_state.get("visible_text") or ""), str(extracted_text or ""), str(typed_value or "")]).lower()

    checks: list[VerificationCheck] = [
        VerificationCheck(code="dom_available", passed=bool(after_state.get("dom_available", True))),
    ]
    if screenshot_path:
        checks.append(VerificationCheck(code="screenshot_present", passed=True, details={"path": screenshot_path}))
    failures: list[str] = []

    if action == "open":
        has_expectation = bool(expected_url or expected_title)
        nav_ok = bool(
            after_url
            and (
                (after_url != before_url or not before_url)
                or (expected_url and expected_url.lower() in after_url.lower())
                or (expected_title and expected_title.lower() in after_title.lower())
                or (bool(action_result.get("success")) and not has_expectation)
            )
        )
        title_ok = True if not expected_title else expected_title.lower() in after_title.lower()
        url_ok = True if not expected_url else expected_url.lower() in after_url.lower()
        checks.extend(
            [
                VerificationCheck(code="navigation_changed", passed=nav_ok, details={"before_url": before_url, "after_url": after_url}),
                VerificationCheck(code="title_matches", passed=title_ok, details={"title": after_title}),
                VerificationCheck(code="url_matches", passed=url_ok, details={"url": after_url}),
            ]
        )
        if not (nav_ok and title_ok and url_ok):
            failures.append("NAVIGATION_NOT_VERIFIED")
    elif action == "click":
        changed = bool(after_url != before_url or after_title != before_title or after_hash != before_hash)
        checks.append(VerificationCheck(code="dom_or_navigation_changed", passed=changed, details={"before_hash": before_hash, "after_hash": after_hash}))
        if expected_text:
            text_ok = expected_text.lower() in text_blob
            checks.append(VerificationCheck(code="expected_text_visible", passed=text_ok, details={"expected_text": expected_text}))
            changed = changed or text_ok
        if not changed:
            failures.append(FailureCode.NO_VISUAL_CHANGE.value)
    elif action == "type":
        typed_ok = bool(typed_value) and typed_value == str(action_result.get("text") or "")
        checks.append(VerificationCheck(code="typed_value_persisted", passed=typed_ok, details={"typed_value": typed_value}))
        if not typed_ok:
            failures.append(FailureCode.ARTIFACT_MISSING.value)
    elif action == "submit":
        submit_ok = bool(after_url != before_url or after_title != before_title or after_hash != before_hash)
        if expected_text:
            submit_ok = submit_ok or expected_text.lower() in text_blob
        checks.append(VerificationCheck(code="submit_state_transition", passed=submit_ok, details={"before_url": before_url, "after_url": after_url}))
        if not submit_ok:
            failures.append("SUBMIT_NOT_VERIFIED")
    elif action == "extract":
        text_ok = bool(extracted_text.strip())
        checks.append(VerificationCheck(code="text_extracted", passed=text_ok, details={"length": len(extracted_text or "")}))
        if not text_ok:
            failures.append(FailureCode.ARTIFACT_MISSING.value)
    elif action == "scroll":
        before_scroll = before_state.get("scroll") if isinstance(before_state.get("scroll"), dict) else {}
        after_scroll = after_state.get("scroll") if isinstance(after_state.get("scroll"), dict) else {}
        scroll_ok = before_scroll != after_scroll
        checks.append(VerificationCheck(code="scroll_position_changed", passed=scroll_ok, details={"before": before_scroll, "after": after_scroll}))
        if not scroll_ok:
            failures.append(FailureCode.NO_VISUAL_CHANGE.value)

    result = VerificationResult.from_checks(
        checks,
        summary=f"browser verification for {action}",
        evidence_refs=[{"type": "browser_state", "before_url": before_url, "after_url": after_url}, {"type": "screenshot", "path": screenshot_path}],
        metrics={"dom_changed": int(before_hash != after_hash), "url_changed": int(before_url != after_url), "title_changed": int(before_title != after_title)},
        repairable=True,
    ).to_dict()
    result["failed_codes"] = list(dict.fromkeys(failures or list(result.get("failed_codes") or [])))
    result["ok"] = bool(not result["failed_codes"] and result.get("status") == "success")
    return result


def _browser_recovery_hints(
    *,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    verification: dict[str, Any],
    fallback: dict[str, Any] | None = None,
    action: str = "",
    selector: str = "",
    expected_text: str = "",
) -> dict[str, Any]:
    failed_codes = [str(code).strip() for code in list(verification.get("failed_codes") or []) if str(code).strip()]
    return {
        "action": str(action or "").strip(),
        "selector": str(selector or "").strip(),
        "dom_available": bool(after_state.get("dom_available", before_state.get("dom_available", False))),
        "current_url": str(after_state.get("url") or before_state.get("url") or "").strip(),
        "current_title": str(after_state.get("title") or before_state.get("title") or "").strip(),
        "visible_text": str(after_state.get("visible_text") or "").strip(),
        "fallback_used": bool((fallback or {}).get("used")),
        "fallback_reason": str((fallback or {}).get("reason") or "").strip(),
        "expected_text": str(expected_text or "").strip(),
        "failed_codes": failed_codes,
    }


async def _browser_screen_fallback(
    *,
    action: str,
    url: str,
    selector: str,
    text: str,
    screen_instruction: str,
    reason: str,
    screen_operator_runner: ScreenOperatorRunner | None,
    services: BrowserRuntimeServices | None = None,
) -> dict[str, Any]:
    if screen_operator_runner is None:
        return {
            "success": False,
            "status": "failed",
            "error": reason.lower(),
            "error_code": reason,
            "message": f"Browser DOM unavailable and no screen operator fallback configured ({reason}).",
            "fallback": {"used": False, "reason": reason},
        }
    instruction = str(screen_instruction or "").strip()
    if not instruction:
        if action == "open" and url:
            instruction = f"Tarayicida {url} adresini ac"
        elif action == "click" and selector:
            instruction = f"Tarayicida gerekli tarayici chrome hedefini ac ve {selector} ile ilgili kontrolu yap"
        elif action == "type" and text:
            instruction = f'Tarayicidaki alana "{text}" yaz'
        else:
            instruction = "Tarayici uzerindeki dogrulanamayan yuzeyi kontrol et"
    screen_result = await screen_operator_runner(instruction=instruction, mode="control")
    goal_achieved = bool(screen_result.get("goal_achieved"))
    fallback_ok = bool(screen_result.get("success")) and (goal_achieved or str(screen_result.get("status") or "").strip().lower() == "success")
    browser_state: dict[str, Any] = {}
    if services is not None:
        try:
            browser_state = await services.get_state()
        except Exception:
            browser_state = {}
    payload = {
        "success": fallback_ok,
        "status": "success" if fallback_ok else "failed",
        "goal_achieved": goal_achieved,
        "message": str(screen_result.get("message") or "").strip(),
        "summary": str(screen_result.get("summary") or screen_result.get("message") or "").strip(),
        "browser_state": browser_state if isinstance(browser_state, dict) else {},
        "fallback": {"used": True, "reason": reason, "mode": "screen_operator"},
        "artifacts": list(screen_result.get("artifacts") or []),
        "screenshots": list(screen_result.get("screenshots") or []),
        "action_logs": list(screen_result.get("action_logs") or []),
        "verifier_outcomes": list(screen_result.get("verifier_outcomes") or []),
        "task_state": dict(screen_result.get("task_state") or {}),
        "ui_state": dict(screen_result.get("ui_state") or {}),
    }
    if not fallback_ok:
        failed_codes: list[str] = []
        for item in list(payload.get("verifier_outcomes") or []):
            if not isinstance(item, dict):
                continue
            for code in list(item.get("failed_codes") or []):
                normalized = str(code or "").strip()
                if normalized and normalized not in failed_codes:
                    failed_codes.append(normalized)
        if not failed_codes:
            failed_codes = [reason]
        payload["error"] = str(screen_result.get("error") or reason.lower())
        payload["error_code"] = failed_codes[0]
        payload["verifier_outcomes"] = list(payload.get("verifier_outcomes") or []) + [{"ok": False, "failed_codes": failed_codes}]
    payload["recovery_hints"] = _browser_recovery_hints(
        before_state={},
        after_state=browser_state if isinstance(browser_state, dict) else {},
        verification={"failed_codes": list((payload.get("verifier_outcomes") or [{}])[-1].get("failed_codes") or ([] if fallback_ok else [reason]))},
        fallback=payload.get("fallback") if isinstance(payload.get("fallback"), dict) else {},
        action=action,
        selector=selector,
        expected_text=text,
    )
    return payload


async def run_browser_runtime(
    *,
    action: str,
    url: str = "",
    selector: str = "",
    text: str = "",
    headless: bool = True,
    timeout_ms: int = 10000,
    screenshot: bool = True,
    expected_text: str = "",
    expected_url_contains: str = "",
    expected_title_contains: str = "",
    native_dialog_expected: bool = False,
    uncontrolled_chrome_expected: bool = False,
    screen_instruction: str = "",
    services: BrowserRuntimeServices | None = None,
    screen_operator_runner: ScreenOperatorRunner | None = None,
    table_selector: str = "table",
    pattern: str = "",
) -> dict[str, Any]:
    runtime_services = services or default_browser_runtime_services()
    normalized_action = str(action or "").strip().lower()
    root = _artifact_root()
    action_logs: list[dict[str, Any]] = []

    if native_dialog_expected:
        return await _browser_screen_fallback(
            action=normalized_action,
            url=url,
            selector=selector,
            text=text,
            screen_instruction=screen_instruction,
            reason=NATIVE_DIALOG_REQUIRED,
            screen_operator_runner=screen_operator_runner,
            services=runtime_services,
        )
    if uncontrolled_chrome_expected:
        return await _browser_screen_fallback(
            action=normalized_action,
            url=url,
            selector=selector,
            text=text,
            screen_instruction=screen_instruction,
            reason=UNCONTROLLED_BROWSER_CHROME,
            screen_operator_runner=screen_operator_runner,
            services=runtime_services,
        )

    if normalized_action == "close":
        close_result = await runtime_services.close()
        return {
            "success": bool(close_result.get("success")),
            "status": "success" if close_result.get("success") else "failed",
            "message": "Browser closed." if close_result.get("success") else str(close_result.get("error") or ""),
            "action_logs": [],
            "artifacts": [],
            "screenshots": [],
            "verifier_outcomes": [],
            "recovery_hints": _browser_recovery_hints(before_state={}, after_state={}, verification={"failed_codes": []}, action=normalized_action),
        }
    if normalized_action == "status":
        state = await runtime_services.get_state()
        if not state.get("success"):
            state = {"url": None, "title": None, "session_id": None, "headless": bool(headless), "dom_available": False}
        return {
            "success": True,
            "status": "success",
            "message": str(state.get("title") or state.get("url") or ""),
            "browser_state": state,
            "action_logs": [],
            "artifacts": [],
            "screenshots": [],
            "verifier_outcomes": [],
            "recovery_hints": _browser_recovery_hints(before_state={}, after_state=state if isinstance(state, dict) else {}, verification={"failed_codes": []}, action=normalized_action),
        }

    session = await runtime_services.ensure_session(headless=headless)
    if not session.get("success"):
        return await _browser_screen_fallback(
            action=normalized_action,
            url=url,
            selector=selector,
            text=text,
            screen_instruction=screen_instruction,
            reason=str(session.get("error_code") or DOM_UNAVAILABLE),
            screen_operator_runner=screen_operator_runner,
            services=runtime_services,
        )

    before_state = await runtime_services.get_state()
    if not before_state.get("success"):
        before_state = {"success": True, "dom_available": True, "url": "", "title": "", "visible_text": "", "dom_hash": ""}

    action_result: dict[str, Any]
    extracted_text = ""
    typed_value = ""
    if normalized_action == "open":
        action_result = await runtime_services.goto(url=_normalize_url(url), timeout_ms=timeout_ms)
    elif normalized_action == "click":
        action_result = await runtime_services.click(selector=selector, timeout_ms=timeout_ms)
    elif normalized_action == "type":
        action_result = await runtime_services.fill(selector=selector, text=text, timeout_ms=timeout_ms)
        value_result = await runtime_services.get_value(selector=selector)
        typed_value = str(value_result.get("value") or "")
    elif normalized_action == "submit":
        action_result = await runtime_services.press(selector=selector or None, key="Enter", timeout_ms=timeout_ms)
    elif normalized_action == "extract":
        action_result = await runtime_services.get_text(selector=selector or None)
        extracted_text = str(action_result.get("text") or "")
    elif normalized_action == "screenshot":
        action_result = {"success": True}
    elif normalized_action == "wait":
        action_result = await runtime_services.wait_for(selector=selector, timeout_ms=timeout_ms, state="visible")
    elif normalized_action == "scroll":
        action_result = await runtime_services.scroll(direction=selector or "down", amount=int(text or 500))
    elif normalized_action == "links":
        action_result = await runtime_services.query_links(pattern=pattern or None)
    elif normalized_action == "table":
        action_result = await runtime_services.query_table(selector=table_selector)
    else:
        return {
            "success": False,
            "status": "failed",
            "error": "unsupported_browser_action",
            "error_code": "INTENT_PARAM_MISSING",
            "message": f"Unsupported browser action: {normalized_action}",
            "artifacts": [],
            "screenshots": [],
            "action_logs": [],
            "verifier_outcomes": [],
        }

    action_logs.append({"step": 1, "action": normalized_action, "params": {"url": url, "selector": selector, "text": text}, "result": dict(action_result)})
    if not action_result.get("success"):
        failure_code = str(action_result.get("error_code") or DOM_UNAVAILABLE)
        payload = {
            "success": False,
            "status": "failed",
            "error": str(action_result.get("error") or "browser_action_failed"),
            "error_code": failure_code,
            "message": str(action_result.get("error") or "browser_action_failed"),
            "browser_state": before_state,
            "artifacts": [],
            "screenshots": [],
            "action_logs": action_logs,
            "verifier_outcomes": [{"ok": False, "failed_codes": [failure_code]}],
        }
        payload["recovery_hints"] = _browser_recovery_hints(
            before_state=before_state if isinstance(before_state, dict) else {},
            after_state=before_state if isinstance(before_state, dict) else {},
            verification={"failed_codes": [failure_code]},
            action=normalized_action,
            selector=selector,
            expected_text=expected_text,
        )
        return payload

    dom_snapshot = await runtime_services.get_dom_snapshot()
    after_state = await runtime_services.get_state()
    screenshot_path = ""
    if screenshot:
        screenshot_result = await runtime_services.screenshot(path=str(root / "page.png"))
        screenshot_path = str(screenshot_result.get("path") or "").strip() if screenshot_result.get("success") else ""
    verification = _verify_browser_result(
        action=normalized_action,
        before_state=before_state if isinstance(before_state, dict) else {},
        after_state=after_state if isinstance(after_state, dict) else {},
        action_result=action_result,
        extracted_text=extracted_text,
        typed_value=typed_value,
        expected_text=expected_text,
        expected_url=expected_url_contains,
        expected_title=expected_title_contains,
        screenshot_path=screenshot_path,
    )
    artifacts = _materialize_artifacts(
        root=root,
        dom_snapshot=dom_snapshot if isinstance(dom_snapshot, dict) else {},
        screenshot_path=screenshot_path,
        action_logs=action_logs,
        verification=verification,
    )

    message = str(after_state.get("title") or after_state.get("url") or extracted_text or action_result.get("message") or normalized_action).strip()
    payload = {
        "success": bool(verification.get("ok")),
        "status": "success" if verification.get("ok") else "failed",
        "message": message,
        "summary": message,
        "url": str(after_state.get("url") or action_result.get("url") or ""),
        "title": str(after_state.get("title") or action_result.get("title") or ""),
        "browser_state": after_state,
        "dom_snapshot": dom_snapshot,
        "extracted_text": extracted_text,
        "links": list(action_result.get("links") or []),
        "table": {"headers": list(action_result.get("headers") or []), "rows": list(action_result.get("rows") or [])} if normalized_action == "table" else {},
        "artifacts": artifacts,
        "screenshots": [screenshot_path] if screenshot_path else [],
        "action_logs": action_logs,
        "action_result": dict(action_result),
        "verifier_outcomes": [verification],
        "fallback": {"used": False},
        "playwright_available": bool(PLAYWRIGHT_AVAILABLE),
    }
    payload["recovery_hints"] = _browser_recovery_hints(
        before_state=before_state if isinstance(before_state, dict) else {},
        after_state=after_state if isinstance(after_state, dict) else {},
        verification=verification,
        fallback=payload.get("fallback") if isinstance(payload.get("fallback"), dict) else {},
        action=normalized_action,
        selector=selector,
        expected_text=expected_text,
    )
    if not payload["success"]:
        failed_codes = list(verification.get("failed_codes") or [FailureCode.NO_VISUAL_CHANGE.value])
        payload["error"] = failed_codes[0].lower()
        payload["error_code"] = failed_codes[0]
    return payload


__all__ = ["run_browser_runtime"]
