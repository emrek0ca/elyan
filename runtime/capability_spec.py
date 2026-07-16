"""Tek Spec mimarisi — bir yeteneğin TÜM tanımı tek kayıtta.

Eskiden bir yetenek eklemek 7 ayrı tabloya dokunmaktı: _ADAPTER_SPECS,
_handlers(), TOOL_DECLARATIONS, _CAPABILITY_DISPLAY_NAMES,
_SIDE_EFFECT_CAPABILITIES, kategori/doğrulama if-zincirleri,
_CAPABILITY_DEPENDENCY_KEYS — artı safety_policy kuralları. Tablolar
birbirinden koptukça "available ama kör operatör" gibi tutarsızlıklar doğdu
(canlı arıza). Bu modül tek doğruluk kaynağıdır: capability_registry ve
safety_policy buradaki spec listesinden TÜRETİR.

Göç aşamalıdır: yeni yetenekler yalnız buraya yazılır; eski yetenekler grup
grup taşınır. Bir ad hem legacy tabloda hem burada varsa spec kazanır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ── Şema ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArgSpec:
    """Tek argüman: tip + açıklama (planlayıcı kataloğuna gider) + eşleme.

    `aliases` gelen payload'daki alternatif anahtarlar (ör. camelCase);
    handler üretimi ilk dolu olanı kullanır.
    """

    name: str
    type: str = "string"  # string | number | boolean | array | object
    description: str = ""
    required: bool = False
    default: Any = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilitySpec:
    """Bir yeteneğin tek kayıtta tam tanımı."""

    name: str
    module: str
    attribute: str
    description: str
    args: tuple[ArgSpec, ...] = ()
    usage: str = ""
    examples: tuple[dict[str, Any], ...] = ()
    display_name: str = ""
    category: str = "other"
    side_effect: bool = False
    verification_mode: str = "tool_result"
    dependency_keys: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("darwin", "win32", "linux")
    # safety_policy kapısı:
    #   "open"        → her zaman serbest (temizlik/iptal türü)
    #   "permission:<anahtar>" → ilgili gizlilik izni / tam yetki oturumu ister
    #   "confirm"     → onaylı planda çalışır (_confirmed=True gerekir)
    policy: str = "open"
    # Modüldeki hazırlık probu fonksiyon adı (ör. "browser_session_status").
    status_function: str = ""
    retryable: bool = False
    timeout_seconds: int = 60


# ── Handler üretimi ──────────────────────────────────────────────────────────


def _coerce(value: Any, arg: ArgSpec) -> Any:
    if value is None:
        return arg.default
    if arg.type == "string":
        return str(value or "")
    if arg.type == "number":
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return arg.default
    if arg.type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
    if arg.type == "array":
        return list(value) if isinstance(value, (list, tuple)) else arg.default
    if arg.type == "object":
        return dict(value) if isinstance(value, dict) else arg.default
    return value


def build_handler(spec: CapabilitySpec, load_adapter: Callable[[str], Callable[..., Any]]) -> Callable[[dict[str, Any]], Any]:
    """Spec'in arg şemasından payload→keyword-çağrı handler'ı üretir.

    Elle `args.get(...)` dizmek biter: eşleme, alias ve tip dönüşümü tek yerde.
    """

    def _handler(payload: dict[str, Any]) -> Any:
        kwargs: dict[str, Any] = {}
        for arg in spec.args:
            raw = payload.get(arg.name)
            if raw is None:
                for alias in arg.aliases:
                    raw = payload.get(alias)
                    if raw is not None:
                        break
            value = _coerce(raw, arg)
            if value is None and arg.default is None and not arg.required:
                # Opsiyonel ve değersiz: adapter varsayılanına bırak.
                continue
            kwargs[arg.name] = value
        return load_adapter(spec.name)(**kwargs)

    return _handler


def tool_declaration(spec: CapabilitySpec) -> dict[str, Any]:
    """Planlayıcı kataloğu (TOOL_DECLARATIONS) girdisi."""
    type_map = {"string": "STRING", "number": "NUMBER", "boolean": "BOOLEAN", "array": "ARRAY", "object": "OBJECT"}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for arg in spec.args:
        entry: dict[str, Any] = {"type": type_map.get(arg.type, "STRING")}
        if arg.description:
            entry["description"] = arg.description
        properties[arg.name] = entry
        if arg.required:
            required.append(arg.name)
    payload: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
        "parameters": {"type": "OBJECT", "properties": properties},
    }
    if required:
        payload["parameters"]["required"] = required
    if spec.usage:
        payload["usage"] = spec.usage
    if spec.examples:
        payload["examples"] = [dict(item) for item in spec.examples]
    return payload


# ── Spec kayıtları (göç edilen yetenekler) ───────────────────────────────────

_BROWSER_SESSION_DEPS = ("playwright",)

SPECS: tuple[CapabilitySpec, ...] = (
    CapabilitySpec(
        name="browser_session.goto",
        module="actions.browser_session",
        attribute="session_goto",
        description="Kalıcı tarayıcı oturumunda bir adrese gider; sonraki adımlar AYNI sayfada devam eder.",
        args=(ArgSpec("url", description="Gidilecek http/https adresi.", required=True),),
        usage="Çok adımlı tarayıcı işlerinde (gez → tıkla → çıkar → indir) ilk adım. Tek seferlik 'URL aç ve bırak' için browser_control kullan.",
        display_name="Tarayıcı oturumu — sayfaya git",
        category="local_execution",
        side_effect=True,
        dependency_keys=_BROWSER_SESSION_DEPS,
        policy="permission:allow_browser_control",
        status_function="browser_session_status",
    ),
    CapabilitySpec(
        name="browser_session.click",
        module="actions.browser_session",
        attribute="session_click",
        description="Oturumdaki sayfada bir öğeye tıklar (CSS selector, görünür metin ya da rol+metin ile).",
        args=(
            ArgSpec("selector", description="CSS selector (en kesin yol)."),
            ArgSpec("text", description="Öğenin görünür metni."),
            ArgSpec("role", description="ARIA rolü (button, link, tab...)."),
        ),
        usage="browser_session.snapshot ile öğeleri gördükten sonra hedefe tıklamak.",
        display_name="Tarayıcı oturumu — tıkla",
        category="local_execution",
        side_effect=True,
        dependency_keys=_BROWSER_SESSION_DEPS,
        policy="permission:allow_browser_control",
        status_function="browser_session_status",
    ),
    CapabilitySpec(
        name="browser_session.type",
        module="actions.browser_session",
        attribute="session_type",
        description="Oturumdaki sayfada bir alana metin yazar; submit=true ile Enter'a basar. Şifre alanlarına yazmaz.",
        args=(
            ArgSpec("value", description="Yazılacak metin.", required=True, aliases=("text_value",)),
            ArgSpec("selector", description="Hedef alanın CSS selector'ı."),
            ArgSpec("text", description="Alanın görünür etiketi/placeholder metni."),
            ArgSpec("submit", type="boolean", description="Yazdıktan sonra Enter'a bas.", default=False),
        ),
        usage="Arama kutusu doldurma, form alanına URL yapıştırma gibi işlerde.",
        display_name="Tarayıcı oturumu — yaz",
        category="local_execution",
        side_effect=True,
        dependency_keys=_BROWSER_SESSION_DEPS,
        policy="permission:allow_browser_control",
        status_function="browser_session_status",
    ),
    CapabilitySpec(
        name="browser_session.extract",
        module="actions.browser_session",
        attribute="session_extract",
        description="Sayfadan yapılandırılmış veri çıkarır: selector eşleşmelerinin metni ve istenirse bir attribute'u (ör. href). Selector verilmezse sayfanın okunur metnini döndürür.",
        args=(
            ArgSpec("selector", description="CSS selector (ör. 'a#video-title')."),
            ArgSpec("attribute", description="Çıkarılacak attribute (ör. 'href')."),
            ArgSpec("limit", type="number", description="En fazla öğe sayısı (varsayılan 20).", default=20),
        ),
        usage="Liste toplama işlerinde: video linkleri, başlıklar, tablo hücreleri. Sonuç result.items listesindedir; sonraki adımlar {{steps.<id>.result.items}} ile kullanır.",
        display_name="Tarayıcı oturumu — veri çıkar",
        category="local_execution",
        dependency_keys=_BROWSER_SESSION_DEPS,
        policy="permission:allow_browser_control",
        status_function="browser_session_status",
    ),
    CapabilitySpec(
        name="browser_session.snapshot",
        module="actions.browser_session",
        attribute="session_snapshot",
        description="Sayfanın etkileşimli öğelerini (link/buton/alan, metinleriyle) listeler — sonraki tıklama/yazma adımını doğru hedefe yöneltmek için gözlem.",
        args=(ArgSpec("limit", type="number", description="En fazla öğe (varsayılan 80).", default=80),),
        usage="Sayfanın yapısı bilinmiyorken tıklamadan ÖNCE gözlem almak.",
        display_name="Tarayıcı oturumu — sayfa gözlemi",
        category="local_execution",
        dependency_keys=_BROWSER_SESSION_DEPS,
        policy="permission:allow_browser_control",
        status_function="browser_session_status",
    ),
    CapabilitySpec(
        name="browser_session.download",
        module="actions.browser_session",
        attribute="session_download",
        description="Sayfadan dosya indirir (indirme başlatan öğeye tıklayarak ya da doğrudan URL ile) ve dosya yolunu döndürür.",
        args=(
            ArgSpec("selector", description="İndirmeyi başlatan öğenin CSS selector'ı."),
            ArgSpec("text", description="İndirme öğesinin görünür metni."),
            ArgSpec("url", description="Doğrudan indirme adresi."),
            ArgSpec("output_dir", description="Hedef klasör (varsayılan Elyan indirmeleri).", aliases=("outputDir",)),
        ),
        usage="Transcript/rapor/dosya indirme adımlarında; dönen outputPath sonraki file_move adımına verilir.",
        display_name="Tarayıcı oturumu — dosya indir",
        category="local_execution",
        side_effect=True,
        verification_mode="artifact_exists",
        dependency_keys=_BROWSER_SESSION_DEPS,
        policy="permission:allow_browser_control",
        status_function="browser_session_status",
    ),
    CapabilitySpec(
        name="browser_session.close",
        module="actions.browser_session",
        attribute="session_close",
        description="Kalıcı tarayıcı oturumunu kapatır.",
        usage="Çok adımlı tarayıcı işi bittiğinde temizlik.",
        display_name="Tarayıcı oturumu — kapat",
        category="local_execution",
        dependency_keys=_BROWSER_SESSION_DEPS,
        policy="open",
        status_function="browser_session_status",
    ),
    CapabilitySpec(
        name="browser_agent.run",
        module="runtime.browser_agent",
        attribute="run",
        description="Tarayıcıda hedefi KENDİ gözleyip karar vererek adım adım gerçekleştiren ajan: sayfayı gözler, tıklar, yazar, veri toplar, dosya indirir; hedef bitince özet ve toplanan verileri döndürür.",
        args=(
            ArgSpec("goal", description="Doğal dille hedef (ör. 'YouTube kanalımdaki son 5 uzun videonun linkini topla').", required=True),
            ArgSpec("max_turns", type="number", description="En fazla gözlem-eylem turu (varsayılan 12, üst sınır 24).", default=12, aliases=("maxTurns",)),
        ),
        usage="Sayfa yapısı önceden bilinmeyen çok adımlı tarayıcı görevlerinde TEK adım olarak kullan. Adımları kendin yazabiliyorsan browser_session.* daha hızlıdır; buradaki ajan keşif gerektiren işler içindir.",
        display_name="Tarayıcı ajanı",
        category="local_execution",
        side_effect=True,
        dependency_keys=("playwright",),
        policy="permission:allow_browser_control",
        status_function="browser_agent_status",
        timeout_seconds=1200,
    ),
    CapabilitySpec(
        name="make_directory",
        module="actions.file_write",
        attribute="make_directory",
        description="Klasör oluşturur (üst klasörler dahil; varsa hata vermez).",
        args=(ArgSpec("path", description="Oluşturulacak klasör yolu (ör. ~/Desktop/youtube-transkript).", required=True),),
        usage="İndirilen/üretilen dosyaları toplamadan önce hedef klasörü hazırlamak veya kullanıcının istediği klasörü açmak.",
        display_name="Klasör oluşturma",
        category="developer",
        side_effect=True,
        verification_mode="artifact_exists",
        # Zararsız + geri alınabilir (yalnız YENİ klasör; silme/üzerine yazma
        # yok) → açık izin. "confirm" iken mobil dispatch'te görev onaya
        # takılıp kullanıcı kartı göremeyince sonsuz bekliyordu.
        policy="open",
    ),
    CapabilitySpec(
        name="file_move",
        module="actions.file_write",
        attribute="file_move",
        description="Dosyayı başka bir konuma taşır (hedef klasörse içine).",
        args=(
            ArgSpec("source", description="Taşınacak dosyanın yolu.", required=True),
            ArgSpec("destination", description="Hedef yol ya da klasör.", required=True),
            ArgSpec("overwrite", type="boolean", description="Hedef varsa üzerine yaz (varsayılan hayır).", default=False),
        ),
        usage="İndirilen dosyaları kullanıcının istediği klasöre toplamak.",
        display_name="Dosya taşıma",
        category="developer",
        side_effect=True,
        verification_mode="artifact_exists",
        policy="confirm",
    ),
)

SPECS_BY_NAME: dict[str, CapabilitySpec] = {spec.name: spec for spec in SPECS}


def spec_for(name: str) -> CapabilitySpec | None:
    return SPECS_BY_NAME.get(str(name or "").strip())


def policy_gate_for(name: str) -> str:
    """safety_policy için kapı türü; spec'te yoksa boş döner (legacy kurallar)."""
    spec = spec_for(name)
    return spec.policy if spec is not None else ""
