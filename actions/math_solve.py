from __future__ import annotations

import re
from typing import Any

from runtime.capability_registry import SafeCapabilityError

_ALLOWED_MODES = {"solve", "simplify", "factor", "expand", "evaluate"}

# LLM planları matematik ifadesini sık "kirli" verir: para birimi/birim ekli
# ("44700 TL"), binlik ayraçlı ("12.000,50"), yüzde ("%20"), ya da doğal-dil
# gürültüsüyle. Aracı bu varyansa dayanıklı yaparız → planlayıcı kusursuz argüman
# vermek zorunda kalmaz (tüm araçlar için doğru yaklaşım: forgiving tools).
_CURRENCY_UNIT_RE = re.compile(
    r"(?i)\b(tl|try|usd|eur|adet|kg|gr|litre|lt|₺|\$|€|£)\b|[₺$€£]"
)
_THOUSANDS_RE = re.compile(r"(?<=\d)\.(?=\d{3}(\D|$))")


def _sanitize_math_expression(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    # Para birimi / birim sembollerini at.
    text = _CURRENCY_UNIT_RE.sub(" ", text)
    # Yüzde: "%20" → "(20/100)", "20%" → "(20/100)".
    text = re.sub(r"%\s*(\d+(?:[.,]\d+)?)", r"(\1/100)", text)
    text = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", r"(\1/100)", text)
    # Türkçe binlik ayracı (12.000 → 12000) ve ondalık virgülü (,5 → .5).
    text = _THOUSANDS_RE.sub("", text)
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    # Yalnız matematik anlamlı karakterleri koru (harfler = değişkenler kalır).
    text = re.sub(r"[^0-9A-Za-z+\-*/^%().,=\s]", " ", text)
    return " ".join(text.split()).strip()


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
    expression = _sanitize_math_expression(raw_expression)
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


def math_solve(expression: str = "", mode: str = "solve", **kwargs: Any) -> dict[str, Any]:
    # LLM ifadeyi bazen farklı anahtarla verir; hepsini kabul et (forgiving tool).
    if not str(expression or "").strip():
        for alt in ("query", "text", "problem", "input", "expr", "equation", "formula"):
            candidate = kwargs.get(alt)
            if str(candidate or "").strip():
                expression = str(candidate)
                break
    normalized_mode = str(mode or "solve").strip().lower() or "solve"
    if normalized_mode not in _ALLOWED_MODES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz matematik modu.")

    from sympy import N, expand, factor, latex, simplify  # type: ignore[reportMissingImports]

    # İfadede hiç sayı yoksa (planlayıcı rakam yerine açıklama geçmiş — "faturaların
    # toplamı") sympy'yi zorlamadan NET, okunaklı hata döndür (çökme/opak
    # TOOL_EXECUTION_FAILED yerine ReAct replan'in düzeltebileceği yönlendirici
    # mesaj).
    sanitized_preview = _sanitize_math_expression(expression)
    if not re.search(r"\d", sanitized_preview):
        raise SafeCapabilityError(
            "INVALID_ARGUMENT",
            "Matematik ifadesi sayısal olmalı; açıklama değil rakamlı ifade ver "
            "(ör. '12000+8500+15000+9200' veya '(sum)*(20/100)').",
        )

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
