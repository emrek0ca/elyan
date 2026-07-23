"""Install a bundled Elyan payload and launch the existing CLI.

The downloadable desktop packages carry a portable CPython distribution,
Elyan's Python sources, and all release dependencies. This bootstrap copies
that immutable payload into the current user's data directory, creates a
convenience command, and hands control to ``python -m cli``. It never needs a
system Python or Node.js installation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


def user_runtime_root(
    *,
    platform_name: str | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    platform_name = platform_name or sys.platform
    home = home or Path.home()
    environ = environ or os.environ
    if platform_name == "darwin":
        return home / "Library" / "Application Support" / "Elyan" / "runtime"
    if platform_name == "win32":
        local_app_data = environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
        return base / "Elyan" / "runtime"
    xdg_data_home = environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else home / ".local" / "share"
    return base / "elyan" / "runtime"


def payload_version(payload_root: Path) -> str:
    package_json = payload_root / "app" / "package.json"
    try:
        value = json.loads(package_json.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("Elyan paket surumu okunamadi.") from exc
    version = str(value or "").strip()
    if not version or any(char not in "0123456789.-" for char in version):
        raise RuntimeError("Elyan paket surumu gecersiz.")
    return version


def find_portable_python(payload_root: Path, *, platform_name: str | None = None) -> Path:
    platform_name = platform_name or sys.platform
    python_root = payload_root / "python"
    if platform_name == "win32":
        candidates = sorted(python_root.glob("cpython-*/python.exe"))
    else:
        candidates = sorted(python_root.glob("cpython-*/bin/python3"))
        if not candidates:
            candidates = sorted(python_root.glob("cpython-*/bin/python3.*"))
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise RuntimeError("Paketlenmis Python calistiricisi bulunamadi.")
    return executable


def install_payload(payload_root: Path, destination_root: Path) -> tuple[Path, bool]:
    """Atomically copy one version of the immutable payload into user space."""
    payload_root = payload_root.resolve()
    version = payload_version(payload_root)
    destination_root = destination_root.expanduser().resolve()
    destination = destination_root / version
    marker = destination / ".elyan-payload.json"
    try:
        current = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        current = {}
    if current.get("version") == version and (destination / "app" / "cli" / "main.py").is_file():
        find_portable_python(destination)
        return destination, False

    destination_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{version}-", dir=str(destination_root))
    )
    try:
        shutil.copytree(payload_root / "app", temporary / "app", symlinks=True)
        shutil.copytree(payload_root / "python", temporary / "python", symlinks=True)
        (temporary / ".elyan-payload.json").write_text(
            json.dumps({"contract": "elyan.portable-runtime.v1", "version": version}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        find_portable_python(temporary)
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination, True


def write_cli_launcher(
    installed_root: Path,
    python_executable: Path,
    *,
    platform_name: str | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    platform_name = platform_name or sys.platform
    home = home or Path.home()
    environ = environ or os.environ
    app_root = installed_root / "app"
    if platform_name == "win32":
        local_app_data = environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
        launcher = base / "Elyan" / "bin" / "elyan.cmd"
        _replace_launcher(
            launcher,
            "@echo off\r\n"
            f"set \"PYTHONPATH={app_root}\"\r\n"
            f"\"{python_executable}\" -m cli %*\r\n",
        )
        return launcher

    launcher = home / ".local" / "bin" / "elyan"
    _replace_launcher(
        launcher,
        "#!/bin/sh\n"
        f"export PYTHONPATH={_shell_quote(str(app_root))}\n"
        f"exec {_shell_quote(str(python_executable))} -m cli \"$@\"\n",
        executable=True,
    )
    return launcher


def _replace_launcher(path: Path, content: str, *, executable: bool = False) -> None:
    """Replace the launcher entry itself without following an existing symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        if executable:
            temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def launch_cli(installed_root: Path, cli_args: Sequence[str]) -> int:
    python_executable = find_portable_python(installed_root)
    app_root = installed_root / "app"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(app_root)
    environment["ELYAN_INSTALL_ROOT"] = str(installed_root)
    environment["ELYAN_INSTALLER_MANAGES_SERVICE"] = "1"
    result = subprocess.run(
        [str(python_executable), "-m", "cli", *cli_args],
        cwd=str(app_root),
        env=environment,
        check=False,
    )
    if result.returncode == 0 and not cli_args:
        service_result = subprocess.run(
            [str(python_executable), "-m", "cli", "service", "install"],
            cwd=str(app_root),
            env=environment,
            check=False,
        )
        if service_result.returncode != 0:
            return service_result.returncode
        print("\nElyan hazir. Artik telefondan gorev gonderebilirsin.")
    return int(result.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Elyan tasinabilir masaustu kurulumu")
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("cli_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload_root = args.payload.expanduser().resolve()
    destination_root = args.destination or user_runtime_root()
    try:
        installed_root, copied = install_payload(payload_root, destination_root)
        python_executable = find_portable_python(installed_root)
        launcher = write_cli_launcher(installed_root, python_executable)
    except Exception as exc:
        print(f"Elyan kurulumu tamamlanamadi: {exc}", file=sys.stderr)
        return 1

    version = payload_version(installed_root)
    print(f"Elyan {version} {'kuruldu' if copied else 'hazir'}.")
    print(f"Komut: {launcher}")
    if args.prepare_only:
        return 0
    cli_args = list(args.cli_args)
    if cli_args and cli_args[0] == "--":
        cli_args = cli_args[1:]
    return launch_cli(installed_root, cli_args)


if __name__ == "__main__":
    raise SystemExit(main())
