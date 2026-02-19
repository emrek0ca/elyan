"""
core/intent_parser.py — Backward-compatibility shim
BUG-FUNC-004: Gerçek implementasyon core/intent_parser/ paketine taşındı.
Bu dosya eski import'ları kırmamak için mevcuttur.
"""
from core.intent_parser import IntentParser, get_intent_parser  # noqa: F401

__all__ = ["IntentParser", "get_intent_parser"]
