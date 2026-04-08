"""
api/jarvis_api.py
───────────────────────────────────────────────────────────────────────────────
Jarvis API blueprint

Routes:
  POST /api/jarvis/voice/trigger        — manually fire voice pipeline
  GET  /api/jarvis/status               — pipeline + wake-word state
  POST /api/jarvis/chat                 — single-shot text command → JSON response
  POST /api/jarvis/chat/stream          — streaming SSE text command → chunks
"""
from __future__ import annotations

import asyncio
import json as _json
import threading
import time

try:
    from flask import Blueprint, Response, jsonify, request as flask_request, stream_with_context
    _FLASK_OK = True
except ImportError:
    _FLASK_OK = False
    Blueprint = None  # type: ignore[misc,assignment]
    jsonify = None    # type: ignore[assignment]

from utils.logger import get_logger

logger = get_logger("jarvis_api")

if not _FLASK_OK:
    logger.warning(
        "api/jarvis_api: Flask not installed — Jarvis API endpoints will be unavailable. "
        "Fix: pip install flask flask-cors"
    )


def create_jarvis_blueprint():
    """Returns a Flask Blueprint, or None if Flask is not installed."""
    if not _FLASK_OK:
        return None

    bp = Blueprint("jarvis", __name__)

    # ── Voice trigger ─────────────────────────────────────────────────────────

    @bp.route("/api/jarvis/voice/trigger", methods=["POST"])
    def voice_trigger():
        """Fire a voice interaction cycle from the UI button."""
        try:
            from core.voice.voice_pipeline import get_voice_pipeline
            pipeline = get_voice_pipeline()
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(pipeline.trigger(), loop)
            else:
                loop.run_until_complete(pipeline.trigger())
            return jsonify({"status": "ok", "pipeline_state": pipeline.state.value})
        except Exception as exc:
            logger.warning(f"Voice trigger error: {exc}")
            return jsonify({"status": "error", "detail": str(exc)}), 500

    # ── Status ────────────────────────────────────────────────────────────────

    @bp.route("/api/jarvis/status", methods=["GET"])
    def jarvis_status():
        """Return current pipeline + wake-word detector state."""
        try:
            from core.voice.voice_pipeline import get_voice_pipeline
            from core.voice.wake_word import get_wake_word_detector
            pipeline  = get_voice_pipeline()
            detector  = get_wake_word_detector()
            return jsonify({
                "pipeline_state": pipeline.state.value,
                "wake_backend":   detector.backend,
                "wake_running":   detector.running,
            })
        except Exception as exc:
            logger.warning(f"Jarvis status error: {exc}")
            return jsonify({"pipeline_state": "idle", "wake_backend": "none", "wake_running": False})

    # ── Single-shot chat ──────────────────────────────────────────────────────

    @bp.route("/api/jarvis/chat", methods=["POST"])
    def chat():
        """Non-streaming: send text, get full response as JSON."""
        body    = flask_request.get_json(silent=True) or {}
        text    = str(body.get("text", "")).strip()
        user_id = str(body.get("user_id", "desktop"))
        channel = str(body.get("channel", "desktop"))

        if not text:
            return jsonify({"error": "text required"}), 400

        try:
            from core.jarvis.jarvis_core import get_jarvis_core
            jc   = get_jarvis_core()
            loop = _get_or_create_loop()
            resp = loop.run_until_complete(jc.handle(text, channel, user_id))
            return jsonify({
                "text":       resp.text,
                "duration_s": resp.duration_s,
                "metadata":   resp.metadata,
            })
        except Exception as exc:
            logger.error(f"Chat error: {exc}")
            return jsonify({"error": str(exc)}), 500

    # ── Streaming SSE chat ────────────────────────────────────────────────────

    @bp.route("/api/jarvis/chat/stream", methods=["POST"])
    def chat_stream():
        """Streaming SSE: Ollama chunks arrive in real-time.

        Client subscribes via EventSource or fetch + ReadableStream.
        Each event: data: {"chunk": "..."}\n\n
        Final event: data: [DONE]\n\n
        """
        body    = flask_request.get_json(silent=True) or {}
        text    = str(body.get("text", "")).strip()
        user_id = str(body.get("user_id", "desktop"))

        if not text:
            return jsonify({"error": "text required"}), 400

        def generate():
            """Blocking SSE generator — runs in Flask request thread."""
            try:
                from core.jarvis.jarvis_core import get_jarvis_core, _ollama_stream
                jc = get_jarvis_core()

                # First classify intent — if it's an executable action,
                # run it fully and emit the single result as one chunk.
                intent = jc.classify_intent(text)
                EXECUTABLE = {"system_control", "monitoring", "information", "communication"}

                if intent.category.value in EXECUTABLE:
                    loop = _get_or_create_loop()
                    resp = loop.run_until_complete(jc.handle(text, "desktop", user_id))
                    yield f"data: {_json.dumps({'chunk': resp.text})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # Conversation intent → Ollama streaming
                chunks: list[str] = []

                def on_chunk(c: str):
                    chunks.append(c)

                loop = _get_or_create_loop()

                # Check for pending approval first
                resp = loop.run_until_complete(jc.handle(text, "desktop", user_id))
                if resp.metadata.get("requires_approval") or "Onay Gerekiyor" in resp.text:
                    yield f"data: {_json.dumps({'chunk': resp.text})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # True streaming for conversation
                chunks.clear()
                full = loop.run_until_complete(_ollama_stream(text, on_chunk=on_chunk))

                if chunks:
                    for chunk in chunks:
                        yield f"data: {_json.dumps({'chunk': chunk})}\n\n"
                else:
                    # Fallback — emit full response at once
                    fallback = full or resp.text
                    yield f"data: {_json.dumps({'chunk': fallback})}\n\n"

                yield "data: [DONE]\n\n"

            except GeneratorExit:
                pass
            except Exception as exc:
                logger.error(f"Stream error: {exc}")
                yield f"data: {_json.dumps({'chunk': f'Hata: {exc}'})}\n\n"
                yield "data: [DONE]\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control":   "no-cache",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    return bp


# ── Helpers ───────────────────────────────────────────────────────────────────

_loop_lock = threading.Lock()
_thread_local = threading.local()


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Get or create an event loop for the current thread (Flask worker threads)."""
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            return loop
    except RuntimeError:
        pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop
