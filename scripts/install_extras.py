"""Ağır/opsiyonel paketleri kontrollü biçimde tek tek kurar.

`bin/elyan.js` ilk kurulumda bunun tamamlanmasını bekleyerek çalıştırır. Paketler
tek tek kurulur ki biri derlenemezse (ör. portaudio'suz pyaudio) kalanlar
etkilenmesin. CLI süreç boyunca ilerlemeyi doğrudan terminale yazar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE = REPO_ROOT / "requirements-core.txt"
FULL = REPO_ROOT / "requirements.txt"
# Marker venv'İN İÇİNDE yaşar: venv yeniden kurulursa (Python güncellemesi)
# marker da gider ve extras yeniden kurulur. Eski ~/.elyan konumundaki marker
# venv'i temsil etmediği için güvenilmez (paketler eksikken atlanıyordu).
DONE_MARKER = Path(sys.prefix) / ".elyan-extras-installed"


def _packages(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _manifest_hash() -> str:
    digest = hashlib.sha256()
    for path in (CORE, FULL):
        digest.update(path.read_bytes() if path.exists() else b"")
    return digest.hexdigest()


def _marker_is_current() -> bool:
    try:
        payload = json.loads(DONE_MARKER.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return bool(payload.get("complete")) and payload.get("manifestHash") == _manifest_hash()


def _write_marker(*, failures: list[str]) -> None:
    payload = {
        "version": 1,
        "complete": not failures,
        "manifestHash": _manifest_hash(),
        "failedPackages": failures,
    }
    DONE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    temporary = DONE_MARKER.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(DONE_MARKER)


def main(*, force: bool = False) -> int:
    if not force and _marker_is_current():
        return 0
    core_names = {p.split(">")[0].split("=")[0].strip().lower() for p in _packages(CORE)}
    failures: list[str] = []
    try:
        timeout_seconds = int(os.environ.get("ELYAN_EXTRAS_PACKAGE_TIMEOUT_SECONDS", "900") or 900)
    except (TypeError, ValueError):
        timeout_seconds = 900
    timeout_seconds = max(60, min(timeout_seconds, 3600))
    for package in _packages(FULL):
        name = package.split(">")[0].split("=")[0].strip().lower()
        if name in core_names:
            continue
        print(f"--- pip install {package}", flush=True)
        try:
            result = subprocess.run(
                # --only-binary=:all: — opsiyonel yetenekler için de derleme YOK.
                # pyaudio/qiskit-aer gibi paketler kaynaktan kurulmaya
                # kalkınca dakikalarca derleyip sonunda derleyici bulunamadığı
                # için düşüyordu; kullanıcı bu sırada kurulumun donduğunu
                # sanıyordu. Wheel'i olmayan opsiyonel paket sessizce atlanır
                # (zaten atlanabilir olduğu için "opsiyonel") ve
                # `elyan doctor` çıktısında görünür.
                [
                    sys.executable, "-m", "pip", "install", "--quiet",
                    "--disable-pip-version-check", "--no-input",
                    "--only-binary=:all:", package,
                ],
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            result = None
        if result is None or result.returncode != 0:
            failures.append(package)
            print(f"!!! kurulamadı: {package} (atlandı)", flush=True)
    _write_marker(failures=failures)
    print(f"Bitti. Başarısız paket: {len(failures)}", flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    raise SystemExit(main(force=parser.parse_args().force))
