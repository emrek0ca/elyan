"""Yerel Ayarlar penceresi — menü çubuğu/tepsideki "Ayarlar…" öğesinden açılır.

Native tkinter modalı (web GUI değil): macOS/Windows/Linux'ta Python'la gelen
Tk ile ekranda mobil uygulamayla AYNI tasarım dilinde (orman adaçayı paleti,
kart yüzeyler) küçük bir ayar penceresi açılır. pystray macOS'ta AppKit run
loop'unu ana thread'de tuttuğu için pencere AYRI SÜREÇTE çalışır
(`python -m runtime.settings_ui`) — üç platformda da thread/run-loop
çakışması yaşanmaz.

Kimlik: pencere hiçbir yerde "Python" olarak görünmez — macOS'ta bundle adı
ve Dock ikonu Elyan/logo.png yapılır; Windows/Linux'ta pencere ikonu logo'dur.

Pencere STATE dosyasını okur/yazar (state_store); servis işlemleri
(yeniden başlat / eşleşmeyi kopar) mevcut `elyan` CLI komutlarına delege
edilir — iş mantığı burada çoğaltılmaz. Değişiklikler anında kaydedilir.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOGO_PATH = _REPO_ROOT / "logo.png"
_LOCK_PATH = Path.home() / ".elyan" / "settings-ui.pid"

# Mobil uygulamanın koyu orman-adaçayı paleti (mobile_preferences.dart: elyan).
_BG = "#1C2820"  # darkBackground
_SURFACE = "#2A3A2E"  # darkSurface
_SURFACE_MUTED = "#344538"  # darkSurfaceMuted
_PRIMARY = "#86AA84"  # darkPrimary
_PRIMARY_DARK = "#688A66"
_TEXT = "#E9EDE7"
_MUTED = "#9AA896"
_DANGER = "#C96A5F"
_OUTLINE = "#3A4A3E"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def open_settings() -> None:
    """Ayar penceresini ayrı süreçte açar; zaten açıksa ikinci pencere açmaz."""
    try:
        existing = int(_LOCK_PATH.read_text().strip() or "0")
        if _pid_alive(existing):
            return
    except Exception:
        pass
    subprocess.Popen(
        [sys.executable, "-m", "runtime.settings_ui"],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# ---------------------------------------------------------------------------
# Pencere süreci


def _summary() -> dict[str, Any]:
    try:
        from runtime.daemon import runtime_status_summary

        return runtime_status_summary()
    except Exception:
        return {}


def _elyan_cli(*args: str) -> None:
    subprocess.Popen(
        [sys.executable, "-m", "cli.main", *args],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _apply_elyan_identity(root: Any) -> None:
    """Uygulama hiçbir yüzeyde "Python" görünmesin: ad Elyan, ikon logo.png.

    * macOS: bundle adı (uygulama menüsü) + Dock ikonu AppKit ile ayarlanır.
    * Windows/Linux: pencere ikonu iconphoto ile logo yapılır; Windows'ta
      ayrıca AppUserModelID atanır ki görev çubuğu gruplaması Elyan olsun.
    """
    if sys.platform == "darwin":
        try:
            from AppKit import NSApplication, NSImage
            from Foundation import NSBundle

            info = NSBundle.mainBundle().infoDictionary()
            if isinstance(info, object):
                info["CFBundleName"] = "Elyan"
            if _LOGO_PATH.exists():
                image = NSImage.alloc().initWithContentsOfFile_(str(_LOGO_PATH))
                if image is not None:
                    NSApplication.sharedApplication().setApplicationIconImage_(image)
        except Exception:
            pass
        return
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("dev.elyan.desktop")  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        import tkinter as tk

        if _LOGO_PATH.exists():
            icon = tk.PhotoImage(file=str(_LOGO_PATH))
            root.iconphoto(True, icon)
            root._elyan_icon_ref = icon  # GC koruması
    except Exception:
        pass


def _run_window() -> int:
    try:
        import setproctitle

        setproctitle.setproctitle("elyan-settings")
    except Exception:
        pass

    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import messagebox

    from runtime import state_store

    # Tek örnek kilidi
    try:
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LOCK_PATH.write_text(str(os.getpid()))
    except Exception:
        pass

    state = state_store.snapshot()
    pairing = state.get("pairing", {}) if isinstance(state.get("pairing"), dict) else {}
    privacy = state.get("privacy", {}) if isinstance(state.get("privacy"), dict) else {}

    root = tk.Tk()
    root.title("Elyan Ayarları")
    root.configure(bg=_BG)
    root.resizable(False, False)
    _apply_elyan_identity(root)
    try:  # pencereyi öne getir
        root.attributes("-topmost", True)
        root.after(400, lambda: root.attributes("-topmost", False))
    except Exception:
        pass

    base_family = "SF Pro Text" if sys.platform == "darwin" else "Segoe UI" if sys.platform.startswith("win") else "Cantarell"
    try:
        tkfont.Font(family=base_family, size=12)
    except Exception:
        base_family = "TkDefaultFont"
    font_body = (base_family, 12)
    font_label = (base_family, 11)
    font_section = (base_family, 11, "bold")
    font_title = (base_family, 16, "bold")

    outer = tk.Frame(root, bg=_BG, padx=20, pady=18)
    outer.pack(fill="both", expand=True)

    tk.Label(outer, text="Elyan", bg=_BG, fg=_TEXT, font=font_title, anchor="w").pack(fill="x")
    tk.Label(
        outer,
        text="Ayarlar — değişiklikler anında kaydedilir",
        bg=_BG,
        fg=_MUTED,
        font=font_label,
        anchor="w",
    ).pack(fill="x", pady=(0, 12))

    saved_var = tk.StringVar(value="")

    def _flash_saved(text: str = "Kaydedildi ✓") -> None:
        saved_var.set(text)
        root.after(1600, lambda: saved_var.set(""))

    def _apply(patch: dict[str, Any]) -> None:
        try:
            state_store.update_state(patch)
            _flash_saved()
        except Exception:
            _flash_saved("Kaydedilemedi!")

    def _card(title: str) -> tk.Frame:
        """Mobil ElyanPreferenceGroup görünümünde kart."""
        wrapper = tk.Frame(outer, bg=_SURFACE, padx=14, pady=12, highlightthickness=1)
        wrapper.configure(highlightbackground=_OUTLINE, highlightcolor=_OUTLINE)
        tk.Label(wrapper, text=title.upper(), bg=_SURFACE, fg=_MUTED, font=font_section, anchor="w").pack(
            fill="x", pady=(0, 8)
        )
        wrapper.pack(fill="x", pady=(0, 10))
        return wrapper

    def _row(parent: tk.Frame) -> tk.Frame:
        row = tk.Frame(parent, bg=_SURFACE)
        row.pack(fill="x", pady=2)
        return row

    def _pill(parent: tk.Frame, var: tk.StringVar) -> tk.Label:
        pill = tk.Label(
            parent,
            textvariable=var,
            bg=_SURFACE_MUTED,
            fg=_PRIMARY,
            font=font_label,
            padx=10,
            pady=1,
        )
        pill.pack(side="right")
        return pill

    def _check(parent: tk.Frame, label: str, var: tk.BooleanVar, command: Any) -> None:
        check = tk.Checkbutton(
            parent,
            text=label,
            variable=var,
            command=command,
            bg=_SURFACE,
            fg=_TEXT,
            activebackground=_SURFACE,
            activeforeground=_TEXT,
            selectcolor=_SURFACE_MUTED,
            highlightthickness=0,
            font=font_body,
            anchor="w",
        )
        check.pack(fill="x", pady=1)

    def _button(parent: tk.Frame, label: str, command: Any, *, danger: bool = False, primary: bool = False) -> tk.Button:
        bg = _PRIMARY if primary else _SURFACE_MUTED
        fg = _BG if primary else (_DANGER if danger else _TEXT)
        button = tk.Button(
            parent,
            text=label,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=_PRIMARY_DARK if primary else _OUTLINE,
            activeforeground=fg,
            relief="flat",
            font=font_label,
            padx=12,
            pady=5,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        return button

    # --- Durum -------------------------------------------------------------
    status_card = _card("Durum")
    conn_var = tk.StringVar(value="…")
    account_var = tk.StringVar(value="…")
    device_var = tk.StringVar(value="…")
    tasks_var = tk.StringVar(value="…")
    for label, var in (
        ("Bağlantı", conn_var),
        ("Hesap", account_var),
        ("Cihaz kimliği", device_var),
        ("Aktif görev", tasks_var),
    ):
        row = _row(status_card)
        tk.Label(row, text=label, bg=_SURFACE, fg=_TEXT, font=font_body, anchor="w").pack(side="left")
        _pill(row, var)

    def _refresh_status() -> None:
        summary = _summary()
        runtime = state_store.snapshot().get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        connected = bool(summary.get("websocketConnected", False))
        lifecycle = str(summary.get("lifecycleState", "") or "stopped")
        conn_var.set("● Bağlı" if connected else lifecycle)
        email = str(summary.get("email", "") or "")
        paired = bool(str(runtime.get("runtimeToken", "") or "").strip())
        account_var.set(email or ("Telefon eşleşmesi" if paired else "Bağlı değil"))
        device_id = str(runtime.get("deviceId", "") or "")
        device_var.set(device_id[:8] + "…" if device_id else "—")
        active = summary.get("activeTasks", []) or []
        tasks_var.set(str(len(active)) if active else "Yok")
        root.after(3000, _refresh_status)

    # --- Cihaz -------------------------------------------------------------
    device_card = _card("Cihaz")
    name_row = _row(device_card)
    tk.Label(name_row, text="Cihaz adı", bg=_SURFACE, fg=_TEXT, font=font_body, anchor="w").pack(side="left")
    name_var = tk.StringVar(value=str(pairing.get("deviceName", "") or ""))
    name_entry = tk.Entry(
        name_row,
        textvariable=name_var,
        width=20,
        bg=_SURFACE_MUTED,
        fg=_TEXT,
        insertbackground=_TEXT,
        relief="flat",
        font=font_body,
        highlightthickness=1,
        highlightbackground=_OUTLINE,
        highlightcolor=_PRIMARY,
    )
    name_entry.pack(side="right", ipady=3)

    def _save_name(_event: Any = None) -> None:
        value = name_var.get().strip()[:64]
        if value:
            _apply({"pairing": {"deviceName": value}})

    name_entry.bind("<FocusOut>", _save_name)
    name_entry.bind("<Return>", _save_name)

    links_var = tk.BooleanVar(value=bool(pairing.get("allowNewLinks", True)))
    _check(
        device_card,
        "Yeni eşleşmelere izin ver",
        links_var,
        lambda: _apply({"pairing": {"allowNewLinks": links_var.get()}}),
    )

    button_row = tk.Frame(device_card, bg=_SURFACE)
    button_row.pack(fill="x", pady=(8, 0))

    def _restart() -> None:
        _elyan_cli("restart")
        _flash_saved("Yeniden başlatılıyor…")

    def _unpair() -> None:
        if messagebox.askyesno(
            "Eşleşmeyi Kopar",
            "Eşleşme tamamen koparılacak; bu bilgisayar telefondan görev alamayacak. Emin misin?",
            parent=root,
        ):
            _elyan_cli("unpair")
            _flash_saved("Eşleşme koparılıyor…")

    _button(button_row, "Yeniden Başlat", _restart, primary=True).pack(side="left", padx=(0, 8))
    _button(button_row, "Eşleşmeyi Kopar…", _unpair, danger=True).pack(side="left")

    # --- Gizlilik ----------------------------------------------------------
    privacy_card = _card("Gizlilik")
    privacy_items = (
        ("localDataStaysLocal", "Yerel veri yerelde kalsın", True),
        ("analytics", "Anonim kullanım analitiği", False),
        ("redactCrashReports", "Çökme raporlarında kişisel veriyi maskele", True),
        ("autoClearHistory", "Geçmişi otomatik temizle", False),
    )
    for key, label, default in privacy_items:
        var = tk.BooleanVar(value=bool(privacy.get(key, default)))
        _check(
            privacy_card,
            label,
            var,
            lambda k=key, v=var: _apply({"privacy": {k: v.get()}}),
        )

    # --- Alt bilgi -----------------------------------------------------------
    footer = tk.Frame(outer, bg=_BG)
    footer.pack(fill="x", pady=(4, 0))
    tk.Label(footer, textvariable=saved_var, bg=_BG, fg=_PRIMARY, font=font_label).pack(side="left")
    _button(footer, "Kapat", lambda: (_cleanup(), root.destroy())).pack(side="right")

    def _cleanup() -> None:
        try:
            _LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", lambda: (_cleanup(), root.destroy()))
    _refresh_status()
    root.update_idletasks()
    root.eval("tk::PlaceWindow . center")
    # Otomatik doğrulama modu: pencereyi kurup kısa süre sonra kendini kapatır
    # (CI/smoke-test; kullanıcı akışında etkisiz).
    if os.environ.get("ELYAN_SETTINGS_UI_SELFTEST"):
        root.after(1200, lambda: (_cleanup(), root.destroy()))
    try:
        root.mainloop()
    finally:
        _cleanup()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO_ROOT))
    raise SystemExit(_run_window())
