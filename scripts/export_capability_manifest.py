"""Desktop yetenek kataloğunu backend'e MANIFEST olarak üretir.

TEK KAYNAK: runtime/capability_registry.TOOL_DECLARATIONS (77 kendini-belgeleyen
yetenek). Backend'in sunucu-materyalize planlayıcısı (materialize-plan.ts) bu
manifest'i kullanır — böylece sunucu planları desktop'un TAM kataloğuyla uyumlu
kalır; iki tarafta elle tutulan liste sürüklenmesi (canlı arıza sınıfı) biter.

Kullanım:
    venv/bin/python scripts/export_capability_manifest.py \
        /Users/emrekoca/elyan-backend/src/modules/tasks/desktop-capability-manifest.ts

Backend değişmez; yalnız üretilen dosya commit'lenir. Katalog değişince bu
script yeniden koşulur (test_capability_manifest_export guard'ı üretimin
katalogla bire bir örtüştüğünü garanti eder).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.bridge import REMOTE_APPROVAL_CAPABILITIES  # noqa: E402
from runtime.capability_registry import TOOL_DECLARATIONS  # noqa: E402


def _clip(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_manifest() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for decl in TOOL_DECLARATIONS:
        name = str(decl.get("name", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        parameters = decl.get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}
        required = parameters.get("required")
        required = [str(item) for item in required] if isinstance(required, list) else []
        entries.append(
            {
                "name": name,
                "description": _clip(decl.get("description", ""), 200),
                "usage": _clip(decl.get("usage", ""), 200),
                "requiredArgs": required,
                "requiresApproval": name in REMOTE_APPROVAL_CAPABILITIES,
            }
        )
    entries.sort(key=lambda item: str(item["name"]))
    return entries


def render_typescript(entries: list[dict[str, object]]) -> str:
    payload = json.dumps(entries, ensure_ascii=False, indent=2)
    return (
        "// ÜRETİLEN DOSYA — ELLE DÜZENLEME.\n"
        "// Kaynak: elyan-desktop runtime/capability_registry.TOOL_DECLARATIONS.\n"
        "// Yeniden üretim: venv/bin/python scripts/export_capability_manifest.py <bu dosya>\n"
        "// Sunucu-materyalize planlayıcı desktop'un TAM kataloğunu bu manifest'ten\n"
        "// okur; onay gerektirenler desktop tarafında yine onaya takılır (güvenlik\n"
        "// sınırı desktop'tadır — manifest yalnız planlama kelime dağarcığıdır).\n\n"
        "export type DesktopCapabilityManifestEntry = {\n"
        "  name: string;\n"
        "  description: string;\n"
        "  usage: string;\n"
        "  requiredArgs: string[];\n"
        "  requiresApproval: boolean;\n"
        "};\n\n"
        f"export const DESKTOP_CAPABILITY_MANIFEST: DesktopCapabilityManifestEntry[] = {payload};\n"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("kullanım: export_capability_manifest.py <çıktı .ts yolu>", file=sys.stderr)
        return 2
    output = Path(sys.argv[1]).expanduser()
    entries = build_manifest()
    output.write_text(render_typescript(entries), encoding="utf-8")
    print(f"{len(entries)} yetenek yazıldı → {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
