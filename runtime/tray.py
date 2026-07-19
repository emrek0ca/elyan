"""
Sistem tepsisi / menü çubuğu ikonu — daemon'un tek görünür yüzü (3 platform).

GUI yok: pystray ile macOS menü çubuğunda, Windows sistem tepsisinde ve
Linux'ta (AppIndicator/GTK/X11) küçük bir ikon durur; menüde bağlantı durumu
ve aktif görevler görünür. Veri kaynağı STATE dosyasıdır (bridge relay
thread'i görevleri oraya işler) — tray hiçbir iş mantığı taşımaz, yalnız
gösterir. Menü her açılışta taze kurulur (pystray dinamik Menu üreticisi).

Akıllı yüzey: ikon dikkat gerektiren durumu rozetle anlatır (onay bekleyen
görev → amber, bağlantı yok → kızıl, toparlanıyor → gri); menüde onay
bekleyenler en üstte tek tıkla çözülür, biten son işler göreli zamanla
görünür; araç ipucu canlı özet taşır. Görev başlığı boşsa etiket özetten
türetilir — kullanıcı asla anlamsız "Görev" satırıyla baş başa kalmaz.

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

_CONNECTED_STATES = {"ready", "online", "connected"}
_RECOVERING_STATES = {"reconnecting", "degraded"}

_TASK_STATUS_LABELS = {
    "queued": "sırada",
    "pending": "sırada",
    "claimed": "hazırlanıyor",
    "planning": "planlanıyor",
    "running": "çalışıyor",
    "waiting_approval": "onay bekliyor",
    "completed": "tamamlandı",
    "failed": "başarısız",
    "canceled": "iptal",
}

_DONE_STATUSES = {"completed", "failed", "canceled"}

# Dikkat rozeti renkleri (ikonun köşesindeki nokta).
_ATTENTION_COLORS: dict[str, tuple[int, int, int, int]] = {
    "approval": (229, 166, 60, 255),  # amber — onay bekleyen görev var
    "offline": (201, 106, 95, 255),  # kızıl — bağlantı yok
    "recovering": (154, 168, 150, 255),  # gri-adaçayı — toparlanıyor
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


def _with_badge(image: Any, color: tuple[int, int, int, int]) -> Any:
    """Sağ alt köşeye durum noktası basar; nokta çevresinde tabandan delik
    açılır ki rozet her zeminde (açık/koyu menübar, renkli logo) okunsun."""
    from PIL import Image, ImageDraw

    base = image.copy()
    width, height = base.size
    # Rozet geometrisi ikon boyutuna oranlı (64px tabanda ~22px nokta).
    dot = max(10, int(min(width, height) * 0.36))
    pad = max(2, dot // 6)
    x1, y1 = width - dot, height - dot
    hole = Image.new("L", base.size, 0)
    ImageDraw.Draw(hole).ellipse((x1 - pad, y1 - pad, width + pad, height + pad), fill=255)
    alpha = base.getchannel("A")
    base.putalpha(Image.composite(Image.new("L", base.size, 0), alpha, hole))
    badge = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(badge).ellipse((x1, y1, width - 1, height - 1), fill=color)
    return Image.alpha_composite(base, badge)


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


def _load_icon_image(attention: str | None = None) -> Any:
    """Platforma göre profesyonel tepsi ikonu; `attention` verilirse köşeye
    renkli durum noktası eklenir.

    * macOS: menü çubuğu ikon dili TEK RENK gliftir. Rozet yokken NSImage
      template işaretlenir (sistem açık/koyu menübara göre kendisi boyar);
      rozet varken template kapatılır ki nokta rengi görünsün, glif rengi
      görünüme göre seçilir.
    * Windows/Linux: sistem tepsisi renkli marka ikonu bekler → logo.png
      olduğu gibi kullanılır, rozet üstüne basılır.
    """
    import sys as _sys

    from PIL import Image

    if _sys.platform == "darwin":
        color = (255, 255, 255, 255) if _macos_dark_menubar() else (20, 24, 20, 255)
        image = _glyph_image(color)
    else:
        image = None
        if _LOGO_PATH.exists():
            try:
                image = Image.open(_LOGO_PATH).convert("RGBA")
                image.thumbnail((64, 64), Image.LANCZOS)
            except Exception:
                image = None
        if image is None:
            image = _glyph_image((255, 255, 255, 255))
    if attention in _ATTENTION_COLORS:
        try:
            image = _with_badge(image, _ATTENTION_COLORS[attention])
        except Exception:
            pass
    return image


def _maybe_mark_template(icon: Any, template: bool = True) -> None:
    """macOS: NSStatusBar ikonunu template işaretle/kaldır — template modda
    sistem, açık/koyu menü çubuğuna göre glifi otomatik boyar; rozetli ikonda
    template KAPATILIR ki durum noktasının rengi ezilmesin. pystray bunu
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
            image.setTemplate_(template)
    except Exception:
        pass


def _attention_state(summary: dict[str, Any]) -> str | None:
    """Özet durumdan ikon rozetini seçer: onay > bağlantı > toparlanma."""
    active = summary.get("activeTasks", []) or []
    for task in active:
        if isinstance(task, dict) and str(task.get("status", "") or "") == "waiting_approval":
            return "approval"
    lifecycle = str(summary.get("lifecycleState", "") or "stopped")
    if lifecycle in _CONNECTED_STATES:
        return None
    if lifecycle in _RECOVERING_STATES:
        return "recovering"
    return "offline"


def _task_label(task: dict[str, Any], limit: int = 44) -> str:
    """Görev için insan-okur etiket: başlık boşsa özet, o da yoksa plan özeti.
    (Mobil dispatch başlığı çoğu zaman boş bırakır — özet asıl bilgiyi taşır.)"""
    text = str(task.get("title", "") or "").strip()
    if not text:
        text = str(task.get("summary", "") or "").strip()
    if not text:
        plan = task.get("planPreview")
        if isinstance(plan, dict):
            text = str(plan.get("summary", "") or "").strip()
    text = " ".join(text.split()) or "Görev"
    return text[: limit - 1] + "…" if len(text) > limit else text


def _rel_time(value: Any) -> str:
    """ISO zaman damgasını göreli Türkçe metne çevirir ("5 dk önce")."""
    from datetime import datetime, timezone

    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    seconds = max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())
    if seconds < 90:
        return "şimdi"
    if seconds < 3600:
        return f"{int(seconds // 60)} dk önce"
    if seconds < 86400:
        return f"{int(seconds // 3600)} sa önce"
    return f"{int(seconds // 86400)} gün önce"


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
        dot = "●" if lifecycle in _CONNECTED_STATES else ("◌" if lifecycle in _RECOVERING_STATES else "○")
        yield pystray.MenuItem(f"{dot} {label}", None, enabled=False)
        error_code = str(summary.get("lastErrorCode", "") or "").strip()
        if error_code and lifecycle not in _CONNECTED_STATES:
            yield pystray.MenuItem(f"   {error_code}", None, enabled=False)
        yield pystray.Menu.SEPARATOR

        active = [t for t in (summary.get("activeTasks", []) or []) if isinstance(t, dict)]
        waiting = [
            t
            for t in active
            if str(t.get("status", "") or "") == "waiting_approval" and str(t.get("id", "") or "").strip()
        ]
        others = [t for t in active if t not in waiting]

        if waiting:
            # Onay bekleyenler en üstte, tek tıkla çözülür — mobil kartı
            # kaçırıldıysa kullanıcı burada sıkışıp kalmaz.
            yield pystray.MenuItem(f"Onay bekliyor ({len(waiting)})", None, enabled=False)
            for task in waiting[:4]:
                yield pystray.MenuItem(
                    f"  {_task_label(task)}",
                    _approval_actions(str(task.get("id", "")).strip()),
                )
        if others:
            yield pystray.MenuItem(f"Aktif görevler ({len(others)})", None, enabled=False)
            for task in others[:6]:
                status = _TASK_STATUS_LABELS.get(str(task.get("status", "") or ""), str(task.get("status", "") or ""))
                yield pystray.MenuItem(f"  {_task_label(task)} — {status}", None, enabled=False)
        if not active:
            yield pystray.MenuItem("Aktif görev yok", None, enabled=False)

        recent_done = [
            t
            for t in (summary.get("recentTasks", []) or [])
            if isinstance(t, dict) and str(t.get("status", "") or "") in _DONE_STATUSES
        ][:3]
        if recent_done:
            yield pystray.Menu.SEPARATOR
            for task in recent_done:
                mark = "✓" if str(task.get("status", "")) == "completed" else "✕"
                when = _rel_time(task.get("completedAt") or task.get("updatedAt"))
                suffix = f" · {when}" if when else ""
                yield pystray.MenuItem(f"{mark} {_task_label(task, 36)}{suffix}", None, enabled=False)

        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Ayarlar…", _open_settings)
        yield pystray.MenuItem("Günlükleri Aç", _open_logs)
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
        # Yerel ayar penceresi ayrı süreçte açılır (runtime/settings_ui.py);
        # tepsi thread'i bloklanmaz.
        try:
            from runtime.settings_ui import open_settings

            open_settings()
        except Exception:
            pass

    def _open_logs(_icon: Any, _item: Any = None) -> None:
        # daemon.log'u sistemin varsayılan görüntüleyicisinde aç — sorun
        # anında kullanıcıyı terminale göndermeden teşhis imkânı.
        import os
        import subprocess

        try:
            from runtime.daemon import LOG_PATH

            if not LOG_PATH.exists():
                return
            if _sys.platform == "darwin":
                subprocess.Popen(["open", str(LOG_PATH)])
            elif _sys.platform.startswith("win"):
                os.startfile(str(LOG_PATH))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(LOG_PATH)])
        except Exception:
            pass

    def _quit(icon: Any, _item: Any = None) -> None:
        daemon.stop()
        icon.stop()

    initial_attention = _attention_state(_summary())
    icon = pystray.Icon(
        "elyan",
        icon=_load_icon_image(initial_attention),
        title="Elyan",
        menu=pystray.Menu(_menu_items),
    )

    def _refresh_tooltip(icon_ref: Any, summary: dict[str, Any]) -> None:
        # Canlı özet araç ipucunda (Windows'ta hover, macOS'ta erişilebilirlik).
        # Menü zaten her açılışta taze kurulur.
        lifecycle = str(summary.get("lifecycleState", "") or "stopped")
        label = _STATUS_LABELS.get(lifecycle, lifecycle)
        active = [t for t in (summary.get("activeTasks", []) or []) if isinstance(t, dict)]
        waiting = sum(1 for t in active if str(t.get("status", "") or "") == "waiting_approval")
        running = len(active) - waiting
        parts = [f"Elyan — {label}"]
        if running:
            parts.append(f"{running} görev çalışıyor")
        if waiting:
            parts.append(f"{waiting} onay bekliyor")
        icon_ref.title = " · ".join(parts)

    def _setup(icon_ref: Any) -> None:
        icon_ref.visible = True
        _maybe_mark_template(icon_ref, template=initial_attention is None)
        import threading

        def _tick() -> None:
            # İkon yalnız imza (rozet + görünüm) değişince tazelenir; araç
            # ipucu her turda güncellenir. Görev sürerken sık (2 sn), boşta
            # seyrek (6 sn) bakılır — akıllı ama israfsız.
            last_signature = (
                initial_attention,
                _macos_dark_menubar() if _sys.platform == "darwin" else None,
            )
            while icon_ref.visible and not daemon._stop.is_set():
                interval = 6.0
                try:
                    summary = _summary()
                    _refresh_tooltip(icon_ref, summary)
                    attention = _attention_state(summary)
                    appearance = _macos_dark_menubar() if _sys.platform == "darwin" else None
                    signature = (attention, appearance)
                    if signature != last_signature:
                        last_signature = signature
                        icon_ref.icon = _load_icon_image(attention)
                        _maybe_mark_template(icon_ref, template=attention is None)
                    if summary.get("activeTasks"):
                        interval = 2.0
                except Exception:
                    pass
                daemon._stop.wait(interval)
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
