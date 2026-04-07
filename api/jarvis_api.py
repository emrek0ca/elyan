"""
api/jarvis_api.py
───────────────────────────────────────────────────────────────────────────────
Jarvis API blueprint — voice trigger + status endpoints

Routes:
  POST /api/jarvis/voice/trigger   — manually fire voice pipeline
  GET  /api/jarvis/status          — pipeline + wake-word state
"""
from __future__ import annotations

from flask import Blueprint, jsonify
from utils.logger import get_logger

logger = get_logger("jarvis_api")


def create_jarvis_blueprint() -> Blueprint:
    bp = Blueprint("jarvis", __name__)

    @bp.route("/api/jarvis/voice/trigger", methods=["POST"])
    def voice_trigger():
        """Fire a voice interaction cycle from the UI button."""
        import asyncio
        try:
            from core.voice.voice_pipeline import get_voice_pipeline
            pipeline = get_voice_pipeline()

            # Schedule trigger in the running event loop (non-blocking)
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(pipeline.trigger(), loop)
            else:
                loop.run_until_complete(pipeline.trigger())

            return jsonify({"status": "ok", "pipeline_state": pipeline.state.value})
        except Exception as exc:
            logger.warning(f"Voice trigger error: {exc}")
            return jsonify({"status": "error", "detail": str(exc)}), 500

    @bp.route("/api/jarvis/status", methods=["GET"])
    def jarvis_status():
        """Return current pipeline + wake-word detector state."""
        try:
            from core.voice.voice_pipeline import get_voice_pipeline
            from core.voice.wake_word import get_wake_word_detector

            pipeline = get_voice_pipeline()
            detector = get_wake_word_detector()

            return jsonify({
                "pipeline_state": pipeline.state.value,
                "wake_backend": detector.backend,
                "wake_running": detector.running,
            })
        except Exception as exc:
            logger.warning(f"Jarvis status error: {exc}")
            return jsonify({"pipeline_state": "idle", "wake_backend": "none", "wake_running": False})

    return bp
