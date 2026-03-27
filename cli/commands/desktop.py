from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2]


def _spawn(cmd: list[str], *, cwd: Path, detached: bool, project_root: Path) -> int:
    env = {**os.environ, "ELYAN_PROJECT_DIR": str(project_root)}
    if detached:
        kwargs: dict[str, object] = {
            "cwd": str(cwd),
            "env": env,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True
        subprocess.Popen(cmd, **kwargs)  # noqa: S603
        return 0
    return subprocess.call(cmd, cwd=str(cwd), env=env)


def _tauri_binary_candidates(root: Path) -> list[Path]:
    binary = "elyan_desktop.exe" if os.name == "nt" else "elyan_desktop"
    src_tauri = root / "apps" / "desktop" / "src-tauri" / "target"
    return [
        src_tauri / "release" / binary,
        src_tauri / "debug" / binary,
    ]


def open_desktop(*, detached: bool = False) -> int:
    """Launch Elyan desktop app. Prefer Tauri/TS shell, fallback to legacy PyQt."""
    root = _project_root()
    desktop_dir = root / "apps" / "desktop"

    for candidate in _tauri_binary_candidates(root):
        if candidate.exists():
            print(f"🖥️  Elyan Desktop (Tauri) açılıyor: {candidate}")
            result = _spawn([str(candidate)], cwd=root, detached=detached, project_root=root)
            if detached:
                print("🖥️  Elyan Desktop arka planda başlatıldı.")
            return result

    package_json = desktop_dir / "package.json"
    if package_json.exists() and shutil.which("npm"):
        print("🖥️  Elyan Desktop (Tauri dev shell) açılıyor...")
        result = _spawn(["npm", "run", "tauri:dev"], cwd=desktop_dir, detached=detached, project_root=root)
        if detached:
            print("🖥️  Elyan Desktop arka planda başlatıldı.")
        return result

    app_script = root / "ui" / "clean_main_app.py"
    if app_script.exists():
        print("ℹ️  Tauri shell hazır değil; legacy PyQt desktop açılıyor.")
        result = _spawn([sys.executable, str(app_script)], cwd=root, detached=detached, project_root=root)
        if detached:
            print("🖥️  Elyan Desktop arka planda başlatıldı.")
        return result

    print("❌ Desktop uygulama bulunamadı: Tauri shell veya legacy PyQt mevcut değil.")
    return 1
