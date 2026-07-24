"""Bilgisayar kullanımı döngüsü — P2 (OSWorld sınıfı işler).

NEDEN
-----
``desktop_operator`` zaten algı (observe/locate) ve eylem (execute_action)
primitiflerini veriyordu; eksik olan **döngü ve kanıt**tı: bir tık attıktan
sonra ekranın gerçekten değiştiğini kimse doğrulamıyordu. Bu yüzden çok adımlı
GUI işleri sessizce yanlış yerde devam ediyordu.

DÖNGÜ
-----
    algıla → karar ver → TEK eylem → YENİDEN algıla → değişti mi? → devam/onar

GROUNDING SIRASI (maliyet ve güvenilirlik sırasına göre)
-------------------------------------------------------
1. **Accessibility ağacı** — metin, ucuz, kararlı; öğe adı/rolü ile hedefleme.
2. **Vision** — yalnız a11y hedefi bulamazsa; koordinat tabanlı, kırılgan.

Bu sıra bilinçlidir: a11y varken ekran görüntüsüne düşmek hem pahalı hem
hatalıdır (çözünürlük/tema/ölçek farkları koordinatları bozar).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

COMPUTER_USE_CONTRACT = "elyan.computer_use_loop.v1"

DEFAULT_MAX_ACTIONS = 20
DEFAULT_DEADLINE_SECONDS = 600.0
# Aynı ekran durumunda üst üste bu kadar eylem sonuç vermezse takıldı sayılır.
NO_CHANGE_LIMIT = 3


@dataclass(slots=True)
class ScreenState:
    """Bir algı turunun sınırlanmış özeti."""

    signature: str
    summary: str
    elements: list[dict[str, Any]] = field(default_factory=list)
    source: str = "accessibility"  # "accessibility" | "vision"

    def to_context(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "summary": self.summary[:1_200],
            "elements": self.elements[:40],
        }


@dataclass(slots=True)
class ComputerUseResult:
    ok: bool
    summary: str
    stop_reason: str
    actions_used: int
    history: list[dict[str, Any]] = field(default_factory=list)
    error_code: str = ""

    def trace(self) -> dict[str, Any]:
        return {
            "contract": COMPUTER_USE_CONTRACT,
            "ok": self.ok,
            "stopReason": self.stop_reason,
            "actionsUsed": self.actions_used,
            "errorCode": self.error_code,
            "history": self.history[-16:],
        }


def _text_of(value: Any, limit: int = 2_000) -> str:
    text = str(value or "").strip()
    return text[:limit]


def build_screen_state(observation: dict[str, Any]) -> ScreenState:
    """Ham ``observe_screen`` sonucunu sınırlanmış bir duruma çevirir.

    Accessibility öğeleri varsa onlar otoritedir; yoksa görsel özete düşülür.
    ``signature`` değişim tespiti içindir — ekran gerçekten değişti mi?
    """
    result = observation.get("result") if isinstance(observation.get("result"), dict) else observation
    result = result if isinstance(result, dict) else {}

    raw_elements = result.get("elements")
    if not isinstance(raw_elements, list):
        raw_elements = result.get("accessibilityElements")
    elements: list[dict[str, Any]] = []
    if isinstance(raw_elements, list):
        for item in raw_elements[:60]:
            if not isinstance(item, dict):
                continue
            label = _text_of(item.get("title") or item.get("label") or item.get("name"), 120)
            role = _text_of(item.get("role") or item.get("type"), 48)
            if not label and not role:
                continue
            entry: dict[str, Any] = {"label": label, "role": role}
            if item.get("enabled") is not None:
                entry["enabled"] = bool(item.get("enabled"))
            elements.append(entry)

    summary = _text_of(
        result.get("analysis") or result.get("summary") or result.get("text")
    )
    source = "accessibility" if elements else "vision"
    signature = str(
        hash((tuple((e["label"], e["role"]) for e in elements), summary[:400]))
    )
    return ScreenState(
        signature=signature,
        summary=summary,
        elements=elements,
        source=source,
    )


def run_computer_use_loop(
    *,
    goal: str,
    observe: Callable[[], dict[str, Any]],
    decide_action: Callable[[dict[str, Any]], dict[str, Any]],
    act: Callable[[dict[str, Any]], dict[str, Any]],
    max_actions: int = DEFAULT_MAX_ACTIONS,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    should_cancel: Callable[[], bool] | None = None,
) -> ComputerUseResult:
    """GUI hedefini algı-eylem-doğrulama döngüsüyle yürütür.

    ``decide_action(context) -> {"kind": "act"|"done"|"give_up", ...}``
    ``act(action) -> {"ok": bool, ...}``
    Her eylemden sonra ekran YENİDEN algılanır ve değişim kanıtı aranır; kanıt
    yoksa aynı eylem körü körüne tekrarlanmaz.
    """
    history: list[dict[str, Any]] = []
    started_at = time.monotonic()
    actions_used = 0
    unchanged_streak = 0

    def finish(ok: bool, summary: str, reason: str, code: str = "") -> ComputerUseResult:
        return ComputerUseResult(
            ok=ok,
            summary=summary,
            stop_reason=reason,
            actions_used=actions_used,
            history=history,
            error_code=code,
        )

    try:
        state = build_screen_state(observe())
    except Exception:
        return finish(False, "Ekran algılanamadı.", "perception_failed", "PERCEPTION_FAILED")

    bounded_actions = max(1, min(int(max_actions or DEFAULT_MAX_ACTIONS), 60))

    while True:
        if should_cancel is not None and should_cancel():
            return finish(False, "İşlem iptal edildi.", "cancelled", "CANCELLED")
        if actions_used >= bounded_actions:
            return finish(
                False, "Eylem bütçesi doldu.", "action_budget_exhausted", "BUDGET_EXHAUSTED"
            )
        if time.monotonic() - started_at > max(1.0, float(deadline_seconds)):
            return finish(False, "Süre bütçesi doldu.", "deadline_exceeded", "TIMEOUT")

        context = {
            "contract": COMPUTER_USE_CONTRACT,
            "goal": goal,
            "screen": state.to_context(),
            "history": history[-8:],
            "actionsRemaining": bounded_actions - actions_used,
            # a11y hedefi yoksa modele açıkça söyle: koordinata düşmeden önce
            # pencereyi öne getirmek/kaydırmak gerekebilir.
            "groundingHint": (
                "Accessibility öğeleri mevcut — hedefi label/role ile seç."
                if state.source == "accessibility"
                else "Accessibility öğesi yok; önce pencereyi öne getir ya da görsel konumla."
            ),
        }
        if unchanged_streak:
            context["warning"] = (
                f"Son {unchanged_streak} eylem ekranda değişiklik üretmedi. "
                "Aynı hedefi tekrar deneme; farklı bir öğe ya da yaklaşım seç."
            )

        try:
            decision = decide_action(context)
        except Exception:
            return finish(False, "Karar alınamadı.", "decider_error", "DECIDER_FAILED")

        kind = str((decision or {}).get("kind", "") or "").strip().lower()
        if kind in {"done", "finish", "complete"}:
            return finish(True, _text_of((decision or {}).get("summary")) or "Hedef tamamlandı.", "completed")
        if kind in {"give_up", "ask", "blocked"}:
            return finish(
                False,
                _text_of((decision or {}).get("summary")) or "Hedefe ulaşılamadı.",
                "gave_up",
                "GAVE_UP",
            )

        before_signature = state.signature
        actions_used += 1
        try:
            outcome = act(decision)
        except Exception as exc:
            outcome = {"ok": False, "error": {"message": str(exc)}}

        # DOĞRULAMA: eylemden sonra ekranı YENİDEN algıla ve değişim ara.
        try:
            state = build_screen_state(observe())
        except Exception:
            return finish(False, "Eylem sonrası ekran algılanamadı.", "perception_failed", "PERCEPTION_FAILED")

        changed = state.signature != before_signature
        unchanged_streak = 0 if changed else unchanged_streak + 1
        history.append(
            {
                "action": {
                    key: value
                    for key, value in (decision or {}).items()
                    if key in {"kind", "target", "label", "role", "text", "coordinate", "rationale"}
                },
                "ok": bool((outcome or {}).get("ok", False)),
                "screenChanged": changed,
                "source": state.source,
            }
        )

        if unchanged_streak >= NO_CHANGE_LIMIT:
            return finish(
                False,
                "Eylemler ekranda değişiklik üretmedi; güvenli şekilde durduruldu.",
                "no_progress",
                "NO_PROGRESS",
            )
