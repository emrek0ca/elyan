from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import multiprocessing as mp
import os
import re
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from core.capabilities.screen_operator.runtime import run_screen_operator
from core.capabilities.screen_operator.services import ScreenOperatorServices, default_screen_operator_services
from core.capabilities.screen_operator.runtime import _verify_action as _screen_verify_action
from core.contracts.operator_runtime import ExecutionEvidence, FrameObservation
from core.contracts.failure_taxonomy import FailureCode
from core.contracts.verification_result import VerificationCheck, VerificationResult
from core.storage_paths import resolve_elyan_data_dir
from elyan.core.security import get_security_layer
from utils.logger import get_logger

logger = get_logger("realtime_actuator")


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _sha256(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    p = Path(raw).expanduser()
    if not p.exists() or not p.is_file():
        return ""
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> float:
    return time.time()


def _compact_text(value: Any) -> str:
    raw = str(value or "").lower().strip()
    if not raw:
        return ""
    parts = re.split(r"[^a-z0-9ğüşöçıİĞÜŞÖÇ]+", raw)
    return " ".join(part for part in parts if part)


@dataclass
class StateCache:
    max_frames: int = 10
    max_actions: int = 32
    frames: deque[dict[str, Any]] = field(default_factory=deque)
    actions: deque[dict[str, Any]] = field(default_factory=deque)
    last_observation: dict[str, Any] = field(default_factory=dict)
    last_action: dict[str, Any] = field(default_factory=dict)
    last_frame_hash: str = ""
    updated_at: float = field(default_factory=_now)

    def remember_observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        row = dict(observation or {})
        screenshot_value = row.get("screenshot")
        screenshot_path = str(
            row.get("screenshot_path")
            or (screenshot_value.get("path") if isinstance(screenshot_value, dict) else screenshot_value)
            or ""
        ).strip()
        if screenshot_path and not row.get("screenshot_hash"):
            row["screenshot_hash"] = _sha256(screenshot_path)
        row.setdefault("captured_at", _now())
        row.setdefault("changed", bool(row.get("changed", False)))
        frame_hash = str(row.get("screenshot_hash") or "").strip() or str(row.get("summary") or "")
        if self.last_frame_hash:
            row["changed"] = bool(frame_hash and frame_hash != self.last_frame_hash)
        self.last_frame_hash = frame_hash or self.last_frame_hash
        self.last_observation = dict(row)
        self.frames.append(dict(row))
        while len(self.frames) > max(1, int(self.max_frames or 10)):
            self.frames.popleft()
        self.updated_at = _now()
        return dict(row)

    def remember_action(self, action: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any]:
        row = {
            "action": dict(action or {}),
            "result": dict(result or {}),
            "captured_at": _now(),
        }
        self.last_action = dict(row)
        self.actions.append(dict(row))
        while len(self.actions) > max(1, int(self.max_actions or 32)):
            self.actions.popleft()
        self.updated_at = _now()
        return dict(row)

    def snapshot(self) -> dict[str, Any]:
        return {
            "last_observation": dict(self.last_observation),
            "last_action": dict(self.last_action),
            "frames": list(self.frames),
            "actions": list(self.actions),
            "last_frame_hash": str(self.last_frame_hash or ""),
            "updated_at": float(self.updated_at or 0.0),
        }


class ScreenpipeClient:
    def __init__(self, base_url: str = "http://localhost:3030", timeout_s: float = 2.5) -> None:
        self.base_url = str(base_url or "http://localhost:3030").rstrip("/")
        self.timeout_s = max(0.25, float(timeout_s or 2.5))
        self._availability_cache: tuple[float, bool] | None = None

    def available(self) -> bool:
        cached = self._availability_cache
        if cached and (_now() - float(cached[0])) < 2.0:
            return bool(cached[1])
        available = False
        endpoints = ("/health", "/screen", "/snapshot", "/accessibility")
        for suffix in endpoints:
            try:
                response = requests.get(f"{self.base_url}{suffix}", timeout=min(self.timeout_s, 1.25))
                if response.status_code < 400:
                    available = True
                    break
            except Exception:
                continue
        self._availability_cache = (_now(), available)
        return available

    def fetch_snapshot(self) -> dict[str, Any]:
        endpoints = ("/screen", "/snapshot", "/state", "/accessibility")
        for suffix in endpoints:
            try:
                response = requests.get(f"{self.base_url}{suffix}", timeout=self.timeout_s)
                if response.status_code >= 400:
                    continue
                data = response.json()
                if isinstance(data, dict):
                    return {"success": True, "source": "screenpipe", **data}
            except Exception:
                continue
        return {"success": False, "source": "screenpipe", "error": "screenpipe_unavailable"}


class AccessibilityEngine:
    def normalize(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        elements: list[dict[str, Any]] = []
        for item in list(snapshot.get("elements") or []):
            if not isinstance(item, dict):
                continue
            row = {
                "label": str(item.get("label") or item.get("text") or "").strip(),
                "role": str(item.get("role") or item.get("kind") or "unknown").strip().lower() or "unknown",
                "confidence": float(item.get("confidence", 0.0) or 0.0),
                "x": int(item.get("x") or 0) if item.get("x") is not None else None,
                "y": int(item.get("y") or 0) if item.get("y") is not None else None,
                "width": int(item.get("width") or 0) if item.get("width") is not None else None,
                "height": int(item.get("height") or 0) if item.get("height") is not None else None,
                "source": str(item.get("source") or "accessibility"),
            }
            if row["label"] or row["role"]:
                elements.append({k: v for k, v in row.items() if v is not None})
        return {
            "frontmost_app": str(snapshot.get("frontmost_app") or "").strip(),
            "window_title": str(snapshot.get("window_title") or "").strip(),
            "elements": elements,
            "summary": str(snapshot.get("summary") or "").strip(),
            "source": "accessibility",
        }

    def quick_match(self, query: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
        low = str(query or "").lower().strip()
        if not low:
            return {}
        for item in elements:
            label = str(item.get("label") or item.get("text") or "").lower()
            if label and (label == low or low in label):
                return dict(item)
        return {}


class FastVisionTier:
    def __init__(self, services: ScreenOperatorServices | None = None) -> None:
        self.services = services or default_screen_operator_services()

    async def summarize(self, screenshot_path: str, prompt: str) -> dict[str, Any]:
        if not screenshot_path:
            return {"success": False, "error": "missing_screenshot"}
        try:
            result = await self.services.run_vision(screenshot_path, prompt)
        except Exception as exc:
            return {"success": False, "error": str(exc), "summary": "", "elements": []}
        if not isinstance(result, dict):
            return {"success": False, "error": "invalid_vision_result", "summary": "", "elements": []}
        return dict(result)


class ScreenObserver:
    def __init__(
        self,
        *,
        services: ScreenOperatorServices | None = None,
        screenpipe_client: ScreenpipeClient | None = None,
        fps: int = 60,
        region: dict[str, Any] | None = None,
        daemon_id: str = "realtime",
        state_cache: StateCache | None = None,
    ) -> None:
        self.services = services or default_screen_operator_services()
        self.screenpipe_client = screenpipe_client or ScreenpipeClient()
        self.fps = max(1, int(fps or 60))
        self.region = dict(region or {})
        self.daemon_id = str(daemon_id or "realtime")
        self.state_cache = state_cache or StateCache()
        self.accessibility_engine = AccessibilityEngine()
        self.fast_vision = FastVisionTier(self.services)

    @staticmethod
    def _goal_tokens(goal: str) -> list[str]:
        return [part for part in _compact_text(goal).split(" ") if len(part) > 2]

    def _should_use_vision(
        self,
        goal: str,
        *,
        accessibility_payload: dict[str, Any],
        ocr_payload: dict[str, Any],
        window_metadata: dict[str, Any],
    ) -> bool:
        low_goal = str(goal or "").lower()
        visual_markers = (
            "gör",
            "gor",
            "bak",
            "look",
            "describe",
            "analyze",
            "analyse",
            "what is on",
            "what's on",
            "what do you see",
            "screenshot",
            "ekran",
            "image",
            "visual",
            "vision",
            "inspect",
            "read the screen",
            "read screen",
            "check screenshot",
        )
        if any(marker in low_goal for marker in visual_markers):
            return True
        accessibility_elements = [item for item in list(accessibility_payload.get("elements") or []) if isinstance(item, dict)]
        ocr_text = str(ocr_payload.get("text") or "").strip().lower()
        if accessibility_elements and (ocr_text or str(accessibility_payload.get("summary") or "").strip() or str(window_metadata.get("window_title") or "").strip()):
            return False
        if accessibility_elements:
            labels = " ".join(str(item.get("label") or item.get("text") or "").lower() for item in accessibility_elements)
            goal_tokens = self._goal_tokens(goal)
            if goal_tokens and any(token in labels or token in ocr_text for token in goal_tokens):
                return False
        if not accessibility_elements and not ocr_text:
            return True
        return False

    async def _observe_with_services(self, goal: str) -> dict[str, Any]:
        if self.region and {"x", "y", "width", "height"}.issubset(self.region):
            screenshot = await self.services.capture_region(
                x=int(self.region.get("x", 0)),
                y=int(self.region.get("y", 0)),
                width=int(self.region.get("width", 0)),
                height=int(self.region.get("height", 0)),
                filename=f"realtime_{int(time.time() * 1000)}.png",
            )
        else:
            screenshot = await self.services.take_screenshot(filename=f"realtime_{int(time.time() * 1000)}.png")
        if not isinstance(screenshot, dict) or not bool(screenshot.get("success")):
            return {"success": False, "error": str((screenshot or {}).get("error") or "screenshot_failed")}
        screenshot_path = str(screenshot.get("path") or "").strip()
        window_metadata, accessibility, ocr = await asyncio.gather(
            self.services.get_window_metadata(),
            self.services.get_accessibility_snapshot(),
            self.services.run_ocr(screenshot_path),
        )
        vision: dict[str, Any] = {}
        accessibility_payload = self.accessibility_engine.normalize(accessibility if isinstance(accessibility, dict) else {})
        should_use_vision = self._should_use_vision(
            goal,
            accessibility_payload=accessibility_payload,
            ocr_payload=dict(ocr or {}),
            window_metadata=dict(window_metadata or {}),
        )
        if should_use_vision:
            vision = await self.fast_vision.summarize(screenshot_path, goal)
        else:
            vision = {
                "success": True,
                "skipped": True,
                "summary": "",
                "elements": [],
                "provider": "accessibility_first",
            }
        summary_bits = [
            str((vision or {}).get("summary") or "").strip(),
            str((ocr or {}).get("text") or "").strip(),
            str(accessibility_payload.get("summary") or "").strip(),
            str((window_metadata or {}).get("window_title") or "").strip(),
        ]
        summary = " ".join(bit for bit in summary_bits if bit).strip()
        observation = FrameObservation(
            daemon_id=self.daemon_id,
            fps=float(self.fps),
            latency_ms=0.0,
            screenshot_path=screenshot_path,
            window_metadata=dict(window_metadata or {}),
            accessibility=accessibility_payload,
            vision=dict(vision or {}),
            ocr=dict(ocr or {}),
            summary=summary,
            changed=False,
            source="services",
            metadata={"goal": goal, "region": dict(self.region or {}), "screenshot": dict(screenshot)},
        ).model_dump()
        return {
            "success": True,
            "frame": observation,
            "screenshot": dict(screenshot),
            "window_metadata": dict(window_metadata or {}),
            "accessibility": accessibility_payload,
            "ui_state": dict(accessibility_payload),
            "ocr": dict(ocr or {}),
            "vision": dict(vision or {}),
            "summary": summary,
            "vision_used": bool(should_use_vision),
        }

    async def _observe_with_screenpipe(self, goal: str) -> dict[str, Any]:
        snapshot = self.screenpipe_client.fetch_snapshot()
        if not isinstance(snapshot, dict) or not bool(snapshot.get("success")):
            return {"success": False, "error": str(snapshot.get("error") or "screenpipe_failed")}
        accessibility = self.accessibility_engine.normalize(snapshot)
        summary = str(snapshot.get("summary") or snapshot.get("text") or "").strip()
        frame = FrameObservation(
            daemon_id=self.daemon_id,
            fps=float(self.fps),
            latency_ms=0.0,
            screenshot_path=str(snapshot.get("screenshot_path") or snapshot.get("path") or ""),
            window_metadata=dict(snapshot.get("window_metadata") or {}),
            accessibility=accessibility,
            vision=dict(snapshot.get("vision") or {}),
            ocr=dict(snapshot.get("ocr") or {}),
            summary=summary,
            changed=False,
            source="screenpipe",
            metadata={"goal": goal, "snapshot": dict(snapshot)},
        ).model_dump()
        return {
            "success": True,
            "frame": frame,
            "summary": summary,
            "accessibility": accessibility,
            "ui_state": dict(accessibility),
            "snapshot": snapshot,
        }

    async def observe_once(self, goal: str = "") -> dict[str, Any]:
        started = time.perf_counter()
        use_screenpipe = self.screenpipe_client.available()
        observation = await self._observe_with_screenpipe(goal) if use_screenpipe else await self._observe_with_services(goal)
        latency_ms = (time.perf_counter() - started) * 1000.0
        if observation.get("success") and isinstance(observation.get("frame"), dict):
            frame = dict(observation["frame"])
            frame["latency_ms"] = float(latency_ms)
            frame["changed"] = frame.get("screenshot_hash") != self.state_cache.last_frame_hash if frame.get("screenshot_hash") else bool(frame.get("changed"))
            observation["frame"] = self.state_cache.remember_observation(frame)
            observation["changed"] = bool(observation["frame"].get("changed"))
        observation["latency_ms"] = float(latency_ms)
        observation["daemon_id"] = self.daemon_id
        if observation.get("success") and isinstance(observation.get("frame"), dict):
            self._last_snapshot = self.state_cache.snapshot()
        return observation

    async def monitor_loop(
        self,
        *,
        stop_event: threading.Event | mp.Event,
        command_queue: queue.Queue | mp.queues.Queue | None = None,
        result_queue: queue.Queue | mp.queues.Queue | None = None,
        goal: str = "",
    ) -> None:
        interval_s = 1.0 / float(max(1, self.fps))
        while not stop_event.is_set():
            started = time.perf_counter()
            if command_queue is not None:
                try:
                    while True:
                        message = command_queue.get_nowait()
                        if isinstance(message, dict) and message.get("type") == "stop":
                            stop_event.set()
                            break
                        if isinstance(message, dict) and message.get("type") == "action":
                            if result_queue is not None:
                                result_queue.put({"type": "action", "payload": dict(message), "status": "queued"})
                except queue.Empty:
                    pass
            observation = await self.observe_once(goal=goal)
            if result_queue is not None:
                result_queue.put({"type": "observation", "payload": dict(observation)})
            elapsed = time.perf_counter() - started
            sleep_for = max(0.0, interval_s - elapsed)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)


class VisionVerifier:
    def __init__(
        self,
        *,
        services: ScreenOperatorServices | None = None,
        state_cache: StateCache | None = None,
        fast_vision: FastVisionTier | None = None,
        accessibility_engine: AccessibilityEngine | None = None,
    ) -> None:
        self.services = services or default_screen_operator_services()
        self.state_cache = state_cache or StateCache()
        self.fast_vision = fast_vision or FastVisionTier(self.services)
        self.accessibility_engine = accessibility_engine or AccessibilityEngine()

    @staticmethod
    def _goal_tokens(goal: str) -> list[str]:
        parts = re.split(r"[^a-z0-9ğüşöçıİĞÜŞÖÇ]+", str(goal or "").lower())
        return [part for part in parts if len(part) > 2]

    def _vision_hint_matches(self, goal: str, vision_payload: dict[str, Any]) -> bool:
        summary = _compact_text(vision_payload.get("summary") or "")
        elements = [item for item in list(vision_payload.get("elements") or []) if isinstance(item, dict)]
        labels = " ".join(_compact_text(item.get("label") or item.get("text") or "") for item in elements)
        goal_tokens = self._goal_tokens(goal)
        if not goal_tokens:
            return bool(summary or labels)
        return any(token in summary or token in labels for token in goal_tokens)

    @staticmethod
    def _label_for_point(elements: list[dict[str, Any]], x: int | float | None, y: int | float | None) -> str:
        if x is None or y is None:
            return ""
        try:
            px = float(x)
            py = float(y)
        except Exception:
            return ""
        best_label = ""
        best_score: float | None = None
        for item in elements:
            if not isinstance(item, dict):
                continue
            label = _compact_text(item.get("label") or item.get("text") or "")
            if not label:
                continue
            ix = item.get("x")
            iy = item.get("y")
            iw = item.get("width")
            ih = item.get("height")
            if all(isinstance(v, (int, float)) for v in (ix, iy, iw, ih)):
                left = float(ix)
                top = float(iy)
                right = left + float(iw)
                bottom = top + float(ih)
                if left <= px <= right and top <= py <= bottom:
                    return label
                center_x = left + float(iw) / 2.0
                center_y = top + float(ih) / 2.0
                score = abs(px - center_x) + abs(py - center_y)
            else:
                score = 9999.0
            if best_score is None or score < best_score:
                best_label = label
                best_score = score
        return best_label

    async def verify_transition(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
        action: dict[str, Any],
        *,
        goal: str = "",
    ) -> dict[str, Any]:
        base_result = dict(_screen_verify_action(before or {}, after or {}, action or {}))
        base_result.setdefault("vision_used", False)
        base_result.setdefault("vision_attempted", False)
        if base_result.get("ok"):
            return base_result

        failed_codes = {str(code).strip() for code in list(base_result.get("failed_codes") or []) if str(code).strip()}
        needs_vision = bool(
            failed_codes & {
                FailureCode.NO_VISUAL_CHANGE.value,
                FailureCode.UI_TARGET_NOT_FOUND.value,
                FailureCode.TEXT_NOT_VERIFIED.value,
                FailureCode.NAVIGATION_NOT_VERIFIED.value,
            }
            or str(goal or "").strip()
        )
        if not needs_vision:
            return base_result

        # Pull the best available screenshot path from the observation payload.
        after_path = str(
            ((after or {}).get("screenshot") if isinstance((after or {}).get("screenshot"), dict) else {}).get("path")
            or (after or {}).get("screenshot_path")
            or ((after or {}).get("frame") if isinstance((after or {}).get("frame"), dict) else {}).get("screenshot_path")
            or ""
        ).strip()
        if not after_path:
            base_result["vision_attempted"] = True
            return base_result

        base_result["vision_attempted"] = True
        try:
            vision = await self.fast_vision.summarize(after_path, goal or str(action.get("instruction") or action.get("kind") or ""))
        except Exception as exc:
            base_result["vision_error"] = str(exc)
            return base_result

        if not isinstance(vision, dict) or not bool(vision.get("success")):
            base_result["vision_error"] = str((vision or {}).get("error") or "vision_failed")
            return base_result

        base_result["vision_used"] = True
        base_result["vision_summary"] = str(vision.get("summary") or "")
        base_result["vision_elements"] = list(vision.get("elements") or [])
        augmented_after = dict(after or {})
        augmented_after.setdefault("vision", {})
        if isinstance(augmented_after.get("vision"), dict):
            augmented_after["vision"] = {**dict(augmented_after.get("vision") or {}), **dict(vision)}
        augmented_after["summary"] = " ".join(
            bit for bit in [
                str(vision.get("summary") or "").strip(),
                str((augmented_after.get("summary") or "")).strip(),
            ]
            if bit
        ).strip()

        vision_recheck = dict(_screen_verify_action(before or {}, augmented_after, action or {}))
        if vision_recheck.get("ok"):
            vision_recheck["vision_used"] = True
            vision_recheck["vision_attempted"] = True
            vision_recheck["vision_summary"] = str(vision.get("summary") or "")
            vision_recheck["vision_elements"] = list(vision.get("elements") or [])
            return vision_recheck

        if self._vision_hint_matches(goal, vision):
            vision_recheck["vision_used"] = True
            vision_recheck["vision_attempted"] = True
            vision_recheck["vision_summary"] = str(vision.get("summary") or "")
            vision_recheck["vision_elements"] = list(vision.get("elements") or [])
            if not vision_recheck.get("failed_codes"):
                vision_recheck["ok"] = True
                vision_recheck["status"] = "success"
            elif set(vision_recheck.get("failed_codes") or []) <= {FailureCode.NO_VISUAL_CHANGE.value}:
                vision_recheck["ok"] = True
                vision_recheck["status"] = "success"
                vision_recheck["failed_codes"] = []
                vision_recheck["failed"] = []
            return vision_recheck

        action_kind = str(action.get("kind") or "").strip().lower()
        if action_kind == "click":
            target = action.get("target") if isinstance(action.get("target"), dict) else {}
            target_label = _compact_text(
                target.get("label")
                or target.get("text")
                or action.get("label")
                or action.get("goal")
                or goal
            )
            before_elements = [item for item in list(((before or {}).get("accessibility") or {}).get("elements") or []) if isinstance(item, dict)]
            after_elements = [item for item in list(((after or {}).get("accessibility") or {}).get("elements") or []) if isinstance(item, dict)]
            if not target_label:
                target_label = self._label_for_point(
                    before_elements or after_elements,
                    action.get("x"),
                    action.get("y"),
                )
            if target_label:
                before_labels = " ".join(_compact_text(item.get("label") or item.get("text") or "") for item in before_elements)
                after_labels = " ".join(_compact_text(item.get("label") or item.get("text") or "") for item in after_elements)
                if target_label in before_labels or target_label in after_labels:
                    fallback = dict(vision_recheck)
                    fallback["ok"] = True
                    fallback["status"] = "success"
                    fallback["vision_used"] = bool(fallback.get("vision_used"))
                    fallback["vision_attempted"] = bool(fallback.get("vision_attempted"))
                    fallback["verification_mode"] = "accessibility_target_confirmed"
                    fallback["verification_target"] = target_label
                    fallback["failed_codes"] = []
                    fallback["failed"] = []
                    return fallback

        vision_recheck["vision_used"] = True
        vision_recheck["vision_attempted"] = True
        vision_recheck["vision_summary"] = str(vision.get("summary") or "")
        vision_recheck["vision_elements"] = list(vision.get("elements") or [])
        return vision_recheck


class ActionExecutor:
    def __init__(
        self,
        *,
        services: ScreenOperatorServices | None = None,
        state_cache: StateCache | None = None,
    ) -> None:
        self.services = services or default_screen_operator_services()
        self.state_cache = state_cache or StateCache()
        self.observer = ScreenObserver(services=self.services, state_cache=self.state_cache)
        self.verifier = VisionVerifier(services=self.services, state_cache=self.state_cache)
        self.security = get_security_layer()

    async def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        payload = dict(action or {})
        if not bool(payload.pop("_security_preapproved", False)):
            interactive = bool(getattr(sys.stdin, "isatty", lambda: False)() and getattr(sys.stdout, "isatty", lambda: False)())
            try:
                await self.security.authorize_action(
                    "screen_operator",
                    {
                        "type": str(payload.get("kind") or payload.get("action") or "realtime_action"),
                        "description": str(
                            payload.get("instruction")
                            or payload.get("goal")
                            or payload.get("description")
                            or payload.get("action")
                            or payload.get("kind")
                            or ""
                        ),
                        "approval_required": bool(payload.get("approval_required", False)),
                        "destructive": bool(payload.get("destructive", False)),
                        "needs_network": bool(payload.get("needs_network", False)),
                        "workspace_dir": str(payload.get("workspace_dir") or ""),
                    },
                    {
                        "source": "realtime_actuator",
                        "interactive": interactive,
                        "screenshot_path": str(payload.get("screenshot_path") or ""),
                    },
                )
            except PermissionError as exc:
                result = {
                    "success": False,
                    "status": "blocked",
                    "error": str(exc),
                    "errors": ["APPROVAL_DENIED"],
                    "data": {"error_code": "APPROVAL_DENIED"},
                    "latency_ms": float((time.perf_counter() - started) * 1000.0),
                }
                self.state_cache.remember_action(payload, result)
                return result
        if "instruction" in payload and str(payload.get("instruction") or "").strip():
            result = await run_screen_operator(
                instruction=str(payload.get("instruction") or ""),
                mode=str(payload.get("mode") or "inspect_and_control"),
                region=dict(payload.get("region") or {}) if isinstance(payload.get("region"), dict) else None,
                final_screenshot=bool(payload.get("final_screenshot", True)),
                max_actions=int(payload.get("max_actions", 4) or 4),
                max_retries_per_action=int(payload.get("max_retries_per_action", 2) or 2),
                services=self.services,
                task_state=dict(self.state_cache.snapshot()),
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            result["latency_ms"] = float(latency_ms)
            self.state_cache.remember_action(payload, result)
            if isinstance(result.get("ui_state"), dict):
                self.state_cache.remember_observation(
                    {
                        "summary": str(result.get("summary") or ""),
                        "screenshot_path": str((result.get("screenshots") or [None])[-1] or ""),
                        "window_metadata": dict(result.get("ui_state") or {}),
                        "accessibility": dict(result.get("ui_state") or {}),
                        "latency_ms": float(latency_ms),
                        "source": "run_screen_operator",
                    }
                )
            return result

        kind = str(payload.get("kind") or payload.get("action") or "").strip().lower()
        if kind == "inspect":
            observation = await self.observer.observe_once(
                goal=str(payload.get("goal") or payload.get("instruction") or "")
            )
            result = dict(observation)
            result.setdefault("status", "success" if observation.get("success") else "failed")
            result["latency_ms"] = float((time.perf_counter() - started) * 1000.0)
            self.state_cache.remember_action(payload, result)
            return result

        if kind in {"click", "type", "press_key", "key_combo", "wait"}:
            result: dict[str, Any]
            goal = str(payload.get("goal") or payload.get("instruction") or "")
            verify_requested = bool(payload.get("verify", kind != "wait"))
            before = await self.observer.observe_once(goal=goal) if verify_requested and kind != "wait" else {}
            if kind == "click":
                result = await self.services.mouse_click(
                    x=int(payload.get("x", 0)),
                    y=int(payload.get("y", 0)),
                    button=str(payload.get("button") or "left"),
                    double=bool(payload.get("double", False)),
                )
            elif kind == "type":
                result = await self.services.type_text(
                    text=str(payload.get("text") or ""),
                    press_enter=bool(payload.get("press_enter", False)),
                )
            elif kind == "press_key":
                result = await self.services.press_key(
                    key=str(payload.get("key") or ""),
                    modifiers=list(payload.get("modifiers") or []),
                )
            elif kind == "key_combo":
                result = await self.services.key_combo(combo=str(payload.get("combo") or ""))
            else:
                await self.services.sleep(float(payload.get("seconds") or 0.2))
                result = {"success": True, "status": "success", "action": "wait"}
            result["action"] = kind
            result["latency_ms"] = float((time.perf_counter() - started) * 1000.0)
            if verify_requested and kind != "wait":
                after = await self.observer.observe_once(goal=goal)
                verification = await self.verifier.verify_transition(before, after, payload, goal=goal)
                result["verification"] = verification
                result["verified"] = bool(verification.get("ok"))
                if not verification.get("ok"):
                    result["success"] = False
                    result["status"] = "failed"
                    result["error"] = str(verification.get("summary") or verification.get("failed_codes") or "verification_failed")
                else:
                    result.setdefault("success", True)
                    result.setdefault("status", "success")
            self.state_cache.remember_action(payload, result)
            return result

        if kind == "realtime_observe":
            observation = await self.observer.observe_once(
                goal=str(payload.get("goal") or payload.get("instruction") or "")
            )
            observation["latency_ms"] = float((time.perf_counter() - started) * 1000.0)
            self.state_cache.remember_action(payload, observation)
            return observation

        result = {"success": True, "status": "success", "message": "noop", "action": kind or "noop"}
        result["latency_ms"] = float((time.perf_counter() - started) * 1000.0)
        self.state_cache.remember_action(payload, result)
        return result


class _BaseTransport:
    mode = "queue"
    fallback_reason = ""

    def worker_kwargs(self) -> dict[str, Any]:
        return {}

    def send(self, message: dict[str, Any]) -> None:
        raise NotImplementedError

    def drain(self) -> list[dict[str, Any]]:
        return []

    def stop(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {
            "transport_mode": self.mode,
            "transport_ready": True,
            "transport_fallback_reason": str(self.fallback_reason or ""),
        }


class _QueueTransport(_BaseTransport):
    mode = "queue"

    def __init__(self) -> None:
        ctx = mp.get_context("spawn")
        self.command_queue = ctx.Queue()
        self.result_queue = ctx.Queue()
        self.stop_event = ctx.Event()

    def worker_kwargs(self) -> dict[str, Any]:
        return {
            "command_queue": self.command_queue,
            "result_queue": self.result_queue,
            "stop_event": self.stop_event,
        }

    def send(self, message: dict[str, Any]) -> None:
        self.command_queue.put(dict(message or {}))

    def drain(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        try:
            while True:
                message = self.result_queue.get_nowait()
                if isinstance(message, dict):
                    messages.append(dict(message))
        except queue.Empty:
            pass
        return messages

    def stop(self) -> None:
        try:
            self.stop_event.set()
        except Exception:
            pass
        try:
            self.command_queue.put({"type": "stop"})
        except Exception:
            pass

    def close(self) -> None:
        return None


class _ZmqTransport(_BaseTransport):
    mode = "zmq"

    def __init__(self) -> None:
        self._zmq = importlib.import_module("zmq")
        self._context = self._zmq.Context.instance()
        self.command_socket = self._context.socket(self._zmq.PUSH)
        self.command_socket.linger = 0
        self.result_socket = self._context.socket(self._zmq.PULL)
        self.result_socket.linger = 0
        self.command_port = self.command_socket.bind_to_random_port("tcp://127.0.0.1")
        self.result_port = self.result_socket.bind_to_random_port("tcp://127.0.0.1")
        self.command_endpoint = f"tcp://127.0.0.1:{self.command_port}"
        self.result_endpoint = f"tcp://127.0.0.1:{self.result_port}"

    def worker_kwargs(self) -> dict[str, Any]:
        return {
            "command_endpoint": self.command_endpoint,
            "result_endpoint": self.result_endpoint,
        }

    def send(self, message: dict[str, Any]) -> None:
        self.command_socket.send_json(dict(message or {}))

    def drain(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        while True:
            try:
                if not self.result_socket.poll(timeout=0):
                    break
                payload = self.result_socket.recv_json(flags=self._zmq.NOBLOCK)
                if isinstance(payload, dict):
                    messages.append(dict(payload))
            except self._zmq.Again:
                break
            except Exception:
                break
        return messages

    def stop(self) -> None:
        try:
            self.send({"type": "stop"})
        except Exception:
            pass

    def close(self) -> None:
        for sock in (getattr(self, "command_socket", None), getattr(self, "result_socket", None)):
            if sock is None:
                continue
            try:
                sock.close(linger=0)
            except Exception:
                pass

    def status(self) -> dict[str, Any]:
        data = super().status()
        data.update(
            {
                "transport_endpoint_command": self.command_endpoint,
                "transport_endpoint_result": self.result_endpoint,
                "transport_provider": "pyzmq",
            }
        )
        return data


class _ZmqWorkerTransport:
    def __init__(self, *, command_endpoint: str, result_endpoint: str) -> None:
        self._zmq = importlib.import_module("zmq")
        self._context = self._zmq.Context.instance()
        self.command_socket = self._context.socket(self._zmq.PULL)
        self.command_socket.linger = 0
        self.command_socket.connect(str(command_endpoint))
        self.result_socket = self._context.socket(self._zmq.PUSH)
        self.result_socket.linger = 0
        self.result_socket.connect(str(result_endpoint))

    def recv_nowait(self) -> dict[str, Any] | None:
        try:
            if not self.command_socket.poll(timeout=0):
                return None
            payload = self.command_socket.recv_json(flags=self._zmq.NOBLOCK)
            return dict(payload) if isinstance(payload, dict) else None
        except self._zmq.Again:
            return None
        except Exception:
            return None

    def send(self, message: dict[str, Any]) -> None:
        self.result_socket.send_json(dict(message or {}))

    def close(self) -> None:
        for sock in (getattr(self, "command_socket", None), getattr(self, "result_socket", None)):
            if sock is None:
                continue
            try:
                sock.close(linger=0)
            except Exception:
                pass


def _daemon_worker(
    *,
    command_queue: Any | None = None,
    result_queue: Any | None = None,
    command_endpoint: str = "",
    result_endpoint: str = "",
    stop_event: Any | None = None,
    config: dict[str, Any],
    services: ScreenOperatorServices | None = None,
) -> None:
    if stop_event is None:
        stop_event = threading.Event()
    observer = ScreenObserver(
        services=services,
        screenpipe_client=ScreenpipeClient(
            base_url=str(config.get("screenpipe_url") or "http://localhost:3030"),
            timeout_s=float(config.get("screenpipe_timeout_s", 2.5) or 2.5),
        ),
        fps=int(config.get("fps", 60) or 60),
        region=dict(config.get("region") or {}),
        daemon_id=str(config.get("daemon_id") or "realtime"),
        state_cache=StateCache(
            max_frames=int(config.get("max_frames", 10) or 10),
            max_actions=int(config.get("max_actions", 32) or 32),
        ),
    )
    executor = ActionExecutor(services=services, state_cache=observer.state_cache)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run() -> None:
        interval_s = 1.0 / float(max(1, int(config.get("fps", 60) or 60)))
        transport_mode = str(config.get("transport_mode") or "queue").strip().lower() or "queue"
        zmq_transport = None
        if transport_mode == "zmq" and _module_available("zmq") and command_endpoint and result_endpoint:
            try:
                zmq_transport = _ZmqWorkerTransport(
                    command_endpoint=str(command_endpoint),
                    result_endpoint=str(result_endpoint),
                )
            except Exception as exc:
                logger.warning(f"ZMQ worker transport failed, falling back to queues: {exc}")
                zmq_transport = None
        while not stop_event.is_set():
            started = time.perf_counter()
            processed = False
            if zmq_transport is not None:
                while True:
                    message = zmq_transport.recv_nowait()
                    if not isinstance(message, dict):
                        break
                    if message.get("type") == "stop":
                        stop_event.set()
                        break
                    if message.get("type") == "action":
                        processed = True
                        result = await executor.execute(dict(message.get("payload") or {}))
                        zmq_transport.send({"type": "action_result", "ticket_id": str(message.get("ticket_id") or ""), "payload": result})
            else:
                if command_queue is None:
                    stop_event.set()
                else:
                    try:
                        while True:
                            message = command_queue.get_nowait()
                            if not isinstance(message, dict):
                                continue
                            if message.get("type") == "stop":
                                stop_event.set()
                                break
                            if message.get("type") == "action":
                                processed = True
                                result = await executor.execute(dict(message.get("payload") or {}))
                                if result_queue is not None:
                                    result_queue.put({"type": "action_result", "ticket_id": str(message.get("ticket_id") or ""), "payload": result})
                    except queue.Empty:
                        pass
            if not stop_event.is_set():
                observation = await observer.observe_once(goal=str(config.get("goal") or ""))
                if zmq_transport is not None:
                    zmq_transport.send({"type": "observation", "payload": observation})
                elif result_queue is not None:
                    result_queue.put({"type": "observation", "payload": observation})
            elapsed = time.perf_counter() - started
            sleep_for = max(0.0, interval_s - elapsed)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            if processed and bool(config.get("one_shot", False)):
                stop_event.set()

    try:
        loop.run_until_complete(_run())
    finally:
        try:
            if "zmq_transport" in locals() and zmq_transport is not None:
                zmq_transport.close()
        except Exception:
            pass
        try:
            loop.stop()
            loop.close()
        except Exception:
            pass


class RealTimeActuator:
    def __init__(
        self,
        *,
        services: ScreenOperatorServices | None = None,
        fps: int = 60,
        region: dict[str, Any] | None = None,
        transport_mode: str = "auto",
        process_mode: bool = False,
        screenpipe_url: str = "http://localhost:3030",
        daemon_id: str = "realtime",
        max_frames: int = 10,
        max_actions: int = 32,
    ) -> None:
        self.services = services or default_screen_operator_services()
        self.fps = max(1, int(fps or 60))
        self.region = dict(region or {})
        self.transport_mode = str(transport_mode or "auto").strip().lower() or "auto"
        self.process_mode = bool(process_mode)
        self.screenpipe_url = str(screenpipe_url or "http://localhost:3030")
        self.daemon_id = str(daemon_id or "realtime")
        self.state_cache = StateCache(max_frames=max_frames, max_actions=max_actions)
        self._transport: _BaseTransport | None = None
        self._transport_mode_actual: str = "inline"
        self._transport_fallback_reason: str = ""
        self._stop_event: Any | None = None
        self._process: mp.Process | None = None
        self._lock = threading.Lock()
        self._active = False
        self._last_snapshot: dict[str, Any] = {}
        self._last_ticket = 0
        self._screenpipe_client = ScreenpipeClient(base_url=self.screenpipe_url)
        self._backend_profile: dict[str, Any] = self._build_backend_profile("inline")
        self.security = get_security_layer()

    def _build_config(self) -> dict[str, Any]:
        return {
            "fps": self.fps,
            "region": dict(self.region or {}),
            "screenpipe_url": self.screenpipe_url,
            "daemon_id": self.daemon_id,
            "max_frames": self.state_cache.max_frames,
            "max_actions": self.state_cache.max_actions,
            "transport_mode": self._transport_mode_actual,
            "transport_fallback_reason": self._transport_fallback_reason,
        }

    def _build_backend_profile(self, transport_mode: str | None = None) -> dict[str, Any]:
        screenpipe_available = bool(self._screenpipe_client.available())
        selected_transport = str(transport_mode or ("inline" if not self.process_mode else self._transport_mode_actual or "queue")).strip().lower() or "queue"
        platform_backend = "services"
        if sys.platform.startswith("win"):
            if _module_available("dxcam"):
                platform_backend = "windows_dxcam"
            elif _module_available("pywinauto"):
                platform_backend = "windows_uia"
        elif sys.platform == "darwin":
            if _module_available("atomacos") or _module_available("pyobjc"):
                platform_backend = "mac_axapi"
        elif sys.platform.startswith("linux"):
            if _module_available("pyatspi"):
                platform_backend = "linux_pyatspi"
        return {
            "transport": selected_transport,
            "platform": sys.platform,
            "screenpipe": screenpipe_available,
            "sdk_available": _module_available("screenpipe"),
            "screen_backend": "screenpipe" if screenpipe_available else "services",
            "platform_backend_candidate": platform_backend,
        }

    def _ensure_transport(self) -> None:
        if self._transport is not None:
            return
        requested = str(self.transport_mode or "auto").strip().lower() or "auto"
        use_zmq = requested == "zmq" or (requested == "auto" and _module_available("zmq"))
        fallback_reason = ""
        if use_zmq:
            try:
                self._transport = _ZmqTransport()
                self._transport_mode_actual = "zmq"
                self._stop_event = mp.get_context("spawn").Event()
                self._backend_profile = self._build_backend_profile("zmq")
                return
            except Exception as exc:
                fallback_reason = str(exc)
                logger.warning(f"ZMQ transport unavailable, using queue fallback: {exc}")
        self._transport = _QueueTransport()
        self._stop_event = self._transport.stop_event
        self._transport_mode_actual = "queue" if self.process_mode else "inline"
        self._transport_fallback_reason = fallback_reason or ("zmq_unavailable" if requested == "zmq" else "")
        self._backend_profile = self._build_backend_profile(self._transport_mode_actual)

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._active:
                return self.get_status()
            self._ensure_transport()
            if not self.process_mode:
                self._active = True
                return self.get_status()
            if self._process is not None and self._process.is_alive():
                self._active = True
                return self.get_status()
            transport_kwargs = dict(self._transport.worker_kwargs() if self._transport is not None else {})
            transport_kwargs.pop("stop_event", None)
            self._process = mp.get_context("spawn").Process(
                target=_daemon_worker,
                kwargs={
                    **transport_kwargs,
                    "stop_event": self._stop_event,
                    "config": self._build_config(),
                    # Keep the child process self-contained; non-picklable service
                    # implementations stay in the parent process and tests can still
                    # inject inline services when process_mode is disabled.
                    "services": None,
                },
                daemon=True,
            )
            self._process.start()
            self._active = True
            return self.get_status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._transport is not None:
                try:
                    self._transport.stop()
                except Exception:
                    pass
            if self._stop_event is not None:
                try:
                    self._stop_event.set()
                except Exception:
                    pass
            if self._process is not None and self._process.is_alive():
                self._process.join(timeout=5.0)
                if self._process.is_alive():
                    try:
                        self._process.terminate()
                    except Exception:
                        pass
            if self._transport is not None:
                try:
                    self._transport.close()
                except Exception:
                    pass
            self._active = False
            return self.get_status()

    def _drain_results(self) -> None:
        if self._transport is None:
            return

        def _frame_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
            frame = payload.get("frame")
            if isinstance(frame, dict):
                return dict(frame)
            return dict(payload or {})

        for message in self._transport.drain():
            if not isinstance(message, dict):
                continue
            if message.get("type") == "observation":
                payload = message.get("payload")
                if isinstance(payload, dict):
                    frame = _frame_from_payload(payload)
                    self.state_cache.remember_observation(
                        {
                            "summary": str(payload.get("summary") or frame.get("summary") or ""),
                            "screenshot_path": str(frame.get("screenshot_path") or ""),
                            "window_metadata": dict(frame.get("window_metadata") or payload.get("window_metadata") or {}),
                            "accessibility": dict(frame.get("accessibility") or payload.get("accessibility") or {}),
                            "vision": dict(frame.get("vision") or payload.get("vision") or {}),
                            "ocr": dict(frame.get("ocr") or payload.get("ocr") or {}),
                            "latency_ms": float(payload.get("latency_ms") or frame.get("latency_ms") or 0.0),
                            "source": str(frame.get("source") or payload.get("source") or "daemon"),
                        }
                    )
                    self._last_snapshot = self.state_cache.snapshot()
            elif message.get("type") == "action_result":
                payload = message.get("payload")
                if isinstance(payload, dict):
                    self.state_cache.remember_action(dict(payload.get("action") or {}), dict(payload))

    def submit(self, action: dict[str, Any]) -> dict[str, Any]:
        payload = dict(action or {})
        interactive = bool(getattr(sys.stdin, "isatty", lambda: False)() and getattr(sys.stdout, "isatty", lambda: False)())
        with self._lock:
            self._last_ticket += 1
            ticket_id = f"ticket-{self._last_ticket}"
            self._drain_results()
            if not bool(payload.get("_security_preapproved", False)):
                try:
                    asyncio.run(
                        self.security.authorize_action(
                            "screen_operator",
                            {
                                "type": str(payload.get("kind") or payload.get("action") or "realtime_action"),
                                "description": str(
                                    payload.get("instruction")
                                    or payload.get("goal")
                                    or payload.get("description")
                                    or payload.get("action")
                                    or payload.get("kind")
                                    or ""
                                ),
                                "approval_required": bool(payload.get("approval_required", False)),
                                "destructive": bool(payload.get("destructive", False)),
                                "needs_network": bool(payload.get("needs_network", False)),
                                "workspace_dir": str(payload.get("workspace_dir") or ""),
                            },
                            {
                                "source": "realtime_actuator",
                                "interactive": interactive,
                                "screenshot_path": str(payload.get("screenshot_path") or ""),
                            },
                        )
                    )
                except PermissionError as exc:
                    return {
                        "ticket_id": ticket_id,
                        "queued": False,
                        "status": "blocked",
                        "action": payload,
                        "error": str(exc),
                        "result": {
                            "success": False,
                            "status": "blocked",
                            "error": str(exc),
                            "errors": ["APPROVAL_DENIED"],
                            "data": {"error_code": "APPROVAL_DENIED"},
                        },
                    }
                payload["_security_preapproved"] = True
            if self.process_mode and self._transport is not None:
                self._transport.send({"type": "action", "ticket_id": ticket_id, "payload": payload})
                return {"ticket_id": ticket_id, "queued": True, "status": "queued", "action": payload}
        # Fallback to inline execution for test/dev or when process mode is disabled.
        payload["_security_preapproved"] = True
        result = asyncio.run(ActionExecutor(services=self.services, state_cache=self.state_cache).execute(payload))
        self._last_snapshot = self.state_cache.snapshot()
        return {
            "ticket_id": ticket_id,
            "queued": bool(self.process_mode),
            "status": str(result.get("status") or ("success" if result.get("success") else "failed")),
            "action": payload,
            "result": result,
        }

    async def submit_async(self, action: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self.submit, action)

    @staticmethod
    def _requires_serial(action: dict[str, Any]) -> bool:
        payload = dict(action or {})
        if bool(payload.get("requires_serial")) or bool(payload.get("approval_required")) or bool(payload.get("serial")):
            return True
        kind = str(payload.get("kind") or payload.get("action") or "").strip().lower()
        return kind in {"send", "delete", "post", "publish", "share", "write", "remove"}

    async def submit_parallel(self, actions: list[dict[str, Any]], max_parallel: int = 3) -> list[dict[str, Any]]:
        items = [dict(action or {}) for action in list(actions or [])]
        if not items:
            return []
        limit = max(1, int(max_parallel or 3))
        results: list[dict[str, Any]] = [dict() for _ in items]

        async def _run_item(index: int, action: dict[str, Any]) -> None:
            results[index] = await self.submit_async(action)

        batch: list[tuple[int, dict[str, Any]]] = []

        async def _flush_batch() -> None:
            if not batch:
                return
            sem = asyncio.Semaphore(limit)

            async def _bounded_run(index: int, action: dict[str, Any]) -> None:
                async with sem:
                    await _run_item(index, action)

            async with asyncio.TaskGroup() as tg:
                for index, action in list(batch):
                    tg.create_task(_bounded_run(index, action))
            batch.clear()

        for index, action in enumerate(items):
            if self._requires_serial(action):
                await _flush_batch()
                results[index] = await self.submit_async(action)
            else:
                batch.append((index, action))
                if len(batch) >= limit:
                    await _flush_batch()
        await _flush_batch()
        return results

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._drain_results()
            if self._last_snapshot:
                return dict(self._last_snapshot)
            return self.state_cache.snapshot()

    def observe_once(self, goal: str = "") -> dict[str, Any]:
        result = asyncio.run(
            ScreenObserver(
                services=self.services,
                screenpipe_client=self._screenpipe_client,
                fps=self.fps,
                region=self.region,
                daemon_id=self.daemon_id,
                state_cache=self.state_cache,
            ).observe_once(goal=goal)
        )
        if isinstance(result, dict) and result.get("success") and isinstance(result.get("frame"), dict):
            self.state_cache.remember_observation(dict(result["frame"]))
            self._last_snapshot = self.state_cache.snapshot()
        return result

    def get_status(self) -> dict[str, Any]:
        process_alive = bool(self._process and self._process.is_alive())
        if not self.process_mode:
            transport_status = {
                "transport_mode": "inline",
                "transport_ready": True,
                "transport_fallback_reason": str(self._transport_fallback_reason or ""),
            }
        else:
            transport_status = dict(self._transport.status() if self._transport is not None else {})
            if not transport_status:
                transport_status = {
                    "transport_mode": str(self._transport_mode_actual or "queue"),
                    "transport_ready": bool(self._transport is not None),
                    "transport_fallback_reason": str(self._transport_fallback_reason or ""),
                }
            transport_status.setdefault("transport_mode", str(self._transport_mode_actual or "queue"))
            transport_status.setdefault("transport_ready", bool(self._transport is not None))
            transport_status.setdefault("transport_fallback_reason", str(self._transport_fallback_reason or ""))
        return {
            "enabled": True,
            "active": bool(self._active),
            "process_mode": bool(self.process_mode),
            "process_alive": process_alive,
            **transport_status,
            "fps": int(self.fps),
            "region": dict(self.region or {}),
            "screenpipe_url": self.screenpipe_url,
            "screenpipe_available": bool(self._screenpipe_client.available()),
            "backend_profile": dict(self._backend_profile or self._build_backend_profile(None)),
            "last_snapshot": dict(self._last_snapshot or self.state_cache.snapshot()),
        }


_REALTIME_ACTUATOR: RealTimeActuator | None = None


def get_realtime_actuator() -> RealTimeActuator:
    global _REALTIME_ACTUATOR
    if _REALTIME_ACTUATOR is None:
        _REALTIME_ACTUATOR = RealTimeActuator()
    return _REALTIME_ACTUATOR


__all__ = [
    "AccessibilityEngine",
    "ActionExecutor",
    "FastVisionTier",
    "RealTimeActuator",
    "ScreenObserver",
    "ScreenpipeClient",
    "StateCache",
    "get_realtime_actuator",
]
