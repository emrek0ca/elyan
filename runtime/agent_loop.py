"""Çok turlu ajan döngüsü (P0).

MEVCUT MİMARİ İLE FARKI
-----------------------
``executor_core`` bir *workflow motoru*: plan bir kez kurulur, adımlar sırayla
uygulanır, model yalnız HATA anında (replan_fn) tekrar düşünür. Bu, kalıba oturan
işlerde hızlı ve güvenlidir; ancak "gerçek yazılım görevi", bilgisayarı insan gibi
kullanma (OSWorld) ve uçtan uca otomasyon gibi NOVEL işlerde yetersizdir çünkü
model adımlar arasında gerçek gözlem görmez.

Bu modül eksik halkayı ekler:

    gözlemle → düşün → TEK adım at → sonucu gözlemle → yeniden düşün → …

Tasarım ilkeleri
----------------
* **Bağımlılık enjeksiyonu.** Model çağrısı (``decide_next``) ve araç yürütmesi
  (``execute_step``) dışarıdan verilir. Böylece döngü saf/test edilebilirdir ve
  backend erişimi olmadan da doğrulanabilir.
* **Mevcut kapılar korunur.** Araçlar çağıranın ``execute_step``'i üzerinden
  koşar; safety_policy, onay (authorize), doğrulama ve kanıt kapıları aynen
  devrede kalır. Bu modül YENİ bir ayrıcalık yolu açmaz.
* **Sınırlı bağlam.** Gözlemler kırpılır ve alt çizgili iç bayraklar ayıklanır;
  bağlam şişmesi ve veri sızıntısı önlenir.
* **Canlılık.** Adım bütçesi, süre bütçesi ve "takıldı" (aynı eylemin tekrarı)
  dedektörü ile sonsuz döngü imkânsızdır.
* **Öz-düzeltme.** Geçici hatalarda modele dönmeden önce deterministik onarım
  (``error_recovery``) denenir — ucuz ve öngörülebilir.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from runtime.capability_registry import capability_metadata, capability_names
from runtime.error_recovery import CORRECTIVE_MAX_ATTEMPTS, plan_corrective_retry

AGENT_LOOP_CONTRACT = "elyan.agent_loop.v1"

# Canlılık sınırları: novel işlerde bile sonlu kalması için sert tavanlar.
# NOT: Bütçe, İSRAF KESİLDİKTEN SONRA artırıldı. Sırası önemliydi — israf
# dururken bütçe artırmak kaliteyi değil yalnız maliyeti büyütür. Kesilen
# israflar: (a) exit≠0'ın hata sayılması, (b) yapılandırılmış sonucun geri
# beslenmemesi, (c) teslimat kayması, (d) tüm kataloğun her turda gönderilmesi.
DEFAULT_MAX_STEPS = 32
DEFAULT_DEADLINE_SECONDS = 1_200.0
# Aynı (capability, args) çiftinin ardışık tekrar sayısı bu sınırı aşarsa
# ilerleme yok kabul edilir ve döngü modele "değiştir" baskısıyla kapanır.
STUCK_REPEAT_LIMIT = 3
# Gözlem metinlerinin üst sınırı — bağlam şişmesini ve sızıntıyı önler.
MAX_OBSERVATION_CHARS = 2_000
MAX_HISTORY_OBSERVATIONS = 12


def _clip(value: Any, limit: int = MAX_OBSERVATION_CHARS) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def public_args(args: Any) -> dict[str, Any]:
    """Alt çizgili runtime bayraklarını (``_confirmed``, ``_previousResult`` …)
    ayıklar. Bunlar iç güven/veri taşıyıcılarıdır; modele veya loga gitmemeli."""
    if not isinstance(args, dict):
        return {}
    return {
        str(key): value
        for key, value in args.items()
        if not str(key).startswith("_")
    }


def _bounded_result(result: dict[str, Any], *, max_keys: int = 14) -> dict[str, Any]:
    """Yapılandırılmış sonucu modele güvenle geri beslenebilecek boyuta indirir.

    Skalerler ve kısa listeler korunur (kimlikler burada yaşar); büyük/iç içe
    gövdeler özetlenir. Amaç: zincirleme için gereken kimlikleri kaybetmeden
    bağlamı şişirmemek."""
    bounded: dict[str, Any] = {}
    for key, value in list(result.items())[:max_keys]:
        name = str(key)
        if name.startswith("_"):
            continue
        if isinstance(value, (bool, int, float)) or value is None:
            bounded[name] = value
        elif isinstance(value, str):
            bounded[name] = value[:400]
        elif isinstance(value, list):
            bounded[name] = f"<{len(value)} öğe>"
        elif isinstance(value, dict):
            bounded[name] = f"<nesne: {', '.join(list(value)[:6])}>"
    return bounded


def _action_signature(capability: str, args: dict[str, Any]) -> str:
    try:
        payload = json.dumps(public_args(args), sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        payload = str(sorted(public_args(args).keys()))
    return f"{capability}::{payload}"


@dataclass(frozen=True, slots=True)
class AgentAction:
    """Modelin bir turda seçtiği tek eylem.

    ``kind``:
      * ``tool``   — bir yetenek çalıştır (capability + args)
      * ``finish`` — iş bitti, ``summary`` teslim metnidir
      * ``ask``    — kullanıcıdan bilgi gerekiyor (döngü güvenle durur)
    """

    kind: str
    capability: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    summary: str = ""

    @property
    def is_tool(self) -> bool:
        return self.kind == "tool"


@dataclass(slots=True)
class AgentObservation:
    """Bir adımın modele geri beslenecek, sınırlanmış sonucu."""

    index: int
    capability: str
    args: dict[str, Any]
    ok: bool
    output: str = ""
    error_code: str = ""
    error_message: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    # Adımın yapılandırılmış çıktısı. Zincirleme için ŞARTTIR: bir sonraki adım
    # çoğu zaman buradaki kimliklere/yollara ihtiyaç duyar (ör. sessionId).
    result: dict[str, Any] = field(default_factory=dict)

    def to_context(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step": self.index,
            "capability": self.capability,
            "args": self.args,
            "ok": self.ok,
        }
        if self.output:
            payload["output"] = _clip(self.output)
        # Yapılandırılmış sonucu da geri besle — aksi halde model önceki adımın
        # ürettiği kimliği (sessionId, path, id…) göremez ve uydurur.
        if self.result:
            payload["result"] = _bounded_result(self.result)
        if not self.ok:
            payload["errorCode"] = self.error_code
            payload["error"] = _clip(self.error_message, 480)
        if self.artifacts:
            payload["artifacts"] = [
                {
                    "name": str(item.get("name", "") or ""),
                    "path": str(item.get("path", "") or ""),
                }
                for item in self.artifacts[:6]
                if isinstance(item, dict)
            ]
        if self.evidence:
            payload["evidence"] = {
                "kind": str(self.evidence.get("kind", "") or ""),
                "verified": bool(self.evidence.get("verified", False)),
            }
        return payload


@dataclass(slots=True)
class AgentLoopResult:
    ok: bool
    summary: str
    stop_reason: str
    steps_used: int
    observations: list[AgentObservation] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    structured_result: dict[str, Any] | None = None
    error_code: str = ""
    # P0.5: onay bekleyen yan etkili adım. ``stop_reason == "needs_approval"``
    # olduğunda doldurulur; çağıran bunu plan önizlemesi + pendingPlan'a çevirir.
    pending_action: dict[str, Any] | None = None

    def trace(self) -> dict[str, Any]:
        return {
            "contract": AGENT_LOOP_CONTRACT,
            "ok": self.ok,
            "stopReason": self.stop_reason,
            "stepsUsed": self.steps_used,
            "errorCode": self.error_code,
            "observations": [item.to_context() for item in self.observations],
        }


def build_tool_catalog(
    allowed_capabilities: set[str] | None = None,
    *,
    limit: int = 80,
    goal: str = "",
) -> list[dict[str, Any]]:
    """Modele sunulacak araç kataloğu. Tek kaynak capability_registry'dir —
    burada elle liste tutulmaz (liste-sürüklenmesi hata sınıfı önlenir).

    ``goal`` verilirse katalog o göreve İLGİLİ araçlara kısaltılır. Tüm katalog
    (~78 araç) her turda gönderilmek zorunda değildir: bu hem büyük bir token
    israfıdır hem de modelin odağını dağıtır. Kısa liste deterministiktir ve
    çekirdek araçları her zaman içerir."""
    names = sorted(capability_names())
    if allowed_capabilities:
        allowed = {str(item or "").strip() for item in allowed_capabilities}
        names = [name for name in names if name in allowed]
    if goal.strip():
        try:
            from runtime.capability_shortlist import shortlist_capabilities

            short = shortlist_capabilities(goal, known_capabilities=names)
            if short:
                names = [name for name in names if name in set(short)]
        except Exception:
            # Kısaltma başarısızsa tam katalogla devam et (davranış bozulmaz).
            pass
    catalog: list[dict[str, Any]] = []
    for name in names[:limit]:
        metadata = capability_metadata(name)
        if not metadata:
            continue
        entry = {
            "name": name,
            "description": _clip(metadata.get("description", ""), 240),
            "sideEffect": bool(metadata.get("sideEffect", False)),
            "approvalRequired": bool(metadata.get("approvalRequired", False)),
        }
        guidance = _tool_guidance(metadata)
        if guidance:
            entry["guidance"] = guidance
        catalog.append(entry)
    return catalog


def _undelivered(
    deliverables: list[str] | None,
    artifacts: list[dict[str, Any]],
    observations: list[Any],
) -> list[str]:
    """Beyan edilen teslimatlardan hangileri KANITSIZ kaldı?

    Kanıt tanımı kasıtlı olarak geniştir: bir artifact üretildiyse ya da
    herhangi bir adım yol/çıktı taşıyan yapılandırılmış sonuç döndürdüyse
    teslimat gerçekleşmiş sayılır. Amaç mükemmel eşleme değil, **hiçbir şey
    üretmeden 'bitti' demeyi** yakalamak: dar bir eşleme kuralı yanlış
    pozitif üretir ve gerçek işi engeller (bu, kural yazma tuzağıdır)."""
    wanted = [str(item or "").strip() for item in (deliverables or []) if str(item or "").strip()]
    if not wanted:
        return []
    if artifacts:
        return []
    for observation in observations:
        result = getattr(observation, "result", None)
        if isinstance(result, dict) and (
            result.get("path") or result.get("outputPath") or result.get("artifacts")
        ):
            return []
    return wanted[:3]


def _tool_guidance(metadata: dict[str, Any]) -> list[str]:
    """Aracın ANLAMSAL kullanım rehberi — kayıt metadata'sından TÜRETİLİR.

    Amaç seçimi kelime eşleşmesinden çıkarıp anlama taşımak: model "ne zaman
    uygun, neyi gerektirir, tekrarı güvenli mi" bilgisini görür ve kendi karar
    verir. Burada araca özel elle yazılmış kural YOKTUR — her madde spec'te
    zaten duran bir alandan çıkar, dolayısıyla kod değişince bayatlamaz."""
    hints: list[str] = []
    permissions = metadata.get("requiredPermissions")
    if isinstance(permissions, (list, tuple)) and permissions:
        hints.append("izin gerekir: " + ", ".join(str(item) for item in permissions[:3]))
    if str(metadata.get("idempotency", "")) == "non_idempotent":
        # Tekrar çağrı yeni yan etki üretir: model aynı adımı "emin olmak için"
        # tekrarlamasın (canlı sınavda görülen israf sınıfı).
        hints.append("tekrarı güvenli değil; sonucu doğrula, yeniden çalıştırma")
    if metadata.get("retryable") is True:
        hints.append("geçici hatada yeniden denenebilir")
    dependencies = metadata.get("dependencyKeys")
    if isinstance(dependencies, (list, tuple)) and dependencies:
        hints.append("ön koşul: " + ", ".join(str(item) for item in dependencies[:3]))
    platforms = metadata.get("supportedPlatforms")
    if isinstance(platforms, (list, tuple)) and 0 < len(platforms) < 3:
        hints.append("yalnız şu platformlarda: " + ", ".join(str(p) for p in platforms))
    return hints[:4]


# Salt bilgi toplayan (yan etkisiz) yetenekler: bunlar üst üste tekrarlanıyorsa
# ajan "araştırma"da takılmış demektir.
_GATHERING_CAPABILITIES = {
    "file_read", "file_search", "directory_tree", "sys_info", "document_read",
    "retrieve_context", "web_research", "ocr_read", "image_read", "data_analyze",
    "text_analyze", "analyze_screen", "desktop_os.status", "desktop_os.processes",
}


def _is_gathering(capability: str, result: dict[str, Any] | None = None) -> bool:
    name = str(capability or "").strip()
    if name in _GATHERING_CAPABILITIES:
        return True
    # Salt-okunur kabuk komutları da bilgi toplamadır (exit kodu ne olursa olsun).
    return name == "shell_session_run"


def _delivery_pressure(
    *, steps_remaining: int, total_steps: int, gathering_streak: int
) -> str:
    """Bütçe/streak durumuna göre sertleşen teslimat direktifi."""
    if total_steps > 0 and steps_remaining <= max(2, total_steps // 4):
        return (
            "SON ADIMLAR. Yeni bilgi TOPLAMA. Elindeki verilerle teslimatı ŞİMDİ üret "
            "(dosyayı yaz / sonucu ver), sonra 'finish' de. Eksik ama teslim edilmiş iş, "
            "mükemmel ama yarım kalmış işten iyidir."
        )
    if gathering_streak >= 3:
        return (
            f"UYARI: {gathering_streak} turdur yalnız bilgi topluyorsun ve ilerleme yok. "
            "Aynı veriyi farklı komutlarla yeniden toplamayı BIRAK. Elindekiler yeterli — "
            "teslimatı üretmeye geç."
        )
    return ""


def build_decision_context(
    *,
    goal: str,
    goal_context: dict[str, Any] | None,
    observations: list[AgentObservation],
    tool_catalog: list[dict[str, Any]],
    steps_remaining: int,
    stuck_hint: str = "",
    gathering_streak: int = 0,
    total_steps: int = 0,
    deliverables: list[str] | None = None,
) -> dict[str, Any]:
    """Model turuna gönderilecek sınırlanmış karar bağlamı."""
    recent = observations[-MAX_HISTORY_OBSERVATIONS:]
    context: dict[str, Any] = {
        "contract": AGENT_LOOP_CONTRACT,
        "goal": _clip(goal, 1_200),
        "tools": tool_catalog,
        "history": [item.to_context() for item in recent],
        "stepsRemaining": max(0, int(steps_remaining)),
    }
    # TESLİMAT BASKISI: model bilgi toplamada takılıp bütçeyi tüketmesin.
    # Prompt'taki statik kural yetmiyor (canlı sınavda model aynı veriyi farklı
    # komutlarla tekrar tekrar topladı); bu yüzden DURUMA bağlı, sertleşen bir
    # direktif enjekte edilir.
    pressure = _delivery_pressure(
        steps_remaining=steps_remaining,
        total_steps=total_steps,
        gathering_streak=gathering_streak,
    )
    if pressure:
        context["deliveryDirective"] = pressure
    if isinstance(goal_context, dict) and goal_context:
        context["goalContext"] = goal_context
    if stuck_hint:
        # Modele açık geri bildirim: aynı eylemi tekrarlıyorsun, stratejini değiştir.
        context["warning"] = stuck_hint
    if deliverables:
        # Model her turda "elinde ne kalmalı"yı görür; teslimat kapısı da
        # bunu ölçer. İkisi aynı sözleşmeye bakar.
        context["deliverables"] = deliverables[:3]
    # DENEYİMDEN DERS: bu turun araç kümesiyle örtüşen geçmiş dersler. Alaka
    # kapısı lesson_store'dadır — örtüşme yoksa hiçbir şey eklenmez.
    try:
        from runtime.lesson_store import relevant_lessons

        names = [
            str(tool.get("name", "") or "")
            for tool in (tool_catalog or [])
            if isinstance(tool, dict)
        ]
        lessons = relevant_lessons(capabilities=names)
        if lessons:
            context["lessons"] = lessons
    except Exception:
        pass
    return context


def coerce_action(value: Any) -> AgentAction:
    """Model çıktısını güvenli bir ``AgentAction``a çevirir.

    Tanınmayan/bozuk çıktı ``ask``a düşer: uydurma bir araç çağrısı üretmektense
    güvenle durmak yeğdir (fail-closed)."""
    if isinstance(value, AgentAction):
        return value
    if not isinstance(value, dict):
        return AgentAction("ask", summary="Model kararı okunamadı.")

    kind = str(value.get("kind", "") or value.get("action", "") or "").strip().lower()
    capability = str(
        value.get("capability", "") or value.get("tool", "") or ""
    ).strip()
    args = value.get("args")
    args = dict(args) if isinstance(args, dict) else {}
    rationale = _clip(value.get("rationale", "") or value.get("reason", ""), 480)
    summary = _clip(value.get("summary", "") or value.get("answer", ""), MAX_OBSERVATION_CHARS)

    if kind in {"finish", "done", "complete"}:
        return AgentAction("finish", rationale=rationale, summary=summary)
    if kind in {"ask", "clarify", "question"}:
        return AgentAction("ask", rationale=rationale, summary=summary)
    if kind in {"tool", "act", "call"} or capability:
        if not capability:
            return AgentAction("ask", summary="Araç adı belirtilmedi.")
        return AgentAction(
            "tool",
            capability=capability,
            args=args,
            rationale=rationale,
        )
    return AgentAction("ask", summary=summary or "Model geçerli bir eylem seçmedi.")


def run_agent_loop(
    *,
    goal: str,
    decide_next: Callable[[dict[str, Any]], Any],
    execute_step: Callable[
        [str, dict[str, Any], dict[str, Any], str], tuple[dict[str, Any], list[dict[str, Any]]]
    ],
    state_factory: Callable[[], dict[str, Any]],
    source: str = "agent_loop",
    goal_context: dict[str, Any] | None = None,
    allowed_capabilities: set[str] | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    confirmed: bool = True,
    require_approval: bool = True,
    should_cancel: Callable[[], str | bool] | None = None,
    on_observation: Callable[[AgentObservation], None] | None = None,
    deliverables: list[str] | None = None,
) -> AgentLoopResult:
    """Hedefi çok turlu gözlem/karar döngüsüyle yürütür.

    Her tur: karar bağlamı kurulur → ``decide_next`` modelden TEK eylem alır →
    eylem çalıştırılır → gerçek sonuç gözlem olarak geri beslenir. Model ``finish``
    dediğinde ya da bütçe bittiğinde durur.
    """
    # Katalog hedefe göre kısaltılır: daha az token, daha keskin odak.
    tool_catalog = build_tool_catalog(allowed_capabilities, goal=goal)
    known_capabilities = capability_names()
    observations: list[AgentObservation] = []
    artifacts: list[dict[str, Any]] = []
    structured_result: dict[str, Any] | None = None
    started_at = time.monotonic()
    recent_signatures: list[str] = []
    stuck_hint = ""
    steps_used = 0
    gathering_streak = 0
    delivery_warned = False

    def cancellation_reason() -> str:
        if should_cancel is None:
            return ""
        try:
            value = should_cancel()
        except Exception:
            return ""
        if isinstance(value, str):
            return value.strip()
        return "agent_loop_cancelled" if value else ""

    def finish(
        ok: bool,
        summary: str,
        stop_reason: str,
        error_code: str = "",
        pending_action: dict[str, Any] | None = None,
    ) -> AgentLoopResult:
        return AgentLoopResult(
            ok=ok,
            summary=summary,
            stop_reason=stop_reason,
            steps_used=steps_used,
            observations=observations,
            artifacts=artifacts,
            structured_result=structured_result,
            error_code=error_code,
            pending_action=pending_action,
        )

    bounded_max_steps = max(1, min(int(max_steps or DEFAULT_MAX_STEPS), 64))

    while True:
        cancel_reason = cancellation_reason()
        if cancel_reason:
            return finish(False, "Görev iptal edildi.", cancel_reason, "AGENT_LOOP_CANCELLED")

        if steps_used >= bounded_max_steps:
            return finish(
                False,
                "Adım bütçesi doldu; görev güvenli noktada durduruldu.",
                "step_budget_exhausted",
                "AGENT_LOOP_BUDGET_EXHAUSTED",
            )
        if time.monotonic() - started_at > max(1.0, float(deadline_seconds)):
            return finish(
                False,
                "Süre bütçesi doldu; görev güvenli noktada durduruldu.",
                "deadline_exceeded",
                "AGENT_LOOP_TIMEOUT",
            )

        context = build_decision_context(
            goal=goal,
            goal_context=goal_context,
            observations=observations,
            tool_catalog=tool_catalog,
            steps_remaining=bounded_max_steps - steps_used,
            stuck_hint=stuck_hint,
            gathering_streak=gathering_streak,
            total_steps=bounded_max_steps,
            deliverables=deliverables,
        )
        stuck_hint = ""

        try:
            action = coerce_action(decide_next(context))
        except Exception:
            return finish(
                False,
                "Planlayıcı yanıtı alınamadı.",
                "decider_error",
                "AGENT_LOOP_DECIDER_FAILED",
            )

        if action.kind == "finish":
            summary = action.summary or "İşlem tamamlandı."
            # TESLİMAT KAPISI: kullanıcı somut bir çıktı bekliyorduysa ("elinde
            # ne kalmalı"), o çıktının GERÇEKTEN üretildiğini kanıtla. Model
            # "bitti" diyebilir ama hiçbir şey üretmemiş olabilir — canlıda
            # görülen en pahalı hata sınıfı budur ("yaptım" uydurması).
            # Kapı bir kez uyarır ve döngüye geri döner: teslim et, sonra bitir.
            missing = _undelivered(deliverables, artifacts, observations)
            if missing and not delivery_warned:
                delivery_warned = True
                stuck_hint = (
                    "TESLİMAT EKSİK: şu beklenen çıktı(lar) henüz üretilmedi: "
                    + "; ".join(missing[:3])
                    + ". Bitirme — önce üret. Üretemiyorsan 'ask' ile neyin "
                    "engellediğini söyle; yaptığını İDDİA ETME."
                )
                continue
            return finish(True, summary, "completed")
        if action.kind == "ask":
            return finish(
                False,
                action.summary or "Devam etmek için ek bilgi gerekiyor.",
                "needs_user_input",
                "AGENT_LOOP_NEEDS_INPUT",
            )

        capability = action.capability
        if capability not in known_capabilities:
            # Uydurulmuş araç: gözleme yaz, modele düzeltme şansı ver.
            steps_used += 1
            observation = AgentObservation(
                index=steps_used,
                capability=capability,
                args=public_args(action.args),
                ok=False,
                error_code="UNKNOWN_CAPABILITY",
                error_message="Bu isimde bir yetenek yok. Katalogdaki adlardan birini seç.",
            )
            observations.append(observation)
            if on_observation is not None:
                on_observation(observation)
            continue
        if allowed_capabilities and capability not in allowed_capabilities:
            steps_used += 1
            observation = AgentObservation(
                index=steps_used,
                capability=capability,
                args=public_args(action.args),
                ok=False,
                error_code="CAPABILITY_OUT_OF_SCOPE",
                error_message="Bu yetenek görev kapsamı dışında.",
            )
            observations.append(observation)
            if on_observation is not None:
                on_observation(observation)
            continue

        # P0.5 ONAY KAPISI: yan etkili / onay gerektiren bir adım seçildiyse ve
        # bu tur onaylı değilse, adımı ÇALIŞTIRMA — plan önizlemesi olarak
        # kullanıcıya sun. Salt-okunur adımlar serbestçe akar, böylece döngü
        # keşif yapabilir ama yan etki asla onaysız çalışmaz.
        if require_approval and not confirmed:
            step_metadata = capability_metadata(capability) or {}
            needs_approval = bool(
                step_metadata.get("approvalRequired", False)
                or step_metadata.get("sideEffect", False)
            )
            if needs_approval:
                return finish(
                    False,
                    _clip(
                        action.rationale
                        or f"Bu işlem için onayın gerekiyor: {capability}",
                        480,
                    ),
                    "needs_approval",
                    "AGENT_LOOP_NEEDS_APPROVAL",
                    pending_action={
                        "capability": capability,
                        "args": public_args(action.args),
                        "rationale": _clip(action.rationale, 480),
                        "sideEffect": bool(step_metadata.get("sideEffect", False)),
                        "approvalRequired": bool(
                            step_metadata.get("approvalRequired", False)
                        ),
                        # Onaya kadar tamamlanmış keşif adımları: kullanıcı neyin
                        # üzerine karar verdiğini görsün.
                        "completedSteps": [item.to_context() for item in observations],
                    },
                )

        # Takıldı dedektörü: aynı eylem üst üste tekrarlanıyorsa modele uyar.
        signature = _action_signature(capability, action.args)
        recent_signatures.append(signature)
        repeat_count = sum(
            1 for item in recent_signatures[-STUCK_REPEAT_LIMIT:] if item == signature
        )
        if repeat_count >= STUCK_REPEAT_LIMIT:
            return finish(
                False,
                "Aynı adım ilerleme sağlamadan tekrarlandı; görev durduruldu.",
                "no_progress",
                "AGENT_LOOP_NO_PROGRESS",
            )

        # --- Eylemi çalıştır (mevcut güvenlik/onay/doğrulama kapılarıyla) ---
        attempt = 0
        tool_result: dict[str, Any] = {}
        call_args = dict(action.args)
        while True:
            attempt += 1
            steps_used += 1
            run_args = dict(call_args)
            run_args["_confirmed"] = bool(confirmed)
            run_args["_retryAttempt"] = attempt
            try:
                tool_result, _events = execute_step(
                    capability, run_args, state_factory(), source
                )
            except Exception as exc:  # araç patlarsa döngü düşmesin
                tool_result = {
                    "ok": False,
                    "output": "",
                    "error": {
                        "code": str(getattr(exc, "code", "TOOL_EXECUTION_FAILED")),
                        "message": str(getattr(exc, "message", "") or exc),
                    },
                }

            if tool_result.get("ok"):
                break

            error = tool_result.get("error")
            error = error if isinstance(error, dict) else {}
            error_code = str(error.get("code") or "TOOL_EXECUTION_FAILED")
            message = str(error.get("message") or tool_result.get("output") or "")

            # Deterministik öz-düzeltme: geçici/onarılabilir hatada modele
            # dönmeden ucuz bir düzeltme dene (izin hataları fail-closed).
            corrective = plan_corrective_retry(
                capability=capability,
                args=public_args(call_args),
                error_code=error_code,
                message=message,
                attempt=attempt,
            )
            if (
                corrective is not None
                and corrective.should_retry
                and attempt < CORRECTIVE_MAX_ATTEMPTS
                and steps_used < bounded_max_steps
            ):
                if corrective.adjusted_args:
                    call_args.update(corrective.adjusted_args)
                continue
            break

        error = tool_result.get("error")
        error = error if isinstance(error, dict) else {}
        result_payload = tool_result.get("result")
        step_artifacts = [
            item for item in (tool_result.get("artifacts") or []) if isinstance(item, dict)
        ]
        if step_artifacts:
            artifacts.extend(step_artifacts)
        if isinstance(result_payload, dict) and result_payload:
            structured_result = dict(result_payload)

        observation = AgentObservation(
            index=steps_used,
            capability=capability,
            args=public_args(call_args),
            ok=bool(tool_result.get("ok")),
            output=str(tool_result.get("output", "") or ""),
            error_code=str(error.get("code", "") or ("" if tool_result.get("ok") else "TOOL_EXECUTION_FAILED")),
            error_message=str(error.get("message", "") or ""),
            artifacts=step_artifacts,
            evidence=(
                dict(tool_result.get("stepEvidence"))
                if isinstance(tool_result.get("stepEvidence"), dict)
                else {}
            ),
            result=dict(result_payload) if isinstance(result_payload, dict) else {},
        )
        observations.append(observation)
        if on_observation is not None:
            on_observation(observation)
        # Bilgi toplama streak'i: üretim/teslimat adımı gelince sıfırlanır.
        gathering_streak = (
            gathering_streak + 1 if _is_gathering(capability) else 0
        )

        if not observation.ok and repeat_count >= 2:
            stuck_hint = (
                "Son denemeler aynı hatayla başarısız oldu. Aynı çağrıyı tekrar etme; "
                "farklı bir yetenek ya da farklı argümanlar dene."
            )
