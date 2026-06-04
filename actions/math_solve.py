from __future__ import annotations

from typing import Any

from runtime.capability_registry import SafeCapabilityError

_ALLOWED_MODES = {"solve", "simplify", "factor", "expand", "evaluate"}


def _parse_expression(raw_expression: str) -> tuple[Any, Any, Any]:
    from sympy.parsing.sympy_parser import (  # type: ignore[reportMissingImports]
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    transformations = standard_transformations + (
        implicit_multiplication_application,
        convert_xor,
    )
    expression = str(raw_expression or "").strip()
    if not expression:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Matematik ifadesi gerekli.")
    return parse_expr, transformations, expression


def _solve_equation(expression: str) -> tuple[str, dict[str, Any]]:
    from sympy import Eq, latex, simplify, solve  # type: ignore[reportMissingImports]

    parse_expr, transformations, raw = _parse_expression(expression)
    if "=" in raw:
        lhs_raw, rhs_raw = raw.split("=", 1)
        lhs = parse_expr(lhs_raw.strip(), transformations=transformations)
        rhs = parse_expr(rhs_raw.strip(), transformations=transformations)
        equation = Eq(lhs, rhs)
        variables = sorted(equation.free_symbols, key=lambda item: item.name)
        if not variables:
            simplified = simplify(lhs - rhs)
            return (
                f"Denklem farkı: {simplified}",
                {
                    "expression": raw,
                    "mode": "solve",
                    "result": str(simplified),
                    "variables": [],
                    "latex": latex(simplified),
                },
            )
        target = variables[0]
        solutions = solve(equation, target)
        rendered = ", ".join(str(item) for item in solutions) or "çözüm yok"
        return (
            f"Çözüm: {target} = {rendered}" if rendered != "çözüm yok" else "Çözüm bulunamadı.",
            {
                "expression": raw,
                "mode": "solve",
                "result": [str(item) for item in solutions],
                "variables": [symbol.name for symbol in variables],
                "latex": latex(equation),
            },
        )

    expr = parse_expr(raw, transformations=transformations)
    variables = sorted(expr.free_symbols, key=lambda item: item.name)
    if variables:
        target = variables[0]
        solutions = solve(expr, target)
        rendered = ", ".join(str(item) for item in solutions) or "çözüm yok"
        return (
            f"Çözüm: {target} = {rendered}" if rendered != "çözüm yok" else "Çözüm bulunamadı.",
            {
                "expression": raw,
                "mode": "solve",
                "result": [str(item) for item in solutions],
                "variables": [symbol.name for symbol in variables],
                "latex": latex(expr),
            },
        )

    evaluated = simplify(expr)
    return (
        f"Sonuç: {evaluated}",
        {
            "expression": raw,
            "mode": "solve",
            "result": str(evaluated),
            "variables": [],
            "latex": latex(evaluated),
        },
    )


def math_solve(expression: str, mode: str = "solve") -> dict[str, Any]:
    normalized_mode = str(mode or "solve").strip().lower() or "solve"
    if normalized_mode not in _ALLOWED_MODES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz matematik modu.")

    from sympy import N, expand, factor, latex, simplify  # type: ignore[reportMissingImports]

    parse_expr, transformations, raw = _parse_expression(expression)
    if normalized_mode == "solve":
        text, payload = _solve_equation(raw)
        return {
            "text": text,
            "result": {
                "kind": "math_solve",
                **payload,
            },
            "artifacts": [],
        }

    expr = parse_expr(raw, transformations=transformations)
    if normalized_mode == "simplify":
        solved = simplify(expr)
        text = f"Sadeleştirilmiş ifade: {solved}"
    elif normalized_mode == "factor":
        solved = factor(expr)
        text = f"Çarpanlara ayrılmış ifade: {solved}"
    elif normalized_mode == "expand":
        solved = expand(expr)
        text = f"Genişletilmiş ifade: {solved}"
    else:
        solved = N(expr)
        text = f"Sayısal sonuç: {solved}"

    return {
        "text": text,
        "result": {
            "kind": "math_solve",
            "expression": raw,
            "mode": normalized_mode,
            "result": str(solved),
            "variables": [symbol.name for symbol in sorted(expr.free_symbols, key=lambda item: item.name)],
            "latex": latex(solved),
        },
        "artifacts": [],
    }
