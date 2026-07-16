"""
Sistem tepsisi / menü çubuğu ikonu — daemon'un tek görünür yüzü (3 platform).

GUI yok: pystray ile macOS menü çubuğunda, Windows sistem tepsisinde ve
Linux'ta (AppIndicator/GTK/X11) küçük bir ikon durur; menüde bağlantı durumu
ve aktif görevler görünür. Veri kaynağı STATE dosyasıdır (bridge relay
thread'i görevleri oraya işler) — tray hiçbir iş mantığı taşımaz, yalnız
gösterir. Menü her açılışta taze kurulur (pystray dinamik Menu üreticisi).

pystray macOS'ta ana thread ister (AppKit run loop); daemon bunu bilerek
çağırır (runtime/daemon.py: bekçi döngüsü yan thread'e alınır).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - yalnız tip denetimi
    from runtime.daemon import ElyanDaemon

_STATUS_LABELS = {
    "ready": "Bağlı",
    "online": "Bağlı",
    "connected": "Bağlı",
    "reconnecting": "Yeniden bağlanıyor…",
    "offline": "Çevrimdışı",
    "stopped": "Durduruldu",
    "degraded": "Kısıtlı",
}

_TASK_STATUS_LABELS = {
    "queued": "sırada",
    "planning": "planlanıyor",
    "running": "çalışıyor",
    "waiting_approval": "onay bekliyor",
    "completed": "tamamlandı",
    "failed": "başarısız",
    "canceled": "iptal",
}


_LOGO_PATH = Path(__file__).resolve().parent.parent / "logo.png"


def _glyph_image(color: tuple[int, int, int, int]) -> Any:
    """Logo alfa kanalından tek renk glif üretir; logo yoksa E rozeti çizer."""
    from PIL import Image, ImageDraw

    if _LOGO_PATH.exists():
        try:
            image = Image.open(_LOGO_PATH).convert("RGBA")
            image.thumbnail((64, 64), Image.LANCZOS)
            alpha = image.getchannel("A")
            solid = Image.new("RGBA", image.size, color)
            solid.putalpha(alpha)
            return solid
        except Exception:
            pass
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), outline=color, width=5)
    draw.text((22, 14), "E", fill=color)
    return image


def _macos_dark_menubar() -> bool:
    """macOS görünümü koyu mu? (Koyu menü çubuğu → beyaz glif.)"""
    import subprocess

    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return "dark" in (result.stdout or "").strip().lower()
    except Exception:
        return True


def _load_icon_image() -> Any:
    """Platforma göre profesyonel tepsi ikonu.

    * macOS: menü çubuğu ikon dili TEK RENK gliftir. Template modu pystray'de
      doğrudan yoksa görünüme göre renk seçilir (koyu menübar → beyaz, açık →
      siyah); `_maybe_mark_template` NSImage'ı template olarak işaretlemeyi
      dener — başarılıysa macOS rengi kendisi uyarlarlar.
    * Windows/Linux: sistem tepsisi renkli marka ikonu bekler → logo.png
      olduğu gibi kullanılır.
    """
    import sys as _sys

    from PIL import Image

    if _sys.platform == "darwin":
        color = (255, 255, 255, 255) if _macos_dark_menubar() else (20, 24, 20, 255)
        return _glyph_image(color)
    if _LOGO_PATH.exists():
        try:
            image = Image.open(_LOGO_PATH).convert("RGBA")
            image.thumbnail((64, 64), Image.LANCZOS)
            return image
        except Exception:
            pass
    return _glyph_image((255, 255, 255, 255))


def _maybe_mark_template(icon: Any) -> None:
    """macOS: NSStatusBar ikonunu template olarak işaretle — sistem, açık/koyu
    menü çubuğuna ve vurgu rengine göre glifi otomatik boyar. pystray bunu
    doğrudan sunmadığından iç API'ye kibarca dokunulur; her sürümde çalışmasa
    da güvenlidir (başarısızsa görünüm-tabanlı renk zaten doğru)."""
    import sys as _sys

    if _sys.platform != "darwin":
        return
    try:
        status_item = getattr(icon, "_status_item", None)
        if status_item is None:
            return
        button = status_item.button()
        image = button.image()
        if image is not None:
            image.setTemplate_(True)
    except Exception:
        pass


def run_tray(daemon: "ElyanDaemon") -> bool:
    """Tepsi ikonunu ana thread'te çalıştırır. pystray kurulamazsa / görüntü
    sunucusu yoksa (başsız Linux) False döner — çağıran saf arka plan
    döngüsüne düşer."""
    try:
        import pystray
    except Exception:
        return False

    import sys as _sys

    if _sys.platform == "darwin":
        # Arka plan ajanı: Dock'ta ve Cmd-Tab'da GÖRÜNME — yalnız menü çubuğu.
        # (NSApplicationActivationPolicyAccessory; süreç adının "Python"
        # görünmemesi için bundle adı da Elyan yapılır.)
        try:
            from AppKit import NSApplication
            from Foundation import NSBundle

            info = NSBundle.mainBundle().infoDictionary()
            if isinstance(info, object):
                info["CFBundleName"] = "Elyan"
            NSApplication.sharedApplication().setActivationPolicy_(1)
        except Exception:
            pass

    from runtime.daemon import runtime_status_summary

    def _summary() -> dict[str, Any]:
        try:
            return runtime_status_summary()
        except Exception:
            return {}

    def _resolve_approval(task_id: str, approved: bool) -> None:
        """Onay kararını backend'e bildirir; backend ws task.approval mesajıyla
        runner'ı sürdürür/iptal eder. Tepsi thread'ini bloklamamak için ayrı
        thread'de koşar."""
        import threading

        def _run() -> None:
            try:
                daemon.bridge.backend_task_approval(task_id, approved)
            except Exception:
                pass

        threading.Thread(
            target=_run,
            name=f"elyan-tray-approval-{task_id[:8]}",
            daemon=True,
        ).start()

    def _approval_actions(task_id: str) -> Any:
        return pystray.Menu(
            pystray.MenuItem(
                "Onayla ve Sürdür",
                lambda *_a, tid=task_id: _resolve_approval(tid, True),
            ),
            pystray.MenuItem(
                "Reddet ve İptal Et",
                lambda *_a, tid=task_id: _resolve_approval(tid, False),
            ),
        )

    def _menu_items() -> Any:
        summary = _summary()
        lifecycle = str(summary.get("lifecycleState", "") or "stopped")
        label = _STATUS_LABELS.get(lifecycle, lifecycle)
        email = str(summary.get("email", "") or "")
        status_line = f"Durum: {label}" + (f" · {email}" if email else "")
        active = summary.get("activeTasks", []) or []

        yield pystray.MenuItem(status_line, None, enabled=False)
        yield pystray.Menu.SEPARATOR
        if active:
            yield pystray.MenuItem(f"Aktif görevler ({len(active)})", None, enabled=False)
            for task in active[:8]:
                title = str(task.get("title", "") or "Görev")[:48]
                raw_status = str(task.get("status", "") or "")
                status = _TASK_STATUS_LABELS.get(raw_status, raw_status)
                task_id = str(task.get("id", "") or "").strip()
                if raw_status == "waiting_approval" and task_id:
                    # Onay bekleyen görev tepsiden çözülebilir — mobil kartı
                    # kaçırıldıysa kullanıcı burada sıkışıp kalmaz.
                    yield pystray.MenuItem(
                        f"  {title} — {status}",
                        _approval_actions(task_id),
                    )
                else:
                    yield pystray.MenuItem(f"  {title} — {status}", None, enabled=False)
        else:
            yield pystray.MenuItem("Aktif görev yok", None, enabled=False)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Ayarlar…", _open_settings)
        yield pystray.MenuItem("Yeniden Başlat", _restart)
        yield pystray.MenuItem("Elyan'ı Durdur", _quit)

    def _restart(_icon: Any, _item: Any = None) -> None:
        # Ayrık süreçte `elyan restart`: bu daemon düzgün kapanır, yenisi başlar.
        import subprocess
        import sys as _sys

        try:
            subprocess.Popen(
                [_sys.executable, "-m", "cli.main", "restart"],
                cwd=str(Path(__file__).resolve().parent.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            pass

    def _open_settings(_icon: Any, _item: Any = None) -> None:
        # Yerel ayar paneli (127.0.0.1, token korumalı) tarayıcıda açılır;
        # tepsi thread'ini bloklamamak için tembel sunucu zaten daemon thread.
        try:
            from runtime.settings_ui import open_settings

            open_settings()
        except Exception:
            pass

    def _quit(icon: Any, _item: Any = None) -> None:
        daemon.stop()
        icon.stop()

    icon = pystray.Icon(
        "elyan",
        icon=_load_icon_image(),
        title="Elyan",
        menu=pystray.Menu(_menu_items),
    )

    def _refresh_tooltip(icon_ref: Any) -> None:
        # Görev sayısını araç ipucuna yansıt (Windows'ta hover, macOS'ta
        # erişilebilirlik). Menü zaten her açılışta taze kurulur.
        summary = _summary()
        active = summary.get("activeTasks", []) or []
        icon_ref.title = "Elyan" if not active else f"Elyan — {len(active)} aktif görev"

    def _setup(icon_ref: Any) -> None:
        icon_ref.visible = True
        _maybe_mark_template(icon_ref)
        import sys as _sys
        import threading

        # Template işaretlenemediyse macOS'ta açık/koyu geçişini elle izle.
        appearance_dark = _macos_dark_menubar() if _sys.platform == "darwin" else None

        def _tick() -> None:
            nonlocal appearance_dark
            while icon_ref.visible and not daemon._stop.is_set():
                try:
                    _refresh_tooltip(icon_ref)
                    if _sys.platform == "darwin":
                        now_dark = _macos_dark_menubar()
                        if now_dark != appearance_dark:
                            appearance_dark = now_dark
                            icon_ref.icon = _load_icon_image()
                            _maybe_mark_template(icon_ref)
                except Exception:
                    pass
                daemon._stop.wait(5)
            if daemon._stop.is_set() and icon_ref.visible:
                try:
                    icon_ref.stop()
                except Exception:
                    pass

        threading.Thread(target=_tick, name="elyan-tray-tick", daemon=True).start()

    try:
        icon.run(setup=_setup)
    except Exception:
        # Başsız oturum (SSH / display yok) veya tepsi arka ucu kurulamadı.
        return False
    return True
