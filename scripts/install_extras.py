"""Ağır/opsiyonel paketleri arka planda tek tek kurar.

`bin/elyan.js` ilk kurulumdan sonra bunu ayrık (detached) başlatır. Paketler
tek tek kurulur ki biri derlenemezse (ör. portaudio'suz pyaudio) kalanlar
etkilenmesin. Çıktı ~/.elyan/extras.log dosyasına yazılır.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE = REPO_ROOT / "requirements-core.txt"
FULL = REPO_ROOT / "requirements.txt"
DONE_MARKER = Path.home() / ".elyan" / ".extras-installed"


def _packages(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def main() -> int:
    if DONE_MARKER.exists():
        return 0
    core_names = {p.split(">")[0].split("=")[0].strip().lower() for p in _packages(CORE)}
    failures = 0
    for package in _packages(FULL):
        name = package.split(">")[0].split("=")[0].strip().lower()
        if name in core_names:
            continue
        print(f"--- pip install {package}", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", package],
        )
        if result.returncode != 0:
            failures += 1
            print(f"!!! kurulamadı: {package} (atlandı)", flush=True)
    DONE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    DONE_MARKER.write_text(f"failures={failures}\n")
    print(f"Bitti. Başarısız paket: {failures}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
