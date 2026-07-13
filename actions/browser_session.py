"""Kalıcı, durum koruyan tarayıcı oturumu — mini-Codex operatörünün temeli.

browser_control "URL aç ve unut"tur; buradaki yetenekler ise AYNI sayfada
kalarak adım adım ilerler: git → tıkla → yaz → çıkar → indir. Oturum stratejisi:

1. Çalışan bir Chrome CDP ucu varsa (kullanıcı --remote-debugging-port ile
   açtıysa) ona bağlan — kullanıcının gerçek profili, canlı oturum.
2. Yoksa kullanıcının GERÇEK varsayılan Chrome profiliyle Chrome başlat.
   Elyan ayrı bir profil TUTMAZ; kullanıcının kendi girişlerini/oturumlarını
   kullanır (tam kişisel ajan). Profil zaten açıksa dizin kilitli olur →
   kullanıcı tarayıcıyı kapatır ya da debug portuyla açar. Dizin
   ELYAN_BROWSER_PROFILE_DIR ile geçersiz kılınabilir.

Playwright sync API nesneleri oluşturuldukları thread'e bağlıdır; executor
farklı thread'lerden çağırdığı için oturum TEK bir işçi thread'te yaşar,
komutlar kuyruğa yazılır, sonuç Event ile beklenir.
"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from actions._platform_common import capability_unavailable, invalid_argument, timeout_error
from runtime.capability_registry import SafeCapabilityError

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

_DOWNLOAD_DIR = Path.home() / ".elyan" / "browser" / "downloads"
_COMMAND_TIMEOUT_SECONDS = 60.0
_NAV_TIMEOUT_MS = 30_000
_ACTION_TIMEOUT_MS = 12_000
_MAX_EXTRACT_ITEMS = 100
_MAX_SNAPSHOT_ELEMENTS = 80

# Şifre/hassas alanlara otomatik yazmayı reddet — operatör güvenlik sınırı.
_SENSITIVE_INPUT_TYPES = {"password"}
_SENSITIVE_FIELD_PATTERN = re.compile(
    r"(?:\bpassword\b|\bpasscode\b|\bone[\s_-]*time[\s_-]*code\b|\botp\b|\bpin\b|"
    r"\bcredit[\s_-]*card\b|\bcard[\s_-]*(?:number|no)\b|\bcc[\s_-]*number\b|"
    r"\bcvc\b|\bcvv\b|\bsecurity[\s_-]*code\b|\bexpir(?:y|ation)\b|\biban\b|"
    r"\brouting[\s_-]*number\b|\bbank[\s_-]*account\b|\bşifre\b|\bparola\b|"
    r"\bkart[\s_-]*numaras[\u0131i]\b|\bson[\s_-]*kullanma\b|\bgüvenlik[\s_-]*kodu\b|"
    r"\bbanka[\s_-]*hesab[\u0131i]\b)",
    flags=re.IGNORECASE,
)
_BLOCKED_CLICK_PATTERN = re.compile(
    r"(?:\bpay\b|\bpurchase\b|\bbuy[\s_-]*now\b|\bcheckout\b|"
    r"\bplace[\s_-]*order\b|\bconfirm[\s_-]*(?:purchase|order|payment)\b|"
    r"\bsend[\s_-]*money\b|\bwire[\s_-]*transfer\b|\btransfer[\s_-]*funds\b|"
    r"\bdelete[\s_-]*account\b|\böde\b|\bödeme\b|\bsat[\u0131i]n[\s_-]*al\b|"
    r"\bsipariş(?:i|i)[\s_-]*ver\b|\bpara[\s_-]*gönder\b|\bhavale\b|"
    r"\bhesab[\u0131i][\s_-]*sil\b)",
    flags=re.IGNORECASE,
)


def _locator_safety_text(locator: Any) -> str:
    parts: list[str] = []
    for attribute in ("type", "name", "autocomplete", "aria-label", "placeholder", "id"):
        try:
            parts.append(str(locator.get_attribute(attribute) or ""))
        except Exception:
            continue
    try:
        parts.append(str(locator.inner_text(timeout=1_000) or ""))
    except Exception:
        pass
    return " ".join(" ".join(parts).split())[:800]


def _default_chrome_profile_dir() -> Path:
    """Kullanıcının GERÇEK varsayılan Chrome user-data dizini.

    Elyan ayrı bir profil tutmaz — kullanıcının kendi tarayıcısını, kendi
    oturumlarını/girişlerini kullanır. ELYAN_BROWSER_PROFILE_DIR ile elle
    geçersiz kılınabilir (ör. Brave/Edge veya farklı bir profil için).
    """
    override = str(os.environ.get("ELYAN_BROWSER_PROFILE_DIR", "") or "").strip()
    if override:
        return Path(override).expanduser()
    home = Path.home()
    platform = sys.platform
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Google" / "Chrome"
    if platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(local) / "Google" / "Chrome" / "User Data"
    # Linux ve diğerleri
    return home / ".config" / "google-chrome"


def _cdp_candidates() -> list[str]:
    endpoints = []
    override = str(os.environ.get("ELYAN_BROWSER_CDP_ENDPOINT", "") or "").strip()
    if override:
        endpoints.append(override)
    endpoints.extend(["http://127.0.0.1:9222", "http://127.0.0.1:9223"])
    return endpoints


def _probe_cdp_endpoint(endpoint: str) -> bool:
    if requests is None:
        return False
    try:
        response = requests.get(f"{endpoint}/json/version", timeout=1.5)
        return response.status_code == 200
    except Exception:
        return False


class _SessionThread:
    """Playwright oturumunu tek thread'te yaşatan komut işleyici."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[tuple[str, dict[str, Any], dict[str, Any], threading.Event]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.mode = ""  # "cdp" | "persistent"

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="elyan-browser-session", daemon=True)
            self._thread.start()

    def submit(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        self._ensure_thread()
        done = threading.Event()
        box: dict[str, Any] = {}
        self._queue.put((command, args, box, done))
        if not done.wait(_COMMAND_TIMEOUT_SECONDS):
            raise timeout_error("Tarayıcı oturumu komutu zaman aşımına uğradı.")
        error = box.get("error")
        if isinstance(error, BaseException):
            raise error
        result = box.get("result")
        return result if isinstance(result, dict) else {}

    # -- işçi thread ---------------------------------------------------------

    def _run(self) -> None:
        playwright = None
        browser = None
        context = None
        page = None

        def _shutdown() -> None:
            nonlocal playwright, browser, context, page
            for closer in (context, browser):
                try:
                    if closer is not None:
                        closer.close()
                except Exception:
                    pass
            try:
                if playwright is not None:
                    playwright.stop()
            except Exception:
                pass
            playwright = browser = context = page = None
            self.mode = ""

        def _ensure_page() -> Any:
            nonlocal playwright, browser, context, page
            if page is not None:
                try:
                    _ = page.url  # oturum hâlâ canlı mı?
                    return page
                except Exception:
                    _shutdown()
            try:
                from playwright.sync_api import sync_playwright
            except Exception as exc:
                raise SafeCapabilityError(
                    "DEPENDENCY_UNAVAILABLE", "Playwright bu kurulumda hazır değil."
                ) from exc

            playwright = sync_playwright().start()
            # 1) Çalışan Chrome'un CDP ucu (kullanıcının gerçek profili).
            for endpoint in _cdp_candidates():
                if not _probe_cdp_endpoint(endpoint):
                    continue
                try:
                    browser = playwright.chromium.connect_over_cdp(endpoint)
                    contexts = browser.contexts
                    context = contexts[0] if contexts else browser.new_context()
                    pages = context.pages
                    page = pages[0] if pages else context.new_page()
                    self.mode = "cdp"
                    return page
                except Exception:
                    browser = context = None
                    continue
            # 2) Kullanıcının GERÇEK Chrome profili ile başlat — ayrı profil YOK.
            #    Elyan kullanıcının kendi oturumlarını/girişlerini kullanır.
            #    (Chrome bu profille zaten açıksa dizin kilitlidir; kullanıcı
            #    tarayıcıyı kapatır ya da debug portuyla açarsa CDP yoluna düşer.)
            profile_dir = _default_chrome_profile_dir()
            _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            launch_kwargs: dict[str, Any] = {
                "user_data_dir": str(profile_dir),
                "headless": False,
                "accept_downloads": True,
                "viewport": None,
                "args": ["--no-first-run", "--no-default-browser-check", "--start-maximized"],
            }
            try:
                context = playwright.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
                self.mode = "persistent"
            except Exception:
                # Google Chrome kanalı yoksa paket Chromium'a düş.
                try:
                    context = playwright.chromium.launch_persistent_context(**launch_kwargs)
                    self.mode = "persistent"
                except Exception as exc:
                    # Profil kilitli (Chrome zaten açık). Görevi hard-fail etmek
                    # yerine geçici (girişsiz) bir bağlama düş — herkese açık
                    # görevler (arama, hava, açık sayfa okuma) yine tamamlanır.
                    # Giriş gerektiren işler için kullanıcıya net yol göster.
                    context = None
                    try:
                        browser = playwright.chromium.launch(
                            channel="chrome", headless=False,
                            args=["--no-first-run", "--no-default-browser-check", "--start-maximized"],
                        )
                    except Exception:
                        try:
                            browser = playwright.chromium.launch(headless=False)
                        except Exception:
                            browser = None
                    if browser is not None:
                        context = browser.new_context(accept_downloads=True, viewport=None)
                        self.mode = "ephemeral"
                    if context is None:
                        _shutdown()
                        raise SafeCapabilityError(
                            "BROWSER_PROFILE_BUSY",
                            "Chrome profiline erişilemedi — tarayıcı zaten açık olabilir. "
                            "Chrome'u kapatıp tekrar deneyin ya da onu "
                            "--remote-debugging-port=9222 ile açın.",
                    ) from exc
            pages = context.pages
            page = pages[0] if pages else context.new_page()
            return page

        while True:
            command, args, box, done = self._queue.get()
            try:
                if command == "close":
                    _shutdown()
                    box["result"] = {"closed": True}
                else:
                    active = _ensure_page()
                    box["result"] = self._execute(active, command, args)
            except BaseException as exc:  # sonucu çağırana taşı
                box["error"] = exc
            finally:
                done.set()

    # -- komutlar ------------------------------------------------------------

    def _execute(self, page: Any, command: str, args: dict[str, Any]) -> dict[str, Any]:
        if command == "goto":
            return self._goto(page, args)
        if command == "click":
            return self._click(page, args)
        if command == "type":
            return self._type(page, args)
        if command == "extract":
            return self._extract(page, args)
        if command == "snapshot":
            return self._snapshot(page, args)
        if command == "download":
            return self._download(page, args)
        if command == "status":
            return {"url": page.url, "title": page.title(), "mode": self.mode}
        raise invalid_argument(f"Bilinmeyen tarayıcı oturumu komutu: {command}")

    @staticmethod
    def _page_state(page: Any) -> dict[str, Any]:
        try:
            return {"url": page.url, "title": page.title()}
        except Exception:
            return {"url": "", "title": ""}

    def _goto(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        url = str(args.get("url", "") or "").strip()
        if not url:
            raise invalid_argument("Gidilecek URL belirtilmedi.")
        if "://" not in url:
            url = "https://" + url
        if not re.match(r"^https?://", url):
            raise invalid_argument("Yalnız http/https adreslerine gidilebilir.")
        page.bring_to_front()
        page.goto(url, timeout=_NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        state = self._page_state(page)
        return {**state, "navigated": True}

    def _locator(self, page: Any, args: dict[str, Any]) -> Any:
        selector = str(args.get("selector", "") or "").strip()
        text = str(args.get("text", "") or "").strip()
        role = str(args.get("role", "") or "").strip()
        if selector:
            return page.locator(selector).first
        if role and text:
            return page.get_by_role(role, name=text).first
        if text:
            return page.get_by_text(text, exact=False).first
        raise invalid_argument("Hedef için selector, role+text ya da text gerekli.")

    def _click(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        locator = self._locator(page, args)
        safety_text = _locator_safety_text(locator)
        if _BLOCKED_CLICK_PATTERN.search(safety_text):
            raise SafeCapabilityError(
                "SENSITIVE_ACTION_BLOCKED",
                "Ödeme, para transferi, sipariş veya hesap silme gibi geri döndürülemez "
                "tarayıcı eylemleri otomatik olarak yürütülemez.",
            )
        locator.click(timeout=_ACTION_TIMEOUT_MS)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        state = self._page_state(page)
        return {**state, "clicked": True}

    def _type(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        value = str(args.get("value", "") or args.get("text_value", "") or "")
        if not value:
            raise invalid_argument("Yazılacak metin boş.")
        locator = self._locator(page, args)
        try:
            input_type = str(locator.get_attribute("type") or "").lower()
        except Exception:
            input_type = ""
        safety_text = _locator_safety_text(locator)
        if input_type in _SENSITIVE_INPUT_TYPES or _SENSITIVE_FIELD_PATTERN.search(safety_text):
            raise SafeCapabilityError(
                "SENSITIVE_FIELD_BLOCKED",
                "Kimlik, doğrulama veya finansal bilgi alanına otomatik yazım "
                "güvenlik gereği engellendi; lütfen kendiniz girin.",
            )
        locator.fill(value, timeout=_ACTION_TIMEOUT_MS)
        if bool(args.get("submit", False)):
            locator.press("Enter")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8_000)
            except Exception:
                pass
        state = self._page_state(page)
        return {**state, "typed": True}

    def _extract(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        selector = str(args.get("selector", "") or "").strip()
        attribute = str(args.get("attribute", "") or "").strip()
        limit = max(1, min(int(args.get("limit", 20) or 20), _MAX_EXTRACT_ITEMS))
        if not selector:
            # Selector yoksa sayfanın okunur metni (kısaltılmış).
            body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
            text = " ".join(str(body_text or "").split())[:8000]
            return {**self._page_state(page), "textContent": text, "itemCount": 1}
        locator = page.locator(selector)
        count = min(locator.count(), limit)
        items: list[dict[str, str]] = []
        for index in range(count):
            node = locator.nth(index)
            try:
                text = " ".join(str(node.inner_text(timeout=2_000) or "").split())[:300]
            except Exception:
                text = ""
            entry = {"text": text}
            if attribute:
                try:
                    raw = node.get_attribute(attribute, timeout=2_000)
                except Exception:
                    raw = None
                value = str(raw or "")
                if attribute == "href" and value and "://" not in value:
                    value = page.evaluate("(u) => new URL(u, document.baseURI).href", value)
                entry[attribute] = value
            items.append(entry)
        return {**self._page_state(page), "items": items, "itemCount": len(items)}

    def _snapshot(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(args.get("limit", _MAX_SNAPSHOT_ELEMENTS) or _MAX_SNAPSHOT_ELEMENTS), _MAX_SNAPSHOT_ELEMENTS))
        elements = page.evaluate(
            """(limit) => {
                const out = [];
                const selectors = 'a[href], button, input, textarea, select, [role="button"], [role="tab"], [role="link"], [onclick]';
                for (const el of document.querySelectorAll(selectors)) {
                    if (out.length >= limit) break;
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 2 || rect.height < 2) continue;
                    // Form değerleri (autofill dahil) asla snapshot'a girmez;
                    // gerçek profil gözlemi server_brain'e gidebilir.
                    const isFormControl = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
                    const text = (
                        isFormControl
                            ? (el.getAttribute('aria-label') || el.getAttribute('placeholder') || '')
                            : (el.innerText || el.getAttribute('aria-label') || '')
                    ).trim().slice(0, 120);
                    if (!text && el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA') continue;
                    out.push({
                        tag: el.tagName.toLowerCase(),
                        text,
                        href: el.getAttribute('href') || '',
                        type: el.getAttribute('type') || '',
                        role: el.getAttribute('role') || '',
                        visible: rect.top >= 0 && rect.top < (window.innerHeight || 900),
                    });
                }
                return out;
            }""",
            limit,
        )
        state = self._page_state(page)
        return {**state, "elements": elements if isinstance(elements, list) else [], "elementCount": len(elements or [])}

    def _download(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        output_dir = str(args.get("outputDir", "") or args.get("output_dir", "") or "").strip()
        target_dir = Path(output_dir).expanduser() if output_dir else _DOWNLOAD_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        url = str(args.get("url", "") or "").strip()
        with page.expect_download(timeout=_NAV_TIMEOUT_MS) as download_info:
            if url:
                # İndirme başlatan doğrudan bağlantı.
                try:
                    page.goto(url, timeout=_NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                except Exception:
                    # İndirme navigation'ı iptal eder — beklenen durum.
                    pass
            else:
                self._locator(page, args).click(timeout=_ACTION_TIMEOUT_MS)
        download = download_info.value
        suggested = download.suggested_filename or f"indirme-{int(time.time())}"
        output_path = target_dir / suggested
        counter = 1
        while output_path.exists():
            output_path = target_dir / f"{output_path.stem}-{counter}{output_path.suffix}"
            counter += 1
        download.save_as(str(output_path))
        state = self._page_state(page)
        return {
            **state,
            "downloaded": True,
            "outputPath": str(output_path),
            "fileName": output_path.name,
            "sizeBytes": output_path.stat().st_size if output_path.exists() else 0,
        }


_SESSION = _SessionThread()


def browser_session_status() -> dict[str, Any]:
    """Registry hazırlık probu: Playwright kurulu mu?"""
    try:
        import playwright  # noqa: F401
    except Exception:
        return {
            "available": False,
            "lastErrorCode": "DEPENDENCY_UNAVAILABLE",
            "lastErrorMessage": "Playwright bu kurulumda hazır değil.",
        }
    return {"available": True}


def _wrap(command: str, args: dict[str, Any], text: str) -> dict[str, Any]:
    result = _SESSION.submit(command, args)
    summary = text.format(**{**result, "url": result.get("url", ""), "title": result.get("title", "")})
    return {"text": summary, "result": result}


def session_goto(url: str) -> dict[str, Any]:
    return _wrap("goto", {"url": url}, "Sayfa açıldı: {title} — {url}")


def session_click(selector: str = "", text: str = "", role: str = "") -> dict[str, Any]:
    return _wrap("click", {"selector": selector, "text": text, "role": role}, "Tıklandı; sayfa: {title}")


def session_type(value: str, selector: str = "", text: str = "", role: str = "", submit: bool = False) -> dict[str, Any]:
    return _wrap(
        "type",
        {"value": value, "selector": selector, "text": text, "role": role, "submit": submit},
        "Metin yazıldı; sayfa: {title}",
    )


def session_extract(selector: str = "", attribute: str = "", limit: int = 20) -> dict[str, Any]:
    result = _SESSION.submit("extract", {"selector": selector, "attribute": attribute, "limit": limit})
    count = int(result.get("itemCount", 0) or 0)
    return {"text": f"{count} öğe çıkarıldı ({result.get('title', '')}).", "result": result}


def session_snapshot(limit: int = _MAX_SNAPSHOT_ELEMENTS) -> dict[str, Any]:
    result = _SESSION.submit("snapshot", {"limit": limit})
    return {
        "text": f"Sayfa gözlemi: {result.get('title', '')} — {int(result.get('elementCount', 0) or 0)} etkileşimli öğe.",
        "result": result,
    }


def session_download(selector: str = "", text: str = "", url: str = "", output_dir: str = "") -> dict[str, Any]:
    result = _SESSION.submit(
        "download",
        {"selector": selector, "text": text, "url": url, "outputDir": output_dir},
    )
    return {"text": f"İndirildi: {result.get('fileName', '')} → {result.get('outputPath', '')}", "result": result}


def session_close() -> dict[str, Any]:
    result = _SESSION.submit("close", {})
    return {"text": "Tarayıcı oturumu kapatıldı.", "result": result}
