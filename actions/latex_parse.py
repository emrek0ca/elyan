from __future__ import annotations

import re
from typing import Any

from runtime.capability_registry import SafeCapabilityError

_LATEX_MODES = {"parse", "normalize"}


def _normalize_mode(value: str) -> str:
    normalized = str(value or "parse").strip().lower() or "parse"
    if normalized not in _LATEX_MODES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz LaTeX modu.")
    return normalized


def _clean_latex(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise SafeCapabilityError("INVALID_ARGUMENT", "LaTeX ifadesi gerekli.")
    if cleaned.startswith("$$") and cleaned.endswith("$$") and len(cleaned) > 4:
        cleaned = cleaned[2:-2].strip()
    elif cleaned.startswith("$") and cleaned.endswith("$") and len(cleaned) > 2:
        cleaned = cleaned[1:-1].strip()
    # JSON and transport layers can double-escape LaTeX commands such as
    # `\\frac`, but row separators like `\\\\` should remain intact.
    return re.sub(r"\\\\(?=[A-Za-z])", r"\\", cleaned)


def _latex_to_sympy(expression: str) -> Any:
    from latex2sympy2_extended import latex2sympy  # type: ignore[reportMissingImports]

    return latex2sympy(expression)


def latex_parse(expression: str, mode: str = "parse") -> dict[str, Any]:
    normalized_mode = _normalize_mode(mode)
    cleaned = _clean_latex(expression)
    try:
        parsed = _latex_to_sympy(cleaned)
    except SafeCapabilityError:
        raise
    except ModuleNotFoundError as exc:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Bu özellik bu kurulumda hazır değil.") from exc
    except Exception as exc:
        raise SafeCapabilityError("INVALID_ARGUMENT", "LaTeX ifadesi çözümlenemedi.") from exc

    try:
        from sympy import latex as to_latex  # type: ignore[reportMissingImports]
    except ModuleNotFoundError as exc:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Bu özellik bu kurulumda hazır değil.") from exc

    normalized_expression = str(parsed)
    rendered_latex = to_latex(parsed)
    text = (
        f"LaTeX normalize edildi: {normalized_expression}"
        if normalized_mode == "normalize"
        else f"LaTeX parse edildi: {normalized_expression}"
    )
    return {
        "text": text,
        "result": {
            "kind": "latex_parse",
            "inputLatex": cleaned,
            "mode": normalized_mode,
            "normalizedExpression": normalized_expression,
            "sympyExpression": normalized_expression,
            "latex": rendered_latex,
        },
        "artifacts": [],
    }
