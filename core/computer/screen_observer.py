"""
core/computer/screen_observer.py
───────────────────────────────────────────────────────────────────────────────
ScreenObserver — macOS screen capture + Qwen2.5-VL vision analysis.

Change detection: pixel-difference proxy for SSIM.
  change_score = mean(abs(frame_t - frame_{t-1})) / 255.0
  alert if score > 0.05
"""
from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import os
from pathlib import Path
from typing import Any, Callable, Awaitable
from utils.logger import get_logger

logger = get_logger("screen_observer")


def _resolve_ollama_endpoint() -> str:
    base = str(os.getenv("OLLAMA_URL") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").strip().rstrip("/")
    return base if base.endswith("/api/generate") else f"{base}/api/generate"


_VISION_MODEL = "qwen2.5-vl:7b"
_CHANGE_THRESHOLD = 0.05


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            payload = json.loads(raw[start:end])
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None
    return None


class ScreenObserver:
    def __init__(self) -> None:
        self._watching = False
        self._last_frame: bytes | None = None

    # ── Capture ─────────────────────────────────────────────────────────────

    async def capture(self) -> bytes:
        """Take screenshot via macOS screencapture, return PNG bytes."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", "-t", "png", path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            return Path(path).read_bytes()
        except Exception as exc:
            logger.debug(f"screencapture failed: {exc}")
            return b""
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

    # ── Describe ─────────────────────────────────────────────────────────────

    async def describe(self, image_bytes: bytes, prompt: str = "Ekranda ne görüyorsun? Kısaca açıkla.") -> str:
        """Ask Ollama Qwen2.5-VL to describe the screenshot."""
        if not image_bytes:
            return ""
        try:
            import aiohttp
        except ImportError:
            return ""
        b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": _VISION_MODEL,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(_resolve_ollama_endpoint(), json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return str(data.get("response", "")).strip()
        except Exception as exc:
            logger.debug(f"Vision describe failed: {exc}")
        return ""

    async def find_element(self, description: str) -> dict[str, Any] | None:
        """Capture screen and ask Ollama to locate an element by description."""
        frame = await self.capture()
        if not frame:
            return None
        prompt = (
            f"Ekranda '{description}' öğesini bul. "
            "Sadece JSON formatında koordinat döndür: {\"x\": 100, \"y\": 200, \"confidence\": 0.9}. "
            "Bulamazsan {\"confidence\": 0.0} döndür."
        )
        raw = await self.describe(frame, prompt)
        obj = _extract_json_object(raw)
        if obj and obj.get("confidence", 0) > 0.3:
            return obj
        return None

    # ── Change Detection ──────────────────────────────────────────────────────

    def _change_score(self, a: bytes, b: bytes) -> float:
        """Pixel-difference proxy for structural similarity."""
        if not a or not b or len(a) != len(b):
            return 1.0
        try:
            ba, bb = bytearray(a[:4096]), bytearray(b[:4096])
            total = sum(abs(int(x) - int(y)) for x, y in zip(ba, bb))
            return total / (255.0 * len(ba))
        except Exception:
            return 0.0

    # ── Watch Loop ────────────────────────────────────────────────────────────

    async def watch(
        self,
        callback: Callable[[bytes, str], Awaitable[None]],
        interval_s: float = 2.0,
    ) -> None:
        """Continuous screen watch — calls callback(frame, description) on change."""
        self._watching = True
        try:
            while self._watching:
                try:
                    frame = await self.capture()
                    if frame and self._change_score(self._last_frame or b"", frame) > _CHANGE_THRESHOLD:
                        self._last_frame = frame
                        desc = await self.describe(frame)
                        await callback(frame, desc)
                except Exception as exc:
                    logger.debug(f"watch iteration error: {exc}")
                await asyncio.sleep(interval_s)
        finally:
            self._watching = False

    def stop_watch(self) -> None:
        self._watching = False


_instance: ScreenObserver | None = None

def get_screen_observer() -> ScreenObserver:
    global _instance
    if _instance is None:
        _instance = ScreenObserver()
    return _instance

__all__ = ["ScreenObserver", "get_screen_observer"]
