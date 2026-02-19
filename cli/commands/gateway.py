import os
import sys
import time
import json
import urllib.request
from collections import deque
import psutil
from pathlib import Path

PID_FILE = Path.home() / ".elyan" / "gateway.pid"
LOG_FILE = Path.home() / ".elyan" / "logs" / "gateway.log"
DEFAULT_PORT = int(os.environ.get("ELYAN_PORT", 18789))


def _read_pidfile() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def _write_pidfile(pid: int) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def _clear_pidfile() -> None:
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


def _find_listener_pid(port: int) -> int | None:
    try:
        for conn in psutil.net_connections(kind="tcp"):
            laddr = getattr(conn, "laddr", None)
            if not laddr:
                continue
            if getattr(laddr, "port", None) != int(port):
                continue
            if conn.status != psutil.CONN_LISTEN:
                continue
            if conn.pid:
                return int(conn.pid)
    except Exception:
        return None
    return None


def _running_gateway_pid(port: int) -> int | None:
    pid = _read_pidfile()
    if pid and psutil.pid_exists(pid):
        return pid
    if pid and not psutil.pid_exists(pid):
        _clear_pidfile()

    listener_pid = _find_listener_pid(port)
    if listener_pid and psutil.pid_exists(listener_pid):
        return listener_pid
    return None


def _is_launchd_service_loaded(label: str = "ai.elyan.gateway") -> bool:
    try:
        import subprocess
        proc = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            check=False,
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    except Exception:
        return False

def _safe_process_info(pid: int) -> dict:
    info = {
        "pid": pid,
        "running": False,
        "memory_mb": None,
        "uptime_s": None,
    }
    try:
        if not psutil.pid_exists(pid):
            return info
        proc = psutil.Process(pid)
        info["running"] = True
        info["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 2)
        info["uptime_s"] = int(time.time() - proc.create_time())
        return info
    except Exception:
        return info


def _fetch_gateway_json(port: int, path: str) -> dict:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _fetch_gateway_status(port: int) -> dict:
    return _fetch_gateway_json(port, "/api/status")


def _fetch_gateway_channels(port: int) -> dict:
    return _fetch_gateway_json(port, "/api/channels")


def start_gateway(daemon=False, port: int | None = None):
    gateway_port = int(port or DEFAULT_PORT)
    running_pid = _running_gateway_pid(gateway_port)
    if running_pid:
        _write_pidfile(running_pid)
        print(f"⚠️  Gateway is already running (PID: {running_pid})")
        print(f"🌐  URL: http://127.0.0.1:{gateway_port}")
        return

    print("🚀  Starting Elyan Gateway...")
    
    # We are calling main.py from the root
    root_dir = Path(__file__).parent.parent.parent
    main_script = root_dir / "main.py"
    
    if daemon:
        # Launch independent process
        import subprocess
        log_file = LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)

        if _is_launchd_service_loaded():
            print("ℹ️  launchd servisi aktif görünüyor (ai.elyan.gateway).")
            print("    Manuel --daemon ile birlikte çalıştırmak port çakışmasına yol açabilir.")
            print("    Tek mod önerisi: ya `elyan service install` ya da `elyan gateway start --daemon`.")
        
        with open(log_file, "a") as log:
            env = dict(os.environ)
            env["ELYAN_PORT"] = str(gateway_port)
            proc = subprocess.Popen(
                [sys.executable, str(main_script), "--cli"],
                stdout=log,
                stderr=log,
                cwd=str(root_dir),
                env=env,
                start_new_session=True,
            )
        
        _write_pidfile(proc.pid)
        print(f"✅  Gateway started in background (PID: {proc.pid})")
        print(f"🌐  Port: {gateway_port}")
        print(f"📄  Logs: {log_file}")

        # Wait briefly for health readiness to avoid immediate "connection refused" confusion.
        ready = False
        adopted_pid: int | None = None
        for _ in range(40):  # ~20s max
            time.sleep(0.5)
            if proc.poll() is not None:
                # Process may exit if launchd/service reclaims startup. Re-check listener.
                adopted_pid = _running_gateway_pid(gateway_port)
                status = _fetch_gateway_status(gateway_port)
                if adopted_pid or status.get("ok"):
                    ready = True
                    break
                continue
            status = _fetch_gateway_status(gateway_port)
            if status.get("ok"):
                ready = True
                break

        if ready:
            if adopted_pid and adopted_pid != proc.pid:
                _write_pidfile(adopted_pid)
                print(f"ℹ️  Gateway başka bir süreç tarafından devralındı (PID: {adopted_pid}).")
            print(f"✅  Gateway is healthy at http://127.0.0.1:{gateway_port}")
        else:
            if proc.poll() is not None:
                takeover_pid = _running_gateway_pid(gateway_port)
                if takeover_pid:
                    _write_pidfile(takeover_pid)
                    print(f"ℹ️  İlk süreç çıktı fakat gateway çalışıyor (PID: {takeover_pid}).")
                    print(f"✅  Gateway is healthy at http://127.0.0.1:{gateway_port}")
                    return
                print("❌  Gateway process exited during startup. Logları kontrol edin:")
                print(f"    tail -n 120 {log_file}")
                _clear_pidfile()
            else:
                print("⚠️  Gateway henüz hazır görünmüyor (startup sürüyor olabilir).")
                print(f"    Kontrol: elyan gateway health --json --port {gateway_port}")
    else:
        # Foreground mode
        try:
            _write_pidfile(os.getpid())
            
            # Add root to path
            sys.path.insert(0, str(root_dir))
            import main as root_module
            root_main = getattr(root_module, 'main')
            prev_port = os.environ.get("ELYAN_PORT")
            os.environ["ELYAN_PORT"] = str(gateway_port)
            root_main(['--cli'])
            if prev_port is None:
                os.environ.pop("ELYAN_PORT", None)
            else:
                os.environ["ELYAN_PORT"] = prev_port
        except KeyboardInterrupt:
            print("\n🛑  Stopping...")
        finally:
            _clear_pidfile()

def stop_gateway(port: int | None = None):
    gateway_port = int(port or DEFAULT_PORT)
    targets = set()
    pid = _read_pidfile()
    if pid:
        targets.add(pid)
    listener_pid = _find_listener_pid(gateway_port)
    if listener_pid:
        targets.add(listener_pid)

    if not targets:
        print("⚠️  Gateway is not running.")
        _clear_pidfile()
        return

    stopped = 0
    for target_pid in sorted(targets):
        try:
            if not psutil.pid_exists(target_pid):
                continue
            proc = psutil.Process(target_pid)
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except psutil.TimeoutExpired:
                proc.kill()
            stopped += 1
            print(f"🛑  Stopped process {target_pid}")
        except Exception as e:
            print(f"❌  Error stopping {target_pid}: {e}")
    _clear_pidfile()
    if stopped == 0:
        print("⚠️  Durdurulacak aktif gateway süreci bulunamadı.")


def gateway_status(as_json: bool = False, port: int | None = None):
    gateway_port = int(port or DEFAULT_PORT)
    pid = _running_gateway_pid(gateway_port)
    proc_info = {"running": False, "memory_mb": None, "uptime_s": None, "pid": None}
    if pid:
        proc_info = _safe_process_info(pid)
        _write_pidfile(pid)
    else:
        _clear_pidfile()

    runtime = _fetch_gateway_status(gateway_port)
    runtime_data = runtime.get("data", {}) if runtime.get("ok") else {}
    channels_resp = _fetch_gateway_channels(gateway_port) if runtime.get("ok") else {"ok": False}
    channels_data = channels_resp.get("data", {}) if channels_resp.get("ok") else {}

    payload = {
        "running": bool(proc_info.get("running") or runtime.get("ok")),
        "pid": proc_info.get("pid") or pid,
        "port": gateway_port,
        "process": proc_info,
        "runtime": runtime_data,
        "runtime_available": bool(runtime.get("ok")),
        "runtime_error": runtime.get("error") if not runtime.get("ok") else None,
        "channels": channels_data.get("channels", []),
        "channels_available": bool(channels_resp.get("ok")),
        "channels_error": (
            channels_resp.get("error")
            if not channels_resp.get("ok")
            else None
        ) or (runtime.get("error") if not runtime.get("ok") else None),
    }

    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if payload["running"]:
        print(f"🟢  RUNNING (PID: {payload['pid'] or 'unknown'})")
    else:
        print("⚪  STOPPED")

    print(f"    Port:   {gateway_port}")
    if proc_info.get("memory_mb") is not None:
        print(f"    Memory: {proc_info['memory_mb']:.1f} MB")
    if proc_info.get("uptime_s") is not None:
        print(f"    Uptime: {proc_info['uptime_s']}s")

    if runtime.get("ok"):
        rt = runtime_data
        print(f"    CPU:    {rt.get('cpu', '—')}")
        print(f"    RAM:    {rt.get('ram', '—')} ({rt.get('ram_pct', '—')}%)")
        print(f"    Version:{rt.get('version', '—')}")
        channels = payload.get("channels", [])
        if channels:
            print("    Channels:")
            for ch in channels:
                name = ch.get("type", "?")
                status = ch.get("status", "unknown")
                health = ch.get("health", {}) or {}
                retries = health.get("retries", 0)
                failures = health.get("failures", 0)
                err = health.get("last_error")
                err_pct = ch.get("failure_rate_pct")
                line = f"      - {name:<12} {str(status):<12} retry={retries} fail={failures}"
                if isinstance(err_pct, (int, float)):
                    line += f" err%={err_pct}"
                if err:
                    line += f" err={str(err)[:60]}"
                print(line)
    else:
        print(f"    Runtime: unavailable ({runtime.get('error', 'unknown error')})")


def gateway_health(as_json: bool = False, port: int | None = None):
    gateway_port = int(port or DEFAULT_PORT)
    runtime = _fetch_gateway_status(gateway_port)
    if runtime.get("ok"):
        data = runtime.get("data", {})
        payload = {
            "healthy": data.get("status") == "online",
            "port": gateway_port,
            "status": data.get("status", "unknown"),
            "cpu_pct": data.get("cpu_pct"),
            "ram_pct": data.get("ram_pct"),
            "uptime_s": data.get("uptime_s"),
        }
    else:
        running_pid = _running_gateway_pid(gateway_port)
        payload = {
            "healthy": False,
            "port": gateway_port,
            "status": "starting" if running_pid else "unreachable",
            "error": runtime.get("error"),
            "pid": running_pid,
        }

    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if payload.get("healthy"):
        print(f"✅  HEALTHY — port {gateway_port}")
        print(f"    CPU: {payload.get('cpu_pct', '—')}%  RAM: {payload.get('ram_pct', '—')}%  Uptime: {payload.get('uptime_s', '—')}s")
    else:
        print(f"❌  UNHEALTHY — port {gateway_port}")
        if payload.get("error"):
            print(f"    Error: {payload['error']}")


def gateway_logs(tail: int = 50, level: str = "info", filter_term: str | None = None):
    if not LOG_FILE.exists():
        print(f"❌  Log dosyası bulunamadı: {LOG_FILE}")
        return

    try:
        with LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
            lines = list(deque(f, maxlen=max(1, int(tail or 50))))
    except Exception as e:
        print(f"❌  Log okunamadı: {e}")
        return

    requested_level = (level or "").strip().upper()
    if requested_level in {"", "ALL", "*"}:
        requested_level = ""

    filtered = []
    for line in lines:
        row = line.rstrip("\n")
        row_upper = row.upper()
        if requested_level and f"| {requested_level} |" not in row_upper:
            continue
        if filter_term and filter_term.lower() not in row.lower():
            continue
        filtered.append(row)

    if not filtered:
        print("ℹ️  Eşleşen log satırı bulunamadı.")
        return

    for row in filtered:
        print(row)
