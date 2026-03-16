from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from core.confidence import coerce_confidence
from core.contracts.failure_taxonomy import FailureCode
from core.contracts.verification_result import VerificationCheck, VerificationResult
from core.storage_paths import resolve_elyan_data_dir
from core.text_artifacts import preferred_text_path

from .services import ScreenOperatorServices, default_screen_operator_services


_SOURCE_PRIORITY = {
    "accessibility": 0,
    "window_metadata": 0,
    "vision": 1,
    "ocr": 2,
    "cache": 3,
    "prior_ui_state": 4,
}
_CLICKABLE_ROLES = {"button", "link", "menu_item", "tab", "checkbox", "radio", "text_field", "search_field", "input", "group"}
_TEXT_FIELD_ROLES = {"text_field", "search_field", "input", "combo_box", "editable_text"}
_BUTTON_LIKE_ROLES = {"button", "link", "menu_item", "tab", "checkbox", "radio"}
_SUBMIT_LIKE_ROLES = {"button", "link", "menu_item", "tab"}
_GENERIC_TARGET_LABELS = {"search", "continue", "submit", "next", "open", "save"}
_ROLE_HINT_PATTERNS: list[tuple[set[str], tuple[str, ...]]] = [
    (_TEXT_FIELD_ROLES, ("search field", "search box", "textbox", "text box", "input", "field", "kutu", "kutusu", "alan", "alani", "alanı")),
    ({"button"}, ("button", "buton", "butonu", "butonuna")),
    ({"link"}, ("link", "baglanti", "bağlantı")),
    ({"tab"}, ("tab", "sekme")),
]


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _coerce_confidence(value: Any, default: float = 0.0) -> float:
    return coerce_confidence(value, default)


def _extract_quoted_text(text: str) -> str:
    match = re.search(r"['\"]([^'\"]{1,280})['\"]", str(text or ""))
    return str(match.group(1) or "").strip() if match else ""


def _tokenize(value: str) -> list[str]:
    return [item for item in re.findall(r"[a-z0-9]+", _normalize_text(value)) if item]


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coerce_bounds(item: dict[str, Any]) -> dict[str, int]:
    bounds = {}
    for key in ("x", "y", "width", "height"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            bounds[key] = int(value)
    return bounds


def _center_from_bounds(item: dict[str, Any]) -> tuple[int, int] | None:
    bounds = _coerce_bounds(item)
    if not {"x", "y"}.issubset(bounds):
        return None
    if {"width", "height"}.issubset(bounds):
        return (int(bounds["x"] + bounds["width"] / 2), int(bounds["y"] + bounds["height"] / 2))
    return (int(bounds["x"]), int(bounds["y"]))


def _dedupe_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int, int]] = set()
    deduped: list[dict[str, Any]] = []
    for item in elements:
        label = _normalize_text(item.get("label") or item.get("text") or "")
        role = _normalize_text(item.get("role") or item.get("kind") or "unknown")
        center = _center_from_bounds(item) or (-1, -1)
        key = (label, role, int(center[0]), int(center[1]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _annotate_element_context(item: dict[str, Any], *, frontmost_app: str, window_title: str) -> dict[str, Any]:
    row = dict(item)
    if frontmost_app and not str(row.get("frontmost_app") or "").strip():
        row["frontmost_app"] = frontmost_app
    if window_title and not str(row.get("window_title") or "").strip():
        row["window_title"] = window_title
    return row


def _infer_role_hints(text: str) -> set[str]:
    low = _normalize_text(text)
    hints: set[str] = set()
    for roles, patterns in _ROLE_HINT_PATTERNS:
        if any(pattern in low for pattern in patterns):
            hints.update(roles)
    return hints


def _preferred_roles_for_intent(intent: dict[str, Any], *, phase: str) -> set[str]:
    role_hints = {str(item).strip().lower() for item in list(intent.get("role_hints") or []) if str(item).strip()}
    if phase == "type":
        return set(_TEXT_FIELD_ROLES)
    if role_hints & _TEXT_FIELD_ROLES:
        return set(_TEXT_FIELD_ROLES)
    if role_hints & {"link"}:
        return {"link"}
    if role_hints & {"tab"}:
        return {"tab"}
    if role_hints & {"button"}:
        return set(_BUTTON_LIKE_ROLES)
    if phase == "submit":
        return set(_SUBMIT_LIKE_ROLES)
    return set(_BUTTON_LIKE_ROLES)


def _is_generic_label(value: str) -> bool:
    return _normalize_text(value) in _GENERIC_TARGET_LABELS


def _cache_meta(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("_cache_meta") if isinstance(item.get("_cache_meta"), dict) else {}
    return dict(payload)


def _context_key(label: str, *, frontmost_app: str, window_title: str) -> str:
    parts = [label, _normalize_text(frontmost_app or ""), _normalize_text(window_title or "")]
    return "@@".join(parts)


def _build_summary(metadata: dict[str, Any], accessibility: dict[str, Any], ocr: dict[str, Any], vision: dict[str, Any]) -> str:
    parts: list[str] = []
    frontmost = str(metadata.get("frontmost_app") or accessibility.get("frontmost_app") or "").strip()
    window_title = str(metadata.get("window_title") or accessibility.get("window_title") or "").strip()
    if frontmost:
        parts.append(f"Frontmost app: {frontmost}.")
    if window_title:
        parts.append(f"Window: {window_title}.")
    vision_summary = str(vision.get("summary") or "").strip()
    if vision_summary:
        parts.append(vision_summary)
    ocr_text = str(ocr.get("text") or "").strip()
    if ocr_text:
        parts.append(f"OCR: {ocr_text[:180]}")
    return " ".join(part for part in parts if part).strip()


def _build_ui_state(
    *,
    metadata: dict[str, Any],
    accessibility: dict[str, Any],
    ocr: dict[str, Any],
    vision: dict[str, Any],
    prior_ui_state: dict[str, Any],
    last_target_cache: dict[str, dict[str, Any]],
    screenshot_path: str,
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    prior_window = prior_ui_state.get("active_window") if isinstance(prior_ui_state.get("active_window"), dict) else {}
    frontmost_app = str(metadata.get("frontmost_app") or accessibility.get("frontmost_app") or prior_ui_state.get("frontmost_app") or "").strip()
    window_title = str(metadata.get("window_title") or accessibility.get("window_title") or prior_window.get("title") or "").strip()
    if frontmost_app:
        elements.append({"label": frontmost_app, "role": "frontmost_app", "source": "window_metadata", "confidence": 0.99})
    if window_title:
        elements.append({"label": window_title, "role": "window_title", "source": "window_metadata", "confidence": 0.95})
    for item in list(accessibility.get("elements") or []):
        if isinstance(item, dict):
            row = _annotate_element_context(item, frontmost_app=frontmost_app, window_title=window_title)
            row.setdefault("source", "accessibility")
            row.setdefault("confidence", 0.92)
            elements.append(row)
    for item in list(vision.get("elements") or []):
        if isinstance(item, dict):
            row = _annotate_element_context(item, frontmost_app=frontmost_app, window_title=window_title)
            row.setdefault("source", "vision")
            row.setdefault("confidence", 0.62)
            elements.append(row)
    for item in list(ocr.get("lines") or []):
        if isinstance(item, dict):
            row = {
                "label": str(item.get("text") or "").strip(),
                "role": "ocr_text",
                "source": "ocr",
                "confidence": _coerce_confidence(item.get("confidence"), 0.5),
                "frontmost_app": frontmost_app,
                "window_title": window_title,
            }
            row.update(_coerce_bounds(item))
            if row["label"]:
                elements.append(row)
    for cached in list(last_target_cache.values()):
        if isinstance(cached, dict):
            row = _annotate_element_context(cached, frontmost_app=frontmost_app, window_title=window_title)
            row["source"] = "cache"
            row.setdefault("confidence", 0.35)
            elements.append(row)
    for item in list(prior_ui_state.get("elements") or []):
        if isinstance(item, dict):
            row = _annotate_element_context(item, frontmost_app=frontmost_app, window_title=window_title)
            row["source"] = "prior_ui_state"
            row.setdefault("confidence", 0.4)
            elements.append(row)

    elements = _dedupe_elements(elements)
    clickable_targets = [item for item in elements if _normalize_text(item.get("role")) in _CLICKABLE_ROLES and _center_from_bounds(item)]
    text_fields = [item for item in elements if _normalize_text(item.get("role")) in _TEXT_FIELD_ROLES]
    source_counts: dict[str, int] = {}
    for item in elements:
        source = str(item.get("source") or "unknown")
        source_counts[source] = int(source_counts.get(source, 0)) + 1
    confidence_values = [_coerce_confidence(item.get("confidence"), 0.0) for item in elements]
    return {
        "frontmost_app": frontmost_app,
        "active_window": {"title": window_title, "bounds": dict(metadata.get("bounds") or {})},
        "screenshot_path": screenshot_path,
        "elements": elements,
        "clickable_targets": clickable_targets,
        "text_fields": text_fields,
        "summary": _build_summary(metadata, accessibility, ocr, vision),
        "fallback_order": ["accessibility_and_window_metadata", "vision_detection", "ocr", "last_known_ui_target_cache"],
        "source_counts": source_counts,
        "confidence": round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0,
    }


def _parse_instruction(goal: str, *, mode: str) -> dict[str, Any]:
    low = _normalize_text(goal)
    typed_text = _extract_quoted_text(goal)
    tokens = _tokenize(goal)
    typed_tokens = set(_tokenize(typed_text))
    wants_click = bool(re.search(r"\b(click|tikla|tıkla|select|sec|seç|open)\b", low))
    wants_type = bool(typed_text) or bool(re.search(r"\b(type|write|yaz|fill|gir)\b", low))
    wants_submit = bool(typed_text) and bool(re.search(r"\b(enter|submit|gonder|gönder)\b", low))
    noise_tokens = {
        "click", "tikla", "tıkla", "select", "sec", "seç", "open", "type", "write", "yaz", "fill", "gir",
        "enter", "submit", "gonder", "gönder", "the", "button", "buton", "butonu", "butonuna",
        "field", "textbox", "input", "box", "kutusu", "kutusuna", "alanina", "alanına", "alani", "alanı",
        "icine", "içine", "icine", "into", "on", "to", "and", "ve", "sonra",
    }
    query_tokens: list[str] = []
    for token in tokens:
        if token in noise_tokens or token in typed_tokens:
            continue
        if token not in query_tokens:
            query_tokens.append(token)
    query_low = " ".join(query_tokens).strip()
    if mode == "inspect":
        wants_click = False
        wants_type = False
        wants_submit = False
    role_hints = _infer_role_hints(low)
    return {
        "goal": str(goal or "").strip(),
        "mode": mode,
        "typed_text": typed_text,
        "target_query": query_low,
        "wants_click": wants_click,
        "wants_type": wants_type,
        "wants_submit": wants_submit,
        "role_hints": sorted(role_hints),
    }


def _score_target(
    query: str,
    item: dict[str, Any],
    *,
    preferred_roles: set[str],
    role_hints: set[str],
    action_kind: str,
    ui_state: dict[str, Any],
    require_coords: bool,
) -> tuple[float, dict[str, Any]]:
    label = str(item.get("label") or item.get("text") or "").strip()
    role = _normalize_text(item.get("role") or item.get("kind") or "unknown")
    source = _normalize_text(item.get("source") or "unknown")
    confidence = _coerce_confidence(item.get("confidence"), 0.0)
    current_app = _normalize_text(ui_state.get("frontmost_app") or "")
    current_window = _normalize_text(((ui_state.get("active_window") if isinstance(ui_state.get("active_window"), dict) else {}) or {}).get("title") or "")
    item_app = _normalize_text(item.get("frontmost_app") or "")
    item_window = _normalize_text(item.get("window_title") or "")
    score = 0.0
    reasons: list[dict[str, Any]] = []

    def add(points: float, code: str, details: dict[str, Any] | None = None) -> None:
        nonlocal score
        score += float(points)
        reasons.append({"code": code, "points": round(float(points), 3), "details": dict(details or {})})

    add(confidence * 100.0, "confidence", {"confidence": confidence})
    if source in _SOURCE_PRIORITY:
        add(max(0.0, 18.0 - (_SOURCE_PRIORITY[source] * 4.0)), "source_priority", {"source": source})

    center = _center_from_bounds(item)
    if center is not None:
        add(18.0 if require_coords or action_kind in {"click", "submit", "type_focus"} else 8.0, "bounded_target")
    elif require_coords:
        add(-80.0, "coordinates_required")

    if role in role_hints:
        add(46.0, "role_hint_match", {"role": role})
    elif role in preferred_roles:
        add(32.0, "preferred_role_match", {"role": role})
    elif action_kind in {"click", "submit"} and role in _TEXT_FIELD_ROLES and not (role_hints & _TEXT_FIELD_ROLES):
        add(-36.0, "click_avoids_text_field", {"role": role})
    elif action_kind in {"type", "type_focus"} and role not in _TEXT_FIELD_ROLES:
        add(-42.0, "typing_prefers_text_field", {"role": role})

    if action_kind in {"click", "submit"} and role in _BUTTON_LIKE_ROLES:
        add(12.0, "button_like_role", {"role": role})
    if action_kind in {"type", "type_focus"} and role in _TEXT_FIELD_ROLES:
        add(20.0, "text_field_role", {"role": role})

    label_low = _normalize_text(label)
    query_low = _normalize_text(query)
    if query_low:
        if label_low == query_low:
            add(96.0 if _is_generic_label(query_low) else 124.0, "label_exact_match")
        elif query_low in label_low:
            add(74.0 if _is_generic_label(query_low) else 92.0, "label_contains_query")
        else:
            q_tokens = set(_tokenize(query_low))
            l_tokens = set(_tokenize(label_low))
            overlap = len(q_tokens & l_tokens)
            if overlap:
                add(float(overlap * 28), "token_overlap", {"overlap": overlap})
            else:
                add(-14.0, "label_mismatch")
        if _is_generic_label(label_low) and not (role in preferred_roles or role in role_hints):
            add(-18.0, "generic_label_penalty", {"label": label_low})

    if item_app and current_app:
        add(16.0 if item_app == current_app else (-40.0 if source in {"cache", "prior_ui_state"} else -24.0), "frontmost_app_context", {"item_app": item_app, "current_app": current_app})
    if item_window and current_window:
        add(18.0 if item_window == current_window else (-48.0 if source in {"cache", "prior_ui_state"} else -28.0), "active_window_context", {"item_window": item_window, "current_window": current_window})

    cache_meta = _cache_meta(item)
    if cache_meta:
        if bool(cache_meta.get("last_verified_success")):
            add(34.0, "recently_verified_success")
        verified_count = max(0, int(cache_meta.get("verified_success_count") or 0))
        if verified_count:
            add(min(float(verified_count * 6), 20.0), "verified_success_count", {"count": verified_count})
        if str(cache_meta.get("last_action_kind") or "").strip().lower() == action_kind:
            add(14.0, "action_kind_history_match", {"action_kind": action_kind})
        recency_anchor = float(cache_meta.get("last_verified_success_at") or cache_meta.get("last_seen_at") or 0.0)
        if recency_anchor > 0:
            age_s = max(0.0, time.time() - recency_anchor)
            recency_bonus = max(0.0, 14.0 - min(age_s, 420.0) / 35.0)
            if recency_bonus > 0:
                add(recency_bonus, "recency_bonus", {"age_s": round(age_s, 3)})
        cached_app = _normalize_text(cache_meta.get("frontmost_app") or "")
        cached_window = _normalize_text(cache_meta.get("window_title") or "")
        if cached_app and current_app:
            add(12.0 if cached_app == current_app else -20.0, "cached_app_context", {"cached_app": cached_app, "current_app": current_app})
        if cached_window and current_window:
            add(12.0 if cached_window == current_window else -24.0, "cached_window_context", {"cached_window": cached_window, "current_window": current_window})

    if query_low and _is_generic_label(query_low):
        if source == "cache" and item_window and current_window and item_window != current_window:
            add(-18.0, "generic_label_stale_cache_penalty", {"item_window": item_window, "current_window": current_window})
        elif source == "prior_ui_state" and item_window and current_window and item_window == current_window:
            add(12.0, "generic_label_prior_ui_context_bonus", {"item_window": item_window, "current_window": current_window})

    trace = {
        "label": label,
        "role": role,
        "source": source,
        "score": round(score, 3),
        "has_coords": bool(center),
        "frontmost_app": item_app,
        "window_title": item_window,
        "reasons": reasons,
    }
    return score, trace


def _choose_target(
    ui_state: dict[str, Any],
    *,
    query: str,
    preferred_roles: set[str],
    role_hints: set[str],
    action_kind: str,
    exclude_labels: set[str] | None = None,
    require_coords: bool = False,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
    exclude = { _normalize_text(item) for item in list(exclude_labels or set()) if _normalize_text(item) }
    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    pool = list(ui_state.get("elements") or [])
    if action_kind in {"type", "type_focus"}:
        pool = list(ui_state.get("text_fields") or pool)
    elif not query:
        pool = list(ui_state.get("clickable_targets") or pool)
    for item in pool:
        if not isinstance(item, dict):
            continue
        if require_coords and _center_from_bounds(item) is None:
            continue
        label = _normalize_text(item.get("label") or item.get("text") or "")
        if label and label in exclude:
            continue
        score, trace = _score_target(
            query,
            item,
            preferred_roles=preferred_roles,
            role_hints=role_hints,
            action_kind=action_kind,
            ui_state=ui_state,
            require_coords=require_coords,
        )
        if not query and action_kind in {"type", "type_focus"} and _normalize_text(item.get("role")) in preferred_roles:
            score += 40.0
            trace = dict(trace)
            trace["score"] = round(score, 3)
            trace["reasons"] = list(trace.get("reasons") or []) + [{"code": "implicit_text_field_preference", "points": 40.0, "details": {}}]
        if score <= 0:
            continue
        candidates.append((score, item, trace))
    candidates.sort(
        key=lambda row: (
            -row[0],
            _SOURCE_PRIORITY.get(_normalize_text(row[1].get("source")), 99),
            -_coerce_confidence(row[1].get("confidence"), 0.0),
        )
    )
    ordered = [item for _score, item, _trace in candidates]
    traces = [trace for _score, _item, trace in candidates]
    decision_trace = {
        "query": str(query or "").strip(),
        "action_kind": action_kind,
        "preferred_roles": sorted(preferred_roles),
        "role_hints": sorted(role_hints),
        "require_coords": bool(require_coords),
        "current_context": {
            "frontmost_app": str(ui_state.get("frontmost_app") or "").strip(),
            "active_window": str(((ui_state.get("active_window") if isinstance(ui_state.get("active_window"), dict) else {}) or {}).get("title") or "").strip(),
        },
        "chosen": traces[0] if traces else None,
        "candidates": traces[:6],
        "rejected": traces[1:6],
    }
    return (ordered[0] if ordered else None, ordered[1:], decision_trace)


def _should_focus_before_type(ui_state: dict[str, Any], focus_target: dict[str, Any]) -> bool:
    if not isinstance(focus_target, dict):
        return False
    label = _normalize_text(focus_target.get("label") or focus_target.get("text") or "")
    text_fields = [item for item in list(ui_state.get("text_fields") or []) if isinstance(item, dict)]
    if len(text_fields) > 1:
        return True
    if not label:
        return False
    for item in list(ui_state.get("elements") or []):
        if not isinstance(item, dict) or item is focus_target:
            continue
        item_label = _normalize_text(item.get("label") or item.get("text") or "")
        item_role = _normalize_text(item.get("role") or item.get("kind") or "")
        if item_label == label and item_role not in _TEXT_FIELD_ROLES:
            return True
    return False


def _build_action_queue(intent: dict[str, Any], ui_state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    target_query = str(intent.get("target_query") or "").strip()
    typed_text = str(intent.get("typed_text") or "").strip()
    role_hints = {str(item).strip().lower() for item in list(intent.get("role_hints") or []) if str(item).strip()}
    if bool(intent.get("wants_click")):
        click_kind = "submit" if bool(intent.get("wants_submit")) and not typed_text else "click"
        preferred = _preferred_roles_for_intent(intent, phase="submit" if click_kind == "submit" else "click")
        target, alternates, trace = _choose_target(
            ui_state,
            query=target_query,
            preferred_roles=preferred,
            role_hints=role_hints,
            action_kind=click_kind,
            require_coords=True,
        )
        if target is None and target_query:
            errors.append(FailureCode.UI_TARGET_NOT_FOUND.value)
        elif target is not None:
            action = {"kind": "click", "target": target, "alternates": alternates, "attempts": 0, "decision_trace": trace}
            center = _center_from_bounds(target)
            if center:
                action["x"] = center[0]
                action["y"] = center[1]
            actions.append(action)
    if typed_text:
        focus_target = None
        focus_trace: dict[str, Any] = {}
        if target_query or role_hints:
            focus_target, focus_alternates, focus_trace = _choose_target(
                ui_state,
                query=target_query,
                preferred_roles=_preferred_roles_for_intent(intent, phase="type"),
                role_hints=role_hints | _TEXT_FIELD_ROLES,
                action_kind="type_focus",
                require_coords=True,
            )
            if focus_target is not None:
                center = _center_from_bounds(focus_target)
                duplicate_click = False
                if actions and str(actions[-1].get("kind") or "") == "click":
                    last_target = actions[-1].get("target") if isinstance(actions[-1].get("target"), dict) else {}
                    duplicate_click = _normalize_text(last_target.get("label") or "") == _normalize_text(focus_target.get("label") or "")
                if center and not duplicate_click and _should_focus_before_type(ui_state, focus_target):
                    actions.append(
                        {
                            "kind": "click",
                            "target": focus_target,
                            "alternates": focus_alternates,
                            "attempts": 0,
                            "x": center[0],
                            "y": center[1],
                            "focus_before_type": True,
                            "decision_trace": focus_trace,
                        }
                    )
        actions.append(
            {
                "kind": "type",
                "text": typed_text,
                "press_enter": bool(intent.get("wants_submit")),
                "attempts": 0,
                "target": focus_target or {},
                "decision_trace": focus_trace,
            }
        )
    elif bool(intent.get("wants_submit")):
        if target_query or role_hints:
            target, alternates, trace = _choose_target(
                ui_state,
                query=target_query,
                preferred_roles=_preferred_roles_for_intent(intent, phase="submit"),
                role_hints=role_hints,
                action_kind="submit",
                require_coords=True,
            )
            if target is not None:
                center = _center_from_bounds(target)
                if center:
                    actions.append(
                        {
                            "kind": "click",
                            "target": target,
                            "alternates": alternates,
                            "attempts": 0,
                            "x": center[0],
                            "y": center[1],
                            "decision_trace": trace,
                        }
                    )
                else:
                    actions.append({"kind": "press_key", "key": "enter", "attempts": 0})
            else:
                actions.append({"kind": "press_key", "key": "enter", "attempts": 0})
        else:
            actions.append({"kind": "press_key", "key": "enter", "attempts": 0})
    if not actions and str(intent.get("mode") or "") == "inspect":
        actions.append({"kind": "noop", "reason": "inspect_mode", "attempts": 0})
    return actions, errors


async def _observe(
    *,
    goal: str,
    services: ScreenOperatorServices,
    label: str,
    last_target_cache: dict[str, dict[str, Any]],
    prior_ui_state: dict[str, Any] | None = None,
    region: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(region, dict) and {"x", "y", "width", "height"}.issubset(region):
        screenshot = await services.capture_region(
            x=int(region.get("x", 0)),
            y=int(region.get("y", 0)),
            width=int(region.get("width", 0)),
            height=int(region.get("height", 0)),
            filename=f"{label}_{int(time.time() * 1000)}.png",
        )
    else:
        screenshot = await services.take_screenshot(filename=f"{label}_{int(time.time() * 1000)}.png")
    if not screenshot.get("success"):
        return {"success": False, "error": screenshot.get("error", "screenshot_failed")}
    screenshot_path = str(screenshot.get("path") or "").strip()

    metadata_task = asyncio.create_task(services.get_window_metadata())
    accessibility_task = asyncio.create_task(services.get_accessibility_snapshot())
    ocr_task = asyncio.create_task(services.run_ocr(screenshot_path))
    vision_task = asyncio.create_task(services.run_vision(screenshot_path, goal))
    metadata, accessibility, ocr, vision = await asyncio.gather(metadata_task, accessibility_task, ocr_task, vision_task)
    ui_state = _build_ui_state(
        metadata=metadata if isinstance(metadata, dict) else {},
        accessibility=accessibility if isinstance(accessibility, dict) else {},
        ocr=ocr if isinstance(ocr, dict) else {},
        vision=vision if isinstance(vision, dict) else {},
        prior_ui_state=prior_ui_state if isinstance(prior_ui_state, dict) else {},
        last_target_cache=last_target_cache,
        screenshot_path=screenshot_path,
    )
    return {
        "success": True,
        "screenshot": dict(screenshot),
        "window_metadata": dict(metadata or {}),
        "accessibility": dict(accessibility or {}),
        "ocr": dict(ocr or {}),
        "vision": dict(vision or {}),
        "ui_state": ui_state,
        "summary": str(ui_state.get("summary") or "").strip(),
    }


async def _execute_action(services: ScreenOperatorServices, action: dict[str, Any]) -> dict[str, Any]:
    kind = str(action.get("kind") or "").strip().lower()
    if kind == "click":
        x = int(action.get("x", 0))
        y = int(action.get("y", 0))
        move_res = await services.mouse_move(x=x, y=y)
        if not move_res.get("success"):
            return {"success": False, "error": move_res.get("error", "mouse_move_failed"), "action": kind}
        click_res = await services.mouse_click(x=x, y=y, button=str(action.get("button") or "left"), double=bool(action.get("double", False)))
        click_res["action"] = kind
        return click_res
    if kind == "type":
        if bool(action.get("retry_after_focus")):
            target = action.get("target") if isinstance(action.get("target"), dict) else {}
            center = _center_from_bounds(target)
            if center is not None:
                move_res = await services.mouse_move(x=int(center[0]), y=int(center[1]))
                if not move_res.get("success"):
                    return {"success": False, "error": move_res.get("error", "mouse_move_failed"), "action": kind}
                click_res = await services.mouse_click(x=int(center[0]), y=int(center[1]), button="left", double=False)
                if not click_res.get("success"):
                    return {"success": False, "error": click_res.get("error", "mouse_click_failed"), "action": kind}
        res = await services.type_text(text=str(action.get("text") or ""), press_enter=bool(action.get("press_enter", False)))
        res["action"] = kind
        return res
    if kind == "press_key":
        res = await services.press_key(key=str(action.get("key") or ""), modifiers=list(action.get("modifiers") or []))
        res["action"] = kind
        return res
    if kind == "key_combo":
        res = await services.key_combo(combo=str(action.get("combo") or ""))
        res["action"] = kind
        return res
    if kind == "wait":
        await services.sleep(float(action.get("seconds") or 0.2))
        return {"success": True, "action": kind}
    return {"success": True, "action": "noop", "message": str(action.get("reason") or "noop")}


def _searchable_text(observation: dict[str, Any]) -> str:
    bits = [
        str(observation.get("summary") or ""),
        str(((observation.get("ocr") if isinstance(observation.get("ocr"), dict) else {}) or {}).get("text") or ""),
        str(((observation.get("vision") if isinstance(observation.get("vision"), dict) else {}) or {}).get("summary") or ""),
        json.dumps(((observation.get("ui_state") if isinstance(observation.get("ui_state"), dict) else {}) or {}).get("elements") or [], ensure_ascii=False),
    ]
    return _normalize_text(" ".join(bits))


def _verify_action(before: dict[str, Any], after: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    before_ui = before.get("ui_state") if isinstance(before.get("ui_state"), dict) else {}
    after_ui = after.get("ui_state") if isinstance(after.get("ui_state"), dict) else {}
    before_path = str(((before.get("screenshot") if isinstance(before.get("screenshot"), dict) else {}) or {}).get("path") or "").strip()
    after_path = str(((after.get("screenshot") if isinstance(after.get("screenshot"), dict) else {}) or {}).get("path") or "").strip()
    visual_change = False
    if before_path and after_path and Path(before_path).exists() and Path(after_path).exists():
        try:
            visual_change = _sha256(before_path) != _sha256(after_path)
        except Exception:
            visual_change = before_path != after_path
    window_changed = str((before_ui.get("active_window") or {}).get("title") or "") != str((after_ui.get("active_window") or {}).get("title") or "")
    app_changed = str(before_ui.get("frontmost_app") or "") != str(after_ui.get("frontmost_app") or "")
    action_kind = str(action.get("kind") or "")
    target_label = _normalize_text(((action.get("target") if isinstance(action.get("target"), dict) else {}) or {}).get("label") or "")
    after_text = _searchable_text(after)
    before_text = _searchable_text(before)
    typed_text = _normalize_text(str(action.get("text") or ""))
    target_visible_after = bool(target_label and target_label in after_text)

    checks: list[VerificationCheck] = [
        VerificationCheck(code="after_screenshot_present", passed=bool(after_path), details={"path": after_path}),
        VerificationCheck(code="ui_state_present", passed=bool(after_ui), details={"element_count": len(list(after_ui.get("elements") or []))}),
    ]
    failure_codes: list[str] = []

    if action_kind == "click":
        changed = bool(visual_change or window_changed or app_changed or not target_visible_after)
        checks.append(VerificationCheck(code="visual_change_observed", passed=changed, details={"visual_change": visual_change, "window_changed": window_changed, "app_changed": app_changed, "target_visible_after": target_visible_after}))
        if not changed:
            failure_codes.append(FailureCode.NO_VISUAL_CHANGE.value)
    elif action_kind == "type":
        typed_visible = bool(typed_text and typed_text in after_text)
        checks.append(VerificationCheck(code="typed_text_visible", passed=typed_visible, details={"typed_text": typed_text}))
        if not typed_visible and after_text == before_text:
            failure_codes.append(FailureCode.NO_VISUAL_CHANGE.value)
        elif not typed_visible:
            failure_codes.append(FailureCode.ARTIFACT_MISSING.value)
    elif action_kind == "press_key":
        changed = bool(visual_change or window_changed or app_changed or after_text != before_text)
        checks.append(VerificationCheck(code="state_transition_detected", passed=changed, details={"visual_change": visual_change, "window_changed": window_changed, "app_changed": app_changed}))
        if not changed:
            failure_codes.append(FailureCode.NO_VISUAL_CHANGE.value)

    result = VerificationResult.from_checks(
        checks,
        summary=f"screen action verification for {action_kind}",
        evidence_refs=[{"type": "screenshot", "path": before_path}, {"type": "screenshot", "path": after_path}],
        metrics={"visual_change": int(bool(visual_change)), "window_changed": int(bool(window_changed)), "app_changed": int(bool(app_changed))},
        repairable=True,
    ).to_dict()
    result["failed_codes"] = list(dict.fromkeys(failure_codes or list(result.get("failed_codes") or [])))
    result["ok"] = bool(not result["failed_codes"] and result.get("status") == "success")
    result["target_visible_after"] = target_visible_after
    return result


def _repair_action(action: dict[str, Any], verify_result: dict[str, Any]) -> dict[str, Any] | None:
    failed_codes = {str(code).strip() for code in list(verify_result.get("failed_codes") or []) if str(code).strip()}
    kind = str(action.get("kind") or "").strip().lower()
    if kind == "click" and FailureCode.NO_VISUAL_CHANGE.value in failed_codes:
        alternates = [item for item in list(action.get("alternates") or []) if isinstance(item, dict)]
        if not alternates:
            return None
        next_target = alternates[0]
        center = _center_from_bounds(next_target)
        if center is None:
            return None
        repaired = dict(action)
        repaired["target"] = next_target
        repaired["x"] = center[0]
        repaired["y"] = center[1]
        repaired["alternates"] = alternates[1:]
        repaired["attempts"] = int(action.get("attempts") or 0) + 1
        repaired["repair_reason"] = FailureCode.NO_VISUAL_CHANGE.value
        return repaired
    if kind == "type" and failed_codes & {FailureCode.NO_VISUAL_CHANGE.value, FailureCode.ARTIFACT_MISSING.value}:
        target = action.get("target") if isinstance(action.get("target"), dict) else {}
        center = _center_from_bounds(target)
        if center is None or bool(action.get("retry_after_focus")):
            return None
        repaired = dict(action)
        repaired["attempts"] = int(action.get("attempts") or 0) + 1
        repaired["retry_after_focus"] = True
        repaired["repair_reason"] = FailureCode.TEXT_NOT_VERIFIED.value
        return repaired
    return None


def _screen_recovery_hints(
    *,
    ui_state: dict[str, Any],
    action_logs: list[dict[str, Any]],
    verifier_outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_log = dict(action_logs[-1]) if action_logs else {}
    planned_action = latest_log.get("planned_action") if isinstance(latest_log.get("planned_action"), dict) else {}
    chosen_target = planned_action.get("target") if isinstance(planned_action.get("target"), dict) else {}
    alternates = [dict(item) for item in list(planned_action.get("alternates") or []) if isinstance(item, dict)]
    failed_codes: list[str] = []
    for item in list(verifier_outcomes or []):
        if isinstance(item, dict):
            for code in list(item.get("failed_codes") or []):
                normalized = str(code or "").strip()
                if normalized and normalized not in failed_codes:
                    failed_codes.append(normalized)
    return {
        "frontmost_app": str(ui_state.get("frontmost_app") or "").strip(),
        "active_window": str(((ui_state.get("active_window") if isinstance(ui_state.get("active_window"), dict) else {}) or {}).get("title") or "").strip(),
        "chosen_target": dict(chosen_target) if chosen_target else {},
        "alternate_targets": alternates[:3],
        "failed_codes": failed_codes,
    }


def _remember_target(
    cache: dict[str, dict[str, Any]],
    item: dict[str, Any],
    *,
    ui_state: dict[str, Any],
    action_kind: str = "",
    verified_success: bool = False,
) -> None:
    if not isinstance(item, dict):
        return
    label = _normalize_text(item.get("label") or item.get("text") or "")
    if not label:
        return
    center = _center_from_bounds(item)
    if center is None:
        return
    now = float(time.time())
    frontmost_app = str(item.get("frontmost_app") or ui_state.get("frontmost_app") or "").strip()
    window_title = str(item.get("window_title") or ((ui_state.get("active_window") if isinstance(ui_state.get("active_window"), dict) else {}) or {}).get("title") or "").strip()
    existing = cache.get(label) if isinstance(cache.get(label), dict) else {}
    existing_meta = _cache_meta(existing)
    row = _annotate_element_context(item, frontmost_app=frontmost_app, window_title=window_title)
    row["source"] = "cache"
    row["confidence"] = max(_coerce_confidence(row.get("confidence"), 0.0), 0.35)
    meta = {
        "seen_count": max(0, int(existing_meta.get("seen_count") or 0)) + 1,
        "last_seen_at": now,
        "last_action_kind": str(action_kind or existing_meta.get("last_action_kind") or "").strip().lower(),
        "frontmost_app": frontmost_app,
        "window_title": window_title,
        "last_verified_success": bool(existing_meta.get("last_verified_success")),
        "verified_success_count": max(0, int(existing_meta.get("verified_success_count") or 0)),
        "last_verified_success_at": float(existing_meta.get("last_verified_success_at") or 0.0),
    }
    if verified_success:
        meta["last_verified_success"] = True
        meta["verified_success_count"] = int(meta["verified_success_count"]) + 1
        meta["last_verified_success_at"] = now
        if action_kind:
            meta["last_action_kind"] = str(action_kind).strip().lower()
    row["_cache_meta"] = meta
    cache[_context_key(label, frontmost_app=frontmost_app, window_title=window_title)] = dict(row)
    if verified_success or label not in cache:
        cache[label] = dict(row)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


def _materialize_artifacts(
    *,
    before_path: str,
    after_path: str,
    ui_state: dict[str, Any],
    summary: str,
    action_logs: list[dict[str, Any]],
    target_decisions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    root = resolve_elyan_data_dir() / "screen_operator" / str(int(time.time() * 1000))
    root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    if before_path and Path(before_path).exists():
        target = root / "before.png"
        shutil.copyfile(before_path, target)
        manifest["before"] = str(target)
    if after_path and Path(after_path).exists():
        target = root / "after.png"
        shutil.copyfile(after_path, target)
        manifest["after"] = str(target)
    ui_path = root / "ui_state.json"
    summary_path = preferred_text_path(root / "screen_summary.txt")
    action_path = root / "action_log.json"
    target_path = root / "target_decisions.json"
    _write_json(ui_path, ui_state)
    _write_text(summary_path, summary)
    _write_json(action_path, action_logs)
    _write_json(target_path, target_decisions)
    manifest["ui_state"] = str(ui_path)
    manifest["summary"] = str(summary_path)
    manifest["action_log"] = str(action_path)
    manifest["target_decisions"] = str(target_path)
    artifacts = [
        {"path": path, "type": "image" if path.endswith(".png") else ("json" if path.endswith(".json") else "text")}
        for path in manifest.values()
    ]
    return artifacts, manifest


async def run_screen_operator(
    *,
    instruction: str,
    mode: str = "inspect",
    region: dict[str, Any] | None = None,
    final_screenshot: bool = True,
    max_actions: int = 4,
    max_retries_per_action: int = 2,
    services: ScreenOperatorServices | None = None,
    task_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_services = services or default_screen_operator_services()
    started_at = time.monotonic()
    normalized_mode = str(mode or "inspect").strip().lower() or "inspect"
    if normalized_mode not in {"inspect", "control", "inspect_and_control"}:
        normalized_mode = "inspect"
    goal = str(instruction or "").strip()
    cached_state = task_state if isinstance(task_state, dict) else {}
    cache: dict[str, dict[str, Any]] = dict(cached_state.get("last_target_cache") or {})
    prior_ui_state = cached_state.get("last_ui_state") if isinstance(cached_state.get("last_ui_state"), dict) else {}
    if not prior_ui_state:
        prior_ui_state = cached_state.get("ui_state") if isinstance(cached_state.get("ui_state"), dict) else {}
    initial = await _observe(
        goal=goal,
        services=runtime_services,
        label="screen_before",
        last_target_cache=cache,
        prior_ui_state=prior_ui_state,
        region=region,
    )
    if not initial.get("success"):
        return {"success": False, "status": "failed", "error": initial.get("error", "screen_observe_failed")}

    before_path = str(((initial.get("screenshot") if isinstance(initial.get("screenshot"), dict) else {}) or {}).get("path") or "")
    ui_state = dict(initial.get("ui_state") or {})
    summary = str(initial.get("summary") or "").strip()
    intent = _parse_instruction(goal, mode=normalized_mode)
    actions, plan_errors = _build_action_queue(intent, ui_state)
    target_decisions = [dict(action.get("decision_trace") or {}) for action in actions if isinstance(action.get("decision_trace"), dict) and action.get("decision_trace")]
    action_logs: list[dict[str, Any]] = []
    verifier_outcomes: list[dict[str, Any]] = []
    current_observation = initial
    after_path = before_path

    for item in list(ui_state.get("elements") or []):
        _remember_target(cache, item, ui_state=ui_state)

    if normalized_mode == "inspect":
        artifacts, manifest = _materialize_artifacts(
            before_path=before_path,
            after_path=before_path if final_screenshot else "",
            ui_state=ui_state,
            summary=summary,
            action_logs=action_logs,
            target_decisions=target_decisions,
        )
        payload = {
            "success": True,
            "status": "success",
            "mode": normalized_mode,
            "goal_achieved": True,
            "message": summary or "Screen inspected.",
            "summary": summary or "Screen inspected.",
            "ui_state": ui_state,
            "plan": actions,
            "initial_observation": initial,
            "final_observation": initial,
            "operator_budget": {"max_actions": int(max_actions or 0), "max_retries_per_action": int(max_retries_per_action or 0), "elapsed_s": round(time.monotonic() - started_at, 3)},
            "screenshots": [path for path in [manifest.get("before"), manifest.get("after")] if path],
            "artifacts": artifacts,
            "action_logs": action_logs,
            "verifier_outcomes": verifier_outcomes,
            "task_state": {
                "current_step": 0,
                "attempts": 0,
                "ui_state": ui_state,
                "last_ui_state": ui_state,
                "last_target_cache": cache,
                "verifier_outcomes": verifier_outcomes,
            },
        }
        payload["recovery_hints"] = _screen_recovery_hints(ui_state=ui_state, action_logs=action_logs, verifier_outcomes=verifier_outcomes)
        return payload

    if plan_errors:
        artifacts, manifest = _materialize_artifacts(
            before_path=before_path,
            after_path="",
            ui_state=ui_state,
            summary=summary,
            action_logs=action_logs,
            target_decisions=target_decisions,
        )
        payload = {
            "success": False,
            "status": "failed",
            "error": "ui_target_not_found",
            "error_code": plan_errors[0],
            "message": "UI target not found.",
            "ui_state": ui_state,
            "plan": actions,
            "initial_observation": initial,
            "final_observation": initial,
            "operator_budget": {"max_actions": int(max_actions or 0), "max_retries_per_action": int(max_retries_per_action or 0), "elapsed_s": round(time.monotonic() - started_at, 3)},
            "screenshots": [manifest.get("before")] if manifest.get("before") else [],
            "artifacts": artifacts,
            "action_logs": action_logs,
            "verifier_outcomes": verifier_outcomes,
            "task_state": {"current_step": 0, "attempts": 0, "ui_state": ui_state, "last_ui_state": ui_state, "last_target_cache": cache, "verifier_outcomes": verifier_outcomes},
        }
        payload["recovery_hints"] = _screen_recovery_hints(ui_state=ui_state, action_logs=action_logs, verifier_outcomes=[{"failed_codes": plan_errors}])
        return payload

    goal_achieved = False
    max_steps = max(1, min(int(max_actions or 1), len(actions)))
    executed = 0
    failed_code = ""
    error_text = ""
    for action_index, planned in enumerate(actions[:max_steps], start=1):
        active_action = dict(planned)
        attempts = 0
        while attempts <= max(0, int(max_retries_per_action or 0)):
            attempts += 1
            active_action["attempts"] = attempts
            action_result = await _execute_action(runtime_services, active_action)
            log_entry = {
                "step": action_index,
                "attempt": attempts,
                "planned_action": dict(active_action),
                "execution_result": dict(action_result),
            }
            if not action_result.get("success"):
                log_entry["verification"] = {"ok": False, "failed_codes": [FailureCode.ARTIFACT_MISSING.value]}
                action_logs.append(log_entry)
                verifier_outcomes.append(log_entry["verification"])
                failed_code = FailureCode.ARTIFACT_MISSING.value
                error_text = str(action_result.get("error") or "screen_action_failed")
                break
            after = await _observe(
                goal=goal,
                services=runtime_services,
                label=f"screen_after_{action_index}_{attempts}",
                last_target_cache=cache,
                prior_ui_state=ui_state,
                region=region,
            )
            if not after.get("success"):
                log_entry["verification"] = {"ok": False, "failed_codes": [FailureCode.ARTIFACT_MISSING.value]}
                action_logs.append(log_entry)
                verifier_outcomes.append(log_entry["verification"])
                failed_code = FailureCode.ARTIFACT_MISSING.value
                error_text = str(after.get("error") or "screen_verify_failed")
                break
            after_path = str(((after.get("screenshot") if isinstance(after.get("screenshot"), dict) else {}) or {}).get("path") or after_path)
            verify = _verify_action(current_observation, after, active_action)
            log_entry["verification"] = verify
            log_entry["after_summary"] = str(after.get("summary") or "")
            action_logs.append(log_entry)
            verifier_outcomes.append(verify)
            current_observation = after
            ui_state = dict(after.get("ui_state") or ui_state)
            summary = str(after.get("summary") or summary)
            for item in list(ui_state.get("elements") or []):
                _remember_target(cache, item, ui_state=ui_state)
            if verify.get("ok"):
                active_target = active_action.get("target") if isinstance(active_action.get("target"), dict) else {}
                if active_target:
                    _remember_target(
                        cache,
                        active_target,
                        ui_state=ui_state,
                        action_kind=str(active_action.get("kind") or ""),
                        verified_success=True,
                    )
                goal_achieved = True
                executed += 1
                break
            repaired = _repair_action(active_action, verify)
            if repaired is None:
                failed_codes = list(verify.get("failed_codes") or [FailureCode.NO_VISUAL_CHANGE.value])
                failed_code = failed_codes[0]
                error_text = failed_code.lower()
                break
            active_action = repaired
        if failed_code:
            break
        if not goal_achieved and str(planned.get("kind") or "") == "noop":
            goal_achieved = True
            executed += 1
            break
        if not goal_achieved and action_index >= len(actions[:max_steps]):
            executed += 1
        elif goal_achieved:
            executed += 1

    artifacts, manifest = _materialize_artifacts(
        before_path=before_path,
        after_path=after_path if final_screenshot else "",
        ui_state=ui_state,
        summary=summary,
        action_logs=action_logs,
        target_decisions=target_decisions,
    )
    if failed_code:
        payload = {
            "success": False,
            "status": "failed",
            "mode": normalized_mode,
            "goal_achieved": False,
            "error": error_text or failed_code.lower(),
            "error_code": failed_code,
            "message": summary or error_text or failed_code.lower(),
            "summary": summary,
            "ui_state": ui_state,
            "plan": actions,
            "initial_observation": initial,
            "final_observation": current_observation,
            "operator_budget": {"max_actions": int(max_actions or 0), "max_retries_per_action": int(max_retries_per_action or 0), "elapsed_s": round(time.monotonic() - started_at, 3)},
            "screenshots": [path for path in [manifest.get("before"), manifest.get("after")] if path],
            "artifacts": artifacts,
            "action_logs": action_logs,
            "verifier_outcomes": verifier_outcomes,
            "task_state": {
                "current_step": executed,
                "attempts": sum(int(item.get("attempt") or 0) for item in action_logs),
                "ui_state": ui_state,
                "last_ui_state": ui_state,
                "last_target_cache": cache,
                "verifier_outcomes": verifier_outcomes,
            },
        }
        payload["recovery_hints"] = _screen_recovery_hints(ui_state=ui_state, action_logs=action_logs, verifier_outcomes=verifier_outcomes)
        return payload
    payload = {
        "success": True,
        "status": "success" if goal_achieved else "partial",
        "mode": normalized_mode,
        "goal_achieved": bool(goal_achieved),
        "message": summary or "Screen operator completed.",
        "summary": summary or "Screen operator completed.",
        "ui_state": ui_state,
        "plan": actions,
        "initial_observation": initial,
        "final_observation": current_observation,
        "operator_budget": {"max_actions": int(max_actions or 0), "max_retries_per_action": int(max_retries_per_action or 0), "elapsed_s": round(time.monotonic() - started_at, 3)},
        "screenshots": [path for path in [manifest.get("before"), manifest.get("after")] if path],
        "artifacts": artifacts,
        "action_logs": action_logs,
        "verifier_outcomes": verifier_outcomes,
        "task_state": {
            "current_step": executed,
            "attempts": sum(int(item.get("attempt") or 0) for item in action_logs),
            "ui_state": ui_state,
            "last_ui_state": ui_state,
            "last_target_cache": cache,
            "verifier_outcomes": verifier_outcomes,
        },
    }
    payload["recovery_hints"] = _screen_recovery_hints(ui_state=ui_state, action_logs=action_logs, verifier_outcomes=verifier_outcomes)
    return payload


__all__ = ["run_screen_operator"]
