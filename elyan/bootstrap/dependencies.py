from __future__ import annotations

import json
import os
import platform
import shutil
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class DependencyManager:
    def __init__(
        self,
        workspace: str | Path | None = None,
        *,
        headless: bool = False,
        open_dashboard: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.system = platform.system().lower()
        self.home = Path.home()
        self.workspace = Path(workspace or Path.cwd()).expanduser().resolve()
        self.headless = bool(headless)
        self.open_dashboard_flag = bool(open_dashboard)
        self.dry_run = bool(dry_run or _truthy(os.environ.get("ELYAN_BOOTSTRAP_DRY_RUN")))
        self.runtime_dir = self.home / ".elyan"
        self.logs_dir = self.runtime_dir / "logs"
        self.cursor_dir = self.workspace / ".cursor"
        if not self.dry_run:
            self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _run(
        self,
        cmd: list[str] | str,
        *,
        check: bool = False,
        shell: bool = False,
        timeout: float | None = None,
        cwd: str | Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if self.dry_run:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        try:
            return subprocess.run(
                cmd,
                check=check,
                shell=shell,
                timeout=timeout,
                cwd=str(cwd) if cwd is not None else None,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            return subprocess.CompletedProcess(cmd, 127, "", str(exc))

    def _popen_background(self, cmd: list[str], log_path: Path, cwd: str | Path | None = None) -> subprocess.Popen[str]:
        if self.dry_run:
            raise RuntimeError("dry-run")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("a", encoding="utf-8")
        kwargs: dict[str, Any] = {
            "cwd": str(cwd) if cwd is not None else None,
            "stdout": handle,
            "stderr": handle,
            "text": True,
        }
        if self.system == "windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(cmd, **kwargs)  # type: ignore[arg-type]
        finally:
            handle.close()
        return process

    def _http_ready(self, url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                return int(getattr(response, "status", 200) or 200) < 400
        except Exception:
            return False

    def _wait_for_http(self, url: str, timeout_s: float = 30.0) -> bool:
        deadline = time.time() + max(1.0, timeout_s)
        while time.time() < deadline:
            if self._http_ready(url):
                return True
            time.sleep(1.0)
        return False

    def _node_ready(self) -> bool:
        if not shutil.which("node") or not shutil.which("npx"):
            return False
        try:
            completed = self._run(["node", "--version"], timeout=3.0)
            version = str(completed.stdout or "").strip().lstrip("v")
            major = int(version.split(".", 1)[0]) if version else 0
            return major >= 18
        except Exception:
            return False

    def _ensure_node(self) -> dict[str, Any]:
        if self._node_ready():
            return {"ok": True, "installed": True, "message": "Node.js hazır."}

        if self.dry_run:
            return {"ok": False, "installed": False, "message": "Node.js kurulumu atlandı (dry-run)."}

        if self.system == "darwin" and shutil.which("brew"):
            self._run(["brew", "install", "node"], check=False)
        elif self.system == "linux" and shutil.which("apt-get"):
            prefix = ["sudo"] if shutil.which("sudo") else []
            self._run(prefix + ["apt-get", "update"], check=False)
            self._run(prefix + ["apt-get", "install", "-y", "nodejs", "npm"], check=False)
        elif self.system == "windows" and shutil.which("winget"):
            self._run(["winget", "install", "--id", "OpenJS.NodeJS.LTS", "-e"], check=False)
        else:
            return {
                "ok": False,
                "installed": False,
                "message": "Node.js gerekli. MCP için manuel kurulum gerekiyor.",
            }

        ready = self._node_ready()
        return {
            "ok": ready,
            "installed": ready,
            "message": "Node.js kuruldu." if ready else "Node.js kurulumu tamamlanmadı.",
        }

    def ensure_docker(self) -> dict[str, Any]:
        if shutil.which("docker") and self._run(["docker", "info"], timeout=8.0).returncode == 0:
            return {"ok": True, "installed": True, "running": True, "message": "Docker hazır."}

        if self.dry_run:
            return {"ok": False, "installed": bool(shutil.which("docker")), "running": False, "message": "Docker kontrol edildi (dry-run)."}

        if not shutil.which("docker"):
            if self.system == "darwin" and shutil.which("brew"):
                self._run(["brew", "install", "--cask", "docker"], check=False)
                self._run(["open", "-a", "Docker"], check=False)
            elif self.system == "linux" and shutil.which("apt-get"):
                prefix = ["sudo"] if shutil.which("sudo") else []
                self._run(prefix + ["apt-get", "update"], check=False)
                self._run(prefix + ["apt-get", "install", "-y", "docker.io"], check=False)
            elif self.system == "windows" and shutil.which("winget"):
                self._run(["winget", "install", "--id", "Docker.DockerDesktop", "-e"], check=False)
            else:
                return {
                    "ok": False,
                    "installed": False,
                    "running": False,
                    "message": "Docker Desktop yok. Manuel kurulum gerekli: https://www.docker.com/products/docker-desktop/",
                }

        if self.system == "darwin" and shutil.which("open"):
            self._run(["open", "-a", "Docker"], check=False)
        elif self.system == "linux" and shutil.which("systemctl"):
            prefix = ["sudo"] if shutil.which("sudo") else []
            self._run(prefix + ["systemctl", "start", "docker"], check=False)

        ready = bool(shutil.which("docker")) and self._run(["docker", "info"], timeout=10.0).returncode == 0
        return {
            "ok": ready,
            "installed": True,
            "running": ready,
            "message": "Docker hazır." if ready else "Docker yüklendi ama daemon erişilemedi.",
        }

    def _cursor_mcp_path(self) -> Path:
        return self.cursor_dir / "mcp.json"

    def _claude_config_path(self) -> Path:
        if self.system == "darwin":
            return self.home / "Library/Application Support/Claude/claude_desktop_config.json"
        if self.system == "windows":
            appdata = Path(os.environ.get("APPDATA", str(self.home / "AppData/Roaming")))
            return appdata / "Claude" / "claude_desktop_config.json"
        return self.home / ".config" / "Claude" / "claude_desktop_config.json"

    def _merge_mcp_config(self, path: Path) -> dict[str, Any]:
        payload = _read_json(path)
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
        servers["screenpipe"] = {"command": "npx", "args": ["-y", "screenpipe-mcp"]}
        payload["mcpServers"] = servers
        if not self.dry_run:
            _write_json(path, payload)
        return {"path": str(path), "ok": True}

    def ensure_screenpipe_mcp(self) -> dict[str, Any]:
        node_state = self._ensure_node()
        if self.dry_run:
            return {
                "ok": False,
                "message": "Screenpipe MCP config atlandı (dry-run).",
                "node": node_state,
                "configs": [],
            }

        configs = [self._merge_mcp_config(self._cursor_mcp_path()), self._merge_mcp_config(self._claude_config_path())]

        if shutil.which("claude"):
            self._run(
                [
                    "claude",
                    "mcp",
                    "add",
                    "screenpipe",
                    "--transport",
                    "stdio",
                    "--scope",
                    "user",
                    "--",
                    "npx",
                    "-y",
                    "screenpipe-mcp",
                ],
                check=False,
            )

        return {
            "ok": True,
            "message": "Screenpipe MCP yapılandırıldı.",
            "node": node_state,
            "configs": configs,
            "command": "npx -y screenpipe-mcp",
        }

    def ensure_screenpipe(self) -> dict[str, Any]:
        if self._http_ready("http://localhost:3030/health"):
            mcp_state = self.ensure_screenpipe_mcp()
            return {
                "ok": True,
                "installed": True,
                "running": True,
                "mcp": mcp_state,
                "message": "Screenpipe çalışıyor.",
            }

        node_state = self._ensure_node()
        installed = False
        started = False

        if self.dry_run:
            return {
                "ok": False,
                "installed": False,
                "running": False,
                "node": node_state,
                "message": "Screenpipe kurulumu atlandı (dry-run).",
            }

        if self.system in {"darwin", "linux"} and shutil.which("curl") and shutil.which("sh") and not shutil.which("screenpipe"):
            self._run(["/bin/sh", "-lc", "curl -fsSL https://get.screenpi.pe/cli | sh"], check=False)
            installed = True
        elif self.system == "windows" and shutil.which("powershell") and not shutil.which("screenpipe"):
            self._run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "iwr get.screenpi.pe/cli.ps1 | iex"], check=False)
            installed = True
        else:
            installed = bool(shutil.which("screenpipe"))

        screenpipe_cmd = shutil.which("screenpipe")
        if screenpipe_cmd:
            log_path = self.logs_dir / "screenpipe.log"
            try:
                self._popen_background([screenpipe_cmd], log_path, cwd=self.workspace)
                started = self._wait_for_http("http://localhost:3030/health", timeout_s=45.0)
            except Exception:
                started = False
        elif shutil.which("npx"):
            log_path = self.logs_dir / "screenpipe.log"
            try:
                self._popen_background(["npx", "screenpipe@latest", "record"], log_path, cwd=self.workspace)
                started = self._wait_for_http("http://localhost:3030/health", timeout_s=45.0)
            except Exception:
                started = False

        mcp_state = self.ensure_screenpipe_mcp()
        ready = started or self._http_ready("http://localhost:3030/health")
        return {
            "ok": ready,
            "installed": installed or bool(screenpipe_cmd),
            "running": ready,
            "node": node_state,
            "mcp": mcp_state,
            "message": "Screenpipe hazır." if ready else "Screenpipe başlatılamadı.",
        }

    def ensure_ollama(self) -> dict[str, Any]:
        if self.dry_run:
            return {"ok": False, "installed": False, "running": False, "message": "Ollama kurulumu atlandı (dry-run)."}

        ready = self._http_ready("http://localhost:11434/api/tags")

        if not ready and not shutil.which("ollama"):
            if self.system in {"darwin", "linux"} and shutil.which("curl") and shutil.which("sh"):
                self._run(["/bin/sh", "-lc", "curl -fsSL https://ollama.com/install.sh | sh"], check=False)
            elif self.system == "windows":
                return {
                    "ok": False,
                    "installed": False,
                    "running": False,
                    "message": "Ollama Windows kurulumu manuel gerekir: https://ollama.com/download/windows",
                }

        if not ready and shutil.which("ollama"):
            log_path = self.logs_dir / "ollama.log"
            try:
                self._popen_background([shutil.which("ollama") or "ollama", "serve"], log_path, cwd=self.workspace)
                ready = self._wait_for_http("http://localhost:11434/api/tags", timeout_s=25.0)
            except Exception:
                pass

        pulls = []
        for model in ("qwen2.5vl:7b", "llama3.2"):
            if not shutil.which("ollama"):
                pulls.append({"model": model, "ok": False, "message": "ollama binary missing"})
                continue
            completed = self._run(["ollama", "pull", model], timeout=None, check=False)
            pulls.append(
                {
                    "model": model,
                    "ok": completed.returncode == 0,
                    "stdout": str(completed.stdout or "").strip(),
                    "stderr": str(completed.stderr or "").strip(),
                }
                )

        ready = ready or self._http_ready("http://localhost:11434/api/tags")
        return {
            "ok": ready,
            "installed": bool(shutil.which("ollama")),
            "running": ready,
            "pulls": pulls,
            "message": "Ollama hazır." if ready else "Ollama başlatılamadı.",
        }

    def install_realtime_actuator_service(self) -> dict[str, Any]:
        if self.dry_run:
            return {"ok": False, "message": "RealTimeActuator servisi atlandı (dry-run)."}

        command = [sys.executable, "-m", "elyan.actuator"]
        log_path = self.logs_dir / "actuator.log"
        if self.system == "darwin":
            return self._install_launchd_service(command, log_path)
        if self.system == "linux":
            return self._install_systemd_service(command)
        return {
            "ok": False,
            "message": "RealTimeActuator servisi bu platformda otomatik kurulmadı.",
        }

    def _install_launchd_service(self, command: list[str], log_path: Path) -> dict[str, Any]:
        plist_path = self.home / "Library" / "LaunchAgents" / "com.elyan.actuator.plist"
        args_xml = "\n".join(f"        <string>{arg}</string>" for arg in command)
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.elyan.actuator</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{self.workspace}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ELYAN_PROJECT_DIR</key>
        <string>{self.workspace}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(plist_content, encoding="utf-8")

        uid = os.getuid()
        domain = f"gui/{uid}"
        service = f"{domain}/com.elyan.actuator"
        self._run(["launchctl", "bootout", domain, str(plist_path)], check=False)
        bootstrap = self._run(["launchctl", "bootstrap", domain, str(plist_path)], check=False)
        if bootstrap.returncode != 0:
            return {"ok": False, "message": "launchd bootstrap failed", "stderr": bootstrap.stderr}
        self._run(["launchctl", "enable", service], check=False)
        self._run(["launchctl", "kickstart", "-k", service], check=False)
        verify = self._run(["launchctl", "print", service], check=False)
        return {
            "ok": verify.returncode == 0,
            "message": "launchd servisi kuruldu." if verify.returncode == 0 else "launchd doğrulaması başarısız.",
            "plist": str(plist_path),
            "service": service,
            "stderr": verify.stderr,
        }

    def _install_systemd_service(self, command: list[str]) -> dict[str, Any]:
        unit_path = self.home / ".config" / "systemd" / "user" / "elyan-actuator.service"
        unit_content = f"""[Unit]
Description=Elyan RealTimeActuator
After=network.target

[Service]
Type=simple
WorkingDirectory="{self.workspace}"
Environment="ELYAN_PROJECT_DIR={self.workspace}"
ExecStart={' '.join(shlex.quote(part) for part in command)}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(unit_content, encoding="utf-8")
        if not shutil.which("systemctl"):
            return {"ok": False, "message": "systemctl bulunamadı.", "unit": str(unit_path)}

        self._run(["systemctl", "--user", "daemon-reload"], check=False)
        self._run(["systemctl", "--user", "enable", "--now", "elyan-actuator.service"], check=False)
        active = self._run(["systemctl", "--user", "is-active", "--quiet", "elyan-actuator.service"], check=False)
        return {
            "ok": active.returncode == 0,
            "message": "systemd servisi kuruldu." if active.returncode == 0 else "systemd servisi etkinleşmedi.",
            "unit": str(unit_path),
        }

    def enable_initial_skills(self) -> dict[str, Any]:
        if self.dry_run:
            return {
                "ok": False,
                "message": "Skill enable adımı atlandı (dry-run).",
                "skills": ["browser", "desktop", "calendar"],
            }

        from core.skills.manager import skill_manager
        from core.skills.registry import skill_registry

        rows = []
        for name in ("browser", "desktop", "calendar"):
            ok, msg, info = skill_manager.set_enabled(name, True)
            rows.append({"name": name, "ok": ok, "message": msg, "enabled": bool((info or {}).get("enabled", ok))})
        try:
            skill_registry.refresh()
        except Exception:
            pass
        return {
            "ok": all(row["ok"] for row in rows),
            "message": "İlk skill'ler etkinleştirildi.",
            "skills": rows,
        }

    def open_dashboard(self) -> dict[str, Any]:
        if self.dry_run or self.headless or not self.open_dashboard_flag:
            return {"ok": False, "message": "Dashboard açılmadı."}
        try:
            from cli.commands.dashboard import open_dashboard as _open_dashboard

            _open_dashboard(no_browser=False)
            return {"ok": True, "message": "Dashboard açıldı."}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def bootstrap_all(self) -> dict[str, Any]:
        steps = {
            "docker": self.ensure_docker(),
            "screenpipe": self.ensure_screenpipe(),
            "ollama": self.ensure_ollama(),
            "realtime_actuator": self.install_realtime_actuator_service(),
            "skills": self.enable_initial_skills(),
        }
        steps["dashboard"] = self.open_dashboard()
        return steps
