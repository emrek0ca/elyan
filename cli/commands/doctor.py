"""
Doctor command — System diagnostics with port conflict detection.
FIX BUG-FUNC-009: Port availability check added.
"""
import sys
import shutil
import socket
import platform
import asyncio
import os
import subprocess
from pathlib import Path
from config.elyan_config import elyan_config
from core.dependencies import get_dependency_runtime
from core.dependencies import get_system_dependency_runtime
from security.keychain import keychain
from core.version import APP_VERSION

GATEWAY_PORT = int(os.environ.get("ELYAN_PORT", 18789))
VISION_MODEL_NAME = os.environ.get("ELYAN_VISION_MODEL", "llava:7b")


def _channel_requirements(channel_type: str) -> list[str]:
    return {
        "telegram": ["token"],
        "discord": ["token"],
        "slack": ["bot_token", "app_token"],
        "whatsapp": [],
        "signal": ["phone_number"],
        "matrix": ["homeserver", "user_id", "access_token"],
        "google_chat": ["mode"],
        "teams": ["app_id", "app_password"],
        "imessage": ["server_url", "password"],
        "webchat": [],
    }.get(channel_type, [])


def _is_secret_ref(value) -> bool:
    return isinstance(value, str) and value.startswith("$") and len(value) > 1


def _check_port(port: int, host: str = "127.0.0.1") -> tuple[bool, str]:
    """Check if port is available. Returns (available, detail)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.bind((host, port))
            return True, "Available"
        except OSError:
            # Try to connect to see if it's Elyan
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                s2.settimeout(1)
                try:
                    s2.connect((host, port))
                    return False, "In use (Elyan may already be running)"
                except Exception:
                    return False, "In use by another process"


def run_doctor(fix=False):
    print("\n" + "="*55)
    print(f"🩺  ELYAN SYSTEM DIAGNOSTICS (v{APP_VERSION})")
    print("="*55 + "\n")

    issues = 0

    # 1. Platform & Environment
    print(f"🖥️  Platform: {platform.system()} {platform.release()}")
    print(f"🐍  Python:   {sys.version.split()[0]} ({sys.executable})")

    # 2. Virtual Environment Check
    in_venv = hasattr(sys, 'real_prefix') or (sys.base_prefix != sys.prefix)
    if in_venv:
        print("✅  Virtual Environment: ACTIVE")
    else:
        print("⚠️   Virtual Environment: INACTIVE (Recommended)")
        issues += 1

    # 3. Port Check (BUG-FUNC-009)
    print(f"\n🌐  Network Check:")
    port_ok, port_detail = _check_port(GATEWAY_PORT)
    if port_ok:
        print(f"  - Port {GATEWAY_PORT:<6}: ✅ Available")
    else:
        print(f"  - Port {GATEWAY_PORT:<6}: ❌ {port_detail}")
        print(f"    → Set ELYAN_PORT=<other_port> or stop the conflicting process")
        issues += 1

    # 4. Core Directories
    print("\n📁  Directory Check:")
    dirs = {
        "Base":    Path.home() / ".elyan",
        "Memory":  Path.home() / ".elyan" / "memory",
        "Logs":    Path.home() / ".elyan" / "logs",
        "Skills":  Path.home() / ".elyan" / "skills",
        "Sandbox": Path.home() / ".elyan" / "sandbox",
        "Cron":    Path.home() / ".elyan" / "cron_jobs.json",
        "Subscription": Path.home() / ".elyan" / "subscriptions.json",
        "Usage":   Path.home() / ".elyan" / "user_usage.json",
    }

    for name, path in dirs.items():
        if path.exists():
            print(f"  ✅  {name:<10}: OK")
        else:
            print(f"  ❌  {name:<10}: MISSING")
            issues += 1
            if fix and path.suffix == "":  # Only mkdir for directories
                path.mkdir(parents=True, exist_ok=True)
                print(f"      → Fixed: Created {path}")
                issues -= 1

    # 5. Critical Dependencies
    deps = {
        "pydantic":  {"install_spec": "pydantic", "purpose": "Core"},
        "aiohttp":   {"install_spec": "aiohttp", "purpose": "Core"},
        "telegram":  {"install_spec": "python-telegram-bot", "purpose": "Telegram channel"},
        "PyQt6":     {"install_spec": "PyQt6", "purpose": "Desktop UI"},
        "json5":     {"install_spec": "json5", "purpose": "Config parsing"},
        "apscheduler": {"install_spec": "apscheduler", "purpose": "Cron scheduler"},
    }
    print("\n📦  Dependency Check:")
    dep_runtime = get_dependency_runtime()
    for dep, purpose in deps.items():
        install_spec = str(purpose.get("install_spec") or dep)
        label = str(purpose.get("purpose") or dep)
        try:
            record = dep_runtime.inspect_dependency(dep, install_spec=install_spec, source="pypi", trust_level="trusted")
            if record.get("available", False):
                print(f"  ✅  {dep:<15}: OK ({label})")
            else:
                print(f"  ❌  {dep:<15}: MISSING ({label})")
                issues += 1
                if fix:
                    install_record = dep_runtime.ensure_module(dep, install_spec=install_spec, source="pypi", trust_level="trusted", skill_name="doctor", tool_name=dep, allow_install=True)
                    if install_record.status in {"installed", "ready"} or dep_runtime.inspect_dependency(dep, install_spec=install_spec).get("available", False):
                        print(f"      → Fixed: {install_spec} [{install_record.status}]")
                        issues -= 1
                    else:
                        print(f"      → Fix failed: {install_record.reason or install_record.status}")
        except Exception:
            try:
                __import__(dep)
                print(f"  ✅  {dep:<15}: OK ({label})")
            except ImportError:
                print(f"  ❌  {dep:<15}: MISSING ({label})")
                issues += 1

    # 6. External Tools
    tools = {
        "docker":  "Sandbox isolation",
        "ollama":  "Local AI models",
        "ffmpeg":  "Audio/video processing",
        "tesseract": "OCR engine",
        "xdg-open": "Desktop file opener",
        "xclip": "Clipboard helper",
        "xsel": "Clipboard helper",
        "scrot": "Screenshot helper",
        "gnome-screenshot": "Screenshot helper",
        "xdotool": "X11 automation",
        "xprop": "X11 window metadata",
        "wmctrl": "X11 window control",
        "cliclick": "macOS mouse helper",
    }
    system_runtime = get_system_dependency_runtime()
    print("\n🛠️  External Tool Check:")
    for t, purpose in tools.items():
        if shutil.which(t):
            print(f"  ✅  {t:<12}: FOUND ({purpose})")
        else:
            if fix and t != "docker":
                install_record = system_runtime.ensure_binary(t, allow_install=True, skill_name="doctor", tool_name=t)
                if install_record.status in {"ready", "installed"} or shutil.which(t):
                    print(f"  ✅  {t:<12}: FIXED ({purpose})")
                    continue
                print(f"  ⚠️   {t:<12}: {install_record.status.upper()} (Optional — {purpose})")
                print(f"    → {install_record.reason or system_runtime.get_install_hint(t)}")
            else:
                print(f"  ⚠️   {t:<12}: NOT FOUND (Optional — {purpose})")

    print("\n👁️  Vision Check:")
    if not shutil.which("ollama"):
        ollama_record = system_runtime.ensure_binary("ollama", allow_install=fix, skill_name="doctor", tool_name="ollama")
        if ollama_record.status in {"ready", "installed"} or shutil.which("ollama"):
            print(f"  ✅  Vision runtime: Ollama ready")
        else:
            print(f"  ⚠️   Vision model : Ollama missing (expected local model {VISION_MODEL_NAME})")
            issues += 1
    else:
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            listing = f"{result.stdout}\n{result.stderr}"
            if result.returncode == 0 and VISION_MODEL_NAME in listing:
                print(f"  ✅  Vision model : {VISION_MODEL_NAME} installed")
            else:
                print(f"  ❌  Vision model : {VISION_MODEL_NAME} missing")
                print(f"    → Run: elyan models ollama pull {VISION_MODEL_NAME}")
                issues += 1
        except Exception as e:
            print(f"  ⚠️   Vision model : check failed ({e})")
            issues += 1

    # 6.5 Secret storage health (BUG-SEC-005)
    print("\n🔐  Secret Storage Check:")
    kc_ok = keychain.is_available()
    print(f"  - Keychain      : {'✅ Available' if kc_ok else '⚠️ Not available'}")
    env_audit = keychain.audit_env_plaintext(Path(".env"))
    plaintext_count = len(env_audit.get("findings", []))
    if plaintext_count == 0:
        print("  - .env secrets  : ✅ No plaintext secrets detected")
    else:
        print(f"  - .env secrets  : ⚠️ {plaintext_count} plaintext secret(s) detected")
        print("    → Run: elyan security keychain --fix --clear-env")
        issues += 1
    cfg_path = Path.home() / ".elyan" / "elyan.json"
    cfg_audit = keychain.audit_config_plaintext(cfg_path)
    cfg_plaintext = len(cfg_audit.get("findings", []))
    if cfg_plaintext == 0:
        print("  - config tokens : ✅ No plaintext channel tokens")
    else:
        print(f"  - config tokens : ⚠️ {cfg_plaintext} plaintext token(s) detected")
        print("    → Run: elyan security keychain --fix --clear-env")
        issues += 1

    # 7. Config Check
    print("\n⚙️  Config Check:")
    try:
        provider = elyan_config.get("models.default.provider", None)
        if provider:
            print(f"  ✅  AI Provider:  {provider}")
        else:
            print("  ⚠️   AI Provider:  Not configured")
            issues += 1

        channels = elyan_config.get("channels", [])
        print(f"  ✅  Channels:     {len(channels)} configured")
    except Exception as e:
        print(f"  ❌  Config error: {e}")
        issues += 1

    # 7.5 Dependency Runtime
    print("\n🧰  Dependency Runtime:")
    try:
        dep_snapshot = dep_runtime.snapshot()
        print(f"  - Mode       : {dep_snapshot.get('mode', 'managed_venv')}")
        print(f"  - Venv       : {dep_snapshot.get('managed_venv', '')}")
        print(f"  - Installer  : {dep_snapshot.get('installer', '')}")
        print(f"  - State file : {dep_snapshot.get('state_path', '')}")
        counts = dep_snapshot.get("status_counts", {}) or {}
        print(f"  - Installing : {counts.get('installing', 0)}")
        print(f"  - Installed  : {counts.get('installed', 0)}")
        print(f"  - Ready      : {counts.get('ready', 0)}")
        print(f"  - Blocked    : {counts.get('blocked', 0)}")
        print(f"  - Failed     : {counts.get('failed', 0)}")
    except Exception as e:
        print(f"  ⚠️   Dependency runtime snapshot failed: {e}")

    # 8. Channel resilience checks
    print("\n📡  Channel Resilience Check:")
    reconnect_base_default = 2.0
    reconnect_max_default = 60.0
    enabled_count = 0
    for ch in channels if isinstance(channels, list) else []:
        if not isinstance(ch, dict):
            continue
        ctype = ch.get("type", "?")
        if not ch.get("enabled", True):
            print(f"  - {ctype:<12} ⏸️ disabled")
            continue
        enabled_count += 1
        requirements = _channel_requirements(ctype)
        if ctype == "whatsapp":
            wa_mode = str(ch.get("mode", "bridge") or "bridge").strip().lower()
            if wa_mode == "cloud":
                requirements = ["phone_number_id", "access_token", "verify_token"]
            else:
                requirements = ["bridge_url", "bridge_token"]

        missing = []
        for key in requirements:
            value = ch.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(key)
            elif _is_secret_ref(value):
                resolved = elyan_config._resolve_secret_ref(value)  # noqa: SLF001 (intentional internal use)
                if resolved == value:
                    missing.append(f"{key}(unresolved)")

        if ctype == "whatsapp":
            wa_mode = str(ch.get("mode", "bridge") or "bridge").strip().lower()
            if wa_mode != "cloud":
                # Legacy compatibility: old config may still store whatsapp token under "token".
                legacy_token = ch.get("token")
                if isinstance(legacy_token, str) and legacy_token.strip():
                    missing = [m for m in missing if m != "bridge_token"]
                if "bridge_url" in missing and ch.get("bridge_port"):
                    missing = [m for m in missing if m != "bridge_url"]
        if missing:
            print(f"  ❌  {ctype:<12} missing auth/config: {', '.join(missing)}")
            issues += 1
        else:
            print(f"  ✅  {ctype:<12} auth/config present")

        rbase = float(ch.get("reconnect_base_sec", reconnect_base_default))
        rmax = float(ch.get("reconnect_max_sec", reconnect_max_default))
        if rbase <= 0 or rmax < rbase:
            print(f"     ⚠️ reconnect config unusual (base={rbase}, max={rmax})")
            issues += 1

    if enabled_count == 0:
        print("  ⚠️  No enabled channels. Elyan iletişim kuramaz.")
        issues += 1

    # Summary
    print("\n" + "-"*55)
    if issues == 0:
        print("✨  SYSTEM HEALTHY — Elyan is ready.")
    else:
        print(f"⚠️   {issues} issue(s) found.")
        if not fix:
            print("👉  Run 'elyan doctor --fix' to auto-fix where possible.")
    print("="*55 + "\n")
    return issues
