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
    # v2 kalite sözleşmesi: modelin araç/skill seçimini, argüman üretimini,
    # çıktı beklentisini ve doğrulamayı açıkça besler. Additif alandır; legacy
    # registry davranışını değiştirmez.
    when_to_use: tuple[str, ...] = ()
    when_not_to_use: tuple[str, ...] = ()
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    artifact_contract: dict[str, Any] = field(default_factory=dict)
    verification_plan: tuple[str, ...] = ()
    live_narration: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    few_shots: tuple[dict[str, Any], ...] = ()
    privacy_class: str = ""
    skill_affinity: tuple[str, ...] = ()


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
    payload.update(_quality_payload(spec))
    return payload


def _quality_payload(spec: CapabilitySpec) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if spec.when_to_use:
        payload["whenToUse"] = list(spec.when_to_use)
    if spec.when_not_to_use:
        payload["whenNotToUse"] = list(spec.when_not_to_use)
    if spec.input_contract:
        payload["inputContract"] = dict(spec.input_contract)
    if spec.output_contract:
        payload["outputContract"] = dict(spec.output_contract)
    if spec.artifact_contract:
        payload["artifactContract"] = dict(spec.artifact_contract)
    if spec.verification_plan:
        payload["verificationPlan"] = list(spec.verification_plan)
    if spec.live_narration:
        payload["liveNarration"] = list(spec.live_narration)
    if spec.failure_modes:
        payload["failureModes"] = list(spec.failure_modes)
    if spec.few_shots:
        payload["fewShots"] = [dict(item) for item in spec.few_shots]
    if spec.privacy_class:
        payload["privacyClass"] = spec.privacy_class
    if spec.skill_affinity:
        payload["skillAffinity"] = list(spec.skill_affinity)
    return payload


def enriched_tool_declaration(decl: dict[str, Any]) -> dict[str, Any]:
    """Legacy bildirime v2 kalite overlay'i uygula.

    Mevcut registry handler/safety davranışını değiştirmeden, backend'e giden
    manifestte spec kalitesini öne çıkarır.
    """
    name = str(decl.get("name", "") or "").strip()
    spec = quality_for(name)
    if spec is None:
        return dict(decl)
    merged = dict(decl)
    if spec.description:
        merged["description"] = spec.description
    if spec.usage:
        merged["usage"] = spec.usage
    spec_decl = tool_declaration(spec)
    legacy_params = merged.get("parameters")
    spec_params = spec_decl.get("parameters")
    if isinstance(legacy_params, dict) and isinstance(spec_params, dict):
        properties = dict(legacy_params.get("properties") or {})
        properties.update(dict(spec_params.get("properties") or {}))
        params = dict(legacy_params)
        params["properties"] = properties
        required = list(dict.fromkeys([
            *([str(item) for item in (legacy_params.get("required") or [])] if isinstance(legacy_params.get("required"), list) else []),
            *([str(item) for item in (spec_params.get("required") or [])] if isinstance(spec_params.get("required"), list) else []),
        ]))
        if required:
            params["required"] = required
        merged["parameters"] = params
    for key, value in spec_decl.items():
        if key not in {"name", "description", "parameters", "usage"}:
            merged[key] = value
    return merged


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

CRITICAL_QUALITY_SPECS: tuple[CapabilitySpec, ...] = (
    CapabilitySpec(
        name="canvas_write",
        module="actions.canvas_write",
        attribute="canvas_write",
        description="PDF/PNG canvas çıktısı üretir; metin, bölüm, tablo, grafik ve görsel bloklarını sayfalı veya tek görsel artifact'a dönüştürür.",
        args=(
            ArgSpec("prompt", description="Üretilecek PDF/PNG içeriği ve tasarım talimatı."),
            ArgSpec("outputPath", description="Kaydedilecek .pdf veya .png yolu."),
            ArgSpec("title", description="Belgenin/görsel panonun başlığı."),
            ArgSpec("blocks", type="array", description="Text/table/chart/image blokları; önceki adım çıktıları burada kullanılabilir."),
            ArgSpec("sections", type="array", description="Rapor bölümleri."),
            ArgSpec("outputFormat", description="pdf veya png."),
            ArgSpec("sourceContext", description="Önceki adım metni veya {{steps.<id>.output}} referansı."),
            ArgSpec("sourcePath", description="Dönüştürülecek kaynak dosya."),
        ),
        usage="Kullanıcı PDF, tasarımlı belge, poster, rapor PDF'i veya tablo+metin+grafik birleşik çıktı istediğinde. Word için document_write, Excel için spreadsheet_write, sunum için presentation_write.",
        category="research_docs",
        side_effect=True,
        verification_mode="artifact_exists",
        dependency_keys=("reportlab", "pillow"),
        when_to_use=("PDF olarak ver", "4 sayfalık PDF hazırla", "metni/görseli PDF'e dönüştür", "tablo+grafik içeren tek çıktı üret"),
        when_not_to_use=("Sadece DOCX/Word isteniyorsa document_write kullan.", "Yalnız tablo/xlsx isteniyorsa spreadsheet_write kullan."),
        input_contract={"requiredDecision": "outputFormat must be pdf or png", "contentFields": ["prompt", "blocks", "sections", "sourceContext", "sourcePath"], "references": "{{steps.<id>.output}} allowed"},
        output_contract={"kind": "canvas_write", "primary": "artifact", "formats": ["pdf", "png"], "summaryField": "text"},
        artifact_contract={"artifactTypes": ["pdf", "image"], "mustIncludeOutputPath": True, "mobileBlocksRemainCanonical": True},
        verification_plan=("Check artifact exists and extension matches requested format.", "If PDF was requested, verify the plan uses outputFormat=pdf or .pdf outputPath."),
        live_narration=("PDF içeriği hazırlanıyor", "Sayfa düzeni kuruluyor", "Çıktı dosyası doğrulanıyor"),
        failure_modes=("MISSING_CONTENT", "INVALID_OUTPUT_PATH", "DEPENDENCY_UNAVAILABLE"),
        few_shots=(
            {"goal": "Bunu 4 sayfalık PDF yap", "args": {"title": "Rapor", "outputFormat": "pdf", "sourceContext": "{{steps.s1.output}}"}},
        ),
        privacy_class="local_private_write",
        skill_affinity=("document.pdf_report", "canvas.visual_report"),
    ),
    CapabilitySpec(
        name="document_write",
        module="actions.document_write",
        attribute="document_write",
        description="DOCX/Word belgesi üretir; metin, bölüm, tablo, grafik ve görsel bloklarını düzenli belgeye yazar.",
        args=(
            ArgSpec("prompt", description="Belge içeriği/talimatı."),
            ArgSpec("outputPath", description="Kaydedilecek .docx yolu."),
            ArgSpec("title", description="Belge başlığı."),
            ArgSpec("sections", type="array", description="Başlık ve gövdeden oluşan bölümler."),
            ArgSpec("blocks", type="array", description="Text/table/chart/image blokları."),
            ArgSpec("sourceContext", description="Önceki adım çıktısı veya kullanıcı metni."),
            ArgSpec("sourcePath", description="Dönüştürülecek/özetlenecek kaynak belge."),
        ),
        usage="Word/DOCX, dilekçe, rapor, yazı, taslak, not veya profesyonel belge istendiğinde. PDF için canvas_write, Excel için spreadsheet_write, sunum için presentation_write.",
        category="research_docs",
        side_effect=True,
        verification_mode="artifact_exists",
        dependency_keys=("python_docx",),
        when_to_use=("savunma dilekçesi hazırla", "rapor yaz ve docx kaydet", "okunan metni Word belgesi yap"),
        when_not_to_use=("PDF isteniyorsa canvas_write kullan.", "Sunum/slayt isteniyorsa presentation_write kullan.", "Tablo/xlsx isteniyorsa spreadsheet_write kullan."),
        input_contract={"contentFields": ["prompt", "sections", "blocks", "sourceContext", "sourcePath"], "mustUsePriorOutputs": "research/read/analysis outputs go into sourceContext or prompt"},
        output_contract={"kind": "document_write", "primary": "artifact", "formats": ["docx"]},
        artifact_contract={"artifactTypes": ["document"], "extension": ".docx", "mobileBlocksRemainCanonical": True},
        verification_plan=("Check DOCX artifact exists.", "Writer args must contain concrete content or a prior-step reference."),
        live_narration=("Belge içeriği düzenleniyor", "DOCX dosyası oluşturuluyor", "Belge çıktısı doğrulanıyor"),
        failure_modes=("EMPTY_DOCUMENT", "INVALID_OUTPUT_PATH", "DEPENDENCY_UNAVAILABLE"),
        privacy_class="local_private_write",
        skill_affinity=("document.docx_from_context", "document.summary_and_save"),
    ),
    CapabilitySpec(
        name="spreadsheet_write",
        module="actions.spreadsheet_write",
        attribute="spreadsheet_write",
        description="XLSX/Excel çalışma kitabı üretir; satır, sütun, sheet ve hesap sonuçlarını yapılandırılmış tabloya yazar.",
        args=(ArgSpec("prompt"), ArgSpec("outputPath"), ArgSpec("title"), ArgSpec("sheets", type="array"), ArgSpec("columns", type="array"), ArgSpec("rows", type="array"), ArgSpec("sourceContext")),
        usage="Excel, xlsx, tablo, bütçe, hesap dökümü, karşılaştırma matrisi veya satır/sütunlu çıktı istendiğinde.",
        category="research_docs",
        side_effect=True,
        verification_mode="artifact_exists",
        dependency_keys=("openpyxl",),
        when_to_use=("excele dönüştür", "tablo yap", "hesapları Excel'e yaz", "satış/muhasebe verisi için çalışma sayfası üret"),
        when_not_to_use=("Paragraflı rapor için document_write/canvas_write kullan.", "Grafik görseli tek başına isteniyorsa chart_generate kullan."),
        input_contract={"structuredInputs": ["sheets", "columns", "rows"], "calculationReferences": "math_solve outputs belong in rows/cells via {{steps.<id>.output}}"},
        output_contract={"kind": "spreadsheet_write", "primary": "artifact", "formats": ["xlsx"]},
        artifact_contract={"artifactTypes": ["spreadsheet"], "extension": ".xlsx"},
        verification_plan=("Check XLSX artifact exists.", "Rows/sheets must be concrete, not prose-only."),
        live_narration=("Tablo yapısı kuruluyor", "Excel satırları yazılıyor", "Çalışma kitabı doğrulanıyor"),
        failure_modes=("INVALID_ROWS", "INVALID_OUTPUT_PATH", "DEPENDENCY_UNAVAILABLE"),
        privacy_class="local_private_write",
        skill_affinity=("spreadsheet.table_from_context",),
    ),
    CapabilitySpec(
        name="presentation_write",
        module="actions.presentation_write",
        attribute="presentation_write",
        description="PPTX/PowerPoint sunum üretir; araştırma/analiz çıktısını slaytlara böler.",
        args=(ArgSpec("prompt"), ArgSpec("outputPath"), ArgSpec("title"), ArgSpec("slides", type="array"), ArgSpec("blocks", type="array"), ArgSpec("sourceContext")),
        usage="Sunum, slayt, pptx, ders/proje sunumu veya konuşma deck'i istendiğinde.",
        category="research_docs",
        side_effect=True,
        verification_mode="artifact_exists",
        dependency_keys=("python_pptx",),
        when_to_use=("sunum hazırla", "5 slaytlık deck yap", "araştırmayı pptx'e dönüştür"),
        when_not_to_use=("PDF raporu için canvas_write kullan.", "Word raporu için document_write kullan."),
        input_contract={"contentFields": ["prompt", "slides", "sourceContext"], "slideCount": "derive from user request or use concise default"},
        output_contract={"kind": "presentation_write", "primary": "artifact", "formats": ["pptx"]},
        artifact_contract={"artifactTypes": ["presentation"], "extension": ".pptx"},
        verification_plan=("Check PPTX artifact exists.", "Slides must contain titles and body bullets."),
        live_narration=("Slayt akışı çıkarılıyor", "Sunum dosyası yazılıyor", "PPTX çıktısı doğrulanıyor"),
        failure_modes=("EMPTY_PRESENTATION", "INVALID_OUTPUT_PATH", "DEPENDENCY_UNAVAILABLE"),
        privacy_class="local_private_write",
        skill_affinity=("presentation.deck_from_context",),
    ),
    CapabilitySpec(
        name="document_read",
        module="actions.document_read",
        attribute="document_read",
        description="PDF, DOCX, PPTX ve desteklenen belgelerden metin/özet çıkarır.",
        args=(ArgSpec("path", required=True), ArgSpec("mode"), ArgSpec("max_chars", type="number")),
        usage="Kullanıcının verdiği belgeyi okumadan analiz/yazım yapma. PDF içeriği okunacaksa önce document_read, PDF üretilecekse canvas_write.",
        category="research_docs",
        verification_mode="result_nonempty",
        when_to_use=("bu dosyayı oku", "PDF'i özetle", "belgedeki bilgiden rapor hazırla"),
        when_not_to_use=("Düz .txt/.py dosyaları için file_read kullan.", "Ekrandaki metni okumak için analyze_screen kullan."),
        input_contract={"required": ["path"], "selectedPathsAllowed": True},
        output_contract={"kind": "document_read", "primary": "text", "fields": ["text", "pages", "summary"]},
        verification_plan=("Ensure extracted text or structured page summary is non-empty.",),
        live_narration=("Belge okunuyor", "Metin çıkarılıyor"),
        failure_modes=("FILE_NOT_FOUND", "UNSUPPORTED_FORMAT", "EMPTY_DOCUMENT"),
        privacy_class="local_private_read",
    ),
    CapabilitySpec(
        name="file_read",
        module="actions.filesystem",
        attribute="file_read",
        description="Düz metin/kod dosyasını güvenli şekilde okur; satır aralığı ve boyut sınırı destekler.",
        args=(ArgSpec("path", required=True), ArgSpec("max_bytes", type="number"), ArgSpec("start_line", type="number"), ArgSpec("end_line", type="number")),
        usage="Kod, txt, md, json gibi düz dosyalar için. PDF/DOCX için document_read.",
        category="developer",
        verification_mode="result_nonempty",
        when_to_use=("dosyayı oku", "şu kodu incele", "JSON içeriğini gör"),
        when_not_to_use=("Zengin belge/PDF için document_read kullan.", "Klasör listesi için directory_tree kullan."),
        input_contract={"required": ["path"], "largeFiles": "use max_bytes or line range"},
        output_contract={"kind": "file_read", "primary": "text"},
        verification_plan=("Read result must include path and text excerpt.",),
        live_narration=("Dosya okunuyor",),
        failure_modes=("FILE_NOT_FOUND", "READ_BLOCKED", "TOO_LARGE"),
        privacy_class="local_private_read",
    ),
    CapabilitySpec(
        name="file_write",
        module="actions.file_write",
        attribute="file_write",
        description="Düz metin/kod dosyası oluşturur veya açık overwrite ile değiştirir.",
        args=(ArgSpec("path", required=True), ArgSpec("content"), ArgSpec("overwrite", type="boolean")),
        usage="TXT/MD/JSON/kod dosyası yazmak için. DOCX/PDF/XLSX/PPTX için ilgili writer capability'yi kullan.",
        category="developer",
        side_effect=True,
        verification_mode="artifact_exists",
        when_to_use=("metni dosyaya kaydet", "markdown oluştur", "json dosyası yaz"),
        when_not_to_use=("Word/PDF/Excel/sunum için specialized writer kullan.", "Küçük mevcut dosya düzenlemesi için file_patch daha uygundur."),
        input_contract={"required": ["path"], "contentRequiredUnlessEmptyFile": True, "overwriteMustBeExplicit": True},
        output_contract={"kind": "file_write", "primary": "artifact"},
        artifact_contract={"artifactTypes": ["file"], "mustIncludeOutputPath": True},
        verification_plan=("Check written file exists.", "Overwrite must be explicit when target exists."),
        live_narration=("Dosya içeriği hazırlanıyor", "Dosya yazılıyor"),
        failure_modes=("INVALID_OUTPUT_PATH", "OVERWRITE_REQUIRED", "WRITE_BLOCKED"),
        privacy_class="local_private_write",
    ),
    CapabilitySpec(
        name="file_search",
        module="actions.filesystem",
        attribute="file_search",
        description="Dosya içeriklerinde metin/regex arar; kod ve metin araştırması için hızlı indeksli arama kullanır.",
        args=(ArgSpec("query", required=True), ArgSpec("path"), ArgSpec("glob"), ArgSpec("regex", type="boolean"), ArgSpec("max_results", type="number")),
        usage="Kullanıcı bir repo/klasör içinde geçen metni, fonksiyonu, hatayı veya belge parçasını aradığında.",
        category="developer",
        verification_mode="result_nonempty",
        when_to_use=("bu projede nerede geçiyor", "dosyalarda ara", "fonksiyonu bul"),
        when_not_to_use=("Sadece klasör yapısı için directory_tree kullan.", "Web bilgisi için web_research kullan."),
        input_contract={"required": ["query"], "optionalScope": ["path", "glob"]},
        output_contract={"kind": "file_search", "primary": "matches"},
        verification_plan=("Return matched file paths or explicit empty result.",),
        live_narration=("Dosyalarda aranıyor",),
        failure_modes=("SEARCH_TIMEOUT", "PATH_BLOCKED"),
        privacy_class="local_private_read",
    ),
    CapabilitySpec(
        name="directory_tree",
        module="actions.filesystem",
        attribute="directory_tree",
        description="Klasör/proje yapısını güvenli, sınırlı ağaç olarak listeler.",
        args=(ArgSpec("path"), ArgSpec("max_depth", type="number"), ArgSpec("max_entries", type="number")),
        usage="Klasörde ne var, proje yapısı nasıl, hangi dosyalar mevcut sorularında.",
        category="developer",
        verification_mode="result_nonempty",
        when_to_use=("klasörü listele", "proje ağacını çıkar", "dosya yapısını göster"),
        when_not_to_use=("İçerik aramak için file_search kullan.", "Belge metni okumak için document_read/file_read kullan."),
        input_contract={"defaults": {"path": "workspace", "max_depth": 3}},
        output_contract={"kind": "directory_tree", "primary": "tree"},
        verification_plan=("Tree must include scoped root and bounded entries.",),
        live_narration=("Klasör yapısı çıkarılıyor",),
        failure_modes=("PATH_BLOCKED", "TOO_MANY_ENTRIES"),
        privacy_class="local_private_read",
    ),
    CapabilitySpec(
        name="web_research",
        module="actions.web_research",
        attribute="web_research",
        description="Public web kaynaklarından araştırma özeti ve kaynak listesi üretir.",
        args=(ArgSpec("query", required=True), ArgSpec("max_results", type="number"), ArgSpec("language_hint")),
        usage="Güncel/dış/public bilgi gerektiğinde. Özel dosya/metin içeriğini query'ye koyma; önce public arama, sonra private analiz/yazımda birleştir.",
        category="research_docs",
        verification_mode="result_nonempty",
        when_to_use=("güncel bilgi araştır", "kaynaklı rapor hazırla", "public mevzuat/teknoloji/pazar bilgisi bul"),
        when_not_to_use=("Kullanıcının özel dosyasını analiz etmek için document_read/text_analyze kullan.", "Yerel geçmiş/çalışma alanı için retrieve_context kullan."),
        input_contract={"required": ["query"], "queryMustBePublic": True, "maxPrivateData": "none"},
        output_contract={"kind": "web_research", "primary": "research_summary", "fields": ["summary", "sources"]},
        verification_plan=("Result must include a non-empty summary and source evidence when available.",),
        live_narration=("Kaynaklar araştırılıyor", "Bulgular özetleniyor"),
        failure_modes=("NETWORK_UNAVAILABLE", "NO_SOURCES", "TIMEOUT"),
        privacy_class="public_web",
    ),
    CapabilitySpec(
        name="text_analyze",
        module="actions.text_analyze",
        attribute="text_analyze",
        description="Okunan/araştırılan/hesaplanan içeriği profesyonel muhakeme özeti, karar, risk veya rapor planına dönüştürür.",
        args=(ArgSpec("prompt", required=True), ArgSpec("sourceContext"), ArgSpec("mode")),
        usage="read/research/math çıktılarını belge/tablo/sunum yazmadan önce analiz etmek için. Sadece format export için writer yeterliyse atlanabilir.",
        category="research_docs",
        verification_mode="result_nonempty",
        when_to_use=("analiz et", "yorumla", "riskleri çıkar", "rapor yapmadan önce değerlendir"),
        when_not_to_use=("Sadece basit hesap için math_solve kullan.", "Sadece dosya okuma için document_read/file_read kullan."),
        input_contract={"required": ["prompt"], "sourceContextRecommended": True},
        output_contract={"kind": "text_analyze", "primary": "analysis"},
        verification_plan=("Analysis must answer the requested lens and preserve source facts.",),
        live_narration=("Veri analiz ediliyor", "Sonuçlar yapılandırılıyor"),
        failure_modes=("EMPTY_SOURCE", "INSUFFICIENT_CONTEXT"),
        privacy_class="local_or_server_context",
    ),
    CapabilitySpec(
        name="image_generate",
        module="actions.image_generate",
        attribute="image_generate",
        description="Yeni görsel üretir; prompt önceki görsel/artefact takiplerini ve kullanıcının düzeltmesini taşımalıdır.",
        args=(ArgSpec("prompt", required=True), ArgSpec("size"), ArgSpec("style"), ArgSpec("outputPath")),
        usage="Sıfırdan görsel/resim çizmek/üretmek için. Mevcut görseli değiştirmek için image_edit.",
        category="research_docs",
        side_effect=True,
        verification_mode="artifact_exists",
        when_to_use=("kedi resmi çiz", "görsel oluştur", "kapak görseli üret"),
        when_not_to_use=("Önceki görseli değiştir/daha sinematik/beyaz yap isteniyorsa image_edit veya latestArtifactRef tabanlı generation kullan.", "Web'den hazır görsel indirmek için image_fetch kullan."),
        input_contract={"required": ["prompt"], "promptMustBeFullVisualSpec": True, "followUpMustReusePreviousPrompt": True},
        output_contract={"kind": "image_generate", "primary": "image_artifact"},
        artifact_contract={"artifactTypes": ["image"], "mustIncludeOutputPath": True},
        verification_plan=("Generated artifact exists and matches requested subject/style constraints.",),
        live_narration=("Görsel prompt'u hazırlanıyor", "Görsel üretiliyor", "Sonuç kontrol ediliyor"),
        failure_modes=("GENERATION_UNAVAILABLE", "SAFETY_BLOCKED", "TIMEOUT"),
        privacy_class="external_model_optional",
    ),
    CapabilitySpec(
        name="image_edit",
        module="actions.image_edit",
        attribute="image_edit",
        description="Mevcut görseli kullanıcı düzeltmesine göre değiştirir; son görsel artefact/prompt bağlamını korur.",
        args=(ArgSpec("prompt", required=True), ArgSpec("imagePath"), ArgSpec("sourceImagePath"), ArgSpec("outputPath")),
        usage="'bunu beyaz yap', 'daha sinematik yap', 'arka planı değiştir' gibi follow-up görsel düzenlemelerinde.",
        category="research_docs",
        side_effect=True,
        verification_mode="artifact_exists",
        when_to_use=("mevcut görseli düzenle", "son resmi değiştir", "daha sinematik yap", "rengini değiştir"),
        when_not_to_use=("Sıfırdan alakasız yeni görsel için image_generate kullan.", "Görseli sadece okumak için image_read kullan."),
        input_contract={"required": ["prompt"], "sourceImageRequired": "imagePath or latestArtifactRef.imagePath", "mustPreserveSubject": True},
        output_contract={"kind": "image_edit", "primary": "image_artifact"},
        artifact_contract={"artifactTypes": ["image"], "sourceArtifactRequired": True},
        verification_plan=("Edited artifact exists and preserves requested subject unless user asked otherwise.",),
        live_narration=("Önceki görsel referansı alınıyor", "Düzenleme uygulanıyor", "Görsel kontrol ediliyor"),
        failure_modes=("MISSING_SOURCE_IMAGE", "GENERATION_UNAVAILABLE", "SAFETY_BLOCKED"),
        privacy_class="external_model_optional",
    ),
    CapabilitySpec(
        name="image_read",
        module="actions.image_read",
        attribute="image_read",
        description="Görseli okur, içerik/etiket/metin/özet çıkarır.",
        args=(ArgSpec("path", required=True), ArgSpec("query")),
        usage="Paylaşılan fotoğraf/görsel/screenshot dosyasını anlamak için. Canlı aktif ekran için analyze_screen.",
        category="research_docs",
        verification_mode="result_nonempty",
        when_to_use=("bu görselde ne var", "resmi analiz et", "fotoğraftaki metni oku"),
        when_not_to_use=("Aktif masaüstü ekranı için analyze_screen kullan.", "Yeni görsel üretmek için image_generate kullan."),
        input_contract={"required": ["path"], "queryOptional": True},
        output_contract={"kind": "image_read", "primary": "vision_summary"},
        verification_plan=("Vision summary should mention visible content and uncertainty.",),
        live_narration=("Görsel okunuyor",),
        failure_modes=("FILE_NOT_FOUND", "VISION_UNAVAILABLE", "LOW_CONFIDENCE"),
        privacy_class="local_private_read",
    ),
    CapabilitySpec(
        name="analyze_screen",
        module="actions.screen_vision",
        attribute="analyze_screen",
        description="Aktif pencereyi kullanıcı sorusuna göre görsel olarak analiz eder; basit 'ekranda ne var' cevabı üretir.",
        args=(ArgSpec("query", required=True), ArgSpec("target")),
        usage="Kullanıcı ekranda ne olduğunu, aktif pencerede ne yazdığını veya görünen hata/uyarıyı sorduğunda. Tıklama/yazma için desktop_operator.run.",
        category="local_execution",
        verification_mode="screen_analysis",
        when_to_use=("ekranda ne var", "aktif pencerede ne görünüyor", "bu hata ne diyor"),
        when_not_to_use=("Bir hedefe tıklamak/yazmak/kaydırmak için desktop_operator.run veya execute_action kullan.", "Ekli görsel dosyası için image_read kullan."),
        input_contract={"required": ["query"], "target": "active_window only in v1"},
        output_contract={"kind": "screen_analysis", "primary": "text", "fields": ["ownerName", "windowTitle", "analysis"]},
        verification_plan=("Return active app/window context and visual analysis; do not hide visible third-party names from screen facts.",),
        live_narration=("Ekran görüntüsü alınıyor", "Aktif pencere analiz ediliyor"),
        failure_modes=("OS_PERMISSION_REQUIRED", "VISION_UNAVAILABLE", "BLANK_CAPTURE"),
        privacy_class="local_private_screen",
    ),
    CapabilitySpec(
        name="desktop_operator.observe_screen",
        module="actions.desktop_operator",
        attribute="observe_screen",
        description="Operator için yapılandırılmış ekran gözlemi üretir; sonraki UI eylemini güvenli seçmek için kullanılır.",
        args=(ArgSpec("query"), ArgSpec("target"), ArgSpec("preserveScreenshot", type="boolean")),
        usage="Ekran-eylem planında her kritik tıklama/yazma öncesi ve sonrası durum görmek için.",
        category="local_execution",
        verification_mode="screen_observation",
        when_to_use=("UI görevinin mevcut durumunu gözle", "buton/alan görünür mü kontrol et", "eylem sonrası doğrula"),
        when_not_to_use=("Kullanıcı sadece genel açıklama istiyorsa analyze_screen kullan.", "Tek dosya/görsel için image_read kullan."),
        input_contract={"queryRecommended": True, "preserveScreenshotOnlyWhenNeeded": True},
        output_contract={"kind": "screen_observation", "primary": "observation"},
        verification_plan=("Observation should include active app/window, visible text/elements when available.",),
        live_narration=("Ekran durumu gözlemleniyor",),
        failure_modes=("OS_PERMISSION_REQUIRED", "NO_ACTIVE_WINDOW"),
        privacy_class="local_private_screen",
    ),
    CapabilitySpec(
        name="desktop_operator.execute_action",
        module="actions.desktop_operator",
        attribute="execute_action",
        description="Gözlemlenmiş ekranda tek bir güvenli click/type/key/scroll eylemi uygular.",
        args=(ArgSpec("actionType", required=True), ArgSpec("targetText"), ArgSpec("elementType"), ArgSpec("bbox", type="object"), ArgSpec("text"), ArgSpec("keys", type="array"), ArgSpec("reason")),
        usage="Önce observe_screen ile hedef görüldüyse tek UI eylemi için. Belirsiz/çok adımlı UI hedefinde desktop_operator.run kullan.",
        category="local_execution",
        side_effect=True,
        verification_mode="operator_verified",
        when_to_use=("görünen butona tıkla", "alana şu metni yaz", "enter'a bas", "sayfayı kaydır"),
        when_not_to_use=("Hedef belirsiz veya çok adımlıysa desktop_operator.run kullan.", "Web DOM erişimi varsa browser_session/browser_agent daha güvenilir olabilir."),
        input_contract={"required": ["actionType"], "targetOrReasonRequired": True, "mustDependOnObservation": True},
        output_contract={"kind": "desktop_operator_action", "primary": "action_result"},
        verification_plan=("Follow with observe_screen for important state changes.",),
        live_narration=("Ekranda güvenli eylem uygulanıyor",),
        failure_modes=("TARGET_NOT_FOUND", "OS_PERMISSION_REQUIRED", "ACTION_BLOCKED"),
        privacy_class="local_private_action",
    ),
    CapabilitySpec(
        name="desktop_operator.run",
        module="actions.desktop_operator",
        attribute="run",
        description="Çok adımlı observe→decide→act→verify ekran otomasyonu hedefini yürütür.",
        args=(ArgSpec("goal", required=True), ArgSpec("maxActions", type="number"), ArgSpec("appName"), ArgSpec("steps", type="array")),
        usage="Yerel uygulama veya belirsiz UI üzerinde ardışık tıklama/yazma/kaydırma gerektiğinde; stop condition içeren somut goal ver.",
        category="local_execution",
        side_effect=True,
        verification_mode="operator_verified",
        when_to_use=("ekrandaki formu doldur", "uygulamada şu ayarı bul ve aç", "butonları izleyerek işlemi tamamla"),
        when_not_to_use=("Sadece ekranı anlatmak için analyze_screen kullan.", "Bilinen browser DOM işlerinde browser_session/browser_agent daha uygundur."),
        input_contract={"required": ["goal"], "goalMustIncludeStopCondition": True, "maxActionsRecommended": True},
        output_contract={"kind": "desktop_operator_run", "primary": "run_summary"},
        verification_plan=("Operator loop must stop on success, uncertainty, or maxActions.", "Important final state must be observed before success."),
        live_narration=("Ekran görevi başlatılıyor", "Her adımdan sonra durum kontrol ediliyor", "Son durum doğrulanıyor"),
        failure_modes=("MAX_ACTIONS_REACHED", "TARGET_NOT_FOUND", "OS_PERMISSION_REQUIRED", "UNSAFE_ACTION"),
        privacy_class="local_private_action",
    ),
    CapabilitySpec(
        name="math_solve",
        module="actions.math_solve",
        attribute="math_solve",
        description="Somut matematiksel ifadeyi çözer, sadeleştirir veya hesaplar; açıklama değil ifade alır.",
        args=(ArgSpec("expression", required=True), ArgSpec("mode")),
        usage="Hesaplama, denklem, oran, vergi/KDV, optimizasyon alt hesabı için. expression her zaman rakamlı/sembolik ifade olmalı.",
        category="math_quantum",
        verification_mode="result_nonempty",
        when_to_use=("hesapla", "denklem çöz", "KDV tutarını bul", "toplam/maliyet/oran hesapla"),
        when_not_to_use=("Metin analizi için text_analyze kullan.", "Tablo çıktısı için math_solve sonrası spreadsheet_write kullan."),
        input_contract={"required": ["expression"], "expressionMustBeConcrete": True, "examples": ["12000+8500", "(12000+8500)*0.20"]},
        output_contract={"kind": "math_solve", "primary": "numeric_or_symbolic_result"},
        verification_plan=("Expression must not be prose-only.", "Result must be non-empty and feed writer/table via {{steps.<id>.output}}."),
        live_narration=("Hesaplama yapılıyor",),
        failure_modes=("INVALID_EXPRESSION", "NO_NUMERIC_EXPRESSION"),
        privacy_class="local_safe_compute",
        skill_affinity=("math.solve",),
    ),
    CapabilitySpec(
        name="chart_generate",
        module="actions.chart_generate",
        attribute="chart_generate",
        description="Veri dosyası veya yapılandırılmış veri üzerinden PNG grafik üretir.",
        args=(ArgSpec("path"), ArgSpec("chartType"), ArgSpec("xColumn"), ArgSpec("yColumn"), ArgSpec("title"), ArgSpec("outputPath"), ArgSpec("sourceContext")),
        usage="Kullanıcı grafik/plot/histogram istediğinde; önce veri okuma/analiz, sonra chart_generate, gerekirse canvas/document içine göm.",
        category="research_docs",
        side_effect=True,
        verification_mode="artifact_exists",
        when_to_use=("grafik çiz", "veriden chart üret", "Excel verisini görselleştir"),
        when_not_to_use=("Sadece tablo için spreadsheet_write kullan.", "Grafikli PDF için chart_generate sonrası canvas_write kullan."),
        input_contract={"dataSourceRequired": "path or sourceContext", "chartTypeRecommended": True},
        output_contract={"kind": "chart_generate", "primary": "image_artifact", "formats": ["png"]},
        artifact_contract={"artifactTypes": ["image"], "extension": ".png"},
        verification_plan=("Check PNG artifact exists and chart type/data mapping is explicit.",),
        live_narration=("Grafik verisi hazırlanıyor", "Grafik çiziliyor"),
        failure_modes=("MISSING_DATA", "INVALID_COLUMNS", "DEPENDENCY_UNAVAILABLE"),
        privacy_class="local_private_write",
    ),
    CapabilitySpec(
        name="run_skill",
        module="runtime.skill_runtime",
        attribute="run_skill",
        description="Hazır local skill workflow'unu exact skillId ve payload ile çalıştırır.",
        args=(ArgSpec("skillId", required=True), ArgSpec("payload", type="object")),
        usage="Skill kataloğunda kullanıcının isteğine bire bir uyan hazırlanmış workflow varsa kullan. Skill id'sini capability adı gibi uydurma; yalnız katalogdaki exact id geçerlidir.",
        category="communication_approval",
        side_effect=True,
        verification_mode="tool_result",
        when_to_use=("hazır workflow bire bir uyuyor", "çok adımlı tekrarlı beceri katalogda var", "skill manifesti exact payload alanlarını veriyor"),
        when_not_to_use=("Katalogdaki skill tam uymuyorsa primitive tool zinciri kur.", "Skill id katalogda yoksa run_skill kullanma."),
        input_contract={"required": ["skillId"], "skillIdMustExistInCatalog": True, "payloadMustSatisfyRequiredParameters": True},
        output_contract={"kind": "run_skill", "primary": "lastStepResult"},
        verification_plan=("Chosen skillId must exist in DESKTOP_SKILL_MANIFEST.", "Payload must include every requiredParameter."),
        live_narration=("Hazır beceri akışı başlatılıyor", "Beceri adımları yürütülüyor"),
        failure_modes=("UNKNOWN_SKILL", "MISSING_PAYLOAD_FIELD", "STEP_FAILED"),
        privacy_class="local_private_mixed",
    ),
)

SPECS_BY_NAME: dict[str, CapabilitySpec] = {spec.name: spec for spec in SPECS}
QUALITY_SPECS_BY_NAME: dict[str, CapabilitySpec] = {spec.name: spec for spec in (*SPECS, *CRITICAL_QUALITY_SPECS)}


def spec_for(name: str) -> CapabilitySpec | None:
    return SPECS_BY_NAME.get(str(name or "").strip())


def quality_for(name: str) -> CapabilitySpec | None:
    return QUALITY_SPECS_BY_NAME.get(str(name or "").strip())


def policy_gate_for(name: str) -> str:
    """safety_policy için kapı türü; spec'te yoksa boş döner (legacy kurallar)."""
    spec = spec_for(name)
    return spec.policy if spec is not None else ""
