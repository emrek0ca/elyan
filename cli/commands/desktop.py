from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import time
from pathlib import Path


def _project_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2]


def _login_home_dir() -> Path:
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir).expanduser().resolve()
    except Exception:
        return Path.home().expanduser().resolve()


def _spawn(cmd: list[str], *, cwd: Path, detached: bool, project_root: Path) -> int:
    gateway_port = str(os.environ.get("ELYAN_PORT", "18789") or "18789")
    existing_pythonpath = str(os.environ.get("PYTHONPATH", "") or "").strip()
    project_pythonpath = str(project_root)
    pythonpath = project_pythonpath if not existing_pythonpath else f"{project_pythonpath}{os.pathsep}{existing_pythonpath}"
    login_home = _login_home_dir()
    rustup_home = str(os.environ.get("RUSTUP_HOME") or (login_home / ".rustup"))
    cargo_home = str(os.environ.get("CARGO_HOME") or (login_home / ".cargo"))
    env = {
        **os.environ,
        "ELYAN_PROJECT_DIR": str(project_root),
        "ELYAN_PORT": gateway_port,
        "VITE_ELYAN_API_BASE_URL": os.environ.get("VITE_ELYAN_API_BASE_URL", f"http://127.0.0.1:{gateway_port}"),
        "PYTHONPATH": pythonpath,
        "RUSTUP_HOME": rustup_home,
        "CARGO_HOME": cargo_home,
    }
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


def _gateway_is_online(port: int) -> bool:
    from cli.commands import gateway

    status = gateway._fetch_gateway_status(port)
    if not status.get("ok"):
        return False
    data = status.get("data", {})
    return isinstance(data, dict) and str(data.get("status") or "").strip().lower() == "online"


def _ensure_gateway_ready(project_root: Path) -> None:
    from cli.commands import gateway

    port = int(os.environ.get("ELYAN_PORT", "18789") or "18789")
    if _gateway_is_online(port):
        return

    print("⚙️  Runtime hazırlanıyor. Gateway arka planda başlatılıyor...")
    gateway.start_gateway(daemon=True, port=port)

    deadline = time.time() + 20.0
    while time.time() < deadline:
        if _gateway_is_online(port):
            print(f"✅ Runtime hazır · http://127.0.0.1:{port}")
            return
        time.sleep(0.5)

    print(f"⚠️  Runtime henüz tam hazır değil. Desktop açılacak, bağlantı arka planda tamamlanacak. Port: {port}")


def _tauri_binary_candidates(root: Path) -> list[Path]:
    binary = "elyan_desktop.exe" if os.name == "nt" else "elyan_desktop"
    desktop_root = root / "apps" / "desktop"
    src_tauri = desktop_root / "src-tauri" / "target"
    isolated_target = desktop_root / "target-workspace"
    return [
        isolated_target / "release" / binary,
        isolated_target / "debug" / binary,
        src_tauri / "release" / binary,
        src_tauri / "debug" / binary,
    ]


def open_desktop(*, detached: bool = False) -> int:
    """Launch Elyan desktop app through the canonical React/Tauri shell only."""
    root = _project_root()
    desktop_dir = root / "apps" / "desktop"
    _ensure_gateway_ready(root)

    package_json = desktop_dir / "package.json"
    if package_json.exists() and shutil.which("npm"):
        if not (desktop_dir / "node_modules").exists():
            print("⚙️  Desktop bağımlılıkları hazırlanıyor (npm install)...")
            install_code = subprocess.call(["npm", "install"], cwd=str(desktop_dir), env={**os.environ, "ELYAN_PROJECT_DIR": str(root)})
            if install_code != 0:
                print("❌  Desktop bağımlılıkları hazırlanamadı.")
                return int(install_code or 1)
        print("🖥️  Elyan Desktop (new shell) açılıyor...")
        result = _spawn(["npm", "run", "tauri:dev"], cwd=desktop_dir, detached=detached, project_root=root)
        if detached:
            print("🖥️  Elyan Desktop arka planda başlatıldı.")
        return result

    for candidate in _tauri_binary_candidates(root):
        if candidate.exists():
            print(f"🖥️  Elyan Desktop (built shell) açılıyor: {candidate}")
            result = _spawn([str(candidate)], cwd=root, detached=detached, project_root=root)
            if detached:
                print("🖥️  Elyan Desktop arka planda başlatıldı.")
            return result

    print("❌ Canonical desktop shell hazır değil. apps/desktop bağımlılıklarını veya Tauri build çıktısını kontrol et.")
    return 1
