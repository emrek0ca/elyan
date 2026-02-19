import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


class DaemonManager:
    """Manages system-level background service installation."""

    def __init__(self):
        self.os = platform.system()
        self.label = "ai.elyan.gateway"
        self.project_root = Path(__file__).resolve().parent.parent

    def install(self) -> bool:
        if self.os == "Darwin":
            return self._install_macos()
        if self.os == "Linux":
            return self._install_linux()
        return False

    def _resolve_elyan_binary(self) -> str | None:
        """Resolve a reliable Elyan CLI binary path."""
        candidates = [
            self.project_root / ".venv" / "bin" / "elyan",
            Path(sys.executable).resolve().parent / "elyan",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        found = shutil.which("elyan")
        if found:
            return found
        return None

    def _program_arguments(self) -> list[str]:
        """
        Build launch command.
        Prefer direct `elyan` binary, fallback to module invocation.
        """
        elyan_bin = self._resolve_elyan_binary()
        if elyan_bin:
            return [elyan_bin, "gateway", "start"]
        return [sys.executable, "-m", "cli.main", "gateway", "start"]

    def _install_macos(self) -> bool:
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{self.label}.plist"
        logs_dir = Path.home() / ".elyan" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        args_xml = "\n".join(f"        <string>{arg}</string>" for arg in self._program_arguments())
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{self.label}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{self.project_root}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{logs_dir}/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>{logs_dir}/daemon.log</string>
</dict>
</plist>"""

        try:
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(plist_content, encoding="utf-8")

            uid = os.getuid()
            domain = f"gui/{uid}"
            service = f"{domain}/{self.label}"

            # Remove stale/previously loaded service silently.
            subprocess.run(
                ["launchctl", "bootout", domain, str(plist_path)],
                check=False,
                capture_output=True,
                text=True,
            )

            bootstrap = subprocess.run(
                ["launchctl", "bootstrap", domain, str(plist_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            if bootstrap.returncode != 0:
                err = (bootstrap.stderr or bootstrap.stdout or "").strip()
                print(f"Error installing launchd service: {err or 'bootstrap failed'}")
                return False

            subprocess.run(["launchctl", "enable", service], check=False, capture_output=True, text=True)
            subprocess.run(["launchctl", "kickstart", "-k", service], check=False, capture_output=True, text=True)

            verify = subprocess.run(
                ["launchctl", "print", service],
                check=False,
                capture_output=True,
                text=True,
            )
            if verify.returncode != 0:
                err = (verify.stderr or verify.stdout or "").strip()
                print(f"Error verifying launchd service: {err or 'launchctl print failed'}")
                return False

            return True
        except Exception as e:
            print(f"Error installing launchd service: {e}")
            return False

    def _install_linux(self) -> bool:
        # TODO: systemd support
        return False

    def uninstall(self) -> bool:
        if self.os != "Darwin":
            return False

        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{self.label}.plist"
        uid = os.getuid()
        domain = f"gui/{uid}"

        try:
            if plist_path.exists():
                subprocess.run(
                    ["launchctl", "bootout", domain, str(plist_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                plist_path.unlink()
                return True
        except Exception:
            return False
        return False


# Global instance
daemon_manager = DaemonManager()
