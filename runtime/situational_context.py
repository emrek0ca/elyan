"""Durumsal bağlam füzyonu — Elyan'a "yanında biri var" hissi veren katman.

NEDEN
-----
Bir LLM ile gerçek bir sekreter arasındaki fark daha güzel cümle kurmak değildir;
**durumu bilmektir.** İyi bir sekreter "hangi başlıkla kaydedeyim?" diye sormaz —
takvimindeki toplantının adını bilir. "Nereye kaydedeyim?" demez — alışkanlığını
bilir. Sabah 9'da farklı, gece 23'te farklı davranır.

Elyan'da sinyaller (takvim, konum, sağlık digest'i, aktif uygulama, son üretilen
dosyalar) mevcuttu ama anlama katmanına HİÇ girmiyordu. Sonuç: her mesaj sıfırdan,
bağlamsız yorumlanıyor ve model bariz şeyleri soruyordu — "canlı değil, robot"
hissinin teknik kaynağı buydu.

Bu modül üç şey üretir:
  1. ``SituationalContext`` — o anki durumun sınırlanmış, gizlilik-farkında özeti
  2. ``derive_defaults`` — soru sormak yerine isabetli varsayımlar (başlık, hedef)
  3. ``liveness_cues`` — cevabın doğal biçimde değinebileceği gerçek durum ipuçları

GİZLİLİK
--------
Sağlık gibi hassas sinyaller **asla ham taşınmaz**: yalnız türetilmiş, kaba bir
işaret (ör. "yoğun gün") üretilir ve hassas alanlar dışarı çıkmaz. Sinyal yoksa
katman sessizce devre dışı kalır — uydurma bağlam üretmez.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

SITUATION_CONTRACT = "elyan.situation.v1"

# Hassas sinyaller: modele ham gitmez, yalnız türetilmiş işaret üretir.
_SENSITIVE_KINDS = {"health", "saglik", "medical", "location_precise"}


def _clip(value: Any, limit: int = 160) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _part_of_day(now: dt.datetime) -> str:
    hour = now.hour
    if hour < 6:
        return "gece"
    if hour < 12:
        return "sabah"
    if hour < 17:
        return "öğleden sonra"
    if hour < 22:
        return "akşam"
    return "gece"


@dataclass(slots=True)
class SituationalContext:
    """O anki durumun sınırlanmış özeti."""

    part_of_day: str = ""
    weekday: str = ""
    next_event_title: str = ""
    next_event_in_minutes: int | None = None
    location_hint: str = ""
    active_app: str = ""
    recent_artifacts: list[str] = field(default_factory=list)
    load_hint: str = ""  # "yoğun" | "sakin" | "" (hassas veriden TÜRETİLMİŞ)
    signal_kinds: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.next_event_title,
                self.location_hint,
                self.active_app,
                self.recent_artifacts,
                self.load_hint,
            ]
        )

    def to_prompt_context(self) -> dict[str, Any]:
        """Modele gidecek biçim. Hassas ham veri YOKTUR."""
        payload: dict[str, Any] = {
            "contract": SITUATION_CONTRACT,
            "partOfDay": self.part_of_day,
            "weekday": self.weekday,
        }
        if self.next_event_title:
            payload["nextEvent"] = {
                "title": self.next_event_title,
                **(
                    {"inMinutes": self.next_event_in_minutes}
                    if self.next_event_in_minutes is not None
                    else {}
                ),
            }
        if self.location_hint:
            payload["location"] = self.location_hint
        if self.active_app:
            payload["activeApp"] = self.active_app
        if self.recent_artifacts:
            payload["recentFiles"] = self.recent_artifacts[:4]
        if self.load_hint:
            payload["dayLoad"] = self.load_hint
        return payload


def _read_signals(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    for key in ("worldSignals", "world_signals", "signals"):
        for source in (state, runtime):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def gather_situation(
    state: dict[str, Any] | None = None,
    *,
    now: dt.datetime | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
) -> SituationalContext:
    """Mevcut sinyallerden durumsal bağlam kurar.

    Sinyal yoksa yalnız zaman bilgisi taşıyan, büyük ölçüde boş bir bağlam döner —
    **uydurma yapılmaz.**"""
    moment = now or dt.datetime.now()
    weekdays = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    situation = SituationalContext(
        part_of_day=_part_of_day(moment),
        weekday=weekdays[moment.weekday()],
    )

    signals = _read_signals(state)
    kinds: list[str] = []
    busy_markers = 0
    for signal in signals[:24]:
        kind = str(signal.get("kind") or signal.get("type") or "").strip().lower()
        if kind:
            kinds.append(kind)
        if kind in _SENSITIVE_KINDS:
            # Hassas sinyal: ham değeri ASLA taşıma, yalnız kaba yük işareti üret.
            busy_markers += 1
            continue
        if kind in {"location", "konum"} and not situation.location_hint:
            situation.location_hint = _clip(
                signal.get("label") or signal.get("value") or signal.get("place"), 80
            )
    situation.signal_kinds = sorted(set(kinds))[:8]

    # Takvim: bir sonraki etkinlik — "canlılığın" en güçlü tek kaynağı.
    events = calendar_events if isinstance(calendar_events, list) else []
    upcoming: list[tuple[int, str]] = []
    for event in events[:20]:
        if not isinstance(event, dict):
            continue
        title = _clip(event.get("title") or event.get("summary"), 80)
        raw_start = str(event.get("start") or event.get("start_iso") or "").strip()
        if not title or not raw_start:
            continue
        try:
            start = dt.datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            if start.tzinfo is not None:
                start = start.replace(tzinfo=None)
        except ValueError:
            continue
        delta = int((start - moment).total_seconds() // 60)
        if -30 <= delta <= 24 * 60:
            upcoming.append((delta, title))
    if upcoming:
        upcoming.sort(key=lambda item: abs(item[0]))
        situation.next_event_in_minutes, situation.next_event_title = upcoming[0]
    if len(upcoming) >= 4 or busy_markers >= 2:
        situation.load_hint = "yoğun"

    # Aktif uygulama + son üretilen dosyalar (süreklilik hissi).
    runtime = (state or {}).get("runtime") if isinstance(state, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    active = runtime.get("activeWindow") if isinstance(runtime.get("activeWindow"), dict) else {}
    situation.active_app = _clip(active.get("app") or active.get("name"), 60)
    artifacts = runtime.get("recentArtifacts")
    if isinstance(artifacts, list):
        situation.recent_artifacts = [
            _clip(item.get("name") if isinstance(item, dict) else item, 80)
            for item in artifacts[:4]
        ]
    return situation


def derive_defaults(
    situation: SituationalContext,
    *,
    intent_task_type: str = "",
) -> dict[str, str]:
    """Soru sormak yerine isabetli varsayımlar üretir.

    Bir sekreter "hangi başlık?" diye sormaz; bağlamdan türetir ve gerekirse
    sonradan düzeltir. Buradaki her varsayım GERÇEK bir sinyale dayanır —
    dayanak yoksa alan üretilmez (uydurma yok)."""
    defaults: dict[str, str] = {}
    if situation.next_event_title:
        # Belge/not üretimi istenmişse başlık büyük olasılıkla yaklaşan iş.
        defaults["suggestedTitle"] = situation.next_event_title
        if situation.next_event_in_minutes is not None and situation.next_event_in_minutes >= 0:
            defaults["timeContext"] = (
                f"{situation.next_event_title} toplantısına "
                f"{situation.next_event_in_minutes} dakika var"
            )
    if situation.load_hint == "yoğun":
        defaults["brevity"] = "kısa tut"
    return defaults


def liveness_cues(situation: SituationalContext) -> list[str]:
    """Cevabın doğal biçimde değinebileceği GERÇEK durum ipuçları.

    Amaç süs değil isabet: uydurma samimiyet ("umarım harika bir gün geçiriyorsun")
    değil, doğrulanabilir gerçek ("14:00'teki toplantından önce")."""
    cues: list[str] = []
    if situation.next_event_title and situation.next_event_in_minutes is not None:
        minutes = situation.next_event_in_minutes
        if 0 <= minutes <= 180:
            cues.append(
                f"{situation.next_event_title} için {minutes} dakikan var"
            )
        elif minutes < 0:
            cues.append(f"{situation.next_event_title} az önce başladı")
    if situation.load_hint == "yoğun":
        cues.append("bugün programın yoğun")
    if situation.recent_artifacts:
        cues.append(f"az önce {situation.recent_artifacts[0]} üzerinde çalıştın")
    return cues[:3]
