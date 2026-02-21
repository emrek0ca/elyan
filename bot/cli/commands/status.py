import os
import json
import time
from pathlib import Path
from types import SimpleNamespace


def run(args):
    pid_file = Path.home() / ".elyan" / "gateway.pid"
    config_file = Path.home() / ".elyan" / "elyan.json"

    print("=" * 50)
    print("  ELYAN STATUS")
    print("=" * 50)

    # Gateway status
    gateway_running = False
    gateway_pid = None
    if pid_file.exists():
        try:
            gateway_pid = int(pid_file.read_text().strip())
            # Check if PID is actually running
            os.kill(gateway_pid, 0)
            gateway_running = True
        except (ValueError, ProcessLookupError, PermissionError):
            gateway_running = False

    print(f"\n  Gateway:     {'ACTIVE (PID: ' + str(gateway_pid) + ')' if gateway_running else 'INACTIVE'}")

    # Config
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except Exception:
            pass

    # Provider info
    models = config.get("models", {})
    default = models.get("default", {})
    provider = default.get("provider", "?")
    model = default.get("model", "?")
    print(f"  AI Provider: {provider}")
    print(f"  Model:       {model}")

    # Channels
    channels = config.get("channels", [])
    if isinstance(channels, list):
        active = [c for c in channels if c.get("enabled", False)]
        print(f"  Kanallar:    {len(active)}/{len(channels)} aktif")
    elif isinstance(channels, dict):
        active = sum(1 for c in channels.values() if isinstance(c, dict) and c.get("enabled", False))
        print(f"  Kanallar:    {active}/{len(channels)} aktif")

    # Cron
    cron_jobs = config.get("cron", [])
    if isinstance(cron_jobs, list):
        active_jobs = sum(1 for j in cron_jobs if j.get("enabled", True))
        print(f"  Cron:        {active_jobs}/{len(cron_jobs)} aktif gorev")

    # Skills
    skills_dir = Path.home() / ".elyan" / "skills"
    skill_count = sum(1 for d in skills_dir.iterdir() if d.is_dir()) if skills_dir.exists() else 0
    print(f"  Skills:      {skill_count} harici skill")

    if getattr(args, "deep", False):
        print(f"\n  --- DEEP STATUS ---")

        # Memory files
        memory_dir = Path.home() / ".elyan" / "memory"
        if memory_dir.exists():
            md_files = list(memory_dir.glob("*.md"))
            total_size = sum(f.stat().st_size for f in md_files)
            print(f"  Bellek:      {len(md_files)} dosya, {total_size // 1024}KB")

        # Projects
        projects_dir = Path.home() / ".elyan" / "projects"
        if projects_dir.exists():
            project_count = sum(1 for d in projects_dir.iterdir() if d.is_dir())
            print(f"  Projeler:    {project_count} proje")

        # Logs
        logs_dir = Path.home() / ".elyan" / "logs"
        if logs_dir.exists():
            log_files = list(logs_dir.rglob("*"))
            log_size = sum(f.stat().st_size for f in log_files if f.is_file())
            print(f"  Log boyutu:  {log_size // 1024 // 1024}MB")

        # Process info
        if gateway_running and gateway_pid:
            try:
                import psutil
                proc = psutil.Process(gateway_pid)
                mem_info = proc.memory_info()
                print(f"  Proses RAM:  {mem_info.rss // 1024 // 1024}MB")
                print(f"  Proses CPU:  {proc.cpu_percent(interval=0.5)}%")
                create_time = proc.create_time()
                running_for = time.time() - create_time
                hours = int(running_for // 3600)
                mins = int((running_for % 3600) // 60)
                print(f"  Calisma:     {hours}h {mins}m")
            except Exception:
                pass

    print("\n" + "=" * 50)


def run_status(args=None):
    """Backward-compatible entrypoint used by older CLI callers."""
    run(args or SimpleNamespace(deep=False, json=False))
