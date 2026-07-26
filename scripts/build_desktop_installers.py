"""Build dependency-free Elyan installers for macOS, Windows, and Linux."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
RELEASE_LOCK = ROOT / "desktop_installer" / "requirements-release.lock"
SOURCE_DIRECTORIES = ("actions", "cli", "runtime", "core", "config", "helpers", "resources", "scripts")
SOURCE_FILES = (
    "package.json",
    "requirements-core.txt",
    "requirements.txt",
    "app_config.py",
    "__init__.py",
    "__main__.py",
    "logo.png",
)


def run(command: Sequence[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(list(command), cwd=str(cwd or ROOT), env=env, check=True)


def package_version() -> str:
    payload = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    return str(payload.get("version", "") or "").strip()


def copy_sources(destination: Path, *, target_platform: str | None = None) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {"__pycache__", ".DS_Store"}
            or name.endswith((".pyc", ".pyo"))
        }

    destination.mkdir(parents=True, exist_ok=True)
    for directory in SOURCE_DIRECTORIES:
        source = ROOT / directory
        if source.exists():
            shutil.copytree(source, destination / directory, symlinks=True, ignore=ignore)
    for filename in SOURCE_FILES:
        source = ROOT / filename
        if source.exists():
            shutil.copy2(source, destination / filename)
    if target_platform and target_platform != "macos":
        shutil.rmtree(destination / "helpers", ignore_errors=True)


def portable_python(payload_root: Path, *, target_platform: str) -> Path:
    python_root = payload_root / "python"
    if target_platform == "windows":
        candidates = sorted(python_root.glob("cpython-*/python.exe"))
    else:
        candidates = sorted(python_root.glob("cpython-*/bin/python3"))
    if not candidates:
        raise RuntimeError(f"portable Python missing below {python_root}")
    return candidates[0]


def normalize_portable_python_links(python_root: Path) -> None:
    """Keep uv's version alias relocatable and inside the signed bundle."""
    for candidate in python_root.iterdir():
        if not candidate.is_symlink():
            continue
        target = candidate.resolve()
        if target.parent != python_root.resolve():
            raise RuntimeError(f"portable Python alias escapes payload: {candidate} -> {target}")
        candidate.unlink()
        candidate.symlink_to(target.name, target_is_directory=True)


# Hedef platform/mimari → uv'nin gömülü Python ve wheel seçicileri.
# NEDEN: `uv python install 3.11` HOST mimarisini indirir, hedefinkini değil.
# Ölçüldü: Apple Silicon üzerinde üretilen "x64" paketinin başlatıcısı doğru
# (swiftc çapraz derliyor) ama GÖMÜLÜ PYTHON arm64 çıkıyordu — paket Intel
# Mac'te hiç çalışmazdı. Aynı şekilde wheel'ler de host'a göre çözülüyordu.
# Hedef açıkça istenince uv doğru derlemeyi indiriyor.
_UV_PYTHON_BUILD = {
    ("macos", "arm64"): "cpython-3.11-macos-aarch64",
    ("macos", "x64"): "cpython-3.11-macos-x86_64",
    ("windows", "x64"): "cpython-3.11-windows-x86_64",
    ("windows", "arm64"): "cpython-3.11-windows-aarch64",
    ("linux", "x64"): "cpython-3.11-linux-x86_64",
    ("linux", "arm64"): "cpython-3.11-linux-aarch64",
}

_UV_WHEEL_PLATFORM = {
    ("macos", "arm64"): "aarch64-apple-darwin",
    ("macos", "x64"): "x86_64-apple-darwin",
    ("windows", "x64"): "x86_64-pc-windows-msvc",
    ("windows", "arm64"): "aarch64-pc-windows-msvc",
    ("linux", "x64"): "x86_64-unknown-linux-gnu",
    ("linux", "arm64"): "aarch64-unknown-linux-gnu",
}


# python-build-standalone hedef üçlüleri (uv de aynı kaynağı kullanır).
_STANDALONE_TRIPLE = {
    ("windows", "x64"): "x86_64-pc-windows-msvc",
    ("windows", "arm64"): "aarch64-pc-windows-msvc",
    ("macos", "x64"): "x86_64-apple-darwin",
    ("macos", "arm64"): "aarch64-apple-darwin",
    ("linux", "x64"): "x86_64-unknown-linux-gnu",
    ("linux", "arm64"): "aarch64-unknown-linux-gnu",
}
_STANDALONE_PYTHON_VERSION = "3.11.15"


def _install_standalone_python(python_root: Path, target_platform: str, target_arch: str) -> None:
    """Hedef platformun gömülü Python'unu doğrudan indirip açar.

    Çapraz derlemede kullanılır; host'a özel kurulum adımı yoktur.
    """
    import json as _json
    import tarfile
    import urllib.request

    triple = _STANDALONE_TRIPLE.get((target_platform, target_arch))
    if not triple:
        raise RuntimeError(f"portable python target is not mapped: {target_platform}/{target_arch}")

    with urllib.request.urlopen(
        "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest",
        timeout=60,
    ) as response:
        release = _json.loads(response.read().decode("utf-8"))
    wanted = f"cpython-{_STANDALONE_PYTHON_VERSION}+{release['tag_name']}-{triple}-install_only.tar.gz"
    url = next(
        (
            asset["browser_download_url"]
            for asset in release.get("assets", [])
            if asset.get("name") == wanted
        ),
        "",
    )
    if not url:
        raise RuntimeError(f"portable python archive not found in release: {wanted}")

    python_root.mkdir(parents=True, exist_ok=True)
    archive_path = python_root / "python.tar.gz"
    urllib.request.urlretrieve(url, archive_path)
    # Arşiv tek bir `python/` kökü taşır; yerleşimi uv'ninkiyle hizala ki
    # `portable_python()` çözücüsü değişmeden çalışsın.
    target_dir = python_root / f"cpython-{_STANDALONE_PYTHON_VERSION}-{target_platform}-{target_arch}-none"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(python_root)
    extracted = python_root / "python"
    extracted.rename(target_dir)
    archive_path.unlink(missing_ok=True)


def _target_site_packages(python_executable: Path, target_platform: str) -> Path:
    """Gömülü Python'un site-packages dizini (hedef yerleşimine göre)."""
    root = python_executable.parent
    if target_platform == "windows":
        return root / "Lib" / "site-packages"
    return root.parent / "lib" / "python3.11" / "site-packages"


def prepare_payload(
    payload_root: Path,
    *,
    target_platform: str,
    target_arch: str,
    core_only: bool,
    allow_missing_extras: bool,
) -> None:
    if payload_root.exists():
        shutil.rmtree(payload_root)
    app_root = payload_root / "app"
    copy_sources(app_root, target_platform=target_platform)
    shutil.copy2(ROOT / "desktop_installer" / "bootstrap.py", payload_root / "bootstrap.py")

    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to build the portable Python payload")
    python_root = payload_root / "python"
    python_request = _UV_PYTHON_BUILD.get((target_platform, target_arch), "3.11")
    host_platform = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(platform.system())
    if host_platform == target_platform:
        run(
            [uv, "python", "install", python_request, "--managed-python", "--install-dir", str(python_root), "--no-bin"]
        )
    else:
        # ÇAPRAZ HEDEF: `uv python install` doğru arşivi indirir ama kurulum
        # sonrası HOST'a göre davranır — Windows dağıtımında olmayan
        # `bin/python` sembolik bağını kurmaya çalışıp düşer. Arşivi doğrudan
        # açmak aynı kaynağı (python-build-standalone) host varsayımı olmadan
        # kullanır.
        _install_standalone_python(python_root, target_platform, target_arch)
    normalize_portable_python_links(python_root)
    python_executable = portable_python(payload_root, target_platform=target_platform)
    dependency_manifest = RELEASE_LOCK if RELEASE_LOCK.is_file() and not core_only else app_root / "requirements-core.txt"
    host_platform_now = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(platform.system())
    if host_platform_now == target_platform:
        install_command = [
            uv, "pip", "install",
            "--python", str(python_executable),
            "--break-system-packages",
            "-r", str(dependency_manifest),
        ]
    else:
        # ÇAPRAZ HEDEF: uv, hedefin yorumlayıcısını ÇALIŞTIRARAK inceleyemez
        # (Windows python.exe macOS'ta çalışmaz, exit 126). `--target` ile
        # paketler doğrudan site-packages dizinine açılır; yorumlayıcı hiç
        # çalıştırılmaz, sürüm ve platform açıkça bildirilir.
        site_packages = _target_site_packages(python_executable, target_platform)
        site_packages.mkdir(parents=True, exist_ok=True)
        install_command = [
            uv, "pip", "install",
            "--target", str(site_packages),
            "--python-version", _STANDALONE_PYTHON_VERSION,
            "-r", str(dependency_manifest),
        ]
    # Wheel'ler de hedefe göre çözülür; aksi halde host mimarisinin ikili
    # paketleri (pydantic-core, cryptography…) yanlış pakete girer.
    wheel_platform = _UV_WHEEL_PLATFORM.get((target_platform, target_arch), "")
    if wheel_platform:
        install_command[3:3] = ["--python-platform", wheel_platform]
    if dependency_manifest != RELEASE_LOCK:
        install_command.insert(-2, "pip")
    run(install_command)
    if not core_only and not RELEASE_LOCK.is_file():
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(app_root)
        result = subprocess.run(
            [str(python_executable), str(app_root / "scripts" / "install_extras.py")],
            cwd=str(app_root),
            env=environment,
            check=False,
        )
        if result.returncode != 0 and not allow_missing_extras:
            raise RuntimeError("one or more release capability dependencies failed to install")


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(artifacts: list[Path]) -> None:
    for artifact in artifacts:
        artifact.with_suffix(artifact.suffix + ".sha256").write_text(
            f"{sha256_file(artifact)}  {artifact.name}\n",
            encoding="ascii",
        )


def _mac_info_plist(version: str) -> str:
    return textwrap.dedent(
        f'''<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>CFBundleDisplayName</key><string>Elyan</string>
          <key>CFBundleExecutable</key><string>Elyan</string>
          <key>CFBundleIconFile</key><string>Elyan</string>
          <key>CFBundleIdentifier</key><string>dev.elyan.desktop</string>
          <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
          <key>CFBundleName</key><string>Elyan</string>
          <key>CFBundlePackageType</key><string>APPL</string>
          <key>CFBundleShortVersionString</key><string>{version}</string>
          <key>CFBundleVersion</key><string>{version.replace('.', '')}</string>
          <key>LSMinimumSystemVersion</key><string>13.0</string>
          <key>LSUIElement</key><true/>
          <key>NSHighResolutionCapable</key><true/>
        </dict>
        </plist>
        '''
    ).lstrip()


def sign_macos_app(app_bundle: Path) -> None:
    identity = os.environ.get("MACOS_CODESIGN_IDENTITY", "-").strip() or "-"
    if os.environ.get("ELYAN_REQUIRE_SIGNING") == "1" and identity == "-":
        raise RuntimeError("MACOS_CODESIGN_IDENTITY is required for a production release")
    common = ["codesign", "--force", "--sign", identity]
    if identity != "-":
        common.extend(["--options", "runtime", "--timestamp"])
    executable_candidates: list[Path] = []
    for path in app_bundle.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        probe = subprocess.run(
            ["file", "-b", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if "Mach-O" in probe.stdout:
            executable_candidates.append(path)
    for path in sorted(executable_candidates, key=lambda item: len(item.parts), reverse=True):
        run([*common, str(path)])
    nested_bundles = [path for path in app_bundle.rglob("*.app") if path != app_bundle]
    for path in sorted(nested_bundles, key=lambda item: len(item.parts), reverse=True):
        run([*common, str(path)])
    run([*common, str(app_bundle)])
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_bundle)])


def macos_notary_arguments() -> list[str] | None:
    profile = os.environ.get("MACOS_NOTARY_PROFILE", "").strip()
    if profile:
        arguments = ["--keychain-profile", profile]
        keychain = os.environ.get("MACOS_NOTARY_KEYCHAIN", "").strip()
        if keychain:
            arguments.extend(["--keychain", keychain])
        return arguments
    apple_id = os.environ.get("APPLE_ID", "").strip()
    team_id = os.environ.get("APPLE_TEAM_ID", "").strip()
    password = os.environ.get("APPLE_APP_SPECIFIC_PASSWORD", "").strip()
    if apple_id and team_id and password:
        return ["--apple-id", apple_id, "--team-id", team_id, "--password", password]
    if os.environ.get("ELYAN_REQUIRE_SIGNING") == "1":
        raise RuntimeError(
            "APPLE_ID, APPLE_TEAM_ID, and APPLE_APP_SPECIFIC_PASSWORD are required for notarization"
        )
    return None


def notarize_macos_path(path: Path, *, staple: bool = True) -> None:
    arguments = macos_notary_arguments()
    if not arguments:
        return
    run(["xcrun", "notarytool", "submit", str(path), *arguments, "--wait"])
    if staple:
        run(["xcrun", "stapler", "staple", str(path)])
        run(["xcrun", "stapler", "validate", str(path)])


def build_macos(payload_root: Path, output_dir: Path, *, version: str, arch: str) -> list[Path]:
    app_bundle = output_dir / "Elyan.app"
    if app_bundle.exists():
        shutil.rmtree(app_bundle)
    resources = app_bundle / "Contents" / "Resources"
    launcher = app_bundle / "Contents" / "MacOS" / "Elyan"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    swift_arch = "arm64" if arch == "arm64" else "x86_64"
    run(
        [
            "xcrun",
            "swiftc",
            str(ROOT / "desktop_installer" / "macos" / "ElyanLauncher.swift"),
            "-O",
            "-target",
            f"{swift_arch}-apple-macos13.0",
            "-framework",
            "AppKit",
            "-o",
            str(launcher),
        ]
    )
    resources.mkdir(parents=True, exist_ok=True)
    (app_bundle / "Contents" / "Info.plist").write_text(_mac_info_plist(version), encoding="utf-8")
    shutil.copy2(ROOT / "resources" / "resources" / "icon.icns", resources / "Elyan.icns")
    shutil.copytree(payload_root, resources / "payload", symlinks=True)
    sign_macos_app(app_bundle)

    notary_archive = output_dir / ".Elyan-notary.zip"
    notary_archive.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app_bundle), str(notary_archive)])
    notarize_macos_path(notary_archive, staple=False)
    notary_archive.unlink(missing_ok=True)
    if macos_notary_arguments():
        run(["xcrun", "stapler", "staple", str(app_bundle)])
        run(["xcrun", "stapler", "validate", str(app_bundle)])
        run(["spctl", "--assess", "--type", "execute", "--verbose=4", str(app_bundle)])

    app_zip = output_dir / f"Elyan-{version}-macOS-{arch}.app.zip"
    app_zip.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app_bundle), str(app_zip)])

    dmg_root = output_dir / "dmg-root"
    if dmg_root.exists():
        shutil.rmtree(dmg_root)
    dmg_root.mkdir(parents=True)
    shutil.copytree(app_bundle, dmg_root / "Elyan.app", symlinks=True)
    os.symlink("/Applications", dmg_root / "Applications")
    dmg = output_dir / f"Elyan-{version}-macOS-{arch}.dmg"
    dmg.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", "Elyan", "-srcfolder", str(dmg_root), "-ov", "-format", "UDZO", str(dmg)])
    identity = os.environ.get("MACOS_CODESIGN_IDENTITY", "-").strip() or "-"
    if identity != "-":
        run(["codesign", "--force", "--sign", identity, "--timestamp", str(dmg)])
        run(["codesign", "--verify", "--verbose=2", str(dmg)])
    notarize_macos_path(dmg)
    write_checksums([app_zip, dmg])
    return [app_zip, dmg]


def windows_csc() -> str:
    configured = os.environ.get("CSC_PATH")
    if configured and Path(configured).is_file():
        return configured
    discovered = shutil.which("csc") or shutil.which("csc.exe")
    if discovered:
        return discovered
    candidates = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET"
        / "Framework64"
        / "v4.0.30319"
        / "csc.exe",
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "Microsoft.NET"
        / "Framework"
        / "v4.0.30319"
        / "csc.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Microsoft C# compiler (csc.exe) was not found")


def windows_signtool() -> str:
    configured = os.environ.get("SIGNTOOL_PATH")
    if configured and Path(configured).is_file():
        return configured
    discovered = shutil.which("signtool") or shutil.which("signtool.exe")
    if discovered:
        return discovered
    kits_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    candidates = sorted(kits_root.glob("*/x64/signtool.exe"), reverse=True)
    if candidates:
        return str(candidates[0])
    raise RuntimeError("Windows SDK signtool.exe was not found")


def sign_windows_file(path: Path) -> None:
    certificate = os.environ.get("WINDOWS_CERTIFICATE_PATH", "").strip()
    password = os.environ.get("WINDOWS_CERTIFICATE_PASSWORD", "")
    require_signing = os.environ.get("ELYAN_REQUIRE_SIGNING") == "1"
    if not certificate:
        if require_signing:
            raise RuntimeError("WINDOWS_CERTIFICATE_PATH is required for a production release")
        return
    certificate_path = Path(certificate)
    if not certificate_path.is_file():
        raise RuntimeError(f"Windows signing certificate was not found: {certificate_path}")
    signtool = windows_signtool()
    command = [
        signtool,
        "sign",
        "/fd",
        "SHA256",
        "/td",
        "SHA256",
        "/tr",
        os.environ.get("WINDOWS_TIMESTAMP_URL", "http://timestamp.digicert.com"),
        "/f",
        str(certificate_path),
    ]
    if password:
        command.extend(["/p", password])
    command.append(str(path))
    run(command)
    run([signtool, "verify", "/pa", "/all", "/v", str(path)])


def build_windows(payload_root: Path, output_dir: Path, *, version: str, arch: str) -> list[Path]:
    staging = output_dir / "windows-package"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(payload_root, staging / "payload", symlinks=True)
    shutil.copy2(ROOT / "resources" / "resources" / "icon.ico", staging / "Elyan.ico")
    launcher = staging / "Elyan.exe"
    run(
        [
            windows_csc(),
            "/nologo",
            "/optimize+",
            "/target:exe",
            f"/win32icon:{staging / 'Elyan.ico'}",
            f"/out:{launcher}",
            str(ROOT / "desktop_installer" / "windows" / "ElyanLauncher.cs"),
        ]
    )
    sign_windows_file(launcher)

    portable_zip = output_dir / f"Elyan-{version}-Windows-{arch}-portable.zip"
    portable_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(portable_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, Path("Elyan") / path.relative_to(staging))

    iscc = os.environ.get("ISCC_PATH") or shutil.which("iscc") or shutil.which("ISCC.exe")
    if not iscc:
        default = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
        iscc = str(default) if default.exists() else ""
    if not iscc:
        # Inno Setup yalnız Windows'ta bulunur. Yokluğu KURULUM SİHİRBAZINI
        # engeller ama portable ZIP zaten üretildi ve tek başına kullanılabilir
        # (aç-çalıştır). Üretim sürümü imza/kurulum isterse ELYAN_REQUIRE_SIGNING
        # ile zorlanır; aksi halde eksik olanı söyleyip elimizdekini teslim et.
        if os.environ.get("ELYAN_REQUIRE_SIGNING") == "1":
            raise RuntimeError("Inno Setup 6 compiler (ISCC) was not found")
        print(
            "ISCC bulunamadı: kurulum sihirbazı atlandı, portable ZIP üretildi.",
            flush=True,
        )
        return [portable_zip]
    setup_name = f"Elyan-{version}-Windows-{arch}-Setup"
    iss = output_dir / "elyan-installer.iss"
    source = str(staging).replace("\\", "\\\\")
    icon = str(staging / "Elyan.ico").replace("\\", "\\\\")
    escaped_output = str(output_dir).replace("\\", "\\\\")
    iss.write_text(
        textwrap.dedent(
            f'''[Setup]
            AppId={{{{D2E99DA3-B10A-49D4-A6F2-5E0C5811E17A}}}}
            AppName=Elyan
            AppVersion={version}
            AppPublisher=Elyan
            DefaultDirName={{localappdata}}\\Programs\\Elyan
            DefaultGroupName=Elyan
            OutputDir={escaped_output}
            OutputBaseFilename={setup_name}
            SetupIconFile={icon}
            UninstallDisplayIcon={{app}}\\Elyan.ico
            Compression=lzma2/ultra64
            SolidCompression=yes
            PrivilegesRequired=lowest
            ArchitecturesAllowed=x64compatible
            ArchitecturesInstallIn64BitMode=x64compatible
            WizardStyle=modern
            DisableProgramGroupPage=yes

            [Files]
            Source: "{source}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

            [Icons]
            Name: "{{autoprograms}}\\Elyan"; Filename: "{{app}}\\Elyan.exe"; IconFilename: "{{app}}\\Elyan.ico"
            Name: "{{autodesktop}}\\Elyan"; Filename: "{{app}}\\Elyan.exe"; IconFilename: "{{app}}\\Elyan.ico"

            [Run]
            Filename: "{{app}}\\Elyan.exe"; Description: "Elyan'i baslat"; Flags: postinstall nowait skipifsilent
            '''
        ).lstrip(),
        encoding="utf-8-sig",
    )
    run([iscc, str(iss)])
    setup = output_dir / f"{setup_name}.exe"
    if not setup.exists():
        raise RuntimeError("Windows setup artifact was not created")
    sign_windows_file(setup)
    write_checksums([setup, portable_zip])
    return [setup, portable_zip]


def _linux_terminal_launcher(payload_expression: str) -> str:
    return textwrap.dedent(
        f'''#!/bin/sh
        set -eu
        PAYLOAD={payload_expression}
        PYTHON="$(find "$PAYLOAD/python" -type f -path '*/bin/python3' -perm -111 | head -1)"
        BOOTSTRAP="$PAYLOAD/bootstrap.py"
        if [ -z "$PYTHON" ] || [ ! -f "$BOOTSTRAP" ]; then
          echo "Elyan paketi eksik veya bozuk."
          exit 1
        fi
        if [ -t 1 ]; then
          exec "$PYTHON" "$BOOTSTRAP" --payload "$PAYLOAD" "$@"
        fi
        COMMAND="'$PYTHON' '$BOOTSTRAP' --payload '$PAYLOAD'"
        if command -v x-terminal-emulator >/dev/null 2>&1; then
          exec x-terminal-emulator -e sh -lc "$COMMAND; printf '\\nPencereyi kapatmak icin Enter'a bas. '; read answer"
        elif command -v gnome-terminal >/dev/null 2>&1; then
          exec gnome-terminal -- sh -lc "$COMMAND; printf '\\nPencereyi kapatmak icin Enter'a bas. '; read answer"
        elif command -v konsole >/dev/null 2>&1; then
          exec konsole -e sh -lc "$COMMAND; printf '\\nPencereyi kapatmak icin Enter'a bas. '; read answer"
        fi
        exec "$PYTHON" "$BOOTSTRAP" --payload "$PAYLOAD" "$@"
        '''
    ).lstrip()


def build_linux(payload_root: Path, output_dir: Path, *, version: str, arch: str) -> list[Path]:
    app_dir = output_dir / "Elyan.AppDir"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_payload = app_dir / "usr" / "share" / "elyan" / "payload"
    shutil.copytree(payload_root, app_payload, symlinks=True)
    write_executable(app_dir / "AppRun", _linux_terminal_launcher('"$APPDIR/usr/share/elyan/payload"'))
    shutil.copy2(ROOT / "resources" / "resources" / "icon.png", app_dir / "elyan.png")
    desktop_entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Elyan\n"
        "Comment=Local-first AI agent\n"
        "Exec=elyan\n"
        "Icon=elyan\n"
        "Terminal=false\n"
        "Categories=Utility;Office;\n"
    )
    (app_dir / "elyan.desktop").write_text(desktop_entry, encoding="utf-8")

    artifacts: list[Path] = []
    appimage_tool = os.environ.get("APPIMAGETOOL") or shutil.which("appimagetool")
    if appimage_tool:
        appimage = output_dir / f"Elyan-{version}-Linux-{arch}.AppImage"
        environment = dict(os.environ)
        environment["ARCH"] = "x86_64" if arch == "x64" else arch
        run([appimage_tool, str(app_dir), str(appimage)], env=environment)
        appimage.chmod(appimage.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        artifacts.append(appimage)

    deb_root = output_dir / "deb-root"
    if deb_root.exists():
        shutil.rmtree(deb_root)
    shutil.copytree(payload_root, deb_root / "opt" / "elyan" / "payload", symlinks=True)
    write_executable(
        deb_root / "usr" / "bin" / "elyan",
        _linux_terminal_launcher('"/opt/elyan/payload"'),
    )
    (deb_root / "usr" / "share" / "applications").mkdir(parents=True, exist_ok=True)
    (deb_root / "usr" / "share" / "applications" / "elyan.desktop").write_text(desktop_entry, encoding="utf-8")
    icon_target = deb_root / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
    icon_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "resources" / "resources" / "icon.png", icon_target / "elyan.png")
    control = deb_root / "DEBIAN" / "control"
    control.parent.mkdir(parents=True, exist_ok=True)
    deb_arch = "amd64" if arch == "x64" else "arm64"
    control.write_text(
        (
            "Package: elyan\n"
            f"Version: {version}\n"
            "Section: utils\n"
            "Priority: optional\n"
            f"Architecture: {deb_arch}\n"
            "Maintainer: Elyan <support@elyan.dev>\n"
            "Description: Elyan local-first AI desktop agent\n"
        ),
        encoding="utf-8",
    )
    deb = output_dir / f"Elyan-{version}-Linux-{arch}.deb"
    run(["dpkg-deb", "--build", "--root-owner-group", str(deb_root), str(deb)])
    artifacts.append(deb)

    portable = output_dir / f"Elyan-{version}-Linux-{arch}-portable.tar.gz"
    with tarfile.open(portable, "w:gz") as archive:
        archive.add(app_dir, arcname="Elyan")
    artifacts.append(portable)
    write_checksums(artifacts)
    return artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("macos", "windows", "linux"), required=True)
    parser.add_argument("--arch", choices=("arm64", "x64"), required=True)
    parser.add_argument("--version", default=package_version())
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--allow-missing-extras", action="store_true")
    parser.add_argument(
        "--allow-cross-build",
        action="store_true",
        help="hedef platformdan farklı bir host'ta derlemeye izin ver (portable çıktı)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version != package_version():
        raise SystemExit(f"version mismatch: package.json={package_version()} requested={args.version}")
    host_platform = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(platform.system())
    if host_platform != args.platform and not args.allow_cross_build:
        raise SystemExit(f"{args.platform} artifacts must be built on {args.platform}, host is {host_platform}")
    if host_platform != args.platform:
        # Çapraz derleme AÇIK istendi. Gömülü Python ve wheel'ler hedefe göre
        # seçilir (bkz. _UV_PYTHON_BUILD / _UV_WHEEL_PLATFORM); host'a özel
        # adımlar (imzalama, kurulum sihirbazı) sessizce atlanır ve çıktı
        # portable pakettir. Bunu üretim imzası yerine koyma.
        print(
            f"ÇAPRAZ DERLEME: hedef {args.platform}/{args.arch}, host {host_platform}. "
            "Host'a özel adımlar (imza, kurulum sihirbazı) atlanabilir.",
            flush=True,
        )
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    payload_root = output_dir / "payload"
    prepare_payload(
        payload_root,
        target_platform=args.platform,
        target_arch=args.arch,
        core_only=args.core_only,
        allow_missing_extras=args.allow_missing_extras,
    )
    if args.platform == "macos":
        artifacts = build_macos(payload_root, output_dir, version=args.version, arch=args.arch)
    elif args.platform == "windows":
        artifacts = build_windows(payload_root, output_dir, version=args.version, arch=args.arch)
    else:
        artifacts = build_linux(payload_root, output_dir, version=args.version, arch=args.arch)
    for artifact in artifacts:
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
