from __future__ import annotations

import inspect
import sys
from typing import Any, Awaitable, Callable

import click

from .matrix import ApprovalLevel, ApprovalMatrix, get_approval_matrix


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _resolve_callback(callback: Callable[..., Any] | None, *args: Any, **kwargs: Any) -> bool | None:
    if callback is None:
        return None
    result = await _maybe_await(callback(*args, **kwargs))
    if result is None:
        return None
    return bool(result)


def _interactive_ok(context: dict[str, Any]) -> bool:
    if bool(context.get("interactive", False)):
        return True
    stdin = getattr(sys, "stdin", None)
    stdout = getattr(sys, "stdout", None)
    return bool(stdin and getattr(stdin, "isatty", lambda: False)() and stdout and getattr(stdout, "isatty", lambda: False)())


def _confirm(prompt: str, context: dict[str, Any]) -> bool:
    callback = context.get("confirm_callback")
    if callable(callback):
        try:
            return bool(callback(prompt=prompt, context=context))
        except TypeError:
            return bool(callback(prompt, context))
    if not _interactive_ok(context):
        return False
    try:
        return bool(click.confirm(prompt, default=False))
    except Exception:
        return False


def _screen_confirm(matrix: ApprovalMatrix, action: dict[str, Any], context: dict[str, Any]) -> bool:
    callback = context.get("screen_confirm_callback")
    if callable(callback):
        try:
            return bool(callback(matrix=matrix, action=action, context=context))
        except TypeError:
            return bool(callback(matrix, action, context))
    screenshot = str(context.get("screenshot_path") or context.get("screen_path") or "").strip()
    prompt = f"Screen onayi gerekiyor: {matrix.skill_name or action.get('type') or 'action'}"
    if screenshot:
        prompt = f"{prompt} [{screenshot}]"
    return _confirm(prompt, context)


async def _two_fa_confirm(matrix: ApprovalMatrix, action: dict[str, Any], context: dict[str, Any]) -> bool:
    callback = context.get("two_fa_callback")
    if callable(callback):
        return bool(await _resolve_callback(callback, matrix=matrix, action=action, context=context))
    expected = str(
        context.get("two_fa_code")
        or context.get("expected_two_fa_code")
        or context.get("two_fa_expected")
        or ""
    ).strip()
    if expected and _interactive_ok(context):
        try:
            code = click.prompt("2FA kodu", hide_input=True)
            return str(code or "").strip() == expected
        except Exception:
            return False
    return bool(context.get("two_fa_verified", False))


def _manual_confirm(matrix: ApprovalMatrix, action: dict[str, Any], context: dict[str, Any]) -> bool:
    callback = context.get("manual_callback")
    if callable(callback):
        try:
            return bool(callback(matrix=matrix, action=action, context=context))
        except TypeError:
            return bool(callback(matrix, action, context))
    prompt = f"Manuel onay gerekiyor: {matrix.skill_name or action.get('type') or 'action'}"
    return _confirm(prompt, context)


async def check_approval(skill_name: str, action: dict[str, Any], user_context: dict[str, Any] | None = None) -> bool:
    context = dict(user_context or {})
    if bool(context.get("approval_override", False)):
        return True

    matrix = get_approval_matrix(skill_name, action)
    level = matrix.required_level
    if level <= ApprovalLevel.NONE:
        return True

    if level >= ApprovalLevel.CONFIRM and not _confirm(f"⚠️  {str(action.get('description') or action.get('type') or skill_name or 'action')} onaylıyor musun?", context):
        return False

    if level >= ApprovalLevel.SCREEN and not _screen_confirm(matrix, action, context):
        return False

    if level >= ApprovalLevel.TWO_FA and not await _two_fa_confirm(matrix, action, context):
        return False

    if level >= ApprovalLevel.MANUAL and not _manual_confirm(matrix, action, context):
        return False

    return True

