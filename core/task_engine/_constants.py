"""
core/task_engine/_constants.py
Sabit frozenset'ler — Sprint K modüler bölünme.
"""
from typing import FrozenSet

# LLM'in hallucinate ettiği gerçek tool olmayan action isimleri
_NON_TOOL_ACTIONS: FrozenSet[str] = frozenset({
    "chat", "sohbet", "ask_for_confirmation", "clarify", "confirm",
    "greet", "greeting", "thank", "farewell", "acknowledge",
    "respond", "reply", "conversation", "yanit", "sorgu",
    "ask", "question", "answer", "help", "explain", "unknown",
    "ask_user", "request_info", "get_input", "prompt_user",
    "wait", "pause", "think", "analyze", "process",
})

# Explicit approval is mandatory before these actions are executed.
_EXPLICIT_APPROVAL_ACTIONS: FrozenSet[str] = frozenset({
    "shutdown_system",
    "restart_system",
    "sleep_system",
    "lock_screen",
})
