from __future__ import annotations

import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote as _url_quote, urlparse

from runtime.agent_planning import build_agent_plan


@dataclass(frozen=True)
class RoutedTask:
    tool_name: str
    args: dict[str, Any]
    reason: str
    intent: str = ""
    confidence: float = 1.0
    requires_confirmation: bool = False
    is_multi_step: bool = False
    privacy_class: str = "public_text"
    plan_preview: dict[str, Any] | None = None
    steps: tuple[dict[str, Any], ...] = field(default_factory=tuple)


TR_WEEKDAY_INDEX = {
    "pazartesi": 0,
    "sali": 1,
    "salı": 1,
    "carsamba": 2,
    "çarşamba": 2,
    "persembe": 3,
    "perşembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6,
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
TR_WEEKDAY_LABELS = {
    0: "Pazartesi",
    1: "Salı",
    2: "Çarşamba",
    3: "Perşembe",
    4: "Cuma",
    5: "Cumartesi",
    6: "Pazar",
}


def _normalise(text: str) -> str:
    value = str(text or "").strip().lower()
    value = value.replace("ı", "i")
    value = value.replace("ğ", "g").replace("ü", "u").replace("ş", "s")
    value = value.replace("ö", "o").replace("ç", "c")
    return " ".join(value.split())


# "Safari'yi açar mısın lütfen" gibi istek kipleri deterministik kalıpları
# ıskalatıyordu; komutu emir kipine indirger, kibarlık eklerini atar.
_REQUEST_FORM_REWRITES = [
    (r"a[cç](?:ar\s*m[ıi]s[ıi]n[ıi]?z?|abilir\s*mi[sy]in(?:iz)?)", "aç"),
    (r"kapat(?:[ıi]r\s*m[ıi]s[ıi]n[ıi]?z?|abilir\s*mi[sy]in(?:iz)?)", "kapat"),
    (r"ba[sş]lat(?:[ıi]r\s*m[ıi]s[ıi]n[ıi]?z?|abilir\s*mi[sy]in(?:iz)?)", "başlat"),
    (r"gid(?:er\s*misin(?:iz)?|ebilir\s*misin(?:iz)?)", "git"),
    (r"gir(?:er\s*misin(?:iz)?|ebilir\s*misin(?:iz)?)", "gir"),
    (r"getir(?:ir\s*misin(?:iz)?|ebilir\s*misin(?:iz)?)", "getir"),
    (r"g[oö]ster(?:ir\s*misin(?:iz)?|ebilir\s*misin(?:iz)?)", "göster"),
    (r"olu[sş]tur(?:ur\s*musun(?:uz)?|abilir\s*misin(?:iz)?)", "oluştur"),
    (r"haz[ıi]rla(?:r\s*m[ıi]s[ıi]n[ıi]?z?|yabilir\s*misin(?:iz)?)", "hazırla"),
    (r"ara[sş]t[ıi]r(?:[ıi]r\s*m[ıi]s[ıi]n[ıi]?z?|abilir\s*misin(?:iz)?)", "araştır"),
    (r"yap(?:ar\s*m[ıi]s[ıi]n[ıi]?z?|abilir\s*misin(?:iz)?)", "yap"),
    (r"[cç]al[ıi][sş]t[ıi]r(?:[ıi]r\s*m[ıi]s[ıi]n[ıi]?z?|abilir\s*misin(?:iz)?)", "çalıştır"),
]


def _canonicalize_request(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(
        r"^(?:l[uü]tfen|please|hemen|rica etsem)[\s,]+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"[\s,]+(?:l[uü]tfen|please|rica etsem|rica ederim)[\s.!?]*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    for pattern, replacement in _REQUEST_FORM_REWRITES:
        cleaned = re.sub(rf"\b{pattern}\s*[.!?]*$", replacement, cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" .!?")


def _strip_polite_suffix(value: str) -> str:
    value = value.strip(" .,!?:;")
    value = re.sub(
        r"\b(lutfen|please|acabilir misin|acar misin|acarmisin|gosterir misin|bakabilir misin|anlatir misin)\b",
        "",
        value,
    ).strip()
    return value.strip(" .,!?:;")


def _strip_leading_fillers(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(
        r"^(?:da|de|te|ta|ile|icin|için|hakkinda|hakkında|about|for|the|bir|bu|su|şu|lutfen|lütfen|please)\b[\s,.:;!?-]*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" .,!?:;")


_TRAILING_CASE_TOKENS = {
    "i",
    "ı",
    "u",
    "ü",
    "yi",
    "yı",
    "yu",
    "yü",
    "ni",
    "nı",
    "nu",
    "nü",
}


def _strip_trailing_case_particles(value: str) -> str:
    tokens = [token for token in str(value or "").strip().split() if token]
    while tokens and _normalise(tokens[-1]) in _TRAILING_CASE_TOKENS:
        tokens.pop()
    return " ".join(tokens).strip()


def _clean_app_name(value: str) -> str:
    cleaned = _strip_polite_suffix(value)
    cleaned = _strip_leading_fillers(cleaned)
    cleaned = re.sub(r"[’'](?:i|ı|u|ü|yi|yı|yu|yü)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?i)(.{3,}?)(?:yi|yı|yu|yü|ni|nı|nu|nü)$", r"\1", cleaned)
    cleaned = _strip_trailing_case_particles(cleaned)
    return cleaned.strip(" .,!?:;\"'’")


# Açık GUI eylem fiilleri — bunlar tek başına "ekranda mouse/klavye ile işlem
# yap" demektir; hiçbir spesifik capability bunları karşılamaz.
_OPERATOR_GUI_VERBS = (
    "tikla", "tıkla", "click", "cift tikla", "çift tıkla", "double click",
    "sag tik", "sağ tık", "right click", "surukle", "sürükle", "drag",
    "asagi kaydir", "aşağı kaydır", "yukari kaydir", "yukarı kaydır", "scroll",
    "uzerine gel", "üzerine gel", "butonuna bas", "butonuna tikla",
    "tusuna bas", "tuşuna bas", "alanina yaz", "alanına yaz", "kutusuna yaz",
)
# "Tarayıcıdan bir kaynak (resim/dosya) bul & kaydet" dar kalıbı — bu görevi
# başka hiçbir capability yapamaz, o yüzden operatöre gider. Belge/mesaj/
# hesaplama gibi generic "kaydet/gönder" komutlarını GÖLGELEMEZ.
_OPERATOR_BROWSER_TOKENS = ("safari", "chrome", "firefox", "edge", "opera", "arc", "brave", "tarayici", "tarayıcı", "browser")
_OPERATOR_RESOURCE_TOKENS = ("resim", "resmi", "gorsel", "görsel", "foto", "fotograf", "fotoğraf", "image", "picture", "gif")
_OPERATOR_GRAB_VERBS = ("bul", "kaydet", "indir", "download")


_IMAGE_FIND_VERBS = ("bul", "ara", "goster", "göster", "ac", "aç", "getir", "indir", "kaydet", "bulur musun")
_IMAGE_DRAW_VERBS = ("ciz", "çiz", "olustur", "oluştur", "uret", "üret", "generate", "yap", "tasarla")
_IMAGE_RESOURCE_WORDS = ("resim", "resmi", "resmini", "gorsel", "görsel", "gorseli", "görseli", "foto", "fotograf", "fotoğraf", "image", "picture")
_IMAGE_EDIT_VERBS = (
    "duzenle", "düzenle", "degistir", "değiştir", "kaldir", "kaldır",
    "arka plan", "rengini", "stilini", "retouch", "edit", "remove", "replace",
)
# "kaydet/indir" varsa görseli GERÇEKTEN indirip diske yazan image_fetch'e gider;
# yoksa sadece tarayıcıda arama açılır.
_IMAGE_SAVE_VERBS = ("kaydet", "indir", "download", "save", "kaydeder")
# Hedef klasör anahtarları (normalize edilmiş) → açık yol.
_IMAGE_DEST_KEYWORDS = (
    ("masaustu", "~/Desktop"),
    ("desktop", "~/Desktop"),
    ("indirilenler", "~/Downloads"),
    ("downloads", "~/Downloads"),
    ("resimler klasor", "~/Pictures"),
    ("pictures", "~/Pictures"),
    ("fotograflar klasor", "~/Pictures"),
    ("belgeler", "~/Documents"),
    ("documents", "~/Documents"),
)


def _image_find_route(text: str) -> "RoutedTask | None":
    """"X resmi/görseli bul/ara/göster" → Google Görseller araması (tarayıcıda).
    Kırılgan pikselli operatör yerine %100 güvenilir; 'kedi resmi çiz' gibi ÜRETME
    komutlarını (image_generate) gölgelemez."""
    original = str(text or "").strip()
    if not original:
        return None
    q = _normalise(original)
    has_resource = any(w in q for w in _IMAGE_RESOURCE_WORDS)
    has_find = any(v in q for v in _IMAGE_FIND_VERBS)
    has_draw = any(v in q for v in _IMAGE_DRAW_VERBS)
    if not (has_resource and has_find) or has_draw:
        return None
    # Arama konusunu çıkar: "resim/görsel" kelimesinden ÖNCEki isim öbeği.
    subject = ""
    m = re.search(r"(.+?)\s+(?:resim|resmi|resmini|gorsel|görsel|gorseli|görseli|foto\w*|image|picture)", q)
    if m:
        subject = m.group(1).strip()
    # Baştaki uygulama/ablatif ekli tokenları at ("safariden", "tarayicida").
    subject_tokens = [
        tok for tok in subject.split()
        if not any(tok.startswith(app) for app in _OPERATOR_BROWSER_TOKENS)
        and tok not in {"bir", "bana", "su", "şu", "bu", "internetten", "webden", "googledan"}
    ]
    subject = " ".join(subject_tokens).strip() or subject.strip()
    if not subject:
        return None
    # "kaydet/indir" niyeti → görseli herkese açık kaynaktan indirip diske yaz
    # (kırılgan pikselli operatör yerine %100 güvenilir HTTP indirme).
    if any(v in q for v in _IMAGE_SAVE_VERBS):
        destination = ""
        for keyword, path in _IMAGE_DEST_KEYWORDS:
            if keyword in q:
                destination = path
                break
        return RoutedTask(
            "image_fetch",
            {"query": subject, "destination": destination or "~/Desktop", "count": 1},
            "image_fetch",
            intent="image_fetch",
            confidence=0.92,
            privacy_class="public_text",
        )
    from urllib.parse import quote_plus
    url = f"https://www.google.com/search?tbm=isch&q={quote_plus(subject)}"
    return RoutedTask(
        "browser_control",
        {"action": "open_url", "url": url},
        "image_search",
        intent="image_search",
        confidence=0.9,
        privacy_class="public_text",
    )


def _operator_action_route(text: str) -> "RoutedTask | None":
    """Açık GUI eylem fiili içeren komutları görsel operatöre (observe→plan→
    execute→verify, gerçek mouse/klavye) yönlendirir. Yalnız net GUI fiilleri
    (tıkla/kaydır/yaz…) — kırılgan pikselli otomasyonu sadece gerçekten GUI
    manipülasyonu istenen yerde kullanır. Operatör kendi iznini uygular."""
    original = str(text or "").strip()
    if not original:
        return None
    q = _normalise(original)
    if not any(marker in q for marker in _OPERATOR_GUI_VERBS):
        return None
    return RoutedTask(
        "desktop_operator.run",
        {"goal": original},
        "desktop_operator",
        intent="desktop_operator",
        confidence=0.85,
        privacy_class="local_private",
    )


def _extract_quoted_message(text: str) -> str:
    """Tırnak içi mesajı çıkarır. Çift tırnak öncelikli; tek tırnak yalnız
    boşlukla açılıyorsa (Türkçe ek-kesme işaretini —commit'le— mesaj sanmamak
    için) kabul edilir. En uzun aday seçilir."""
    original = str(text or "")
    doubles = [d.strip() for d in re.findall(r'"([^"]+)"', original) if d.strip()]
    if doubles:
        return max(doubles, key=len)
    singles = [s.strip() for s in re.findall(r"(?:^|\s)'([^']+?)'(?=\s|$)", original) if s.strip()]
    return max(singles, key=len) if singles else ""


def _developer_tool_route(text: str) -> "RoutedTask | None":
    """Yüksek-sinyalli, düşük-çakışmalı geliştirici (kod-ajanı) komutlarını
    okuma-tarafı dev tool'larına yönlendirir: git durumu/diff, proje ağacı,
    kod içinde arama. file_read burada bilinçli yok (document_read çakışması);
    o ajan-içi capability olarak kalır."""
    original = str(text or "").strip()
    if not original:
        return None
    q = _normalise(original)
    tokens = q.split()

    # git commit (mutasyon → onay gerekli; PUSH yapılmaz). Yalnız açık commit niyeti.
    if "commit" in q:
        message = _extract_quoted_message(original)
        return RoutedTask(
            "git_commit", {"path": ".", "message": message, "add_all": True}, "git_commit",
            intent="git_commit", confidence=0.85, requires_confirmation=True, privacy_class="local_private",
        )
    # git branch oluştur (mutasyon → onay gerekli). Yalnız açık oluşturma niyeti.
    if any(p in q for p in ("yeni branch", "branch olustur", "branch ac", "new branch", "create branch", "yeni dal")):
        _branch_verbs = {"yeni", "new", "create", "branch", "git", "olustur", "ac", "dal", "adinda", "adiyla", "isimli"}
        candidates = [
            tok for tok in original.split()
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/\-]*", tok) and _normalise(tok) not in _branch_verbs
        ]
        branch_name = next((c for c in candidates if "/" in c or "-" in c), candidates[-1] if candidates else "")
        if branch_name:
            return RoutedTask(
                "git_branch", {"path": ".", "name": branch_name, "checkout": True}, "git_branch",
                intent="git_branch", confidence=0.85, requires_confirmation=True, privacy_class="local_private",
            )

    # git durumu
    if "git status" in q or ("git" in tokens and any(w in tokens for w in ("durum", "durumu", "status"))):
        return RoutedTask(
            "git_status", {"path": "."}, "git_status",
            intent="git_status", confidence=0.9, privacy_class="local_private",
        )
    # git diff / farklar (yalnız git bağlamında)
    if "git diff" in q or ("git" in tokens and any(w in q for w in ("diff", "fark", "farklar", "farklari", "degisiklik"))):
        staged = any(w in q for w in ("staged", "indekste", "index"))
        return RoutedTask(
            "git_diff", {"path": ".", "staged": staged}, "git_diff",
            intent="git_diff", confidence=0.88, privacy_class="local_private",
        )
    # proje / klasör ağacı
    if any(p in q for p in ("proje yapisi", "proje agaci", "klasor agaci", "dizin agaci", "dosya agaci", "dosya yapisi", "directory tree", "folder tree", "file tree")):
        return RoutedTask(
            "directory_tree", {"path": ".", "max_depth": 3}, "directory_tree",
            intent="directory_tree", confidence=0.9, privacy_class="local_private",
        )
    # kod/proje içinde arama (web/görsel aramasını çalmamak için kod bağlamı şart)
    code_ctx = any(w in q for w in ("kod", "kodda", "kodlarda", "projede", "repoda", "kaynak kod", "codebase", "dosyalarda"))
    if code_ctx and any(w in tokens for w in ("ara", "bul", "search", "grep", "gecen", "geçen")):
        subject = _extract_after(
            [r"(?:kod(?:da|larda)?|projede|repoda|dosyalarda|codebase)\s+(?:icinde\s+|içinde\s+)?['\"]?(.+?)['\"]?\s+(?:ara|bul|search|grep|gecen|geçen)"],
            original,
        )
        subject = subject or _extract_after([r"['\"](.+?)['\"]"], original)
        if subject:
            return RoutedTask(
                "file_search", {"query": subject, "path": "."}, "file_search",
                intent="file_search", confidence=0.82, privacy_class="local_private",
            )
    return None


def _is_non_app_open_target(value: str) -> bool:
    """Uygulama adı gibi görünmeyen, ama 'aç' fiiliyle gelen ifadeler (tarayıcı
    sekmesi vb.) — open_app'e yanlış yönlenmemeleri için."""
    normalized = _normalise(value)
    if normalized in {
        "yeni sekme", "sekme", "new tab", "tab", "yeni pencere", "new window",
        "yeni sayfa", "new page", "gizli sekme", "incognito", "gizli pencere",
        "yeni tab", "bir sekme", "bir tab",
    }:
        return True
    # "... sekme" / "... tab" ile biten kısa ifadeler
    return bool(normalized) and normalized.split()[-1] in {"sekme", "tab"} and len(normalized.split()) <= 3


# "Chrome'dan kedi resmi aç" gibi cümlelerde ayrılma/bulunma eki uygulama adı
# ile İÇERİĞİ ayırır; open_app'e "Chrome dan kedi resmi" gibi uydurma bir ad
# gitmesin. Bağlaçlar hem ayrı jeton ("Chrome dan") hem kesme işaretli
# ("Chrome'dan") hem bitişik ("Safariden") yazımıyla yakalanır.
_APP_CONTENT_CONNECTORS = {"dan", "den", "tan", "ten", "da", "de", "uzerinden", "icinden", "ile"}
_ATTACHED_CONTENT_SUFFIXES = ("dan", "den", "tan", "ten")
_BROWSER_APP_DISPLAY_NAMES = {
    "Safari",
    "Google Chrome",
    "Firefox",
    "Microsoft Edge",
    "Opera",
    "Brave Browser",
    "Arc",
    "Yandex",
}
# Alias tablosunda olmayan yaygın tarayıcı yazımları da tanınsın.
_EXTRA_BROWSER_ALIASES = {
    "edge": "Microsoft Edge",
    "microsoft edge": "Microsoft Edge",
    "opera": "Opera",
    "brave": "Brave Browser",
    "arc": "Arc",
    "yandex": "Yandex",
    "tarayici": "Safari",
    "browser": "Safari",
    "google": "Google Chrome",
}
_IMAGE_CONTENT_WORDS = ("resim", "resmi", "resimleri", "gorsel", "gorseli", "gorselleri", "foto", "fotograf", "image", "photo")

# Masaüstünde yerel uygulaması olmayan (ya da tipik olarak tarayıcıda açılan)
# servisler: "YouTube aç" open_app("YouTube")→APP_NOT_FOUND yerine tarayıcıda
# doğru adrese gitmeli. Yerel uygulaması yaygın olanlar (Spotify, Notion,
# WhatsApp...) bilerek YOK — onlar APP_ALIASES ile uygulamaya gider.
_WEB_SERVICE_URLS = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com",
    "netflix": "https://www.netflix.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "facebook": "https://www.facebook.com",
    "tiktok": "https://www.tiktok.com",
    "twitch": "https://www.twitch.tv",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
}


def _web_service_url(folded_phrase: str) -> str:
    phrase = " ".join(str(folded_phrase or "").split())
    if phrase in _WEB_SERVICE_URLS:
        return _WEB_SERVICE_URLS[phrase]
    # "youtube u" / "youtube'u" gibi hâl ekli yazımlar da servisi bulsun.
    tokens = phrase.replace("'", " ").split()
    if len(tokens) >= 2 and tokens[-1] in {"u", "i", "a", "e", "yi", "yu", "ye", "ya"}:
        return _WEB_SERVICE_URLS.get(" ".join(tokens[:-1]), "")
    return ""


def _browser_content_step(content: str) -> dict[str, Any]:
    """İçerik ifadesini doğru tarayıcı adımına çevirir: bilinen web servisi →
    doğrudan URL, görsel isteği → görsel araması, aksi halde arama."""
    folded = _normalise(content)
    service_url = _web_service_url(folded)
    if service_url:
        return {
            "capability": "browser_control",
            "args": {"action": "open_url", "url": service_url},
            "description": f"{content} açılacak.",
        }
    if any(word in folded.split() for word in _IMAGE_CONTENT_WORDS):
        return {
            "capability": "browser_control",
            "args": {"action": "open_url", "url": "https://www.google.com/search?tbm=isch&q=" + _url_quote(content)},
            "description": f"'{content}' için görsel araması açılacak.",
        }
    return {
        "capability": "browser_control",
        "args": {"action": "search", "query": content},
        "description": f"'{content}' araması yapılacak.",
    }


def _route_app_content_open(original: str) -> RoutedTask | None:
    """'<tarayıcı>'dan <içerik> aç' kalıbını erken yakalar — youtube/arama
    regex'lerinden ÖNCE çağrılır, yoksa "Google dan YouTube aç" gibi cümleler
    youtube_play(query="Google dan") benzeri bozuk rotalara kaçar."""
    target = _extract_after(_OPEN_VERB_PATTERNS, original)
    if not target:
        return None
    target = _clean_app_name(target)
    if _looks_like_url(target):
        return None
    app_content = _split_app_content_target(target)
    if app_content is None:
        return None
    app_display, content = app_content
    if app_display not in _BROWSER_APP_DISPLAY_NAMES:
        return None
    steps = [
        {"capability": "open_app", "args": {"app_name": app_display}, "description": f"{app_display} açılacak."},
        _browser_content_step(content),
    ]
    summary = f"{app_display} açılıp '{content}' görüntülenecek."
    return RoutedTask(
        "open_app",
        {"app_name": app_display},
        "open_app_content",
        intent="open_app_content",
        confidence=0.9,
        is_multi_step=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _resolve_known_app_phrase(folded_phrase: str) -> str | None:
    """Katlanmış ifadeyi bilinen bir uygulama görünen adına çözer; bilinmiyorsa None."""
    from actions.open_app import _FOLDED_ALIASES as _open_app_aliases

    phrase = " ".join(str(folded_phrase or "").split())
    if not phrase:
        return None
    return _open_app_aliases.get(phrase) or _EXTRA_BROWSER_ALIASES.get(phrase)


def _split_app_content_target(value: str) -> tuple[str, str] | None:
    """'<uygulama> dan/den <içerik>' kalıbını (bilinen uygulama + içerik) ayırır.

    Dönen çift: (uygulama görünen adı, içerik metni). Kalıp yoksa None —
    open_app normal tek-uygulama yolunda kalır.
    """
    from actions.open_app import _tr_fold

    tokens = str(value or "").split()
    if len(tokens) < 2:
        return None
    folded = [_tr_fold(token) for token in tokens]

    max_head = min(3, len(tokens))
    for k in range(1, max_head + 1):
        last = folded[k - 1]
        # Kesme işaretli bağlaç: "chrome'dan kedi resmi"
        if "'" in last:
            base, _, suffix = last.partition("'")
            if suffix in _APP_CONTENT_CONNECTORS and k < len(tokens):
                app = _resolve_known_app_phrase(" ".join(folded[: k - 1] + [base]))
                if app:
                    return app, " ".join(tokens[k:])
        # Ayrı jeton bağlaç: "chrome dan kedi resmi"
        app = _resolve_known_app_phrase(" ".join(folded[:k]))
        if app and k < len(folded) - 1 and folded[k].strip("'") in _APP_CONTENT_CONNECTORS:
            return app, " ".join(tokens[k + 1:])
    # Bitişik ek: "safariden kedi resmi"
    first = folded[0]
    for suffix in _ATTACHED_CONTENT_SUFFIXES:
        if first.endswith(suffix) and len(first) > len(suffix) + 2:
            app = _resolve_known_app_phrase(first[: -len(suffix)])
            if app:
                return app, " ".join(tokens[1:])
    return None


_OPEN_VERB_PATTERNS = [
    r"(.+?)\s+(?:uygulamas[ıi]n[ıi]\s+)?(?:ac|aç|open|launch|başlat|baslat|start)$",
    r"(?:ac|aç|open|launch|başlat|baslat|start)\s+(.+)$",
]


def prompt_requests_app_content(prompt: str) -> bool:
    """Prompt 'X uygulamasından Y aç' kalıbında mı? (LLM delegasyon kapısı için.)

    True ise görev tek open_app komutu DEĞİLDİR; kataloglu LLM planlayıcıya
    delege edilmelidir.
    """
    target = _extract_after(_OPEN_VERB_PATTERNS, str(prompt or ""))
    if not target:
        return False
    return _split_app_content_target(_clean_app_name(target)) is not None


def _is_generic_app_target(value: str) -> bool:
    normalized = _normalise(value)
    return normalized in {
        "",
        "app",
        "application",
        "program",
        "onu",
        "bunu",
        "o",
        "bu",
        "uygulama",
        "uygulamayi",
        "pencere",
        "window",
    }


def _is_generic_window_reference(value: str) -> bool:
    normalized = _normalise(value)
    return normalized in {
        "",
        "onu",
        "bunu",
        "o",
        "bu",
        "buradaki",
        "aktif pencere",
        "bu pencere",
        "pencere",
        "window",
    }


def _looks_like_url(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    return bool(parsed.netloc and "." in parsed.netloc)


def _sys_info_query(text: str) -> str | None:
    q = _normalise(text)
    tokens = q.split()

    def _has(stems: set[str]) -> bool:
        # Ekli/çekimli biçimleri de yakala: "pilim", "şarjım", "diskte",
        # "bellekte" → kök önekle eşleşir. Tam token eşitliği "pilim"i
        # ıskalıyordu; bu Jarvis'in en sık kaçırdığı komut ailesiydi.
        for token in tokens:
            for stem in stems:
                if token == stem or (len(stem) >= 3 and token.startswith(stem)):
                    return True
        return False

    if _has({"pil", "battery", "sarj", "batarya"}):
        return "battery"
    if _has({"cpu", "islemci"}) or "islemci" in q:
        return "cpu"
    if _has({"ram", "bellek", "memory", "hafiza"}):
        return "ram"
    if _has({"disk", "depolama", "storage"}):
        return "disk"
    # "internet" yalnız TAM token olarak ağ-durumu sorgusudur; "internetten"/
    # "internette" (kaynak/konum: "internetten indir") bir durum sorgusu değildir.
    if _has({"wifi", "network"}) or "internet" in tokens or "ag durumu" in q or _has({"agim"}):
        return "network"
    if _has({"saat", "time", "zaman"}):
        return "time"
    if _has({"tarih", "date"}) or "bugun hangi gun" in q or "hangi gundeyiz" in q:
        return "date"
    if any(phrase in q for phrase in ("sistem bilgisi", "system info", "sistem durumu", "sistem raporu")):
        return "all"
    return None


def _clipboard_write_text(text: str) -> str:
    """"panoya kopyala X" / "X'i panoya kopyala" biçimlerinden kopyalanacak
    metni çıkarır."""
    original = str(text or "").strip()
    # Sonra gelen biçim: "panoya kopyala: X" / "panoya kopyala X"
    after = _extract_after(
        [
            r"(?:panoya|pano'ya|clipboard'?a)\s+(?:kopyala|yaz|ekle)\s*[:\-]?\s*(.+)$",
            r"copy\s+(?:to\s+clipboard)?\s*[:\-]?\s*(.+?)\s*(?:to\s+clipboard)?$",
        ],
        original,
    )
    if after.strip():
        return after.strip().strip("\"'")
    # Önce gelen biçim: "X panoya kopyala" / "X'i panoya kopyala". Kelimeyi
    # bütün yakala; yalnız apostrofla gelen ek (X'i) ayrıca budanır — böylece
    # "raporu" gibi ekler yanlışlıkla kırpılmaz.
    match = re.search(r"^(.+?)\s+(?:panoya|clipboard'?a)\s+(?:kopyala|yaz)", original, flags=re.IGNORECASE)
    if match and match.group(1).strip():
        captured = match.group(1).strip().strip("\"'")
        captured = re.sub(r"['’](?:i|ı|u|ü|yi|yı|yu|yü)$", "", captured).strip()
        return captured
    return ""


def _clipboard_route(text: str) -> "RoutedTask | None":
    q = _normalise(text)
    read_markers = (
        "panoda ne var", "panodaki", "panodakini", "pano oku", "panoyu oku",
        "panoda ne", "clipboard oku", "kopyalanani", "kopyalanan metni",
        "panonun icerigi", "panoyu goster",
    )
    if any(marker in q for marker in read_markers):
        return RoutedTask(
            "clipboard_read", {}, "clipboard_read",
            intent="clipboard_read", confidence=0.9, privacy_class="local_private",
        )
    if any(marker in q for marker in ("panoya kopyala", "panoya yaz", "clipboarda kopyala", "copy to clipboard", "clipboard a kopyala")):
        payload = _clipboard_write_text(text)
        if payload:
            return RoutedTask(
                "clipboard_write", {"text": payload}, "clipboard_write",
                intent="clipboard_write", confidence=0.88, privacy_class="local_private",
            )
    return None


def _date_query(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("yarin", "tomorrow")):
        return "tomorrow"
    if any(token in q for token in ("siradaki", "sonraki", "next")):
        return "next"
    if any(token in q for token in ("hafta", "week")):
        return "upcoming"
    if any(token in q for token in ("ay", "month")):
        return "this month"
    return "today" if any(token in q for token in ("bugun", "today")) else "agenda"


def _extract_after(patterns: list[str], text: str) -> str:
    original = str(text or "").strip()
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if match:
            return _strip_polite_suffix(match.group(1))
    return ""


def _workspace_root() -> Path:
    return Path.cwd().resolve()


def _slugify_output_hint(value: str, fallback: str) -> str:
    cleaned = _normalise(value)
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return cleaned[:64] or fallback


def _default_output_path(extension: str, hint: str) -> str:
    filename = f"{_slugify_output_hint(hint, 'elyan-output')}{extension}"
    return str((_workspace_root() / "elyan_output" / filename).resolve())


def _resolve_output_path(text: str, extension: str, *, hint: str) -> str:
    explicit = re.search(r'["“](.+?)["”]', text)
    if explicit:
        candidate = Path(explicit.group(1).strip()).expanduser()
        if not candidate.suffix:
            candidate = candidate.with_suffix(extension)
        if not candidate.is_absolute():
            candidate = (_workspace_root() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return str(candidate)
    absolute = re.search(
        rf"((?:/|~)[^\s]+(?:{re.escape(extension.lstrip('.'))}))",
        text,
        flags=re.IGNORECASE,
    )
    if absolute:
        return str(Path(absolute.group(1).strip()).expanduser().resolve())
    relative = re.search(
        rf"([A-Za-z0-9_\-./]+(?:{re.escape(extension.lstrip('.'))}))",
        text,
        flags=re.IGNORECASE,
    )
    if relative:
        return str((_workspace_root() / relative.group(1).strip()).resolve())
    return _default_output_path(extension, hint)


_DOCUMENT_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".md", ".markdown", ".json", ".csv", ".rtf", ".html", ".htm"}
_DATA_SUFFIXES = {".csv", ".json", ".xlsx", ".xls"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_OCR_SUFFIXES = _IMAGE_SUFFIXES | {".pdf"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".mp4", ".webm"}
_DOCUMENT_SUMMARY_SAVE_TOKENS = {"ozetle", "özetle", "summary", "summarize"}
_DOCUMENT_SAVE_TOKENS = {"kaydet", "save", "sakla", "store"}


def _selected_artifact_items(selected_artifacts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(selected_artifacts, list):
        return []
    return [item for item in selected_artifacts if isinstance(item, dict)]


def _resolve_candidate_path(raw: str) -> str:
    candidate = Path(str(raw or "").strip()).expanduser()
    if candidate.is_absolute():
        return str(candidate.resolve())
    return str((_workspace_root() / candidate).resolve())


def _explicit_path_for_suffixes(text: str, allowed_suffixes: set[str]) -> str:
    original = str(text or "").strip()
    if not original:
        return ""
    quoted = re.search(r'["“](.+?)["”]', original)
    if quoted:
        candidate = quoted.group(1).strip()
        if Path(candidate).suffix.lower() in allowed_suffixes:
            return _resolve_candidate_path(candidate)
    for match in re.finditer(
        r"([A-Za-z]:[\\/][^\s\"“”]+|(?:~|/)[^\s\"“”]+|[A-Za-z0-9_.\\/-]+\.[A-Za-z0-9]+)",
        original,
        flags=re.IGNORECASE,
    ):
        candidate = match.group(1).strip(" ,;:()[]{}")
        if Path(candidate).suffix.lower() in allowed_suffixes:
            return _resolve_candidate_path(candidate)
    return ""


def _selected_paths_for(path: str, selected_artifacts: list[dict[str, Any]] | None) -> list[str]:
    normalized_path = str(path or "").strip().lower()
    if not normalized_path:
        return []
    for item in _selected_artifact_items(selected_artifacts):
        candidate = str(item.get("path", "") or "").strip()
        if candidate and candidate.lower() == normalized_path:
            return [candidate]
    return []


def _selected_artifact_path(
    selected_artifacts: list[dict[str, Any]] | None,
    *,
    kinds: set[str] | None = None,
    suffixes: set[str] | None = None,
) -> str:
    normalized_kinds = {str(kind).strip().lower() for kind in (kinds or set()) if str(kind).strip()}
    allowed_suffixes = {str(suffix).strip().lower() for suffix in (suffixes or set()) if str(suffix).strip()}
    for item in _selected_artifact_items(selected_artifacts):
        candidate = str(item.get("path", "") or "").strip()
        if not candidate:
            continue
        kind = str(item.get("kind", "") or "").strip().lower()
        suffix = Path(candidate).suffix.lower()
        kind_ok = not normalized_kinds or kind in normalized_kinds
        suffix_ok = not allowed_suffixes or suffix in allowed_suffixes
        if kind_ok and suffix_ok:
            return candidate
    return ""


def _resolve_document_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"document"},
        suffixes=_DOCUMENT_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _resolve_data_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _DATA_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"document"},
        suffixes=_DATA_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _resolve_ocr_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _OCR_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"image", "document"},
        suffixes=_OCR_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _resolve_audio_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _AUDIO_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"audio"},
        suffixes=_AUDIO_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _resolve_image_target(text: str, selected_artifacts: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    explicit = _explicit_path_for_suffixes(text, _IMAGE_SUFFIXES)
    if explicit:
        return explicit, _selected_paths_for(explicit, selected_artifacts)
    selected = _selected_artifact_path(
        selected_artifacts,
        kinds={"image"},
        suffixes=_IMAGE_SUFFIXES,
    )
    return (selected, [selected]) if selected else ("", [])


def _image_output_options(text: str, *, editing: bool = False) -> tuple[str, str]:
    q = _normalise(text)
    if "21:9" in q:
        ratio = "21:9"
    elif "9:16" in q or any(token in q for token in ("story", "reels", "tiktok", "telefon duvar kagidi", "telefon duvar kağıdı")):
        ratio = "9:16"
    elif "16:9" in q or any(token in q for token in ("banner", "thumbnail", "kapak", "yatay", "landscape")):
        ratio = "16:9"
    elif "3:2" in q:
        ratio = "3:2"
    elif "2:3" in q or any(token in q for token in ("afis", "afiş", "poster", "dikey", "vertical")):
        ratio = "2:3"
    else:
        ratio = "1:1"
    image_size = "4K" if re.search(r"\b4k\b", q, flags=re.IGNORECASE) else "2K"
    return ratio, image_size


def _image_edit_route(
    text: str,
    selected_artifacts: list[dict[str, Any]] | None = None,
) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in _IMAGE_EDIT_VERBS):
        return None
    source_path, selected_paths = _resolve_image_target(text, selected_artifacts)
    if not source_path:
        return None
    inferred_ratio, image_size = _image_output_options(text, editing=True)
    explicit_ratio = inferred_ratio if re.search(r"\b(?:21:9|16:9|9:16|3:2|2:3|1:1)\b", q) else ""
    output_path = _default_output_path(".png", f"{Path(source_path).stem}-edited")
    args: dict[str, Any] = {
        "prompt": str(text or "").strip(),
        "sourcePath": source_path,
        "sourcePaths": [source_path],
        "outputPath": output_path,
        "aspectRatio": explicit_ratio,
        "imageSize": image_size,
        "overwrite": False,
    }
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "image_edit",
        args,
        "selected_image_edit",
        intent="image_edit",
        confidence=0.96,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(
            f"{Path(source_path).name} Gemini ile düzenlenecek ve {Path(output_path).name} oluşturulacak.",
            [{"capability": "image_edit", "args": args, "description": "Seçili görsel Gemini ile düzenlenecek."}],
            "local_private",
        ),
    )


def _image_generate_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if any(token in q for token in ("canvas", "kanvas", "tuval")):
        return None
    if any(token in q for token in ("grafik", "grafi", "grafig", "chart", "plot", "histogram", "denklem", "fonksiyon")):
        return None
    explicit_draw = re.search(r"(?<!\w)(?:çiz|ciz|draw|paint|illustrate)(?!\w)", q, flags=re.IGNORECASE)
    has_resource = any(token in q for token in _IMAGE_RESOURCE_WORDS) or any(
        token in q for token in ("afis", "afiş", "poster", "banner", "logo", "ikon", "avatar", "illüstrasyon", "illustration")
    )
    has_generate = any(token in q for token in ("olustur", "oluştur", "uret", "üret", "generate", "tasarla", "create"))
    if not explicit_draw and not (has_resource and has_generate):
        return None
    aspect_ratio, image_size = _image_output_options(text)
    output_path = _resolve_output_path(text, ".png", hint="elyan-image")
    args = {
        "prompt": str(text or "").strip(),
        "outputPath": output_path,
        "aspectRatio": aspect_ratio,
        "imageSize": image_size,
        "overwrite": False,
    }
    return RoutedTask(
        "image_generate",
        args,
        "image_generate",
        intent="image_generate",
        confidence=0.94,
        requires_confirmation=True,
        privacy_class="public_text",
        plan_preview=_build_plan_summary(
            f"Gemini ile {Path(output_path).name} görseli üretilecek.",
            [{"capability": "image_generate", "args": args, "description": "İstek Gemini ile görsele dönüştürülecek."}],
            "public_text",
        ),
    )


def _embedded_attachment_payload(text: str) -> tuple[str, list[str]]:
    original = str(text or "").strip()
    if not original:
        return "", []
    pattern = re.compile(
        r"---\s*(?P<label>.+?)\s*---\s*\n(?P<body>.*?)\n---\s*BELGE SONU:\s*(?P=label)\s*---",
        flags=re.IGNORECASE | re.DOTALL,
    )
    parts: list[str] = []
    labels: list[str] = []
    for match in pattern.finditer(original):
        body = str(match.group("body") or "").strip()
        if not body:
            continue
        parts.append(body)
        label = " ".join(str(match.group("label") or "").split()).strip()
        if label and label not in labels:
            labels.append(label)
    return ("\n\n".join(parts).strip(), labels) if parts else ("", [])


def _document_source_payload(
    text: str,
    selected_artifacts: list[dict[str, Any]] | None,
) -> tuple[str, str, list[str], list[str]]:
    embedded_text, labels = _embedded_attachment_payload(text)
    path, selected_paths = _resolve_document_target(text, selected_artifacts)
    if path and not embedded_text:
        return path, "", selected_paths, [Path(path).stem]
    if embedded_text:
        return "", embedded_text, [], labels
    if path:
        return path, "", selected_paths, [Path(path).stem]
    return "", "", [], labels


def _document_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("ozetle", "özetle", "summary", "summarize")):
        return "summary"
    if any(token in q for token in ("madde", "bullet", "listele", "sirala", "sırala")):
        return "bullets"
    return "read"


def _ocr_mode(text: str) -> str:
    return _document_mode(text)


def _has_ocr_intent(text: str, *, selected_visual: bool = False) -> bool:
    q = _normalise(text)
    if any(token in q for token in ("ocr", "yazi", "yazı", "metin", "karakter")):
        return True
    return selected_visual and any(token in q for token in ("oku", "okur musun", "read text"))


def _image_read_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("palette", "palet", "renk")):
        return "palette"
    if any(
        token in q
        for token in (
            "metadata",
            "meta",
            "boyut",
            "cozunurluk",
            "çözünürlük",
            "resolution",
        )
    ):
        return "metadata"
    return "summary"


def _data_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("preview", "onizleme", "önizleme", "ilk satir", "ilk satır")):
        return "preview"
    if any(token in q for token in ("profil", "profile", "istatistik")):
        return "profile"
    return "summary"


def _chart_type(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("histogram", "dagilim", "dağılım")):
        return "histogram"
    if any(token in q for token in ("scatter", "daginik", "dağınık")):
        return "scatter"
    if any(token in q for token in ("line", "cizgi", "çizgi")):
        return "line"
    return "bar"


def _latex_parse_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("normalize", "normalizasyon", "normallestir", "normallestir", "normalize et")):
        return "normalize"
    return "parse"


def _math_mode(text: str) -> str:
    q = _normalise(text)
    if any(token in q for token in ("carpanlara ayir", "çarpanlara ayır", "factor")):
        return "factor"
    if any(token in q for token in ("sadelestir", "sadeleştir", "simplify")):
        return "simplify"
    if any(token in q for token in ("genislet", "genişlet", "expand")):
        return "expand"
    if any(token in q for token in ("hesapla", "evaluate", "sayisal", "sayısal")):
        return "evaluate"
    return "solve"


def _is_probably_latex_expression(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    return candidate.startswith(("\\", "$")) or any(
        token in candidate for token in ("\\frac", "\\sqrt", "\\sum", "\\int", "\\alpha", "\\beta", "{", "}")
    )


def _spoken_text_payload(text: str) -> str:
    original = str(text or "").strip()
    quoted = re.search(r'["“](.+?)["”]', original)
    if quoted:
        return quoted.group(1).strip()
    cleaned = re.sub(r"\b(?:sesli|yüksek sesle|yuksek sesle)\b", " ", original, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:oku|okur musun|okuyabilir misin|read aloud|speak)\b", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" .,!?:;")


def _extract_math_expression(text: str) -> str:
    original = str(text or "").strip()
    patterns = [
        r"(.+?)\s+denklemini\s+(?:coz|çöz|solve)$",
        r"(.+?)\s+(?:i|ı|yi|yı|yu|yü)['’]?(?:\s+)?carpanlara\s+ayir$",
        r"(.+?)\s+(?:i|ı|yi|yı|yu|yü)['’]?(?:\s+)?çarpanlara\s+ayır$",
        r"(.+?)\s+(?:ifadesini\s+)?(?:sadelestir|sadeleştir|simplify)$",
        r"(.+?)\s+(?:ifadesini\s+)?(?:genislet|genişlet|expand)$",
        r"(.+?)\s+(?:ifadesini\s+)?(?:hesapla|evaluate)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,!?:;")
    return original.strip(" .,!?:;")


def _extract_latex_expression(text: str) -> str:
    original = str(text or "").strip()
    patterns = [
        r"(.+?)\s+(?:ifadesini\s+)?(?:parse et|normalize et|normallestir|normallestir)$",
        r"(.+?)\s+(?:ifadesini\s+)?(?:coz|çöz|solve|sadelestir|sadeleştir|carpanlara ayir|çarpanlara ayır|factor|genislet|genişlet|expand|hesapla|evaluate)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,!?:;")
    return original.strip(" .,!?:;")


def _schedule_reference_datetime(text: str) -> dt.datetime | None:
    q = _normalise(text)
    now = dt.datetime.now().replace(second=0, microsecond=0)

    target_date = now.date()
    if "yarin" in q or "tomorrow" in q:
        target_date = now.date() + dt.timedelta(days=1)
    elif "bugun" in q or "today" in q:
        target_date = now.date()
    else:
        for token, weekday in TR_WEEKDAY_INDEX.items():
            if token in q:
                delta = (weekday - now.weekday()) % 7
                if delta == 0:
                    delta = 7
                target_date = now.date() + dt.timedelta(days=delta)
                break

    hour = 9
    minute = 0
    time_match = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(?:te|ta|de|da)?\b", q)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or "0")
    elif "sabah" in q:
        hour = 9
    elif any(token in q for token in ("ogle", "öğle", "noon")):
        hour = 12
    elif any(token in q for token in ("aksam", "akşam", "evening")):
        hour = 18

    try:
        return dt.datetime.combine(target_date, dt.time(hour=hour, minute=minute))
    except ValueError:
        return None


def _has_explicit_schedule_day(text: str) -> bool:
    q = _normalise(text)
    if any(token in q for token in ("yarin", "tomorrow", "bugun", "today")):
        return True
    return any(token in q for token in TR_WEEKDAY_INDEX)


def _strip_schedule_tokens(text: str) -> str:
    cleaned = str(text or "").strip()
    patterns = [
        r"\b(?:yarin|tomorrow|bugun|today|sabah|ogle|öğle|aksam|akşam|gece)\b",
        r"\b(?:pazartesi|sali|salı|carsamba|çarşamba|persembe|perşembe|cuma|cumartesi|pazar|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:te|ta|de|da)?\b",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:takvime|reminder|hatirlatici|hatırlatıcı|ekle|olustur|oluştur)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bdiye\b", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" .,!?:;")


def _build_plan_summary(summary: str, steps: list[dict[str, Any]], privacy_class: str) -> dict[str, Any]:
    agent_plan = build_agent_plan(steps, summary=summary)
    return {
        "summary": summary,
        "steps": steps,
        "privacyClass": privacy_class,
        "agentPlan": agent_plan,
        "stepCount": agent_plan.get("stepCount", 0),
        "agentRoles": agent_plan.get("agentRoles", []),
        "executionStrategy": agent_plan.get("executionStrategy", "single_lane"),
    }


def _day_time_label(value: dt.datetime) -> str:
    return f"{TR_WEEKDAY_LABELS.get(value.weekday(), value.strftime('%A'))} {value.strftime('%H:%M')}"


def revise_plan_payload(plan: dict[str, Any], revision_text: str) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        return None
    normalized = _normalise(revision_text)
    if not normalized:
        return None

    capability = str(plan.get("capability", "") or "").strip()
    steps = plan.get("steps", [])
    steps = [dict(step) for step in steps if isinstance(step, dict)]
    if not steps:
        return None

    if capability in {"add_calendar_event", "add_reminder"}:
        schedule_match = _schedule_reference_datetime(revision_text)
        current_args = dict(steps[0].get("args", {}) or {})
        if "bir saat" in normalized and any(token in normalized for token in ("ertele", "later", "sonra")):
            source = current_args.get("start_iso") or current_args.get("due_iso")
            if source:
                try:
                    parsed = dt.datetime.fromisoformat(str(source))
                    schedule_match = parsed + dt.timedelta(hours=1)
                except ValueError:
                    schedule_match = None
        elif "yarina al" in normalized or "yarına al" in revision_text.lower():
            source = current_args.get("start_iso") or current_args.get("due_iso")
            if source:
                try:
                    parsed = dt.datetime.fromisoformat(str(source))
                    schedule_match = parsed + dt.timedelta(days=1)
                except ValueError:
                    schedule_match = None
        elif schedule_match is not None and not _has_explicit_schedule_day(revision_text):
            source = current_args.get("start_iso") or current_args.get("due_iso")
            if source:
                try:
                    parsed = dt.datetime.fromisoformat(str(source))
                    schedule_match = parsed.replace(
                        hour=schedule_match.hour,
                        minute=schedule_match.minute,
                    )
                except ValueError:
                    pass
        if schedule_match is None:
            return None

        title = str(current_args.get("title", "") or "Yeni görev")
        if capability == "add_calendar_event":
            current_args["start_iso"] = schedule_match.isoformat()
            current_args["end_iso"] = (schedule_match + dt.timedelta(hours=1)).isoformat()
            steps[0]["description"] = f"Takvime '{title}' etkinliği eklenecek."
            summary = f"Takvime {_day_time_label(schedule_match)} için '{title}' etkinliğini ekleyeceğim."
        else:
            current_args["due_iso"] = schedule_match.isoformat()
            steps[0]["description"] = f"'{title}' hatırlatıcısı oluşturulacak."
            summary = f"'{title}' için {_day_time_label(schedule_match)} zamanlı bir hatırlatıcı oluşturacağım."
        steps[0]["args"] = current_args
        return {
            "capability": capability,
            "steps": steps,
            "planPreview": _build_plan_summary(summary, steps, "local_private"),
        }

    if capability == "open_app":
        replacement = _clean_app_name(
            _extract_after(
                [
                    r"(.+?)\s+yerine\s+(.+?)\s+(?:ac|aç|open|launch)$",
                    r"(.+?)\s+yap$",
                ],
                revision_text,
            ) or revision_text
        )
        if not replacement or _is_generic_app_target(replacement):
            return None
        steps[0]["args"] = {"app_name": replacement}
        steps[0]["description"] = f"{replacement} açılacak."
        return {
            "capability": capability,
            "steps": steps,
            "planPreview": _build_plan_summary(f"Önce {replacement} açılacak.", steps, "local_private"),
        }

    if capability == "browser_control":
        replacement = _extract_after(
            [
                r"(.+?)\s+yerine\s+(.+?)\s+(?:ac|aç|open|launch)$",
                r"(.+?)\s+yap$",
            ],
            revision_text,
        ) or revision_text
        replacement_url = _site_target_to_url(replacement)
        if not replacement_url:
            return None
        steps[0]["args"] = {"action": "open_url", "url": replacement_url}
        steps[0]["description"] = f"{replacement_url} açılacak."
        return {
            "capability": capability,
            "steps": steps,
            "planPreview": _build_plan_summary(f"{replacement_url} adresi açılacak.", steps, "public_text"),
        }

    if len(steps) >= 2 and str(steps[0].get("capability", "") or "") == "open_app" and str(
        steps[1].get("capability", "") or ""
    ) == "browser_control":
        replacement = _extract_after(
            [
                r".+?\s+yerine\s+(.+?)\s+(?:sitesini\s+)?(?:ac|aç|open|launch)$",
                r"(.+?)\s+yap$",
            ],
            revision_text,
        ) or revision_text
        replacement_url = _site_target_to_url(replacement)
        if not replacement_url:
            return None
        steps[1]["args"] = {"action": "open_url", "url": replacement_url}
        steps[1]["description"] = f"{replacement_url} açılacak."
        first_target = str(steps[0].get("args", {}).get("app_name", "") or "uygulama")
        return {
            "capability": capability,
            "steps": steps,
            "planPreview": _build_plan_summary(
                f"Önce {first_target} açılacak, ardından {replacement_url} adresi yüklenecek.",
                steps,
                "local_private",
            ),
        }

    return None


_KNOWN_SITES = {
    "openai": "https://openai.com",
    "github": "https://github.com",
    "google": "https://google.com",
    "youtube": "https://youtube.com",
    "notion": "https://notion.so",
    "slack": "https://slack.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "instagram": "https://instagram.com",
    "linkedin": "https://linkedin.com",
    "facebook": "https://facebook.com",
    "reddit": "https://reddit.com",
    "wikipedia": "https://tr.wikipedia.org",
    "vikipedi": "https://tr.wikipedia.org",
    "netflix": "https://netflix.com",
    "amazon": "https://amazon.com.tr",
    "trendyol": "https://trendyol.com",
    "hepsiburada": "https://hepsiburada.com",
    "sahibinden": "https://sahibinden.com",
    "gmail": "https://mail.google.com",
    "google maps": "https://maps.google.com",
    "haritalar": "https://maps.google.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "anthropic": "https://anthropic.com",
    "stackoverflow": "https://stackoverflow.com",
    "twitch": "https://twitch.tv",
    "spotify web": "https://open.spotify.com",
}


def _known_or_explicit_url(value: str) -> str | None:
    """Yalnızca bilinen bir site adı veya açıkça URL görünümlü hedefler için
    URL döndürür; belirsiz hedefleri (ör. "işe git") None bırakır ki istek
    semantik planlayıcıya düşsün."""
    cleaned = _clean_app_name(value)
    if not cleaned:
        return None
    normalized = _normalise(cleaned)
    if normalized in _KNOWN_SITES:
        return _KNOWN_SITES[normalized]
    if "." in cleaned and _looks_like_url(cleaned):
        return cleaned if "://" in cleaned else f"https://{cleaned}"
    return None


def _site_visit_route(text: str) -> RoutedTask | None:
    """"youtube'a gir", "google'a git", "şu siteye git: anthropic.com",
    "tarayıcıda openai sitesini aç" gibi gezinme komutları."""
    original = str(text or "").strip()
    patterns = [
        r"(?:[sş]u\s+)?(?:siteye|sayfaya|adrese)\s+(?:git|gir)[:\s]+(.+)$",
        r"(?:taray[ıi]c[ıi]da|browserda)\s+(.+?)\s*(?:sitesini|sayfas[ıi]n[ıi])?\s*(?:a[cç]|git|gir)$",
        r"(.+?)\s+(?:sitesini|sitesine|sayfas[ıi]n[ıi])\s*(?:a[cç]|git|gir)$",
        r"(.+?)(?:['’]\s?(?:a|e|ya|ye))?\s+(?:git|gir|gidelim|girelim)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if not match:
            continue
        target = match.group(1).strip()
        # Türkçe yönelme eki bitişik yazılmışsa ("youtube'a" zaten ayrıldı,
        # "googlea git" gibi) bilinen site + ek varyantını da dene.
        url = _known_or_explicit_url(target)
        if url is None:
            trimmed = re.sub(r"(?:['’]?\s?(?:a|e|ya|ye|na|ne))$", "", target, flags=re.IGNORECASE)
            if trimmed != target:
                url = _known_or_explicit_url(trimmed)
        if url:
            return RoutedTask(
                "browser_control",
                {"action": "open_url", "url": url},
                "open_url",
                intent="open_url",
                confidence=0.95,
            )
    return None


def _site_target_to_url(value: str) -> str | None:
    cleaned = _clean_app_name(value)
    if not cleaned:
        return None
    if _looks_like_url(cleaned):
        return cleaned if "://" in cleaned else f"https://{cleaned}"
    normalized = _normalise(cleaned)
    if normalized in _KNOWN_SITES:
        return _KNOWN_SITES[normalized]
    if normalized.endswith(" sitesi") or normalized.endswith(" sitesi ac"):
        normalized = normalized.replace(" sitesi", "").strip()
    # Uygulama-olmayan ifadeler ("yeni sekme") domain'e ÇEVRİLMEZ — eskiden
    # "yeni sekme" → "yenisekme.com" gibi uydurma URL üretiyordu.
    if _is_non_app_open_target(normalized):
        return None
    # Yalnız TEK kelimelik marka benzeri hedefleri uydurma .com'a çevir; çok
    # kelimeli Türkçe ifadeler domain değildir.
    if " " in normalized:
        return None
    slug = re.sub(r"[^a-z0-9]+", "", normalized)
    if slug and len(slug) >= 2:
        return f"https://{slug}.com"
    return None


def _calendar_add_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    if "takvime" not in q or not any(token in q for token in ("ekle", "olustur", "oluştur")):
        return None
    when = _schedule_reference_datetime(q)
    if when is None:
        return None
    title = _strip_schedule_tokens(_extract_after([r"takvime\s+(.+?)\s+(?:ekle|olustur|oluştur)$"], original) or original)
    if not title:
        title = "Yeni etkinlik"
    end = when + dt.timedelta(hours=1)
    steps = [
        {
            "capability": "add_calendar_event",
            "description": f"Takvime '{title}' etkinliği eklenecek.",
        }
    ]
    summary = f"Takvime {_day_time_label(when)} için '{title}' etkinliğini ekleyeceğim."
    return RoutedTask(
        "add_calendar_event",
        {
            "title": title,
            "start_iso": when.isoformat(),
            "end_iso": end.isoformat(),
        },
        "calendar_add",
        intent="calendar_add",
        confidence=0.88,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
    )


def _reminder_add_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    if not any(token in q for token in ("hatirlatici", "hatırlatıcı", "reminder")) or not any(
        token in q for token in ("ekle", "olustur", "oluştur", "kur")
    ):
        return None
    when = _schedule_reference_datetime(q)
    if when is None:
        return None
    title_match = re.search(r"(.+?)\s+diye\s+(?:hatirlatici|hatırlatıcı|reminder)", original, flags=re.IGNORECASE)
    title = _strip_schedule_tokens(title_match.group(1) if title_match else original)
    if not title:
        title = "Yeni hatırlatıcı"
    steps = [
        {
            "capability": "add_reminder",
            "description": f"'{title}' hatırlatıcısı oluşturulacak.",
        }
    ]
    summary = f"'{title}' için {_day_time_label(when)} zamanlı bir hatırlatıcı oluşturacağım."
    return RoutedTask(
        "add_reminder",
        {
            "title": title,
            "due_iso": when.isoformat(),
        },
        "reminder_add",
        intent="reminder_add",
        confidence=0.9,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
    )


def _workspace_reminders_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if "hafta" in q and any(token in q for token in ("yapilacak", "yapılacak", "todo", "reminder", "hatirlat")):
        return RoutedTask(
            "get_reminders",
            {"query": "upcoming", "limit": 12},
            "reminders_week",
            intent="reminders_read",
            confidence=0.84,
            privacy_class="local_private",
        )
    return None


def _document_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    source_path, source_text, selected_paths, _labels = _document_source_payload(text, selected_artifacts)
    if not source_path and not source_text and not any(
        token in q for token in ("dosya", "belge", "pdf", "docx", "markdown", "json", "csv", "txt")
    ):
        return None
    if not any(token in q for token in ("oku", "ozetle", "özetle", "cikar", "çıkar", "listele", "maddeler")):
        return None
    if not source_path and not source_text:
        return None
    args: dict[str, Any] = {"mode": _document_mode(text)}
    if source_path:
        args["path"] = source_path
    if source_text:
        args["text"] = source_text
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "document_read",
        args,
        "document_read",
        intent="document_read",
        confidence=0.82,
        privacy_class="local_private",
    )


def _document_summary_save_route(
    text: str,
    selected_artifacts: list[dict[str, Any]] | None = None,
) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in _DOCUMENT_SUMMARY_SAVE_TOKENS):
        return None
    if not any(token in q for token in _DOCUMENT_SAVE_TOKENS):
        return None

    source_path, source_text, selected_paths, labels = _document_source_payload(text, selected_artifacts)
    if not source_path and not source_text:
        return None

    source_label = labels[0] if labels else (Path(source_path).stem if source_path else "paylasilan-metin")
    summary_label = Path(source_label).stem.replace("_", " ").strip() or "paylaşılan metin"
    output_path = _resolve_output_path(text, ".docx", hint=f"{summary_label}-ozet")
    title = f"{summary_label} özeti"
    payload: dict[str, Any] = {
        "path": source_path,
        "text": source_text,
        "selectedPaths": selected_paths,
        "outputPath": output_path,
        "title": title,
        "overwrite": False,
    }
    skill_steps = [
        {
            "capability": "document_read",
            "description": "Kaynak içerik özetlenecek.",
            "args": {"mode": "summary"},
            "argsFromPayload": {
                "path": "path",
                "text": "text",
                "_selectedPaths": "selectedPaths",
            },
        },
        {
            "capability": "document_write",
            "description": "Özet DOCX dosyasına kaydedilecek.",
            "args": {"overwrite": False},
            "argsFromPayload": {
                "outputPath": "outputPath",
                "title": "title",
                "overwrite": "overwrite",
            },
            "argsFromPreviousResult": {"source_context": "summary"},
        },
    ]
    summary = f"{summary_label} özetlenecek ve {Path(output_path).name} olarak masaüstüne kaydedilecek."
    return RoutedTask(
        "run_skill",
        {"skillId": "document.summary_and_save", "payload": payload},
        "document_summary_save",
        intent="document_summary_save",
        confidence=0.95,
        requires_confirmation=True,
        is_multi_step=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, skill_steps, "local_private"),
        steps=(
            {
                "capability": "run_skill",
                "args": {"skillId": "document.summary_and_save", "payload": payload},
                "description": summary,
            },
        ),
    )


def _speech_transcription_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_audio = _selected_artifact_path(
        selected_artifacts,
        kinds={"audio"},
        suffixes=_AUDIO_SUFFIXES,
    )
    if not selected_audio and not any(
        token in q
        for token in (
            "transkript",
            "transcribe",
            "yaziya cevir",
            "yazıya çevir",
            "metne cevir",
            "metne çevir",
            "ses kaydi",
            "ses kaydı",
            "audio",
        )
    ):
        return None
    path, selected_paths = _resolve_audio_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {"audioPath": path, "languageHint": "tr"}
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "speech_to_text",
        args,
        "speech_to_text",
        intent="speech_to_text",
        confidence=0.84,
        privacy_class="local_private",
    )


def _text_to_speech_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("sesli oku", "yüksek sesle oku", "yuksek sesle oku", "read aloud")):
        return None
    payload = _spoken_text_payload(text)
    if not payload:
        return None
    return RoutedTask(
        "text_to_speech",
        {"text": payload, "languageHint": "tr", "interrupt": True},
        "text_to_speech",
        intent="text_to_speech",
        confidence=0.82,
        privacy_class="public_text",
    )


def _ocr_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_visual = _selected_artifact_path(
        selected_artifacts,
        kinds={"image", "document"},
        suffixes=_OCR_SUFFIXES,
    )
    if not selected_visual and not any(
        token in q for token in ("gorsel", "görsel", "ocr", "resim", "fotograf", "fotoğraf", "png", "jpg", "jpeg", "pdf")
    ):
        return None
    if not _has_ocr_intent(text, selected_visual=bool(selected_visual)):
        return None
    path, selected_paths = _resolve_ocr_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {"path": path, "mode": _ocr_mode(text)}
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "ocr_read",
        args,
        "ocr_read",
        intent="ocr_read",
        confidence=0.8,
        privacy_class="local_private",
    )


def _image_read_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_image = _selected_artifact_path(
        selected_artifacts,
        kinds={"image"},
        suffixes=_IMAGE_SUFFIXES,
    )
    if not selected_image and not any(
        token in q
        for token in ("gorsel", "görsel", "resim", "fotograf", "fotoğraf", "image", "png", "jpg", "jpeg", "gif", "webp")
    ):
        return None
    if not any(
        token in q
        for token in ("incele", "ozetle", "özetle", "metadata", "meta", "boyut", "cozunurluk", "çözünürlük", "palette", "palet", "renk")
    ):
        return None
    path, selected_paths = _resolve_image_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {"path": path, "mode": _image_read_mode(text)}
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "image_read",
        args,
        "image_read",
        intent="image_read",
        confidence=0.81,
        privacy_class="local_private",
    )


def _data_analyze_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_data = _selected_artifact_path(
        selected_artifacts,
        kinds={"document"},
        suffixes=_DATA_SUFFIXES,
    )
    if not selected_data and not any(token in q for token in ("csv", "json", "xlsx", "xls", "excel", "sheet", "tablo", "veri", "dataset")):
        return None
    if not any(token in q for token in ("analiz", "incele", "profil", "istatistik", "preview", "onizleme", "önizleme")):
        return None
    path, selected_paths = _resolve_data_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {"path": path, "mode": _data_mode(text)}
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "data_analyze",
        args,
        "data_analyze",
        intent="data_analyze",
        confidence=0.84,
        privacy_class="local_private",
    )


def _chart_generate_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    q = _normalise(text)
    selected_data = _selected_artifact_path(
        selected_artifacts,
        kinds={"document"},
        suffixes=_DATA_SUFFIXES,
    )
    if not selected_data and not any(token in q for token in ("csv", "json", "xlsx", "xls", "excel", "sheet", "tablo", "veri", "dataset")):
        return None
    if not any(token in q for token in ("grafik", "chart", "histogram", "scatter", "bar", "line")):
        return None
    if not any(token in q for token in ("cikar", "çıkar", "uret", "üret", "olustur", "oluştur", "hazirla", "hazırla", "yap")):
        return None
    path, selected_paths = _resolve_data_target(text, selected_artifacts)
    if not path:
        return None
    args: dict[str, Any] = {
        "path": path,
        "chartType": _chart_type(text),
        "title": Path(path).stem,
    }
    if selected_paths:
        args["_selectedPaths"] = selected_paths
    return RoutedTask(
        "chart_generate",
        args,
        "chart_generate",
        intent="chart_generate",
        confidence=0.82,
        privacy_class="local_private",
    )


def _math_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("=", "^", "+", "-", "*", "/", "x", "denklem", "ifade")):
        return None
    if not any(
        token in q
        for token in ("coz", "çöz", "solve", "sadelestir", "sadeleştir", "carpanlara ayir", "çarpanlara ayır", "factor", "genislet", "genişlet", "expand", "hesapla", "evaluate")
    ):
        return None
    expression = _extract_math_expression(text)
    if not expression:
        return None
    args: dict[str, Any] = {"expression": expression, "mode": _math_mode(text)}
    if _is_probably_latex_expression(expression):
        args["_latexInput"] = _extract_latex_expression(text)
    return RoutedTask(
        "math_solve",
        args,
        "math_solve",
        intent="math_solve",
        confidence=0.86,
        privacy_class="public_text",
    )


def _latex_parse_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("latex", "parse", "normalize", "normallestir", "normalleştir")):
        return None
    expression = _extract_latex_expression(text)
    if not expression or not _is_probably_latex_expression(expression):
        return None
    return RoutedTask(
        "latex_parse",
        {"expression": expression, "mode": _latex_parse_mode(text)},
        "latex_parse",
        intent="latex_parse",
        confidence=0.84,
        privacy_class="public_text",
    )


def _document_write_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("docx", "word", "belge", "dokuman", "rapor")):
        return None
    if not any(token in q for token in ("yap", "cevir", "çevir", "olustur", "oluştur", "hazirla", "hazırla", "belgele", "dokumante", "donustur", "dönüştür")):
        return None
    # Excel/sunum raporları kendi rotalarına gitmeli; buraya sızmasın.
    if any(token in q for token in ("xlsx", "excel", "tablo", "cizelge", "sheet", "sunum", "pptx", "powerpoint", "slayt", "canvas", "kanvas")):
        return None
    output_path = _resolve_output_path(text, ".docx", hint=text or "elyan-document")
    steps = [
        {
            "capability": "document_write",
            "args": {"prompt": text, "outputPath": output_path, "overwrite": False},
            "description": f"{Path(output_path).name} DOCX dosyası oluşturulacak.",
        }
    ]
    return RoutedTask(
        "document_write",
        {"prompt": text, "outputPath": output_path, "overwrite": False},
        "document_write",
        intent="document_write",
        confidence=0.84,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(
            f"{Path(output_path).name} DOCX dosyasını oluşturacağım.",
            steps,
            "local_private",
        ),
        steps=tuple(steps),
    )


def _canvas_write_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("canvas", "kanvas", "tuval", "whiteboard", "layout", "board")):
        return None
    if not any(token in q for token in ("yap", "cevir", "çevir", "olustur", "oluştur", "hazirla", "hazırla", "tasarla", "design")):
        return None
    output_path = _resolve_output_path(text, ".pdf", hint=text or "elyan-canvas")
    steps = [
        {
            "capability": "canvas_write",
            "args": {"prompt": text, "outputPath": output_path, "outputFormat": "pdf", "overwrite": False},
            "description": f"{Path(output_path).name} canvas çıktısı oluşturulacak.",
        }
    ]
    return RoutedTask(
        "canvas_write",
        {"prompt": text, "outputPath": output_path, "outputFormat": "pdf", "overwrite": False},
        "canvas_write",
        intent="canvas_write",
        confidence=0.84,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(
            f"{Path(output_path).name} canvas çıktısını oluşturacağım.",
            steps,
            "local_private",
        ),
        steps=tuple(steps),
    )


def _pdf_report_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if "pdf" not in q:
        return None
    if not any(token in q for token in ("rapor", "arastirma", "araştırma", "belge", "dokuman", "doküman")):
        return None
    if not any(token in q for token in ("hazirla", "hazırla", "olustur", "oluştur", "yap", "uret", "üret", "yaz")):
        return None

    topic, specific = _research_request_profile(text)
    topic_match = re.search(r"(.{1,160}?)\s+hakk[ıi]nda", text, flags=re.IGNORECASE)
    if topic_match:
        topic = topic_match.group(1)
        topic = re.sub(
            r"^(?:masaüstümde|masaustumde|masaüstünde|masaustunde|masaüstüne|masaustune|desktop(?:ta|a)?|bilgisayarımda|bilgisayarimda)\s+",
            "",
            topic,
            flags=re.IGNORECASE,
        )
        specific = True
    if not specific:
        topic = _strip_leading_fillers(text)
    topic = topic.strip(" .,!?:;") or "araştırma konusu"
    page_count = _extract_page_count(text) or 4
    output_path = _resolve_output_path(text, ".pdf", hint=f"{topic}-rapor")
    output_path = _relocate_to_requested_folder(text, output_path)
    prompt = (
        f"{topic} hakkında kaynakçalı, düzenli, yaklaşık {page_count} sayfalık araştırma raporu hazırla. "
        "Başlık, kısa giriş, ana bölümler, sonuç ve kaynakça olsun."
    )
    steps = [
        {
            "capability": "web_research",
            "args": {"query": topic, "max_results": 6},
            "description": f"{topic} hakkında web araştırması yapılacak.",
        },
        {
            "capability": "canvas_write",
            "args": {
                "prompt": prompt,
                "title": f"{topic} Araştırma Raporu",
                "outputPath": output_path,
                "outputFormat": "pdf",
                "width": 595,
                "height": 842,
                "overwrite": False,
            },
            "description": f"{Path(output_path).name} PDF raporu oluşturulacak.",
            "dependsOn": ["step_1"],
        },
    ]
    steps[0]["id"] = "step_1"
    steps[1]["id"] = "step_2"
    summary = f"{topic} araştırılacak ve {Path(output_path).name} olarak tek PDF raporu oluşturulacak."
    return RoutedTask(
        "canvas_write",
        {
            "prompt": prompt,
            "title": f"{topic} Araştırma Raporu",
            "outputPath": output_path,
            "outputFormat": "pdf",
            "width": 595,
            "height": 842,
            "overwrite": False,
        },
        "pdf_report",
        intent="pdf_report",
        confidence=0.93,
        requires_confirmation=True,
        is_multi_step=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _relocate_to_requested_folder(text: str, output_path: str) -> str:
    candidate = Path(output_path)
    default_parents = {_workspace_root(), _workspace_root() / "elyan_output"}
    if _mentions_location(text) and candidate.parent in default_parents:
        return str((Path(_resolve_location_path(text)) / candidate.name).resolve())
    return output_path


def _sample_budget_table(normalized_text: str) -> tuple[list[str], list[dict[str, Any]]] | None:
    """Return typed demo data only when the user explicitly asks for a sample."""
    q = str(normalized_text or "")
    if not any(token in q for token in ("ornek", "örnek", "sample", "demo", "senaryo")):
        return None
    if not any(token in q for token in ("butce", "bütçe", "budget")):
        return None

    months = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran"]
    categories = [
        ("Gelir", "gelir", [52000, 52500, 53000, 54000, 54500, 55000]),
        ("Kira", "gider", [14500, 14500, 15000, 15000, 15000, 15500]),
        ("Market", "gider", [8200, 8600, 9000, 9400, 9700, 10100]),
        ("Ulaşım", "gider", [2100, 2250, 2350, 2400, 2500, 2600]),
        ("Fatura", "gider", [3800, 3600, 3400, 3200, 3000, 3100]),
        ("Eğitim", "gider", [2500, 2500, 2800, 2800, 3000, 3000]),
        ("Birikim", "birikim", [9000, 9200, 9400, 9800, 10000, 10200]),
    ]
    rows = [
        {"Ay": month, "Kategori": category, "Tür": kind, "Tutar": values[month_index]}
        for month_index, month in enumerate(months)
        for category, kind, values in categories
    ]
    return ["Ay", "Kategori", "Tür", "Tutar"], rows


def _data_artifact_pipeline_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    wants_sheet = any(token in q for token in ("xlsx", "excel", "tablo", "sheet"))
    wants_chart = any(token in q for token in ("grafik", "chart", "png", "gorsel", "görsel"))
    wants_pdf = "pdf" in q and any(token in q for token in ("rapor", "ozet", "özet", "analiz"))
    if not (wants_sheet and wants_chart and wants_pdf):
        return None
    if not any(token in q for token in ("hazirla", "hazırla", "olustur", "oluştur", "uret", "üret", "kaydet", "yap")):
        return None
    sample_table = _sample_budget_table(q)
    if sample_table is None:
        return None

    sheet_path = _relocate_to_requested_folder(
        text,
        _resolve_output_path(text, ".xlsx", hint="veri-analizi"),
    )
    chart_path = _relocate_to_requested_folder(
        text,
        _resolve_output_path(text, ".png", hint=f"{Path(sheet_path).stem}-grafik"),
    )
    report_path = _relocate_to_requested_folder(
        text,
        _resolve_output_path(text, ".pdf", hint=f"{Path(sheet_path).stem}-rapor"),
    )
    title = Path(report_path).stem.replace("_", " ").replace("-", " ").strip().title() or "Veri Analizi Raporu"
    steps = [
        {
            "id": "step_1",
            "capability": "spreadsheet_write",
            "args": {
                "prompt": text,
                "title": Path(sheet_path).stem[:31] or "Veri Analizi",
                "columns": sample_table[0],
                "rows": sample_table[1],
                "outputPath": sheet_path,
                "overwrite": False,
            },
            "description": f"{Path(sheet_path).name} veri tablosu oluşturulacak.",
        },
        {
            "id": "step_2",
            "capability": "chart_generate",
            "args": {
                "path": sheet_path,
                "chartType": "bar",
                "xColumn": "Kategori",
                "yColumn": "Tutar",
                "title": title,
                "outputPath": chart_path,
                "_selectedPaths": [sheet_path],
            },
            "description": f"{Path(sheet_path).name} verisinden {Path(chart_path).name} grafiği üretilecek.",
            "dependsOn": ["step_1"],
        },
        {
            "id": "step_3",
            "capability": "canvas_write",
            "args": {
                "prompt": text,
                "title": title,
                "sourcePath": chart_path,
                "sourceContext": f"{Path(sheet_path).name} ve {Path(chart_path).name} çıktılarından kısa analiz raporu üret.",
                "outputPath": report_path,
                "outputFormat": "pdf",
                "width": 595,
                "height": 842,
                "overwrite": False,
                "_selectedPaths": [chart_path],
            },
            "description": f"Bulgular {Path(report_path).name} PDF raporunda özetlenecek.",
            "dependsOn": ["step_2"],
        },
    ]
    summary = (
        f"{Path(sheet_path).name} oluşturulacak, {Path(chart_path).name} grafiği üretilecek "
        f"ve {Path(report_path).name} PDF raporu hazırlanacak."
    )
    return RoutedTask(
        "spreadsheet_write",
        dict(steps[0]["args"]),
        "data_artifact_pipeline",
        intent="data_artifact_pipeline",
        confidence=0.94,
        requires_confirmation=True,
        is_multi_step=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _research_spreadsheet_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    wants_sheet = any(token in q for token in ("xlsx", "excel", "tablo", "cizelge", "çizelge", "sheet"))
    explicit_public_research = any(
        token in q for token in ("arastir", "araştır", "internetten", "webden", "kaynakli", "kaynaklı")
    )
    public_report = (
        "raporla" in q
        and re.search(r"\b(?:19|20)\d{2}\b", q) is not None
        and any(token in q for token in ("turkiye", "türkiye", "dunya", "dünya", "global", "ulusal", "uluslararasi", "uluslararası"))
    )
    private_data_signal = any(
        token in q
        for token in (
            "dosyam", "tablom", "excelim", "verilerim", "butcem", "bütçem",
            "gelirim", "giderim", "satislarim", "satışlarım", "musterilerim", "müşterilerim",
        )
    )
    needs_public_data = (explicit_public_research or public_report) and not private_data_signal
    if not (wants_sheet and needs_public_data):
        return None

    query = re.sub(
        r"^(?:masaust(?:umde|une|unde|u)?|masaüst(?:ümde|üne|ünde|ü)?|desktop(?:umda|a)?)\s+",
        "",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s+(?:hakkinda\s+|hakkında\s+)?(?:arastir|araştır|raporla|internetten|webden).*$",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip(" .,!?:;")
    query = query or str(text or "").strip()
    output_path = _relocate_to_requested_folder(
        text,
        _resolve_output_path(text, ".xlsx", hint=query or "arastirma-verileri"),
    )
    steps = [
        {
            "id": "step_1",
            "capability": "web_research",
            "args": {"query": query, "max_results": 6, "languageHint": "tr"},
            "description": f"{query} için güncel ve kaynaklı veriler araştırılacak.",
        },
        {
            "id": "step_2",
            "capability": "spreadsheet_write",
            "args": {
                "prompt": text,
                "title": query[:31] or "Araştırma Verileri",
                "columns": ["Başlık", "URL", "Özet"],
                "rows": "{{steps.step_1.result.sources}}",
                "outputPath": output_path,
                "overwrite": False,
            },
            "description": f"Araştırma kaynakları {Path(output_path).name} dosyasına yapılandırılmış satırlar olarak yazılacak.",
            "dependsOn": ["step_1"],
        },
    ]
    summary = f"{query} araştırılacak ve kaynaklı veriler {Path(output_path).name} Excel dosyasına yazılacak."
    return RoutedTask(
        "web_research",
        dict(steps[0]["args"]),
        "research_spreadsheet",
        intent="research_spreadsheet",
        confidence=0.94,
        requires_confirmation=True,
        is_multi_step=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _spreadsheet_write_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("xlsx", "excel", "tablo", "cizelge", "çizelge", "sheet")):
        return None
    if not any(token in q for token in ("yap", "cevir", "çevir", "olustur", "oluştur", "hazirla", "hazırla")):
        return None
    output_path = _resolve_output_path(text, ".xlsx", hint=text or "elyan-sheet")
    steps = [
        {
            "capability": "spreadsheet_write",
            "args": {"prompt": text, "outputPath": output_path, "overwrite": False},
            "description": f"{Path(output_path).name} XLSX çalışma sayfası oluşturulacak.",
        }
    ]
    return RoutedTask(
        "spreadsheet_write",
        {"prompt": text, "outputPath": output_path, "overwrite": False},
        "spreadsheet_write",
        intent="spreadsheet_write",
        confidence=0.83,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(
            f"{Path(output_path).name} XLSX çalışma sayfasını oluşturacağım.",
            steps,
            "local_private",
        ),
        steps=tuple(steps),
    )


def _presentation_write_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("pptx", "powerpoint", "sunum", "slide")):
        return None
    if not any(token in q for token in ("yap", "cevir", "çevir", "olustur", "oluştur", "hazirla", "hazırla")):
        return None
    output_path = _resolve_output_path(text, ".pptx", hint=text or "elyan-presentation")
    steps = [
        {
            "capability": "presentation_write",
            "args": {"prompt": text, "outputPath": output_path, "overwrite": False},
            "description": f"{Path(output_path).name} PPTX sunumu oluşturulacak.",
        }
    ]
    return RoutedTask(
        "presentation_write",
        {"prompt": text, "outputPath": output_path, "overwrite": False},
        "presentation_write",
        intent="presentation_write",
        confidence=0.83,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(
            f"{Path(output_path).name} PPTX sunumunu oluşturacağım.",
            steps,
            "local_private",
        ),
        steps=tuple(steps),
    )


def _selected_document_transform_route(
    text: str,
    selected_artifacts: list[dict[str, Any]] | None,
) -> RoutedTask | None:
    q = _normalise(text)
    if not any(token in q for token in ("cevir", "çevir", "donustur", "dönüştür", "olustur", "oluştur", "hazirla", "hazırla")):
        return None
    source_path, selected_paths = _resolve_document_target(text, selected_artifacts)
    if not source_path:
        return None

    source = Path(source_path)
    target_capability = ""
    extension = ""
    label = ""
    read_mode = "read"
    if any(token in q for token in ("pptx", "powerpoint", "sunum", "slayt", "slide")):
        target_capability, extension, label = "presentation_write", ".pptx", "PPTX sunumu"
    elif any(token in q for token in ("docx", "word", "belge", "dokuman", "doküman")):
        target_capability, extension, label = "document_write", ".docx", "DOCX belgesi"
        if any(token in q for token in ("ozet", "özet", "summary")):
            read_mode = "summary"
    else:
        return None

    explicit_output = _explicit_path_for_suffixes(text, {extension})
    output_path = explicit_output or _default_output_path(extension, f"{source.stem}-{target_capability}")
    title = source.stem.replace("-", " ").replace("_", " ").strip().title()
    reader_args: dict[str, Any] = {"path": source_path, "mode": read_mode}
    if selected_paths:
        reader_args["_selectedPaths"] = selected_paths
    writer_args = {
        "prompt": text,
        "title": title,
        "outputPath": output_path,
        "overwrite": False,
    }
    steps = [
        {
            "id": "step_1",
            "capability": "document_read",
            "args": reader_args,
            "description": f"{source.name} içeriği güvenli biçimde okunacak.",
        },
        {
            "id": "step_2",
            "capability": target_capability,
            "args": writer_args,
            "description": f"Okunan içerikten {Path(output_path).name} {label} oluşturulacak.",
            "dependsOn": ["step_1"],
        },
    ]
    summary = f"{source.name} okunacak ve {Path(output_path).name} olarak dönüştürülecek."
    return RoutedTask(
        target_capability,
        writer_args,
        "selected_document_transform",
        intent="document_transform",
        confidence=0.91,
        requires_confirmation=True,
        is_multi_step=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _multi_step_browser_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    if " ve " not in q or not any(token in q for token in (" ac", " aç", " open", " launch")):
        return None
    match = re.search(r"(.+?)\s+ve\s+(.+)$", original, flags=re.IGNORECASE)
    if not match:
        return None
    first, second = match.group(1).strip(), match.group(2).strip()
    if not any(token in _normalise(first) for token in ("ac", "aç", "open", "launch")):
        return None
    first_target = _clean_app_name(_extract_after([r"(.+?)\s+(?:ac|aç|open|launch)$"], first))
    second_target = _clean_app_name(_extract_after([r"(.+?)\s+(?:sitesini\s+)?(?:ac|aç|open|launch)$"], second))
    if not first_target or not second_target:
        return None
    url = _site_target_to_url(second_target)
    if not url:
        return None
    steps = [
        {"capability": "open_app", "args": {"app_name": first_target}, "description": f"{first_target} açılacak."},
        {"capability": "browser_control", "args": {"action": "open_url", "url": url}, "description": f"{url} açılacak."},
    ]
    summary = f"Önce {first_target} açılacak, ardından {url} adresi yüklenecek."
    return RoutedTask(
        "open_app",
        {"app_name": first_target},
        "multi_step_browser_open",
        intent="multi_step_browser_open",
        confidence=0.86,
        requires_confirmation=True,
        is_multi_step=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _extract_email_addresses(text: str) -> list[str]:
    addresses = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", str(text or ""), flags=re.IGNORECASE)
    ordered: list[str] = []
    for address in addresses:
        candidate = address.strip()
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


_RESEARCH_VERB_NORMS = {
    "aratir", "arat", "arastir", "arastirma", "arastirin", "aratirin",
    "ogren", "ogrenin", "derle", "derleyin", "analiz", "incele", "inceleyin",
    "sorustur", "research", "arastirmak", "arastiralim",
}


def _strip_research_verbs(topic: str) -> str:
    """Konu öbeğinin baş/sonundaki araştırma fiillerini atar:
    'yapay zeka öğren' → 'yapay zeka', 'dif geo ... aratır' → 'dif geo ...'."""
    tokens = str(topic or "").split()
    while tokens and _normalise(tokens[-1]) in _RESEARCH_VERB_NORMS:
        tokens.pop()
    while tokens and _normalise(tokens[0]) in _RESEARCH_VERB_NORMS:
        tokens.pop(0)
    return " ".join(tokens).strip() or str(topic or "").strip()


def _extract_page_count(text: str) -> int:
    """'4 sayfalık', '6 sayfa', '3 page' → 4/6/3. Yoksa 0."""
    match = re.search(r"(\d+)\s*(?:sayfa\w*|page[s]?)", _normalise(text))
    if match:
        try:
            value = int(match.group(1))
            return value if 1 <= value <= 100 else 0
        except ValueError:
            return 0
    return 0


def _research_topic(text: str) -> str:
    original = str(text or "").strip()
    patterns = [
        r"(.+?)\s+(?:hakk[ıi]nda|about|ile ilgili)\s+(?:detayl[ıi]\s+)?(?:araştırma yap|arastirma yap|araştır|araştir|research|incele|bilgi topla|bilgi edin)$",
        r"(?:araştırma yap|arastirma yap|araştır|araştir|research|incele)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if match:
            candidate = _strip_research_verbs(_strip_leading_fillers(match.group(1)))
            if candidate:
                return candidate
    return _strip_research_verbs(_strip_leading_fillers(original))


_RESEARCH_STRONG_TRIGGERS = {"araştır", "arastir", "araştırma", "research", "incele", "bilgi topla", "bilgi edin"}
_RESEARCH_WEAK_TRIGGERS = {"kaynak", "source", "verify"}
# Stem tabanlı araştırma fiili yakalayıcı (normalize edilmiş metinde: ş→s, ı→i).
# YALNIZ araştır/aratır ailesi — "aras?tir" hem araştır→arastir hem aratır→aratir'i
# yakalar. (öğren/derle/analiz gibi fiiller web-arama/veri-analizi ile çakıştığı
# için bilinçli DIŞARIDA; onlar zaten _RESEARCH_STRONG_TRIGGERS'ta gerekiyorsa var.)
_RESEARCH_STEM_RE = re.compile(r"aras?tir")
_RESEARCH_STOPWORDS = {
    "araştır",
    "arastir",
    "arastirma",
    "aratir",
    "arat",
    "ogren",
    "derle",
    "analiz",
    "sorustur",
    "araştırma",
    "research",
    "incele",
    "kaynak",
    "source",
    "verify",
    "ver",
    "bilgi",
    "topla",
    "edin",
    "detayli",
    "detaylı",
    "hakkinda",
    "hakkında",
    "goster",
    "göster",
    "bak",
    "yap",
    "et",
    "please",
    "lutfen",
    "lütfen",
}


def _research_topic_terms(text: str) -> list[str]:
    return [
        word
        for word in _normalise(text).split()
        if word and word not in _RESEARCH_STOPWORDS
    ]


def _research_request_profile(text: str) -> tuple[str, bool]:
    original = str(text or "").strip()
    q = _normalise(original)
    has_strong = bool(_RESEARCH_STEM_RE.search(q)) or any(token in q for token in _RESEARCH_STRONG_TRIGGERS)
    if not (has_strong or any(token in q for token in _RESEARCH_WEAK_TRIGGERS)):
        return "", False
    topic = _research_topic(original)
    topic_terms = _research_topic_terms(topic)
    if not topic_terms:
        return topic, False
    if has_strong or any(token in q for token in ("hakkinda", "about")):
        return topic, True
    return topic, len(topic_terms) >= 2


def _email_subject(topic: str, fallback: str) -> str:
    cleaned = _strip_leading_fillers(topic) or _strip_leading_fillers(fallback)
    if cleaned:
        return f"{cleaned[:80]} hakkında notlar"
    return "Hazırlanan e-posta"


def _build_web_research_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    topic, specific = _research_request_profile(original)
    if not specific:
        return None
    q = _normalise(original)
    if _extract_email_addresses(original) and any(token in q for token in ("mail", "email", "e-posta", "gönder", "gonder", "send")):
        return None

    steps = [
        {
            "capability": "web_research",
            "args": {"query": topic},
            "description": f"{topic} hakkında web araştırması yapılacak.",
        }
    ]
    summary = f"'{topic}' hakkında güvenli web araştırması yapılacak."
    return RoutedTask(
        "web_research",
        {"query": topic},
        "web_research",
        intent="web_research",
        confidence=0.94,
        privacy_class="public_text",
        plan_preview=_build_plan_summary(summary, steps, "public_text"),
        steps=tuple(steps),
    )


def _build_email_draft_plan(
    *,
    recipients: list[str],
    topic: str,
    original: str,
    research_topic: str = "",
    research_query: str = "",
    include_send: bool = False,
) -> RoutedTask | None:
    if not recipients:
        return None
    subject = _email_subject(research_topic or topic, original)
    draft_args = {
        "to": recipients,
        "subject": subject,
        "topic": research_topic or topic or original,
        "prompt": original,
    }
    draft_step = {
        "capability": "email_draft",
        "args": draft_args,
        "description": f"{', '.join(recipients)} için e-posta taslağı hazırlanacak.",
    }
    steps: list[dict[str, Any]] = []
    summary_parts: list[str] = []
    if research_query:
        steps.append(
            {
                "capability": "web_research",
                "args": {"query": research_query},
                "description": f"{research_query} hakkında web araştırması yapılacak.",
            }
        )
        summary_parts.append(f"Önce {research_query} hakkında araştırma yapılacak")
    steps.append(draft_step)
    summary_parts.append(f"sonra {', '.join(recipients)} adresine taslak hazırlanacak")
    if include_send:
        steps.append(
            {
                "capability": "email_send",
                "args": {
                    "to": recipients,
                    "subject": subject,
                },
                "description": f"{', '.join(recipients)} adresine e-posta gönderilecek.",
            }
        )
        summary_parts.append("ve onaydan sonra e-posta gönderilecek")

    summary = "; ".join(summary_parts).strip().capitalize()
    return RoutedTask(
        "email_send" if include_send else "email_draft",
        draft_args,
        "email_draft",
        intent="email_send" if include_send else "email_draft",
        confidence=0.93 if include_send else 0.89,
        requires_confirmation=include_send,
        is_multi_step=include_send or bool(research_query),
        privacy_class="side_effect" if include_send else "public_text",
        plan_preview=_build_plan_summary(summary or "E-posta taslağı hazırlanacak.", steps, "side_effect" if include_send else "public_text"),
        steps=tuple(steps),
    )


def _email_send_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    recipients = _extract_email_addresses(original)
    if not recipients and not any(token in q for token in ("mail", "email", "e-posta")):
        return None
    if not any(token in q for token in ("gönder", "gonder", "yolla", "at", "send", "mail", "email")):
        return None
    research_query, specific_research = _research_request_profile(original)
    research_query = research_query if specific_research else ""
    topic = research_query or _strip_leading_fillers(original)
    if not recipients:
        return None
    return _build_email_draft_plan(
        recipients=recipients,
        topic=topic,
        original=original,
        research_topic=topic,
        research_query=research_query,
        include_send=True,
    )


def _email_draft_route(text: str) -> RoutedTask | None:
    original = str(text or "").strip()
    q = _normalise(original)
    if not any(token in q for token in ("taslak", "draft", "yaz", "hazırla", "hazirla", "compose")):
        return None
    recipients = _extract_email_addresses(original)
    if not recipients:
        return None
    topic = _research_topic(original)
    return _build_email_draft_plan(
        recipients=recipients,
        topic=topic,
        original=original,
        research_topic=topic,
        include_send=False,
    )


def artifact_target_clarification(
    text: str,
    selected_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, str] | None:
    q = _normalise(text)
    data_requested = any(token in q for token in ("csv", "json", "tablo", "veri", "dataset")) and any(
        token in q for token in ("analiz", "incele", "profil", "istatistik", "preview", "onizleme", "önizleme")
    )
    chart_requested = any(token in q for token in ("csv", "json", "tablo", "veri", "dataset")) and any(
        token in q for token in ("grafik", "chart", "histogram", "scatter", "bar", "line")
    )
    document_requested = any(token in q for token in ("dosya", "belge", "pdf", "docx", "markdown", "json", "csv", "txt")) and any(
        token in q for token in ("oku", "ozetle", "özetle", "cikar", "çıkar", "listele", "maddeler")
    )
    ocr_requested = any(
        token in q for token in ("gorsel", "görsel", "ocr", "resim", "fotograf", "fotoğraf", "png", "jpg", "jpeg", "pdf")
    ) and _has_ocr_intent(text)
    audio_requested = any(
        token in q
        for token in (
            "transkript",
            "transcribe",
            "yaziya cevir",
            "yazıya çevir",
            "metne cevir",
            "metne çevir",
            "ses kaydi",
            "ses kaydı",
            "audio",
        )
    )
    image_requested = any(
        token in q for token in ("gorsel", "görsel", "resim", "fotograf", "fotoğraf", "image", "png", "jpg", "jpeg", "gif", "webp")
    ) and any(
        token in q
        for token in ("incele", "ozetle", "özetle", "metadata", "meta", "boyut", "cozunurluk", "çözünürlük", "palette", "palet", "renk")
    )

    if data_requested:
        path, _ = _resolve_data_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "data",
                "question": "Bu tablo için önce bir CSV/JSON dosyası seç veya çalışma alanındaki açık yolu yaz.",
            }
    if chart_requested:
        path, _ = _resolve_data_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "chart",
                "question": "Bu grafik için önce bir CSV/JSON dosyası seç veya çalışma alanındaki açık yolu yaz.",
            }
    if document_requested:
        path, _ = _resolve_document_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "document",
                "question": "Bu dosya için önce bir belge seç veya çalışma alanındaki açık yolu yaz.",
            }
    if ocr_requested:
        path, _ = _resolve_ocr_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "ocr",
                "question": "Bu görsel için önce bir dosya seç veya çalışma alanındaki açık yolu yaz.",
            }
    if image_requested:
        path, _ = _resolve_image_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "image",
                "question": "Bu görsel için önce bir dosya seç veya çalışma alanındaki açık yolu yaz.",
            }
    if any(token in q for token in _DOCUMENT_SUMMARY_SAVE_TOKENS) and any(token in q for token in _DOCUMENT_SAVE_TOKENS):
        path, _ = _resolve_document_target(text, selected_artifacts)
        embedded_text, _labels = _embedded_attachment_payload(text)
        if not path and not embedded_text:
            return {
                "kind": "document",
                "question": "Özetlenecek belgeyi seç veya belge içeriğini paylaş.",
            }
    if audio_requested:
        path, _ = _resolve_audio_target(text, selected_artifacts)
        if not path:
            return {
                "kind": "audio",
                "question": "Bu ses kaydı için önce bir dosya seç veya çalışma alanındaki açık yolu yaz.",
            }
    return None


# ── File system helpers ───────────────────────────────────────────────────────

_COMMON_LOCATIONS: dict[str, str] = {
    # Turkish → English path segment
    "masaustu": "Desktop",
    "masaüstü": "Desktop",
    "indirilenler": "Downloads",
    "downloads": "Downloads",
    "belgeler": "Documents",
    "documents": "Documents",
    "resimler": "Pictures",
    "pictures": "Pictures",
    "muzik": "Music",
    "müzik": "Music",
    "music": "Music",
    "videolar": "Movies",
    "filmler": "Movies",
    "movies": "Movies",
    "ev": "",
    "home": "",
}

_LOCATION_TRIGGER_PATTERNS = {
    "masaustume", "masaüstüme", "masaustumde", "masaüstümde",
    "masaustune", "masaüstüne", "masaustunde", "masaüstünde", "masaustundeki",
    "masaüstündeki", "masaustundan", "masaüstünden", "masaustu", "masaüstü",
    "indirilenlere", "indirilenler", "indirilenlerden", "indirilenlerdeki",
    "belgelere", "belgeler", "belgelerden", "belgelerdeki",
    "desktop", "downloads", "documents",
}


def _resolve_location_path(text: str) -> str:
    """Return ~/LocationName for recognised Turkish/English location names."""
    q = _normalise(text)
    home = Path.home()
    for key, folder in _COMMON_LOCATIONS.items():
        if key in q:
            if folder:
                return str(home / folder)
            return str(home)
    return str(home / "Desktop")  # safe default when context implies a location


def _mentions_location(text: str) -> bool:
    q = _normalise(text)
    return any(tok in q for tok in _LOCATION_TRIGGER_PATTERNS)


def _extract_quoted_name(text: str) -> str:
    match = re.search(r'["\'«»„"](.+?)["\'»"]', text)
    if match:
        return match.group(1).strip()
    return ""


# Tokens that are never valid folder names on their own
_FOLDER_NAME_STOPWORDS = {
    "klasor", "klasör", "folder", "dizin", "yeni", "olustur", "oluştur",
    "yap", "masaustune", "masaüstüne", "masaustunde", "masaüstünde",
    "indirilenlere", "belgelere", "desktop", "downloads", "documents",
    "lutfen", "lütfen", "please",
}


def _extract_folder_name(text: str) -> str:
    """Extract folder name from phrases like 'X adlı klasör', 'X klasörü', 'X adında klasör'."""
    original = str(text or "").strip()
    quoted = _extract_quoted_name(original)
    if quoted:
        return quoted
    patterns = [
        r'"(.+?)"',
        r"(\w[\w\s\-\.]*?)\s+adl[ıi]\s+klasör",
        r"(\w[\w\s\-\.]*?)\s+ad[ıi]nda\s+klasör",
        r"(\w[\w\s\-\.]*?)\s+isimli\s+klasör",
        r"(?:yeni\s+)?klasör(?:ü)?\s+oluştur(?:un?)?\s+(.+)$",
        r"(?:yeni\s+)?klasör\s+yap\s+(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, original, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1).strip(" .,!?:;\"'")
            # Strip leading location words
            candidate = re.sub(
                r"^(?:masaüstüne|masaustune|indirilenlere|belgelere|desktop|downloads?|documents?)\s+",
                "", candidate, flags=re.IGNORECASE,
            ).strip()
            if candidate and _normalise(candidate) not in _FOLDER_NAME_STOPWORDS:
                return candidate
    return ""


def _extract_file_name(text: str) -> str:
    quoted = _extract_quoted_name(text)
    if quoted:
        return quoted
    # Look for common file patterns
    m = re.search(r"([A-Za-z0-9_\-ığüşöçİĞÜŞÖÇ]+(?:\.[a-zA-Z0-9]{1,6})+)", text)
    return m.group(1).strip() if m else ""


def _extract_rename_target(text: str) -> tuple[str, str]:
    """Returns (old_name, new_name) from rename phrases."""
    original = str(text or "").strip()
    # Normalise various quote styles to ASCII double-quote for simpler matching
    normalised_quotes = re.sub(r'[""«»„]', '"', original)
    patterns = [
        r'"(.+?)"\s+ad[ıi]n[ıi]\s+"(.+?)"\s+(?:yap|degistir|değiştir|olarak degistir)',
        r'"(.+?)"\s+(?:dosyas[ıi]n[ıi]|klasör[ü]n[ü])\s+"(.+?)"\s+(?:olarak yeniden adlandir|olarak adlandir)',
        r'"(.+?)"\s+ad[ıi]n[ıi]\s+"(.+?)"\s+(?:olarak\s+)?(?:degistir|değiştir)',
        r"(.+?)\s+ad[ıi]n[ıi]\s+(.+?)\s+(?:yap|degistir)",
    ]
    for pat in patterns:
        m = re.search(pat, normalised_quotes, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return "", ""


def _mkdir_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    # Triggers: "klasör oluştur", "klasör yap", "yeni klasör", "dizin oluştur"
    is_mkdir = any(tok in q for tok in (
        "klasor olustur", "klasör oluştur",
        "klasor yap", "klasör yap",
        "yeni klasor", "yeni klasör",
        "dizin olustur", "dizin oluştur",
        "folder olustur", "folder oluştur",
        "create folder", "make folder", "mkdir",
        "new folder", "yeni dizin",
    ))
    if not is_mkdir:
        return None

    folder_name = _extract_folder_name(text)
    location_path = _resolve_location_path(text)

    if folder_name:
        target_path = str(Path(location_path) / folder_name)
        description = f'"{folder_name}" klasörü {Path(location_path).name} içinde oluşturulacak.'
        summary = f'{Path(location_path).name} konumunda "{folder_name}" adlı klasör oluşturacağım.'
    else:
        target_path = str(Path(location_path) / "Yeni Klasör")
        description = f"{Path(location_path).name} içinde yeni klasör oluşturulacak."
        summary = f'{Path(location_path).name} konumuna yeni bir klasör oluşturacağım.'

    # shell_run DEĞİL: shell dispatch onay blocklist'inde olduğundan basit
    # klasör oluşturma mobilde onay çıkmazına giriyordu. make_directory
    # zararsız + geri alınabilir → onaysız çalışır.
    steps = [{"capability": "make_directory", "args": {"path": target_path}, "description": description}]
    return RoutedTask(
        "make_directory",
        {"path": target_path},
        "mkdir",
        intent="file_system_mkdir",
        confidence=0.95,
        requires_confirmation=False,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _list_dir_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    triggers = (
        "klasor icerigi", "klasör içeriği",
        "dizin icerigi", "dizin içeriği",
        "dosyalari listele", "dosyaları listele",
        "dosyalari goster", "dosyaları göster",
        "icerigi goster", "içeriği göster",
        "ne var", "neler var",
        "listele", "list",
    )
    location_triggers = _LOCATION_TRIGGER_PATTERNS
    has_trigger = any(tok in q for tok in triggers)
    has_location = any(tok in q for tok in location_triggers)

    if not (has_trigger and has_location):
        # Also match "masaüstünü göster" / "indirilenler klasörü"
        if not (any(t in q for t in ("goster", "göster")) and has_location):
            return None

    location_path = _resolve_location_path(text)
    location_name = Path(location_path).name or "Ana dizin"
    description = f"{location_name} klasörünün içeriği listeleniyor."
    summary = f"{location_name} içindeki dosya ve klasörleri listeleceğim."
    # Salt-okunur listeleme shell DEĞİL: shell dispatch onayı kapsamı dışında
    # kaldığından mobilde onay çıkmazına giriyordu ("Onay bekleyen plan
    # bulunamadı"). directory_tree güvenli, onaysız ve yapılı sonuç döndürür.
    args = {"path": location_path, "max_depth": 1, "max_entries": 200}
    steps = [{"capability": "directory_tree", "args": dict(args), "description": description}]
    return RoutedTask(
        "directory_tree",
        args,
        "list_dir",
        intent="file_system_list",
        confidence=0.88,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _file_move_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("tasi", "taşı", "move", "transfer")):
        return None
    # Need a source and destination reference
    file_name = _extract_file_name(text)
    if not file_name and not _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES | _IMAGE_SUFFIXES | _DATA_SUFFIXES | _AUDIO_SUFFIXES):
        return None
    dest_path = _resolve_location_path(text)
    src_explicit = _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES | _IMAGE_SUFFIXES | _DATA_SUFFIXES | _AUDIO_SUFFIXES)
    if src_explicit:
        src = src_explicit
    elif file_name:
        # Try to find source in common locations
        for loc in ("Desktop", "Downloads", "Documents"):
            candidate = str(Path.home() / loc / file_name)
            if Path(candidate).exists():
                src = candidate
                break
        else:
            src = str(Path.home() / "Desktop" / file_name)
    else:
        return None

    command = f'mv "{src}" "{dest_path}/"'
    description = f'"{Path(src).name}" dosyası {Path(dest_path).name} konumuna taşınacak.'
    summary = f'"{Path(src).name}" dosyasını {Path(dest_path).name} klasörüne taşıyacağım.'
    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "file_move",
        intent="file_system_move",
        confidence=0.85,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _file_copy_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("kopyala", "copy", "kopyasini olustur", "kopyasını oluştur", "duplicate")):
        return None
    src_explicit = _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES | _IMAGE_SUFFIXES | _DATA_SUFFIXES | _AUDIO_SUFFIXES)
    file_name = _extract_file_name(text)
    if not src_explicit and not file_name:
        return None
    dest_path = _resolve_location_path(text)
    src = src_explicit or str(Path.home() / "Desktop" / file_name)
    command = f'cp -r "{src}" "{dest_path}/"'
    description = f'"{Path(src).name}" dosyası {Path(dest_path).name} konumuna kopyalanacak.'
    summary = f'"{Path(src).name}" dosyasını {Path(dest_path).name} klasörüne kopyalayacağım.'
    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "file_copy",
        intent="file_system_copy",
        confidence=0.84,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _file_delete_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("sil", "delete", "remove", "kaldir", "kaldır", "cop kutusuna", "çöp kutusuna")):
        return None
    # Be conservative — require explicit file reference, quoted name, or a
    # clear "X klasörünü/dosyasını sil" pattern.
    src_explicit = _explicit_path_for_suffixes(text, _DOCUMENT_SUFFIXES | _IMAGE_SUFFIXES | _DATA_SUFFIXES | _AUDIO_SUFFIXES)
    quoted = _extract_quoted_name(text)
    named = ""
    if not src_explicit and not quoted:
        # "Masaüstündeki Emre klasörünü sil" / "rapor dosyasını çöp kutusuna at"
        named_match = re.search(
            r"([\w][\w .-]{0,60}?)\s+(?:adlı\s+|adli\s+)?(?:klasör(?:ü|u)?n[üu]|klasor(?:u)?nu|dizinini|dosyas[ıi]n[ıi])\s",
            text,
            flags=re.IGNORECASE,
        )
        if named_match:
            candidate = named_match.group(1).strip()
            if candidate and _normalise(candidate) not in _FOLDER_NAME_STOPWORDS:
                named = candidate
    if not src_explicit and not quoted and not named:
        return None
    target_name = quoted or named
    location_path = _resolve_location_path(text) if _mentions_location(text) else str(Path.home() / "Desktop")
    src = src_explicit or str(Path(location_path) / target_name)
    # Move to trash instead of hard delete for safety
    trash_cmd = f'osascript -e \'tell application "Finder" to delete POSIX file "{src}"\''
    description = f'"{Path(src).name}" çöp kutusuna taşınacak.'
    summary = f'"{Path(src).name}" dosyasını çöp kutusuna taşıyacağım.'
    steps = [{"capability": "shell_run", "args": {"command": trash_cmd, "use_shell": True}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": trash_cmd, "use_shell": True},
        "file_delete",
        intent="file_system_delete",
        confidence=0.9,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _file_rename_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("yeniden adlandir", "adini degistir", "olarak degistir", "rename", "isim degistir")):
        return None
    old_name, new_name = _extract_rename_target(text)
    if not old_name or not new_name:
        return None
    location_path = _resolve_location_path(text) if _mentions_location(text) else str(Path.home() / "Desktop")
    src = str(Path(location_path) / old_name)
    dst = str(Path(location_path) / new_name)
    command = f'mv "{src}" "{dst}"'
    description = f'"{old_name}" → "{new_name}" olarak yeniden adlandırılacak.'
    summary = f'"{old_name}" dosyasının adını "{new_name}" olarak değiştireceğim.'
    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "file_rename",
        intent="file_system_rename",
        confidence=0.88,
        requires_confirmation=True,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _create_file_route(text: str) -> RoutedTask | None:
    q = _normalise(text)
    if not any(tok in q for tok in ("dosya olustur", "dosyasi olustur", "yeni dosya", "create file", "txt olustur", "new file")):
        return None
    file_name = _extract_file_name(text) or _extract_folder_name(text) or "yeni-dosya.txt"
    if not Path(file_name).suffix:
        file_name += ".txt"
    location_path = _resolve_location_path(text)
    target_path = str(Path(location_path) / file_name)
    command = f'touch "{target_path}"'
    description = f'"{file_name}" dosyası {Path(location_path).name} konumunda oluşturulacak.'
    summary = f'{Path(location_path).name} konumunda "{file_name}" adlı yeni dosya oluşturacağım.'
    steps = [{"capability": "shell_run", "args": {"command": command, "use_shell": False}, "description": description}]
    return RoutedTask(
        "shell_run",
        {"command": command, "use_shell": False},
        "create_file",
        intent="file_system_create",
        confidence=0.9,
        privacy_class="local_private",
        plan_preview=_build_plan_summary(summary, steps, "local_private"),
        steps=tuple(steps),
    )


def _desktop_document_route(text: str, selected_artifacts: list[dict[str, Any]] | None = None) -> RoutedTask | None:
    """Resolve 'masaüstündeki [dosya]' patterns for document operations."""
    if not _mentions_location(text):
        return None
    q = _normalise(text)
    if not any(tok in q for tok in ("ozetle", "özetle", "oku", "cikar", "çıkar", "analiz", "incele", "summary", "summarize")):
        return None
    # Kaynağı gömülü ek olan istekleri kapma: "bunu özetleyip masaüstüne
    # kaydet" + ekli belge geldiğinde konum SÖZDE kaynak değil KAYIT HEDEFİ.
    # Eskiden buradan document_read'e gidip masaüstünde var olmayan
    # "rapor.pdf"i okumaya çalışıyor, özet+kaydet zinciri hiç çalışmıyordu.
    embedded_text, _embedded_labels = _embedded_attachment_payload(text)
    if embedded_text:
        return None
    # Konum sadece kayıt hedefi olarak geçiyorsa (kaydet/save + "-e/-a" yönelme
    # hali) bu rota kaynak-okuma rotası olarak yanlış eşleşir; sonraki
    # summary_save rotasına bırak.
    if any(tok in q for tok in _DOCUMENT_SAVE_TOKENS) and re.search(
        r"(masaustune|masaüstüne|desktopa|desktop'a|klasorune|klasörüne|belgelerime)", q
    ):
        return None
    # Try to extract file name from text
    file_name = _extract_file_name(text)
    if not file_name:
        return None
    location_path = _resolve_location_path(text)
    candidate = str(Path(location_path) / file_name)
    src = candidate
    suffix = Path(src).suffix.lower() if file_name else ""
    if suffix in _DATA_SUFFIXES:
        return RoutedTask(
            "data_analyze",
            {"path": src, "mode": _data_mode(text)},
            "desktop_data_analyze",
            intent="data_analyze",
            confidence=0.82,
            privacy_class="local_private",
        )
    # Default: document read/summarize
    return RoutedTask(
        "document_read",
        {"path": src, "mode": _document_mode(text)},
        "desktop_document_read",
        intent="document_read",
        confidence=0.80,
        privacy_class="local_private",
    )


# ── route_text_to_tool ────────────────────────────────────────────────────────

# Bileşik komut ayırıcıları — uzun kalıplar önce denenmeli.
_COMPOUND_SPLIT_RE = re.compile(
    r"\s*(?:;|,?\s+ve\s+ard[ıi]ndan|,?\s+ard[ıi]ndan|,?\s+ve\s+sonra(?:\s+da)?|,?\s+daha\s+sonra|,?\s+sonra(?:\s+da)?|\s+ve)\s+",
    re.IGNORECASE,
)
_COMPOUND_MIN_CONFIDENCE = 0.8

# Türkçe -ıp/-ip ulacı bağlaç görevi görür: "yapay zekayı araştırıp sunum
# hazırla" = "araştır VE sunum hazırla". Ana bölücü yalnız açık bağlaçları
# tanıdığı için bu biçim tek segmente düşüyor, araştırma adımı kayboluyor ve
# komutun tamamı yazıcı aracın dosya adı oluyordu. Muhafazakâr kalmak için
# yalnız araştırma köklü fiillerde uygulanır (kaydedip/açıp gibi ulaçlar
# bölünmez — devam segmenti kendi başına rotalanamayabilir).
_RESEARCH_CONVERB_RE = re.compile(
    r"^(?P<first>.+?(?:ara[şs]t[ıi]r|arat))[ıi]p\s+(?P<rest>.{4,})$",
    re.IGNORECASE,
)

# Zincirin 2+ segmentlerinde "bunu belgele", "sonucu bana mail at" gibi önceki
# adımın çıktısını tüketen ifadeler tek başına rotalanamaz (konu zamirde kalır).
# Bu ön ek atılıp kalan fiil bir "tüketici" araca eşlenir; içerik bağlamı
# yürütmede _previousOutput/_writer_source_context üzerinden akar.
_CONTINUATION_PRONOUN_RE = re.compile(
    r"^(?:ve\s+)?(?:bunu|bunlar[ıi]|onu|onlar[ıi]|sonucu|sonu[çc]lar[ıi]n?[ıi]?|"
    r"bulduklar[ıi]n[ıi]|bulgular[ıi]n?[ıi]?|[çc][ıi]kt[ıi]y[ıi]|hepsini)\s+",
    re.IGNORECASE,
)
_CONTINUATION_WRITE_VERBS = (
    "belgele", "raporla", "rapor et", "kaydet", "olustur", "hazirla", "yap",
    "yaz", "cevir", "donustur", "dok", "aktar", "cikar", "dokumante",
)
_MAIL_SEND_VERB_RE = re.compile(r"\b(at|gonder|yolla|ilet|send)\b")
_SELF_MAIL_RE = re.compile(r"\b(bana|kendime|kendi adresime|e-?postama|epostama|mailime)\b", re.IGNORECASE)


def _continuation_task(segment: str, topic_hint: str) -> RoutedTask | None:
    stripped = _CONTINUATION_PRONOUN_RE.sub("", segment.strip())
    q = _normalise(stripped)
    if not q:
        return None
    topic = _strip_leading_fillers(topic_hint) or topic_hint

    # E-posta tüketici: "sonucu bana mail at", "x@y.com adresine gönder".
    if any(token in q for token in ("mail", "e-posta", "eposta", "email")) and _MAIL_SEND_VERB_RE.search(q):
        recipients = _extract_email_addresses(segment)
        if not recipients and _SELF_MAIL_RE.search(segment):
            # "me" yer tutucusu actions.email tarafında hesap e-postasına çözülür.
            recipients = ["me"]
        if not recipients:
            return None
        subject = _email_subject(topic, segment)
        steps = (
            {
                "capability": "email_draft",
                "args": {"to": recipients, "subject": subject, "topic": topic, "prompt": segment.strip()},
                "description": f"{', '.join(recipients)} için önceki adımın çıktısından e-posta taslağı hazırlanacak.",
            },
            {
                "capability": "email_send",
                "args": {"to": recipients, "subject": subject},
                "description": f"{', '.join(recipients)} adresine e-posta gönderilecek.",
            },
        )
        return RoutedTask(
            "email_send",
            dict(steps[0]["args"]),
            "compound_continuation",
            intent="email_send",
            confidence=0.9,
            requires_confirmation=True,
            is_multi_step=True,
            privacy_class="side_effect",
            steps=steps,
        )

    if not any(token in q for token in _CONTINUATION_WRITE_VERBS):
        return None

    def _writer_task(capability: str, extension: str, label: str) -> RoutedTask:
        output_path = _resolve_output_path(topic, extension, hint=topic or "elyan-cikti")
        args = {
            "prompt": f"{topic} hakkında {label} hazırla. İstek: {segment.strip()}",
            "outputPath": output_path,
            "overwrite": False,
        }
        step = {
            "capability": capability,
            "args": args,
            "description": f"Önceki adımın çıktısından {Path(output_path).name} oluşturulacak.",
        }
        return RoutedTask(
            capability,
            dict(args),
            "compound_continuation",
            intent=capability,
            confidence=0.85,
            requires_confirmation=True,
            privacy_class="local_private",
            steps=(step,),
        )

    # Sıra önemli: excel/sunum belirteçleri "rapor" ile birlikte geçebildiği
    # için özgül olanlar önce denenir.
    if any(token in q for token in ("xlsx", "excel", "tablo", "cizelge", "sheet")):
        return _writer_task("spreadsheet_write", ".xlsx", "bir tablo")
    if any(token in q for token in ("pptx", "powerpoint", "sunum", "slayt", "slide")):
        return _writer_task("presentation_write", ".pptx", "bir sunum")
    if any(token in q for token in ("rapor", "belge", "belgele", "raporla", "word", "docx", "dokuman", "dokumante")):
        return _writer_task("document_write", ".docx", "bir rapor")
    return None


def _compound_route(
    text: str,
    selected_artifacts: list[dict[str, Any]] | None,
) -> RoutedTask | None:
    """"X'i araştır ve rapor olarak belgele" gibi tek mesajda birden çok
    eylem içeren komutları sıralı çok adımlı plana çevirir. Muhafazakâr
    davranır: her parça kendi başına yüksek güvenle rotalanamıyorsa
    (ör. "tuz ve biber araştır") bölme iptal edilir ve metin tek görev
    olarak işlenir."""
    segments = [seg.strip(" .,!") for seg in _COMPOUND_SPLIT_RE.split(text)]
    segments = [seg for seg in segments if seg]
    expanded: list[str] = []
    for segment in segments:
        converb = _RESEARCH_CONVERB_RE.match(segment)
        if converb:
            expanded.append(converb.group("first").strip())
            expanded.append(converb.group("rest").strip())
        else:
            expanded.append(segment)
    segments = expanded
    if not 2 <= len(segments) <= 5:
        return None
    parts: list[tuple[str, RoutedTask]] = []
    for index, segment in enumerate(segments):
        routed = route_text_to_tool(
            segment,
            selected_artifacts=selected_artifacts,
            _allow_compound=False,
        )
        if (routed is None or routed.confidence < _COMPOUND_MIN_CONFIDENCE) and index > 0 and parts:
            # "bunu belgele" / "sonucu bana mail at" gibi devam segmentleri
            # konu zamirde kaldığı için tek başına rotalanamaz; ilk adımın
            # konusu bağlam olarak verilerek tüketici araca eşlenir.
            first_routed = parts[0][1]
            topic_hint = str(first_routed.args.get("query", "") or "").strip() or segments[0]
            routed = _continuation_task(segment, topic_hint)
        if routed is None or routed.confidence < _COMPOUND_MIN_CONFIDENCE:
            return None
        parts.append((segment, routed))
    steps: list[dict[str, Any]] = []
    for segment, routed in parts:
        if routed.steps:
            steps.extend(dict(step) for step in routed.steps if isinstance(step, dict))
        else:
            description = (
                str(routed.plan_preview.get("summary", "") or "").strip()
                if isinstance(routed.plan_preview, dict)
                else ""
            ) or segment
            steps.append({
                "capability": routed.tool_name,
                "args": dict(routed.args),
                "description": description,
            })

    deduplicated_steps: list[dict[str, Any]] = []
    data_mode_rank = {"preview": 0, "summary": 1, "profile": 2}
    document_mode_rank = {"read": 0, "bullets": 1, "summary": 2}
    image_mode_rank = {"metadata": 0, "palette": 1, "summary": 2}
    for step in steps:
        capability = str(step.get("capability", "") or "").strip()
        args = dict(step.get("args") or {})
        duplicate = next(
            (
                existing
                for existing in deduplicated_steps
                if str(existing.get("capability", "") or "").strip() == capability
                and dict(existing.get("args") or {}) == args
            ),
            None,
        )
        if duplicate is not None:
            continue
        if capability == "data_analyze":
            same_target = next(
                (
                    existing
                    for existing in deduplicated_steps
                    if str(existing.get("capability", "") or "").strip() == capability
                    and str((existing.get("args") or {}).get("path", "") or "") == str(args.get("path", "") or "")
                ),
                None,
            )
            if same_target is not None:
                existing_args = dict(same_target.get("args") or {})
                existing_mode = str(existing_args.get("mode", "summary") or "summary")
                incoming_mode = str(args.get("mode", "summary") or "summary")
                if data_mode_rank.get(incoming_mode, 0) > data_mode_rank.get(existing_mode, 0):
                    existing_args["mode"] = incoming_mode
                    same_target["args"] = existing_args
                continue
        if capability == "document_read":
            same_target = next(
                (
                    existing
                    for existing in deduplicated_steps
                    if str(existing.get("capability", "") or "").strip() == capability
                    and str((existing.get("args") or {}).get("path", "") or "") == str(args.get("path", "") or "")
                ),
                None,
            )
            if same_target is not None:
                existing_args = dict(same_target.get("args") or {})
                existing_mode = str(existing_args.get("mode", "read") or "read")
                incoming_mode = str(args.get("mode", "read") or "read")
                if document_mode_rank.get(incoming_mode, 0) > document_mode_rank.get(existing_mode, 0):
                    existing_args["mode"] = incoming_mode
                    same_target["args"] = existing_args
                continue
        if capability == "image_read":
            same_target = next(
                (
                    existing
                    for existing in deduplicated_steps
                    if str(existing.get("capability", "") or "").strip() == capability
                    and str((existing.get("args") or {}).get("path", "") or "") == str(args.get("path", "") or "")
                ),
                None,
            )
            if same_target is not None:
                existing_args = dict(same_target.get("args") or {})
                existing_mode = str(existing_args.get("mode", "summary") or "summary")
                incoming_mode = str(args.get("mode", "summary") or "summary")
                if image_mode_rank.get(incoming_mode, 0) > image_mode_rank.get(existing_mode, 0):
                    existing_args["mode"] = incoming_mode
                    same_target["args"] = existing_args
                continue
        deduplicated_steps.append(step)
    steps = deduplicated_steps
    if len(steps) < 2:
        return None

    # ── Profesyonel veri akışı: araştırma adımı bir yazıcı adımını besliyorsa,
    # yazıcının prompt'una KONUYU + (varsa) sayfa hedefini enjekte et. Yürütücü
    # ayrıca web_research çıktısını _previousResult ile document_write'a geçirir
    # (sourceContext) → belge gerçek araştırma içeriğiyle dolar, boş şablon değil.
    research_topic = ""
    for step in steps:
        if str(step.get("capability", "")) == "web_research":
            research_topic = str((step.get("args") or {}).get("query", "") or "").strip()
            break
    if research_topic:
        page_target = _extract_page_count(text)
        for step in steps:
            if str(step.get("capability", "")) in {"document_write", "presentation_write", "spreadsheet_write", "canvas_write"}:
                args = dict(step.get("args") or {})
                prompt = str(args.get("prompt", "") or "").strip()
                if research_topic.lower() not in prompt.lower():
                    prompt = f"{research_topic} hakkında {prompt}".strip() if prompt else f"{research_topic} hakkında ayrıntılı belge"
                if page_target and "sayfa" not in prompt.lower() and "page" not in prompt.lower():
                    prompt = f"{prompt} (yaklaşık {page_target} sayfa)"
                args["prompt"] = prompt
                if not str(args.get("title", "") or "").strip():
                    args["title"] = research_topic[:80]
                current_output = str(args.get("outputPath", "") or "").strip()
                if current_output:
                    suffix = Path(current_output).suffix or ".docx"
                    # Açık yol/tırnaklı ad İSTENMEDİYSE dosya adını konudan üret;
                    # klasör ipuçları (masaüstüne vb.) tam metinden korunur.
                    if not re.search(r'["“/~]', text):
                        args["outputPath"] = _resolve_output_path(
                            research_topic, suffix, hint=research_topic
                        )
                step["args"] = args

    if any(routed.privacy_class == "side_effect" for _, routed in parts):
        privacy_class = "side_effect"
    elif any(routed.privacy_class == "local_private" for _, routed in parts):
        privacy_class = "local_private"
    else:
        privacy_class = "public_text"
    capability_chain = " → ".join(str(step.get("capability", "")) for step in steps)
    summary = f"{len(steps)} adımlı görev planlandı: {capability_chain}"
    first = parts[0][1]
    return RoutedTask(
        first.tool_name,
        dict(first.args),
        "compound_task",
        intent="compound_task",
        confidence=min(routed.confidence for _, routed in parts),
        requires_confirmation=any(routed.requires_confirmation for _, routed in parts),
        is_multi_step=True,
        privacy_class=privacy_class,
        plan_preview=_build_plan_summary(summary, steps, privacy_class),
        steps=tuple(steps),
    )


_AGENTIC_BROWSE_SIGNALS = (
    "tarayici", "tarayıcı", "internetten", "internette", "web den", "webden",
    "web uzerinden", "web üzerinden", "google da", "google'da", "siteye gir",
    "sitesine gir", "hava durumu", "haber", "fiyat", "borsa", "doviz", "döviz",
    "kanalim", "kanalıma", "profilime", "linkini", "linklerini",
)
_AGENTIC_ANSWER_SIGNALS = (
    "soyle", "söyle", "bul", "ogren", "öğren", "arastir", "araştır", "topla",
    "getir", "kontrol et", "ne kadar", "ozetle", "özetle", "derece", "toparla",
    "karsilastir", "karşılaştır",
)


_WEATHER_FILLER = {
    "hava", "durumu", "durumuna", "durum", "bak", "bakar", "misin", "söyle",
    "soyle", "ve", "nasil", "nasıl", "bugun", "bugün", "yarin", "yarın",
    "weather", "sicaklik", "sıcaklık", "yagmur", "yağmur", "derece",
    "derecesini", "derecesi", "kac", "kaç", "ne", "kadar", "için", "icin",
    "bana", "lütfen", "lutfen", "dışarı", "disari", "dışarısı", "disarisi",
    "dışarıda", "disarida", "şu", "su", "an", "anda", "şimdi", "simdi",
}


def _weather_location(original: str) -> str:
    """Hava durumu isteğinden temiz şehir/konum çıkarır. Bulamazsa boş döner
    (get_weather varsayılan konuma düşer) — çöp metni konum sanıp servisi
    kırmaktansa dürüst varsayılan."""
    # 1) İyelik kalıbı: "İstanbul'un derecesi", "Ankara nın havası"
    m = re.search(
        r"([A-Za-zÇĞİıÖŞÜçğıöşü]{3,})['’`]?\s*(?:n[ıiuü]n|[ıiuü]n)\s+"
        r"(?:derece|sicaklik|sıcaklık|hava|hava durumu)",
        original,
        flags=re.IGNORECASE,
    )
    if m and _normalise(m.group(1)) not in _WEATHER_FILLER:
        return m.group(1)
    # 2) Tek anlamlı sözcük kaldıysa onu konum say.
    tokens = re.findall(r"[A-Za-zÇĞİıÖŞÜçğıöşü]{3,}", original)
    cands = [t for t in tokens if _normalise(t) not in _WEATHER_FILLER]
    if len(cands) == 1:
        return cands[0]
    return ""


def _agentic_browser_goal_route(original: str) -> "RoutedTask | None":
    """Tarayıcıdan okuyup cevap/veri üreten serbest hedefleri ReAct ajanına
    yönlendirir. "hava durumuna bak ve söyle", "kanalımdaki son videoların
    linkini topla" gibi işler bir sekme açıp unutulacak iş DEĞİL — sayfaya
    girip veriyi çıkaran kapalı-devre ajan gerekir."""
    q = _normalise(original)
    if not any(sig in q for sig in _AGENTIC_BROWSE_SIGNALS):
        return None
    if not any(sig in q for sig in _AGENTIC_ANSWER_SIGNALS):
        return None
    return RoutedTask(
        "browser_agent.run",
        {"goal": original},
        "agentic_browser_goal",
        intent="agentic_browser_goal",
        confidence=0.82,
        privacy_class="public_text",
    )


def route_text_to_tool(
    text: str,
    *,
    selected_artifacts: list[dict[str, Any]] | None = None,
    _allow_compound: bool = True,
) -> RoutedTask | None:
    original = _canonicalize_request(text)
    if not original:
        return None
    q = _normalise(original)

    image_edit = _image_edit_route(original, selected_artifacts)
    if image_edit is not None:
        return image_edit

    image_generate = _image_generate_route(original)
    if image_generate is not None:
        return image_generate

    data_pipeline = _data_artifact_pipeline_route(original)
    if data_pipeline is not None:
        return data_pipeline

    research_spreadsheet = _research_spreadsheet_route(original)
    if research_spreadsheet is not None:
        return research_spreadsheet

    pdf_report = _pdf_report_route(original)
    if pdf_report is not None:
        return pdf_report

    document_transform = _selected_document_transform_route(original, selected_artifacts)
    if document_transform is not None:
        return document_transform

    multi_step = _multi_step_browser_route(original)
    if multi_step is not None:
        return multi_step

    if _allow_compound:
        compound = _compound_route(original, selected_artifacts)
        if compound is not None:
            return compound

    # Pano komutları dosya-kopyalama ("kopyala") rotasından ÖNCE ele alınır;
    # aksi halde "panoya kopyala X" yanlışlıkla cp olarak yorumlanır.
    clipboard_task = _clipboard_route(original)
    if clipboard_task is not None:
        return clipboard_task

    # ── File system operations (highest priority — very specific intents) ──────
    mkdir = _mkdir_route(original)
    if mkdir is not None:
        return mkdir

    file_rename = _file_rename_route(original)
    if file_rename is not None:
        return file_rename

    file_delete = _file_delete_route(original)
    if file_delete is not None:
        return file_delete

    file_move = _file_move_route(original)
    if file_move is not None:
        return file_move

    file_copy = _file_copy_route(original)
    if file_copy is not None:
        return file_copy

    list_dir = _list_dir_route(original)
    if list_dir is not None:
        return list_dir

    create_file = _create_file_route(original)
    if create_file is not None:
        return create_file

    # Desktop-located document operations ("masaüstündeki belgeyi özetle")
    desktop_doc = _desktop_document_route(original, selected_artifacts)
    if desktop_doc is not None:
        return desktop_doc

    # ── Scheduled / calendar ──────────────────────────────────────────────────
    calendar_add = _calendar_add_route(original)
    if calendar_add is not None:
        return calendar_add

    reminder_add = _reminder_add_route(original)
    if reminder_add is not None:
        return reminder_add

    site_visit = _site_visit_route(original)
    if site_visit is not None:
        return site_visit

    speech_transcription = _speech_transcription_route(original, selected_artifacts)
    if speech_transcription is not None:
        return speech_transcription

    text_to_speech = _text_to_speech_route(original)
    if text_to_speech is not None:
        return text_to_speech

    data_analyze = _data_analyze_route(original, selected_artifacts)
    if data_analyze is not None:
        return data_analyze

    chart_generate = _chart_generate_route(original, selected_artifacts)
    if chart_generate is not None:
        return chart_generate

    document_summary_save = _document_summary_save_route(original, selected_artifacts)
    if document_summary_save is not None:
        return document_summary_save

    canvas_write = _canvas_write_route(original)
    if canvas_write is not None:
        return canvas_write

    document = _document_route(original, selected_artifacts)
    if document is not None:
        return document

    ocr = _ocr_route(original, selected_artifacts)
    if ocr is not None:
        return ocr

    image_read = _image_read_route(original, selected_artifacts)
    if image_read is not None:
        return image_read

    latex_parse = _latex_parse_route(original)
    if latex_parse is not None:
        return latex_parse

    math_route = _math_route(original)
    if math_route is not None:
        return math_route

    document_write = _document_write_route(original)
    if document_write is not None:
        return document_write

    spreadsheet_write = _spreadsheet_write_route(original)
    if spreadsheet_write is not None:
        return spreadsheet_write

    presentation_write = _presentation_write_route(original)
    if presentation_write is not None:
        return presentation_write

    email_send = _email_send_route(original)
    if email_send is not None:
        return email_send

    email_draft = _email_draft_route(original)
    if email_draft is not None:
        return email_draft

    web_research = _build_web_research_route(original)
    if web_research is not None:
        return web_research

    weekly_reminders = _workspace_reminders_route(original)
    if weekly_reminders is not None:
        return weekly_reminders

    # Kanal RAPORU yalnız istatistik sorularında; "youtube-transcript sitesine
    # gir, transkript indir" gibi gezinme/indirme istekleri rapora KAPILMASIN
    # (tarayıcı ajanı/LLM planlayıcı devralır).
    if (
        "youtube" in q
        and any(token in q for token in ("istatistik", "kanal", "son video", "buyume", "analytics"))
        and not any(
            token in q
            for token in ("sitesine", "siteye", "sitesi", "http", "www", "indir", "transkript", "transcript", "yapistir", "tikla", "girip")
        )
    ):
        return RoutedTask(
            "get_youtube_channel_report",
            {"query": original, "video_limit": 6},
            "youtube_report",
            intent="youtube_report",
            confidence=0.92,
        )

    # ── System controls (must be before open/close app to avoid false matches) ──
    _volume_up_tokens = {"ses ac", "sesi ac", "sesi arttir", "sesi yukselt", "volume up", "turn up volume"}
    _volume_down_tokens = {"ses kis", "sesi kis", "sesi azalt", "sesi dusur", "volume down", "turn down volume"}
    _volume_mute_tokens = {"sesi kapat", "sessize al", "sessiz yap", "mute", "sessiz mod"}
    if any(token in q for token in _volume_down_tokens | _volume_mute_tokens | _volume_up_tokens):
        if any(token in q for token in _volume_mute_tokens):
            action = "mute"
        elif any(token in q for token in _volume_down_tokens):
            action = "volume_down"
        else:
            action = "volume_up"
        return RoutedTask("system_control", {"action": action}, "volume_control", intent="volume_control", confidence=0.96, privacy_class="local_private")

    _brightness_up_tokens = {"parlaklik arttir", "parlaklik yukselt", "ekrani aydinlat", "brightness up"}
    _brightness_down_tokens = {"parlaklik azalt", "parlaklik dusur", "ekrani karart", "brightness down"}
    if any(token in q for token in _brightness_up_tokens | _brightness_down_tokens):
        action = "brightness_down" if any(token in q for token in _brightness_down_tokens) else "brightness_up"
        return RoutedTask("system_control", {"action": action}, "brightness_control", intent="brightness_control", confidence=0.95, privacy_class="local_private")

    _sys_toggle_map = {
        "wifi": ("wifi", {"wifi kapat", "wifi ac", "wi-fi kapat", "wi-fi ac"}),
        "bluetooth": ("bluetooth", {"bluetooth kapat", "bluetooth ac"}),
        "dark_mode": ("dark_mode", {"karanlik mod ac", "karanlik mod kapat", "dark mode", "gece modu ac", "gece modu kapat", "acik mod", "light mode"}),
        "do_not_disturb": ("do_not_disturb", {"rahatsiz etme", "do not disturb", "dnd"}),
    }
    for _toggle_key, (_action_name, _toggle_tokens) in _sys_toggle_map.items():
        if any(token in q for token in _toggle_tokens):
            enable = any(token in q for token in ("ac", "enable", "on", "etkinlestir"))
            return RoutedTask(
                "system_control",
                {"action": f"toggle_{_action_name}", "enable": enable},
                f"toggle_{_action_name}",
                intent=f"toggle_{_action_name}",
                confidence=0.94,
                privacy_class="local_private",
            )

    _lock_tokens = {"bilgisayari kilitle", "ekrani kilitle", "lock screen", "lock computer", "mac i kilitle", "kilitle"}
    _sleep_tokens = {"bilgisayari uyut", "uyku moduna al", "sleep", "bilgisayari kapat", "mac i uyut"}
    _reboot_tokens = {"bilgisayari yeniden baslat", "bilgisayari restart", "restart computer", "reboot", "sistemi yeniden baslat"}
    _trash_tokens = {"cop kutusunu bosalt", "cöp kutusunu boşalt", "empty trash", "휴지통 비우기"}
    if any(token in q for token in _lock_tokens):
        return RoutedTask("system_control", {"action": "lock_screen"}, "lock_screen", intent="lock_screen", confidence=0.97, requires_confirmation=True, privacy_class="local_private")
    if any(token in q for token in _sleep_tokens):
        return RoutedTask("system_control", {"action": "sleep"}, "sleep", intent="sleep", confidence=0.95, requires_confirmation=True, privacy_class="local_private")
    if any(token in q for token in _reboot_tokens):
        return RoutedTask("system_control", {"action": "reboot"}, "reboot", intent="reboot", confidence=0.95, requires_confirmation=True, privacy_class="local_private")
    if any(token in q for token in _trash_tokens):
        return RoutedTask("system_control", {"action": "empty_trash"}, "empty_trash", intent="empty_trash", confidence=0.93, requires_confirmation=True, privacy_class="local_private")

    # ── Screenshot / screen analysis ────────────────────────────────────────────
    _screenshot_capture_tokens = {
        "ss al", "ss cek",
        "screenshot al", "screenshot cek", "screenshot",
        "ekran goruntusu al", "ekran goruntusu cek",
        "ekran goruntusunu al", "ekran goruntusunu cek",
        "ekran resmini al", "ekran resmini cek",
        "ekranin resmini al", "ekranin resmini cek",
        "ekrani cek", "ekrani yakala",
        "ekran fotosu al", "ekran fotosu cek",
        "ekran fotografi al", "ekran fotografi cek",
        "ekran fotografini cek",
        "fotografini cek", "fotosunu cek",
        "print screen", "printscreen",
        "capture screen", "take screenshot",
        "take a screenshot",
    }
    _screen_analysis_tokens = {
        "ekranda ne var", "ekrana bak",
        "ekrani analiz", "ekran analizi",
        "bu hatayi oku", "buradaki hatayi oku", "buradaki hatayi incele",
        "pencereyi analiz", "aktif pencereyi analiz",
        "aktif pencereye bak", "bu pencereyi oku",
        "burada ne var", "ne goruyorsun",
        "masaustunde ne var", "masaustune bak",
        "masaustunu analiz", "masaustunu goster",
        "bilgisayarda ne var", "bilgisayarda ne acik",
        "bilgisayara bak", "ne acik",
        "what is on", "whats on", "what's on",
        "what do you see",
        "masaustune bak", "masaustunu goster",
    }
    if any(token in q for token in _screenshot_capture_tokens | _screen_analysis_tokens):
        if any(token in q for token in _screenshot_capture_tokens):
            return RoutedTask(
                "desktop_operator.observe_screen",
                {"query": original, "target": "active_window", "preserveScreenshot": True},
                "screen_screenshot",
                intent="screen_screenshot",
                confidence=0.97,
                privacy_class="local_private",
            )
        return RoutedTask(
            "analyze_screen",
            {"query": original, "target": "active_window"},
            "screen_analysis",
            intent="screen_analysis",
            confidence=0.94,
            privacy_class="local_private",
        )

    if any(token in q for token in ("dosya gezgini", "dosya yoneticisi", "dosya yöneticisi", "finder", "file explorer", "file manager")):
        if any(token in q for token in ("ac", "aç", "open", "launch", "başlat", "baslat", "start")):
            return RoutedTask("open_app", {"app_name": "Finder"}, "open_app", intent="open_app", confidence=0.98, privacy_class="local_private")

    sys_query = _sys_info_query(original)
    if sys_query:
        return RoutedTask("sys_info", {"query": sys_query}, "system_info", intent="system_info", confidence=0.98, privacy_class="local_private")

    if any(token in q for token in ("hava", "weather", "sicaklik", "yagmur")) or (
        "derece" in q and any(t in q for t in ("kac", "kaç", "sicak", "sıcak", "disari", "dışarı"))
    ):
        location = _weather_location(original)
        return RoutedTask("get_weather", {"location": location}, "weather", intent="weather", confidence=0.84)

    if any(token in q for token in ("takvim", "ajanda", "toplanti", "calendar")) and any(
        token in q
        for token in ("ne var", "goster", "kontrol", "oku", "siradaki", "bugun", "yarin", "week", "agenda", "bak")
    ):
        return RoutedTask(
            "get_calendar_events",
            {"query": _date_query(original), "limit": 8},
            "calendar_read",
            intent="calendar_read",
            confidence=0.9,
            privacy_class="local_private",
        )

    if any(token in q for token in ("animsatici", "hatirlatici", "reminder", "yapilacak")) and any(
        token in q for token in ("ne var", "goster", "kontrol", "oku", "bugun", "yarin", "upcoming", "bak")
    ):
        return RoutedTask(
            "get_reminders",
            {"query": _date_query(original), "limit": 8},
            "reminders_read",
            intent="reminders_read",
            confidence=0.9,
            privacy_class="local_private",
        )

    # "Chrome'dan X aç" kalıbı youtube/arama regex'lerinden önce ele alınır.
    app_content_open = _route_app_content_open(original)
    if app_content_open is not None:
        return app_content_open

    # Önce "X youtube'da çal" (içerik önde) denenir — tersi sırada "muse
    # youtube da çal" gibi cümlelerde içerik kaybolur.
    youtube_query = _extract_after(
        [
            r"(.+?)\s+youtube(?:['’]?(?:da|de|dan|den)|\s+(?:da|de|dan|den))?\s+(?:ac|aç|cal|çal|oynat)$",
            r"youtube(?:['’]?(?:da|de|dan|den|a|e|u|ü)|\s+(?:da|de|dan|den|a|e|u|ü))?\s+(?:gir(?:ip)?\s+(?:ve\s+)?)?(.+?)\s+(?:ac|aç|cal|çal|oynat|arat?|izle|bul)$",
        ],
        original,
    )
    if youtube_query:
        youtube_query = _strip_leading_fillers(youtube_query)
        folded_query = _normalise(youtube_query)
        # "youtube u aç" gibi hâl ekinden ibaret sorgu: aranacak içerik yok,
        # YouTube'un kendisi açılmak isteniyor.
        if not folded_query or folded_query in {"u", "i", "a", "e", "yi", "yu", "ye", "ya"}:
            return RoutedTask(
                "browser_control",
                {"action": "open_url", "url": _WEB_SERVICE_URLS["youtube"]},
                "web_service_open",
                intent="web_service_open",
                confidence=0.93,
            )
        return RoutedTask(
            "browser_control",
            {"action": "play_youtube", "query": youtube_query},
            "youtube_play",
            intent="youtube_play",
            confidence=0.95,
        )

    search_query = _extract_after(
        [
            r"(?:google(?:['’]?(?:da|de|dan|den)|\s+(?:da|de|dan|den))?|web(?:['’]?(?:de|den)|\s+(?:de|den))?|internette)\s+(.+?)\s+(?:ara|search)$",
            r"(.+?)\s+(?:google(?:['’]?(?:da|de|dan|den)|\s+(?:da|de|dan|den))?|web(?:['’]?(?:de|den)|\s+(?:de|den))?|internette)\s+(?:ara|search)$",
        ],
        original,
    )
    if search_query:
        search_query = _strip_leading_fillers(search_query)
        return RoutedTask(
            "browser_control",
            {"action": "search", "query": search_query},
            "web_search",
            intent="web_search",
            confidence=0.97,
        )

    close_target = _extract_after(
        [
            r"(.+?)\s+(?:uygulamas[ıi]n[ıi]\s+)?(?:kapat|close|quit|terminate|sonlandir|sonlandır|durdur)$",
            r"(?:kapat|close|quit|terminate|sonlandir|sonlandır|durdur)\s+(.+)$",
        ],
        original,
    )
    if close_target:
        close_target = _clean_app_name(close_target)
        if _is_generic_app_target(close_target):
            return RoutedTask("close_app", {"app_name": ""}, "close_active_app", intent="close_app", confidence=0.9, privacy_class="local_private")
        if close_target and not any(token in _normalise(close_target) for token in ("dosya", "file", "klasor", "folder")):
            return RoutedTask("close_app", {"app_name": close_target}, "close_app", intent="close_app", confidence=0.94, privacy_class="local_private")

    if any(token in q for token in ("onu kapat", "bunu kapat", "aktif pencereyi kapat", "bu pencereyi kapat")):
        return RoutedTask("close_app", {"app_name": ""}, "close_active_app", intent="close_app", confidence=0.93, privacy_class="local_private")

    focus_target = _extract_after(
        [
            r"(.+?)\s+(?:uygulamas[ıi]n[ıi]\s+)?(?:one getir|öne getir|one al|öne al|odakla|focus|bring to front)$",
            r"(?:one getir|öne getir|one al|öne al|odakla|focus|bring to front)\s+(.+)$",
        ],
        original,
    )
    if focus_target:
        focus_target = _clean_app_name(focus_target)
        if not _is_generic_window_reference(focus_target):
            return RoutedTask("open_app", {"app_name": focus_target}, "focus_app", intent="focus_app", confidence=0.92, privacy_class="local_private")

    restart_target = _extract_after(
        [
            r"(.+?)\s+(?:uygulamas[ıi]n[ıi]\s+)?(?:yeniden ac|yeniden aç|restart|relaunch)$",
            r"(?:yeniden ac|yeniden aç|restart|relaunch)\s+(.+)$",
        ],
        original,
    )
    if restart_target:
        restart_target = _clean_app_name(restart_target)
        if restart_target and not _is_generic_window_reference(restart_target):
            steps = [
                {"capability": "close_app", "args": {"app_name": restart_target}, "description": f"{restart_target} kapatılacak."},
                {"capability": "open_app", "args": {"app_name": restart_target}, "description": f"{restart_target} yeniden açılacak."},
            ]
            summary = f"{restart_target} kapatılıp yeniden açılacak."
            return RoutedTask(
                "close_app",
                {"app_name": restart_target},
                "restart_app",
                intent="restart_app",
                confidence=0.9,
                requires_confirmation=True,
                is_multi_step=True,
                privacy_class="local_private",
                plan_preview=_build_plan_summary(summary, steps, "local_private"),
                steps=tuple(steps),
            )

    open_target = _extract_after(_OPEN_VERB_PATTERNS, original)
    if open_target:
        open_target = _clean_app_name(open_target)
        if _looks_like_url(open_target):
            return RoutedTask("browser_control", {"action": "open_url", "url": open_target}, "open_url", intent="open_url", confidence=0.93)
        # Uygulama + içerik kalıbı yukarıda (_route_app_content_open) tarayıcı
        # planına çevrildi; buraya düşen split yalnız TARAYICI-OLMAYAN uygulama
        # demektir ("Notion dan notlarımı aç") — open_app'e uydurma ad göndermek
        # yerine rotayı atla (LLM planlayıcı devralır).
        app_content = _split_app_content_target(open_target)
        # "YouTube aç" gibi yerel uygulaması olmayan web servisleri tarayıcıda
        # doğru adrese gitsin (open_app("YouTube") → APP_NOT_FOUND yerine).
        service_url = _web_service_url(_normalise(open_target))
        if app_content is None and service_url:
            return RoutedTask(
                "browser_control",
                {"action": "open_url", "url": service_url},
                "web_service_open",
                intent="web_service_open",
                confidence=0.93,
            )
        # "yeni sekme aç", "new tab", "sekme aç" gibi ifadeler bir UYGULAMA adı
        # değil; open_app'e kaçarsa "yeni sekme guvenli sekilde acilamadi" diye
        # kafa karıştırıcı hata verirdi. Bunları open_app dışında tut.
        if (
            app_content is None
            and not _is_generic_app_target(open_target)
            and not _is_non_app_open_target(open_target)
            and not any(token in _normalise(open_target) for token in ("dosya", "file", "klasor", "folder"))
        ):
            return RoutedTask("open_app", {"app_name": open_target}, "open_app", intent="open_app", confidence=0.95, privacy_class="local_private")

    # ── Geliştirici (kod-ajanı) okuma tool'ları — SHELL rotasından ÖNCE, çünkü
    # "git durumu/diff" gibi komutlar yoksa ham shell_run'a düşerdi. Yalnız
    # status/diff/ağaç/kod-arama yakalanır; diğer git komutları shell'e kalır. ─
    dev_task = _developer_tool_route(original)
    if dev_task is not None:
        return dev_task

    command = _extract_after(
        [
            r"(?:terminalde|terminal[a-z]*|komut satiri[a-z]*|shell[a-z]*)\s+(.+?)\s+(?:calistir|çalıştır|run|execute|exec)$",
            r"(?:terminalde|terminal[a-z]*|komut satiri[a-z]*|shell[a-z]*)\s+(.+)$",
            r"(?:calistir|çalıştır|run|execute)\s+([\w\-\.]+(?:\s+.+)?)$",
            r"^((?:ls|dir|pwd|echo|cat|grep|find|ps|top|df|du|ping|curl|wget|git|npm|pip|python|python3|node|brew|apt|yum|dnf|pacman|choco|winget)\s*.+)$",
        ],
        original,
    )
    if command:
        # Strip leading quotes if LLM wrapped the command
        command = command.strip("'\"").strip()
        use_shell = any(op in command for op in ("&&", "||", "|", ";", ">", "<", "$(", "`"))
        summary = f"`{command}` komutu çalıştırılacak."
        steps = [
            {
                "capability": "shell_run",
                "args": {"command": command, "use_shell": use_shell},
                "description": summary,
            }
        ]
        return RoutedTask(
            "shell_run",
            {"command": command, "use_shell": use_shell},
            "shell_command",
            intent="shell_command",
            confidence=0.97,
            requires_confirmation=True,
            privacy_class="local_private",
            plan_preview=_build_plan_summary(summary, steps, "local_private"),
            steps=tuple(steps),
        )

    # ── Known folder shortcuts ──────────────────────────────────────────────────
    _folder_map = {
        "indirilenler": "~/Downloads",
        "downloads": "~/Downloads",
        "belgeler": "~/Documents",
        "documents": "~/Documents",
        "masaustu": "~/Desktop",
        "resimler": "~/Pictures",
        "pictures": "~/Pictures",
        "muzik": "~/Music",
        "music": "~/Music",
        "videolar": "~/Movies",
        "movies": "~/Movies",
    }
    for _folder_key, _folder_path in _folder_map.items():
        if _folder_key in q and any(token in q for token in ("ac", "goster", "open", "show", "git")):
            return RoutedTask(
                "open_app",
                {"app_name": "Finder", "path": _folder_path},
                "open_folder",
                intent="open_folder",
                confidence=0.93,
                privacy_class="local_private",
            )

    # ── Görsel bulma → tarayıcı araması (kırılgan operatör yerine güvenilir) ──
    image_find = _image_find_route(original)
    if image_find is not None:
        return image_find

    # ── Operatör (mouse/klavye): yalnız açık GUI fiilleri ────────────────────
    operator_task = _operator_action_route(original)
    if operator_task is not None:
        return operator_task

    # ── Serbest, "oku ve cevapla / topla" tarayıcı hedefi → ReAct ajanı ───────
    #    "arama açıldı" stub'ı yerine gerçekten sayfaya girip veriyi çıkarır.
    agentic = _agentic_browser_goal_route(original)
    if agentic is not None:
        return agentic

    # ── General knowledge / web search fallback ──────────────────────────────
    _info_query_patterns = [
        (r"(.+?)\s+(?:ne(?:dir)?|nedir|kac|kaç|ne kadar)[\s?]*$", "query"),
        (r"(.+?)\s+(?:haberleri?|news)[\s?]*$", "news"),
        (r"(.+?)\s+kuru?\s*(?:ne|kac|kaç)?[\s?]*$", "finance"),
    ]
    for _pattern, _query_type in _info_query_patterns:
        _info_match = re.search(_pattern, original, flags=re.IGNORECASE)
        if _info_match:
            _info_query = _info_match.group(1).strip()
            return RoutedTask(
                "browser_control",
                {"action": "search", "query": f"{_info_query} {_query_type}" if _query_type != "query" else _info_query},
                "web_search",
                intent="web_search",
                confidence=0.78,
            )

    return None
