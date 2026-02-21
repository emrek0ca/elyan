import psutil
import shutil
import platform
import time
from pathlib import Path
from types import SimpleNamespace


def run(args):
    print("=" * 50)
    print("  ELYAN SYSTEM HEALTH")
    print("=" * 50)

    # System
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    boot = psutil.boot_time()
    uptime_s = time.time() - boot
    uptime_h = int(uptime_s // 3600)
    uptime_m = int((uptime_s % 3600) // 60)

    print(f"\n  Platform:  {platform.system()} {platform.release()}")
    print(f"  Python:    {platform.python_version()}")
    print(f"  Uptime:    {uptime_h}h {uptime_m}m")

    print(f"\n  CPU:       {cpu}%", end="")
    if cpu > 80:
        print("  [YUKSEK]")
    elif cpu > 50:
        print("  [ORTA]")
    else:
        print("  [NORMAL]")

    print(f"  RAM:       {ram.percent}% ({ram.used // 1024 // 1024}MB / {ram.total // 1024 // 1024}MB)", end="")
    if ram.percent > 85:
        print("  [KRITIK]")
    else:
        print("  [NORMAL]")

    print(f"  Disk:      {disk.used // 1024 // 1024 // 1024}GB / {disk.total // 1024 // 1024 // 1024}GB ({int(disk.used / disk.total * 100)}%)")

    # Elyan specific
    elyan_dir = Path.home() / ".elyan"
    config_file = elyan_dir / "elyan.json"
    pid_file = elyan_dir / "gateway.pid"
    memory_dir = elyan_dir / "memory"
    skills_dir = elyan_dir / "skills"
    logs_dir = elyan_dir / "logs"

    print(f"\n  Config:    {'OK' if config_file.exists() else 'EKSIK'}")
    print(f"  Gateway:   {'ACTIVE' if pid_file.exists() else 'INACTIVE'}")
    print(f"  Memory:    {sum(1 for _ in memory_dir.glob('*.md')) if memory_dir.exists() else 0} dosya")
    print(f"  Skills:    {sum(1 for d in skills_dir.iterdir() if d.is_dir()) if skills_dir.exists() else 0} skill")

    # Log size
    if logs_dir.exists():
        log_size = sum(f.stat().st_size for f in logs_dir.rglob("*") if f.is_file())
        print(f"  Logs:      {log_size // 1024 // 1024}MB")

    # LLM check
    print("\n  LLM Provider Check:")
    import os
    providers = [
        ("Groq", "GROQ_API_KEY"),
        ("Gemini", "GOOGLE_API_KEY"),
        ("OpenAI", "OPENAI_API_KEY"),
    ]
    for name, env_key in providers:
        key = os.getenv(env_key, "")
        status = "YAPILANDIRILDI" if key else "YOK"
        print(f"    {name:12s} {status}")

    # Ollama
    try:
        import subprocess
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            models = [l.split()[0] for l in result.stdout.strip().splitlines()[1:] if l.strip()]
            print(f"    {'Ollama':12s} AKTIF ({len(models)} model)")
        else:
            print(f"    {'Ollama':12s} KAPALII")
    except Exception:
        print(f"    {'Ollama':12s} KURULU DEGIL")

    print("\n" + "=" * 50)


def run_health():
    """Backward-compatible entrypoint used by older CLI callers."""
    run(SimpleNamespace())
