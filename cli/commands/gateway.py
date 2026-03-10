import os
import sys
import time
import json
import inspect
import urllib.request
import subprocess
import urllib.parse
from collections import deque
import psutil
from pathlib import Path

PID_FILE = Path.home() / ".elyan" / "gateway.pid"
LOG_FILE = Path.home() / ".elyan" / "logs" / "gateway.log"
DEFAULT_PORT = int(os.environ.get("ELYAN_PORT", 18789))
LAUNCHD_LABEL = "ai.elyan.gateway"


def _resolve_project_root() -> Path:
    """
    Resolve Elyan project root robustly for both editable and wheel installs.
    Priority:
    1) ELYAN_PROJECT_DIR env
    2) current working directory (if it looks like project root)
    3) parent traversal from this file
    """
    env_root = os.environ.get("ELYAN_PROJECT_DIR")
    if env_root:
        p = Path(env_root).expanduser().resolve()
        if (p / "main.py").exists():
            return p

    cwd = Path.cwd().resolve()
    if (cwd / "main.py").exists() and (cwd / "cli").exists():
        return cwd

    for parent in Path(__file__).resolve().parents:
        if (parent / "main.py").exists() and (parent / "cli").exists():
            return parent

    # Last resort: current directory
    return cwd


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
    pids = _find_listener_pids(port)
    return pids[0] if pids else None


def _find_listener_pids(port: int) -> list[int]:
    pids: set[int] = set()
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
                pids.add(int(conn.pid))
    except Exception:
        pass

    # Fallback: psutil may miss listener PID on macOS in some environments.
    if not pids:
        try:
            proc = subprocess.run(
                ["lsof", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"],
                check=False,
                capture_output=True,
                text=True,
            )
            for row in (proc.stdout or "").splitlines():
                row = row.strip()
                if row.isdigit():
                    pids.add(int(row))
        except Exception:
            pass
    return sorted(pids)


def _is_port_listening(port: int) -> bool:
    return bool(_find_listener_pids(port))


def _is_elyan_like_process(pid: int) -> bool:
    try:
        if not psutil.pid_exists(pid):
            return False
        proc = psutil.Process(pid)
        cmd = " ".join(proc.cmdline()).lower()
        if not cmd:
            cmd = (proc.name() or "").lower()
        return any(token in cmd for token in ("elyan", "main.py", "cli.main", "gateway"))
    except Exception:
        return False


def _describe_process(pid: int) -> str:
    try:
        if not psutil.pid_exists(pid):
            return f"pid={pid} (not found)"
        proc = psutil.Process(pid)
        cmd = " ".join(proc.cmdline()).strip() or proc.name()
        return f"pid={pid} cmd={cmd}"
    except Exception:
        return f"pid={pid}"


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


def _launchd_service_ref(label: str = LAUNCHD_LABEL) -> str:
    return f"gui/{os.getuid()}/{label}"


def _is_launchd_service_loaded(label: str = LAUNCHD_LABEL) -> bool:
    try:
        proc = subprocess.run(
            ["launchctl", "print", _launchd_service_ref(label)],
            check=False,
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _kickstart_launchd_service(label: str = LAUNCHD_LABEL) -> tuple[bool, str | None]:
    try:
        proc = subprocess.run(
            ["launchctl", "kickstart", "-k", _launchd_service_ref(label)],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return True, None
        err = (proc.stderr or proc.stdout or "").strip() or "launchctl kickstart failed"
        return False, err
    except Exception as exc:
        return False, str(exc)


def _wait_until_gateway_ready(port: int, timeout_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _fetch_gateway_status(port)
        if status.get("ok"):
            return True
        time.sleep(0.5)
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
    
    # Resolve project root even when command is executed from installed wheel.
    root_dir = _resolve_project_root()
    main_script = root_dir / "main.py"
    if not main_script.exists():
        print("❌  main.py bulunamadı.")
        print(f"    Çalışma dizini: {root_dir}")
        print("    Çözüm: proje klasöründe çalıştırın veya ELYAN_PROJECT_DIR ayarlayın.")
        return

    run_gateway_cmd = [
        sys.executable,
        "-c",
        (
            f"import sys; sys.path.insert(0, {str(root_dir)!r}); "
            f"from main import _run_gateway; _run_gateway({gateway_port})"
        ),
    ]
    
    if daemon:
        # Launch independent process
        log_file = LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)

        if _is_launchd_service_loaded():
            print("ℹ️  launchd servisi aktif görünüyor (ai.elyan.gateway).")
            print("    Port çakışmasını önlemek için başlatma launchd üzerinden yapılacak.")

            if _wait_until_gateway_ready(gateway_port, timeout_s=2.0):
                takeover_pid = _running_gateway_pid(gateway_port)
                if takeover_pid:
                    _write_pidfile(takeover_pid)
                print(f"✅  Gateway is healthy at http://127.0.0.1:{gateway_port}")
                return

            kicked, kick_err = _kickstart_launchd_service()
            if not kicked:
                print(f"❌  launchd restart başarısız: {kick_err}")
                print("    Çözüm: `elyan service uninstall` sonrası `elyan gateway start --daemon` kullanın.")
                return

            if _wait_until_gateway_ready(gateway_port, timeout_s=20.0):
                takeover_pid = _running_gateway_pid(gateway_port)
                if takeover_pid:
                    _write_pidfile(takeover_pid)
                print(f"✅  Gateway is healthy at http://127.0.0.1:{gateway_port}")
                return

            print("❌  launchd servisi tetiklendi fakat gateway hazır olmadı.")
            print(f"    Log: tail -n 120 {log_file}")
            print("    Çözüm: `elyan service uninstall` ile servis modunu kapatıp manuel daemon kullanın.")
            return
        
        with open(log_file, "a") as log:
            env = dict(os.environ)
            env["ELYAN_PORT"] = str(gateway_port)
            proc = subprocess.Popen(
                run_gateway_cmd,
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
                # Process may exit if launchd/service reclaims startup. Re-check health.
                adopted_pid = _running_gateway_pid(gateway_port)
                status = _fetch_gateway_status(gateway_port)
                if status.get("ok"):
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
                    if _is_elyan_like_process(takeover_pid):
                        _write_pidfile(takeover_pid)
                        print(f"ℹ️  İlk süreç çıktı fakat gateway çalışıyor (PID: {takeover_pid}).")
                        print(f"✅  Gateway is healthy at http://127.0.0.1:{gateway_port}")
                        return
                    print("❌  Port başka bir süreç tarafından kullanılıyor:")
                    print(f"    {_describe_process(takeover_pid)}")
                    print(f"    Kontrol: lsof -nP -iTCP:{gateway_port} -sTCP:LISTEN")
                    _clear_pidfile()
                    return
                # Retry once automatically for transient startup races.
                print("⚠️  İlk başlangıç başarısız, otomatik olarak bir kez daha deneniyor...")
                time.sleep(1.0)
                with open(log_file, "a") as retry_log:
                    retry_proc = subprocess.Popen(
                        run_gateway_cmd,
                        stdout=retry_log,
                        stderr=retry_log,
                        cwd=str(root_dir),
                        env=env,
                        start_new_session=True,
                    )

                _write_pidfile(retry_proc.pid)
                print(f"✅  Retry process başlatıldı (PID: {retry_proc.pid})")

                retry_ready = False
                for _ in range(30):  # ~15s max
                    time.sleep(0.5)
                    retry_status = _fetch_gateway_status(gateway_port)
                    if retry_status.get("ok"):
                        retry_ready = True
                        break
                    if retry_proc.poll() is not None:
                        continue

                if retry_ready:
                    print(f"✅  Gateway is healthy at http://127.0.0.1:{gateway_port}")
                    return

                retry_takeover = _running_gateway_pid(gateway_port)
                if retry_takeover and _is_elyan_like_process(retry_takeover):
                    _write_pidfile(retry_takeover)
                    print(f"ℹ️  Retry süreci çıktı fakat gateway çalışıyor (PID: {retry_takeover}).")
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
            run_gateway = getattr(root_module, "_run_gateway", None)
            if callable(run_gateway):
                run_gateway(gateway_port)
                return

            root_main = getattr(root_module, "_cli_main", None) or getattr(root_module, "main", None)
            if not callable(root_main):
                print("❌  Geçerli gateway giriş fonksiyonu bulunamadı (_run_gateway/main/_cli_main).")
                return
            prev_port = os.environ.get("ELYAN_PORT")
            os.environ["ELYAN_PORT"] = str(gateway_port)
            sig = inspect.signature(root_main)
            params = list(sig.parameters.values())
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            if has_varargs or len(params) >= 1:
                root_main(["--cli"])
            else:
                root_main()
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
    if _is_launchd_service_loaded():
        print("ℹ️  launchd servisi aktif. KeepAlive nedeniyle süreç otomatik yeniden başlayabilir.")
        print("    Tam durdurma için: `elyan service uninstall`")

    targets = set()
    pid = _read_pidfile()
    if pid:
        targets.add(pid)
    for listener_pid in _find_listener_pids(gateway_port):
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


def restart_gateway(daemon=False, port: int | None = None):
    gateway_port = int(port or DEFAULT_PORT)
    if daemon and _is_launchd_service_loaded():
        print("🔄  launchd servisi üzerinden yeniden başlatılıyor...")
        kicked, kick_err = _kickstart_launchd_service()
        if not kicked:
            print(f"❌  launchd restart başarısız: {kick_err}")
            print("    Çözüm: `elyan service uninstall` sonrası manuel daemon restart deneyin.")
            return

        if _wait_until_gateway_ready(gateway_port, timeout_s=20.0):
            takeover_pid = _running_gateway_pid(gateway_port)
            if takeover_pid:
                _write_pidfile(takeover_pid)
            print(f"✅  Gateway is healthy at http://127.0.0.1:{gateway_port}")
        else:
            print("❌  launchd restart sonrası gateway hazır olmadı.")
            print(f"    Log: tail -n 120 {LOG_FILE}")
        return

    stop_gateway(port=gateway_port)
    deadline = time.time() + 12
    while time.time() < deadline:
        if not _is_port_listening(gateway_port):
            break
        time.sleep(0.25)
    start_gateway(daemon=daemon, port=gateway_port)


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


def gateway_reload(port: int | None = None, as_json: bool = False):
    gateway_port = int(port or DEFAULT_PORT)
    url = f"http://127.0.0.1:{gateway_port}/api/channels/sync"
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        payload = {"ok": False, "message": f"Gateway reload failed: {exc}", "port": gateway_port}
        if as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"❌  {payload['message']}")
        return

    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if data.get("ok"):
        print(f"✅  {data.get('message', 'Gateway runtime reload tamamlandı.')}")
    else:
        print(f"❌  {data.get('message', 'Gateway runtime reload başarısız.')}")


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
