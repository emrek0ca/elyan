"""Ders damıtma — deneyimden öğrenme (desen yazmadan).

NEDEN
-----
`learning_store` yalnız SAYAÇ tutar ("bu yetenek %70 başarılı"); sayaç bir
sonraki turda ne yapılacağını söylemez. Gerçek iyileşme, yaşanan bir hatanın
**tek cümlelik derse** dönüşüp benzer iş geldiğinde geri çağrılmasıyla olur.
Bu, kural yazmanın (yasak) tam tersidir: kuralı biz değil, sistem kendi
deneyiminden üretir; biz yalnız kaydı, sınırı ve alaka kapısını sağlarız.

DEĞİŞMEZLER
-----------
* **Ham içerik saklanmaz.** Ders tek cümledir; kullanıcı metni, dosya içeriği
  ya da kişisel veri taşımaz. Alaka anahtarı yalnız yetenek adları + hata
  sınıfıdır.
* **Alaka kapısı zorunlu.** Alakasız hatırlatma hatırlamamaktan kötüdür
  (modeli dağıtır): ders ancak o turun yetenek/hata bağlamıyla örtüşürse
  yüzeye çıkar.
* **Sınırlı ve tazelik-farkında.** En çok ``_MAX_LESSONS`` ders; en eski düşer.
* Ders bir SÖZ DEĞİL gözlemdir: üretimi başarısız olursa katman sessizce
  devre dışı kalır, akış düşmez.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from runtime import state_store

LESSON_CONTRACT = "elyan.lesson.v1"

_MAX_LESSONS = 24
_MAX_LESSON_CHARS = 180

# UNUTMA: bir ders operasyonel bir gözlemdir, ebedi bir doğru değil. Aylar önce
# "şu araç şu hatayı veriyor" diye öğrenilen ders, hata düzeltildikten sonra
# modeli YANLIŞ yönlendirir — bayat hatırlatma, hatırlamamaktan kötüdür.
# Bu, `situational_context.recent_output_is_fresh` ile aynı ilkedir; episodik
# bellekte eksikti. Zamansız kayıt bayat sayılır (fail-closed).
LESSON_TTL_DAYS = 30


def lesson_is_fresh(entry: Any, *, now: dt.datetime | None = None) -> bool:
    """Bir dersin hâlâ güvenle hatırlatılabilir olduğunu söyler."""
    if not isinstance(entry, dict):
        return False
    raw_recorded = str(entry.get("recordedAt", "") or "").strip()
    if not raw_recorded:
        # Yaşı bilinemeyen kayıt bayat sayılır — sessizce eskimiş ders taşımayız.
        return False
    try:
        recorded = dt.datetime.fromisoformat(raw_recorded.replace("Z", "+00:00"))
        if recorded.tzinfo is not None:
            recorded = recorded.replace(tzinfo=None)
    except ValueError:
        return False
    age_days = ((now or dt.datetime.now()) - recorded).total_seconds() / 86_400
    return -1 <= age_days <= LESSON_TTL_DAYS

_DISTILL_PROMPT = (
    "Aşağıda bir görev yürütmesinin SONUCU var. Bir sonraki benzer işte işe "
    "yarayacak TEK cümlelik ders çıkar.\n"
    "KURALLAR: 1) Somut ve eyleme dönük olsun ('X yaparken Y gerekir'). "
    "2) Kişisel veri, dosya içeriği veya isim TAŞIMA. 3) Genel geçer öğüt "
    "verme ('dikkatli ol' gibi) — dersin yoksa boş string döndür. "
    "4) SADECE tek JSON döndür: {\"lesson\":\"...\"}"
)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _lesson_bucket(state: dict[str, Any]) -> list[dict[str, Any]]:
    intelligence = state.setdefault("taskIntelligence", {})
    if not isinstance(intelligence, dict):
        intelligence = {}
        state["taskIntelligence"] = intelligence
    lessons = intelligence.get("lessons")
    if not isinstance(lessons, list):
        lessons = []
        intelligence["lessons"] = lessons
    return lessons


def _normalize_keys(capabilities: Any) -> list[str]:
    if not isinstance(capabilities, (list, tuple, set)):
        return []
    seen: list[str] = []
    for item in capabilities:
        name = str(item or "").strip().lower()[:80]
        if name and name not in seen:
            seen.append(name)
    return seen[:6]


def record_lesson(
    lesson: str,
    *,
    capabilities: Any = (),
    error_class: str = "",
    ok: bool = False,
) -> bool:
    """Bir dersi kaydeder. Boş/çok kısa ders yazılmaz (gürültü üretmemek için)."""
    text = " ".join(str(lesson or "").split()).strip()[:_MAX_LESSON_CHARS]
    if len(text) < 12:
        return False
    entry = {
        "contract": LESSON_CONTRACT,
        "lesson": text,
        "capabilities": _normalize_keys(capabilities),
        "errorClass": str(error_class or "").strip().lower()[:64],
        "ok": bool(ok),
        "recordedAt": _now(),
    }
    try:
        with state_store._LOCK:
            state = state_store.load_state()
            lessons = _lesson_bucket(state)
            # Aynı ders tekrar yazılmaz; yalnız tazelenir.
            for existing in lessons:
                if isinstance(existing, dict) and existing.get("lesson") == text:
                    existing["recordedAt"] = entry["recordedAt"]
                    state_store.save_state(state)
                    return True
            lessons.append(entry)
            del lessons[:-_MAX_LESSONS]
            state_store.save_state(state)
        return True
    except Exception:  # pragma: no cover - öğrenme kaydı yürütmeyi düşürmesin
        return False


def distill_lesson(
    *,
    goal: str,
    outcome_summary: str,
    capabilities: Any = (),
    error_class: str = "",
    ok: bool = False,
    send_prompt: Callable[[str], str] | None = None,
) -> str:
    """Yürütmeden tek cümlelik ders damıtır.

    Model erişilebilirse ondan; erişilemezse yalnız GERÇEK bir hata sınıfı
    varsa deterministik bir ders üretilir. Başarılı ve olaysız turlarda ders
    üretilmez — her turdan ders çıkarmak belleği gürültüyle doldurur."""
    if send_prompt is not None:
        payload = (
            f"{_DISTILL_PROMPT}\n\nGÖREV: {str(goal or '')[:240]}\n"
            f"SONUÇ: {'başarılı' if ok else 'başarısız'}\n"
            f"HATA SINIFI: {str(error_class or 'yok')[:64]}\n"
            f"ÖZET: {str(outcome_summary or '')[:600]}"
        )
        try:
            raw = send_prompt(payload)
        except Exception:
            raw = ""
        if raw:
            from runtime.agent_decider import extract_json_object

            parsed = extract_json_object(raw)
            if isinstance(parsed, dict):
                return " ".join(str(parsed.get("lesson", "") or "").split())[
                    :_MAX_LESSON_CHARS
                ]
    if not ok and str(error_class or "").strip():
        names = _normalize_keys(capabilities)
        target = names[0] if names else "bu iş"
        return f"{target} çalışırken '{str(error_class).strip()[:40]}' hatası alındı; önce ön koşulu doğrula."
    return ""


def relevant_lessons(
    *,
    capabilities: Any = (),
    error_class: str = "",
    limit: int = 3,
) -> list[str]:
    """O turun bağlamıyla ÖRTÜŞEN dersleri döndürür (alaka kapısı).

    Örtüşme yoksa BOŞ döner — alakasız hatırlatma yapılmaz. Bu, "her şeyi
    hatırla" ile "doğru zamanda hatırla" arasındaki farktır."""
    wanted = set(_normalize_keys(capabilities))
    wanted_error = str(error_class or "").strip().lower()[:64]
    if not wanted and not wanted_error:
        return []
    try:
        snapshot = state_store.snapshot()
    except Exception:
        return []
    intelligence = snapshot.get("taskIntelligence", {})
    lessons = intelligence.get("lessons") if isinstance(intelligence, dict) else None
    if not isinstance(lessons, list):
        return []
    scored: list[tuple[int, str, str]] = []
    for entry in lessons:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("lesson", "") or "").strip()
        if not text:
            continue
        # UNUTMA KAPISI: süresi geçmiş ders hatırlatılmaz.
        if not lesson_is_fresh(entry):
            continue
        entry_caps = set(_normalize_keys(entry.get("capabilities")))
        overlap = len(entry_caps & wanted)
        if wanted_error and str(entry.get("errorClass", "") or "") == wanted_error:
            overlap += 2
        if overlap <= 0:
            continue
        scored.append((overlap, str(entry.get("recordedAt", "") or ""), text))
    # Alaka birinci, tazelik ikinci ölçüt. Eşit alakada YENİ ders kazanır:
    # önceki sürüm iki ayrı sort yüzünden eskiyi öne alıyordu — sistem
    # öğrendikçe eski gözlemi tekrarlıyordu.
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [text for _score, _at, text in scored[: max(0, int(limit or 0))]]
