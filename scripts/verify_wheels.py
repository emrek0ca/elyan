"""Çekirdek bağımlılıkların ÜÇ PLATFORMDA da wheel'i var mı — kanıtlar.

NEDEN
-----
Canlı arıza: `litellm` sabitlenmemişti; pip en yeni sürümü seçti, o sürümün
wheel'i yoktu, kaynaktan derlemeye kalktı ve Windows'ta Rust toolchain isteyip
kurulumu tamamen düşürdü. macOS'ta clang hazır olduğu için aynı paket sessizce
derleniyor ve sorun görünmüyordu — klasik "bende çalışıyor" tuzağı.

Bu script tahmin etmez: pip'in kendi çözücüsünü `--only-binary=:all:` ile
her hedef platform için çalıştırır. Bir paket sdist'e düşüyorsa BURADA patlar,
kullanıcının makinesinde değil.

KULLANIM
--------
    python scripts/verify_wheels.py            # çekirdek küme, 3 platform
    python scripts/verify_wheels.py --python 3.12

Çıkış kodu 0 = her platformda tamamen wheel'den kurulabilir.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Elyan'ın desteklediği masaüstü hedefleri. Her hedef için birden çok etiket
# verilir: bir paket `manylinux2014` yerine `manylinux_2_28`, ya da
# `macosx_10_13` yerine `macosx_11_0` yayınlayabilir; ikisi de geçerli wheel'dir.
TARGETS = [
    ("Windows x64", ["win_amd64"]),
    (
        "macOS Apple Silicon",
        ["macosx_11_0_arm64", "macosx_12_0_arm64", "macosx_14_0_arm64"],
    ),
    (
        "macOS Intel",
        ["macosx_10_13_x86_64", "macosx_10_15_x86_64", "macosx_12_0_x86_64"],
    ),
    (
        "Linux x64",
        ["manylinux2014_x86_64", "manylinux_2_28_x86_64", "manylinux_2_17_x86_64"],
    ),
]


def _requirements(path: Path) -> list[str]:
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


def check(requirement: str, python_version: str, platforms: list[str]) -> bool:
    """Tek bir paketin bu hedefte wheel'i var mı?

    ``--no-deps`` KASITLI: pip'in ``--platform`` bayrağı ortam işaretlerini
    (``sys_platform``) hedefe göre değerlendirmez, host'a göre değerlendirir.
    Bağımlılıklarla birlikte çözülürse ``pyobjc ... ; sys_platform == "darwin"``
    gibi platforma özel bir alt bağımlılık Windows denetiminde yanlış yere
    patlar. Doğrudan sabitlediğimiz paketleri tek tek denetlemek hem kesin
    sonuç verir hem de gerçek arızayı (sdist-only sürüme sabitlenmek) tam
    olarak yakalar — canlı hata tam buydu.
    """
    with tempfile.TemporaryDirectory() as tmp:
        command = [
            sys.executable, "-m", "pip", "download", requirement,
            "--only-binary=:all:", "--no-deps",
            "--python-version", python_version,
            "--dest", tmp,
        ]
        for platform in platforms:
            command += ["--platform", platform]
        result = subprocess.run(command, capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Wheel kapsama doğrulayıcı")
    parser.add_argument("--python", default="3.12", help="hedef Python sürümü")
    parser.add_argument(
        "--requirements",
        default=str(ROOT / "requirements-core.txt"),
        help="denetlenecek gereksinim dosyası",
    )
    args = parser.parse_args()

    requirements = Path(args.requirements)
    if not requirements.exists():
        print(f"gereksinim dosyası yok: {requirements}", file=sys.stderr)
        return 2

    entries = _requirements(requirements)
    print(
        f"Wheel kapsama denetimi — {requirements.name}, "
        f"{len(entries)} paket, Python {args.python}\n"
    )
    ok = True
    for label, platforms in TARGETS:
        missing = [
            entry for entry in entries if not check(entry, args.python, platforms)
        ]
        if missing:
            ok = False
            print(f"  ✗ {label}")
            for entry in missing:
                print(f"      wheel YOK: {entry}")
        else:
            print(f"  ✓ {label}")

    print()
    if ok:
        print("Tüm hedeflerde wheel var: kurulum derleyici istemez.")
        return 0
    print(
        "En az bir hedefte wheel YOK. Sabitlenen sürümü wheel'i olan bir sürüme\n"
        "çek (pip index versions <paket> --only-binary=:all: ile en sonu bul).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
