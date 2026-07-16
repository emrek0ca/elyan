"""Yerel Ayarlar penceresi — menü çubuğundaki "Ayarlar…" öğesinden açılır.

Native tkinter modalı (web GUI değil): macOS/Windows/Linux'ta Python'la gelen
Tk ile ekranda küçük bir ayar penceresi açılır. pystray macOS'ta AppKit run
loop'unu ana thread'de tuttuğu için pencere AYRI SÜREÇTE çalışır
(`python -m runtime.settings_ui`) — üç platformda da thread/run-loop
çakışması yaşanmaz.

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
_LOCK_PATH = Path.home() / ".elyan" / "settings-ui.pid"


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


def _run_window() -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

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
    providers = state.get("providers", {}) if isinstance(state.get("providers"), dict) else {}
    ollama = providers.get("ollama", {}) if isinstance(providers.get("ollama"), dict) else {}

    root = tk.Tk()
    root.title("Elyan Ayarları")
    root.resizable(False, False)
    try:  # pencereyi öne getir
        root.attributes("-topmost", True)
        root.after(400, lambda: root.attributes("-topmost", False))
    except Exception:
        pass

    style = ttk.Style(root)
    if sys.platform == "darwin":
        style.theme_use("aqua")

    outer = ttk.Frame(root, padding=16)
    outer.grid(sticky="nsew")

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

    def _section(title: str) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(outer, text=title, padding=(12, 8))
        frame.pack(fill="x", pady=(0, 10))
        return frame

    # --- Durum -------------------------------------------------------------
    status_frame = _section("Durum")
    conn_var = tk.StringVar(value="…")
    account_var = tk.StringVar(value="…")
    device_var = tk.StringVar(value="…")
    tasks_var = tk.StringVar(value="…")
    for row, (label, var) in enumerate(
        (
            ("Bağlantı", conn_var),
            ("Hesap", account_var),
            ("Cihaz kimliği", device_var),
            ("Aktif görev", tasks_var),
        )
    ):
        ttk.Label(status_frame, text=label).grid(row=row, column=0, sticky="w", pady=1)
        ttk.Label(status_frame, textvariable=var, foreground="#557a53").grid(
            row=row, column=1, sticky="e", pady=1
        )
    status_frame.columnconfigure(0, weight=1)
    status_frame.columnconfigure(1, weight=1)

    def _refresh_status() -> None:
        summary = _summary()
        runtime = state_store.snapshot().get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        connected = bool(summary.get("websocketConnected", False))
        lifecycle = str(summary.get("lifecycleState", "") or "stopped")
        conn_var.set("Bağlı ●" if connected else lifecycle)
        email = str(summary.get("email", "") or "")
        paired = bool(str(runtime.get("runtimeToken", "") or "").strip())
        account_var.set(email or ("QR eşleşmesi" if paired else "Bağlı değil"))
        device_id = str(runtime.get("deviceId", "") or "")
        device_var.set(device_id[:8] + "…" if device_id else "—")
        active = summary.get("activeTasks", []) or []
        tasks_var.set(str(len(active)) if active else "Yok")
        root.after(3000, _refresh_status)

    # --- Cihaz -------------------------------------------------------------
    device_frame = _section("Cihaz")
    ttk.Label(device_frame, text="Cihaz adı").grid(row=0, column=0, sticky="w")
    name_var = tk.StringVar(value=str(pairing.get("deviceName", "") or ""))
    name_entry = ttk.Entry(device_frame, textvariable=name_var, width=24)
    name_entry.grid(row=0, column=1, sticky="e", pady=2)

    def _save_name(_event: Any = None) -> None:
        value = name_var.get().strip()[:64]
        if value:
            _apply({"pairing": {"deviceName": value}})

    name_entry.bind("<FocusOut>", _save_name)
    name_entry.bind("<Return>", _save_name)

    links_var = tk.BooleanVar(value=bool(pairing.get("allowNewLinks", True)))
    ttk.Checkbutton(
        device_frame,
        text="Yeni eşleşmelere izin ver",
        variable=links_var,
        command=lambda: _apply({"pairing": {"allowNewLinks": links_var.get()}}),
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=2)

    button_row = ttk.Frame(device_frame)
    button_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _restart() -> None:
        _elyan_cli("restart")
        _flash_saved("Daemon yeniden başlatılıyor…")

    def _unpair() -> None:
        if messagebox.askyesno(
            "Eşleşmeyi Kopar",
            "Eşleşme tamamen koparılacak; bu bilgisayar telefondan görev alamayacak. Emin misin?",
            parent=root,
        ):
            _elyan_cli("unpair")
            _flash_saved("Eşleşme koparılıyor…")

    ttk.Button(button_row, text="Daemon'u Yeniden Başlat", command=_restart).pack(
        side="left", padx=(0, 8)
    )
    ttk.Button(button_row, text="Eşleşmeyi Kopar…", command=_unpair).pack(side="left")
    device_frame.columnconfigure(0, weight=1)

    # --- Gizlilik ----------------------------------------------------------
    privacy_frame = _section("Gizlilik")
    privacy_items = (
        ("localDataStaysLocal", "Yerel veri yerelde kalsın", True),
        ("analytics", "Anonim kullanım analitiği", False),
        ("redactCrashReports", "Çökme raporlarında kişisel veriyi maskele", True),
        ("autoClearHistory", "Geçmişi otomatik temizle", False),
    )
    for row, (key, label, default) in enumerate(privacy_items):
        var = tk.BooleanVar(value=bool(privacy.get(key, default)))
        ttk.Checkbutton(
            privacy_frame,
            text=label,
            variable=var,
            command=lambda k=key, v=var: _apply({"privacy": {k: v.get()}}),
        ).grid(row=row, column=0, sticky="w", pady=1)

    # --- Yerel model ---------------------------------------------------------
    model_frame = _section("Yerel Model")
    ttk.Label(model_frame, text="Çalışma zamanı").grid(row=0, column=0, sticky="w")
    runtime_var = tk.StringVar(value=str(providers.get("defaultLocalRuntime", "") or "ollama"))
    runtime_box = ttk.Combobox(
        model_frame,
        textvariable=runtime_var,
        values=("ollama", "lmstudio", "llamacpp"),
        state="readonly",
        width=12,
    )
    runtime_box.grid(row=0, column=1, sticky="e", pady=2)
    runtime_box.bind(
        "<<ComboboxSelected>>",
        lambda _e: _apply({"providers": {"defaultLocalRuntime": runtime_var.get()}}),
    )

    ttk.Label(model_frame, text="Ollama adresi").grid(row=1, column=0, sticky="w")
    url_var = tk.StringVar(value=str(ollama.get("baseUrl", "") or "http://127.0.0.1:11434"))
    url_entry = ttk.Entry(model_frame, textvariable=url_var, width=24)
    url_entry.grid(row=1, column=1, sticky="e", pady=2)

    def _save_url(_event: Any = None) -> None:
        value = url_var.get().strip().rstrip("/")
        if value.startswith(("http://", "https://")):
            _apply({"providers": {"ollama": {"baseUrl": value}}})

    url_entry.bind("<FocusOut>", _save_url)
    url_entry.bind("<Return>", _save_url)

    ttk.Label(model_frame, text="Varsayılan model").grid(row=2, column=0, sticky="w")
    model_var = tk.StringVar(value=str(ollama.get("defaultModel", "") or ""))
    model_entry = ttk.Entry(model_frame, textvariable=model_var, width=24)
    model_entry.grid(row=2, column=1, sticky="e", pady=2)

    def _save_model(_event: Any = None) -> None:
        value = model_var.get().strip()[:120]
        if value:
            _apply({"providers": {"ollama": {"defaultModel": value}}})

    model_entry.bind("<FocusOut>", _save_model)
    model_entry.bind("<Return>", _save_model)

    cloud_var = tk.BooleanVar(value=bool(providers.get("fallbackToCloud", True)))
    ttk.Checkbutton(
        model_frame,
        text="Gerekirse buluta düş",
        variable=cloud_var,
        command=lambda: _apply({"providers": {"fallbackToCloud": cloud_var.get()}}),
    ).grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
    model_frame.columnconfigure(0, weight=1)

    # --- Alt bilgi -----------------------------------------------------------
    footer = ttk.Frame(outer)
    footer.pack(fill="x")
    ttk.Label(footer, textvariable=saved_var, foreground="#557a53").pack(side="left")
    ttk.Button(footer, text="Kapat", command=root.destroy).pack(side="right")

    def _cleanup() -> None:
        try:
            _LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", lambda: (_cleanup(), root.destroy()))
    _refresh_status()
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
