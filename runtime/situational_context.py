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
from pathlib import Path
from typing import Any

SITUATION_CONTRACT = "elyan.situation.v1"

# Hassas sinyaller: modele ham gitmez, yalnız türetilmiş işaret üretir.
_SENSITIVE_KINDS = {"health", "saglik", "medical", "location_precise"}

# UNUTMA: bayat referans, referans yokluğundan TEHLİKELİDİR — "onu sil" bir
# hafta önceki dosyayı silebilir. Bu yüzden son-üretilenler bir çalışma
# oturumu kadar yaşar; süresi dolan ya da diskte artık var olmayan kayıt
# bağlama girmez.
RECENT_OUTPUT_TTL_MINUTES = 240


def recent_output_is_fresh(
    entry: Any,
    *,
    now: dt.datetime | None = None,
    check_disk: bool = True,
) -> bool:
    """Bir son-üretilen kaydının hâlâ güvenle referans alınabilir olduğunu söyler.

    Üç kapı: (1) kayıt zamanı VAR ve TTL içinde — zamansız kayıt yaşı
    bilinemeyeceği için bayat sayılır (fail-closed); (2) yol boş değil;
    (3) yol diskte hâlâ mevcut (silinmiş dosyaya gönderme çözülmez)."""
    if not isinstance(entry, dict):
        return False
    path = str(entry.get("path", "") or "").strip()
    if not path:
        return False
    raw_recorded = str(entry.get("recordedAt", "") or "").strip()
    if not raw_recorded:
        return False
    try:
        recorded = dt.datetime.fromisoformat(raw_recorded.replace("Z", "+00:00"))
        if recorded.tzinfo is not None:
            recorded = recorded.replace(tzinfo=None)
    except ValueError:
        return False
    moment = now or dt.datetime.now()
    age_minutes = (moment - recorded).total_seconds() / 60
    if age_minutes < -5 or age_minutes > RECENT_OUTPUT_TTL_MINUTES:
        return False
    if check_disk:
        try:
            if not Path(path).exists():
                return False
        except OSError:
            return False
    return True


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
    # Son üretilenler (ad + yol). Göndermeleri ("o klasör", "onu sil") eyleme
    # çevirebilmek için yol şarttır.
    recent_outputs: list[dict[str, str]] = field(default_factory=list)
    load_hint: str = ""  # "yoğun" | "sakin" | "" (hassas veriden TÜRETİLMİŞ)
    signal_kinds: list[str] = field(default_factory=list)
    # KENDİ DURUMUNUN FARKINDALIĞI: "şu an bir görev yürüyor", "son görev
    # başarısız oldu" bilinirse model kaçamak cevap yerine dürüst durum
    # cümlesi kurar. Yalnız TAZE bilgi taşınır (bkz. gather_situation).
    active_task_count: int = 0
    last_task_ok: bool | None = None
    last_task_detail: str = ""
    last_task_minutes_ago: int | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.next_event_title,
                self.location_hint,
                self.active_app,
                self.recent_artifacts,
                self.load_hint,
                self.active_task_count > 0,
                self.last_task_ok is not None,
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
        if self.recent_outputs:
            # Model bunlara "o dosya/klasör" diye gönderme yapılırsa doğrudan
            # kullanabilsin.
            payload["recentOutputs"] = self.recent_outputs[:4]
        elif self.recent_artifacts:
            payload["recentFiles"] = self.recent_artifacts[:4]
        if self.load_hint:
            payload["dayLoad"] = self.load_hint
        self_state: dict[str, Any] = {}
        if self.active_task_count > 0:
            self_state["taskRunning"] = True
            if self.active_task_count > 1:
                self_state["taskCount"] = self.active_task_count
        if self.last_task_ok is not None:
            last_task: dict[str, Any] = {"ok": self.last_task_ok}
            if self.last_task_minutes_ago is not None:
                last_task["minutesAgo"] = self.last_task_minutes_ago
            if self.last_task_detail:
                last_task["detail"] = self.last_task_detail
            self_state["lastTask"] = last_task
        if self_state:
            payload["selfState"] = self_state
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

    # Kendi durumu: yürüyen görev + son görev sonucu. Bayat sonuç taşınmaz —
    # bir hafta önceki "başarısız" bugünün sorusuna gürültüdür (tazelik: 60 dk).
    executor = runtime.get("executor") if isinstance(runtime.get("executor"), dict) else {}
    try:
        situation.active_task_count = max(0, int(executor.get("activeExecutionCount", 0) or 0))
    except (TypeError, ValueError):
        situation.active_task_count = 0
    raw_last_at = str(executor.get("lastExecutionAt", "") or "").strip()
    if raw_last_at:
        try:
            last_at = dt.datetime.fromisoformat(raw_last_at.replace("Z", "+00:00"))
            if last_at.tzinfo is not None:
                last_at = last_at.replace(tzinfo=None)
            minutes_ago = int((moment - last_at).total_seconds() // 60)
            if 0 <= minutes_ago <= 60:
                situation.last_task_ok = bool(executor.get("lastExecutionOk"))
                situation.last_task_minutes_ago = minutes_ago
                situation.last_task_detail = _clip(executor.get("lastExecutionDetail"), 120)
        except ValueError:
            pass
    artifacts = runtime.get("recentArtifacts")
    if isinstance(artifacts, list):
        # Ad + YOL birlikte taşınır: "o klasörü sil" gibi göndermeler ancak yol
        # bilinirse eyleme çevrilebilir. Yalnız ad verilirse model hedefi tahmin
        # etmek zorunda kalır ve yanlış yeri siler.
        # UNUTMA KAPISI: süresi dolmuş ya da diskte artık olmayan kayıt bağlama
        # GİRMEZ — bayat referans üzerinden yanlış hedefe yan etki üretilmesin.
        fresh = [
            item
            for item in artifacts
            if recent_output_is_fresh(item, now=moment)
        ][:4]
        situation.recent_artifacts = [_clip(item.get("name"), 80) for item in fresh]
        situation.recent_outputs = [
            {
                "name": _clip(item.get("name"), 80),
                "path": _clip(item.get("path"), 240),
                "kind": _clip(item.get("kind"), 24),
            }
            for item in fresh
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


# Durumsal varsayımın uygulanabileceği üretim yetenekleri.
_ARTIFACT_CAPABILITIES = {
    "document_write",
    "canvas_write",
    "presentation_write",
    "spreadsheet_write",
}


def apply_situational_defaults(
    capability: str,
    args: dict[str, Any],
    situation: SituationalContext | None,
) -> dict[str, Any]:
    """Belge/görsel üretiminde EKSİK alanları durumdan doldurur.

    İki katı kural:
      1. **Kullanıcının verdiği hiçbir değer ezilmez** — yalnız boş alan dolar.
      2. Dayanak yoksa alan üretilmez (uydurma başlık atılmaz).

    Böylece "sunum notunu hazırla" gibi bir istek, takvimdeki toplantının adıyla
    isimlendirilir; kullanıcıya "hangi başlık?" diye sorulmaz."""
    if situation is None or not isinstance(args, dict):
        return args
    name = str(capability or "").strip()
    if name not in _ARTIFACT_CAPABILITIES:
        return args

    defaults = derive_defaults(situation, intent_task_type=name)
    suggested = str(defaults.get("suggestedTitle", "") or "").strip()
    if not suggested:
        return args

    enriched = dict(args)
    existing = str(enriched.get("title", "") or "").strip()
    if not existing:
        enriched["title"] = suggested
        # İzlenebilirlik: başlığın nereden geldiği kayıt altında kalsın.
        enriched["_titleSource"] = "situational_calendar"
    return enriched


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
