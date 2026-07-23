"""Generate a deterministic CycloneDX SBOM from the hashed release lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "desktop_installer" / "requirements-release.lock"
PACKAGE_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")


def package_version() -> str:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    return str(package["version"])


def locked_components(lock_path: Path = LOCK) -> list[dict[str, str]]:
    components: list[dict[str, str]] = []
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        match = PACKAGE_LINE.match(line)
        if not match:
            continue
        name, version = match.groups()
        normalized = name.lower().replace("_", "-")
        purl = f"pkg:pypi/{normalized}@{version}"
        components.append(
            {
                "type": "library",
                "bom-ref": purl,
                "name": normalized,
                "version": version,
                "purl": purl,
            }
        )
    return components


def build_sbom(lock_path: Path = LOCK) -> dict[str, object]:
    lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    version = package_version()
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"https://elyan.dev/sbom/{version}/{lock_digest}")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": f"pkg:generic/elyan@{version}",
                "name": "Elyan",
                "version": version,
            },
            "properties": [
                {"name": "elyan:dependency-lock:sha256", "value": lock_digest},
            ],
        },
        "components": locked_components(lock_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=LOCK)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(build_sbom(args.lock), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
