"""Desktop yetenek/skill kataloğunu backend'e MANIFEST olarak üretir.

TEK KAYNAK: runtime/capability_registry.TOOL_DECLARATIONS (77 kendini-belgeleyen
yetenek). Backend'in sunucu-materyalize planlayıcısı (materialize-plan.ts) bu
manifest'i kullanır — böylece sunucu planları desktop'un TAM kataloğuyla uyumlu
kalır; iki tarafta elle tutulan liste sürüklenmesi (canlı arıza sınıfı) biter.

Kullanım:
    venv/bin/python scripts/export_capability_manifest.py \
        /Users/emrekoca/elyan-backend/src/modules/tasks/desktop-capability-manifest.ts

    venv/bin/python scripts/export_capability_manifest.py \
        /Users/emrekoca/elyan-backend/src/modules/tasks/desktop-capability-manifest.ts \
        /Users/emrekoca/elyan-backend/src/modules/tasks/desktop-skill-manifest.ts

Backend değişmez; yalnız üretilen dosyalar commit'lenir. Katalog değişince bu
script yeniden koşulur.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime.bridge import REMOTE_APPROVAL_CAPABILITIES  # noqa: E402
from runtime.capability_registry import TOOL_DECLARATIONS  # noqa: E402
from runtime.capability_spec import enriched_tool_declaration  # noqa: E402
from runtime.skill_catalog import builtin_skill_manifests  # noqa: E402


def _clip(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _string_list(value: object, limit: int = 12, item_limit: int = 240) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clip(item, item_limit) for item in value if str(item or "").strip()][:limit]


def _object_value(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def build_capability_manifest() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_decl in TOOL_DECLARATIONS:
        decl = enriched_tool_declaration(raw_decl)
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
                "whenToUse": _string_list(decl.get("whenToUse"), 8),
                "whenNotToUse": _string_list(decl.get("whenNotToUse"), 6),
                "inputContract": _object_value(decl.get("inputContract")),
                "outputContract": _object_value(decl.get("outputContract")),
                "artifactContract": _object_value(decl.get("artifactContract")),
                "verificationPlan": _string_list(decl.get("verificationPlan"), 6),
                "liveNarration": _string_list(decl.get("liveNarration"), 6),
                "failureModes": _string_list(decl.get("failureModes"), 8, 80),
                "fewShots": [
                    dict(item)
                    for item in (decl.get("fewShots", []) or [])
                    if isinstance(item, dict)
                ][:3],
                "privacyClass": _clip(decl.get("privacyClass", ""), 80),
                "skillAffinity": _string_list(decl.get("skillAffinity"), 8, 120),
            }
        )
    entries.sort(key=lambda item: str(item["name"]))
    return entries


def build_manifest() -> list[dict[str, object]]:
    """Eski test/import adını koruyan uyumluluk alias'ı."""
    return build_capability_manifest()


def build_skill_manifest() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for skill in builtin_skill_manifests():
        skill_id = str(skill.get("id", "") or "").strip()
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        parameters = [
            str(item)
            for item in (skill.get("parameters", []) or [])
            if str(item or "").strip()
        ]
        required = [
            str(item)
            for item in (skill.get("requiredParameters", []) or [])
            if str(item or "").strip()
        ]
        steps = skill.get("steps")
        step_capabilities: list[str] = []
        if isinstance(steps, list):
            for step in steps[:8]:
                if not isinstance(step, dict):
                    continue
                capability = str(step.get("capability", "") or "").strip()
                if capability:
                    step_capabilities.append(capability)
        output_formats = []
        adapter = str(skill.get("adapter", "") or "")
        if adapter == "document_write":
            output_formats = ["docx"]
        elif adapter == "canvas_write":
            output_formats = ["pdf", "png"]
        elif adapter == "spreadsheet_write":
            output_formats = ["xlsx"]
        elif adapter == "presentation_write":
            output_formats = ["pptx"]
        entries.append(
            {
                "id": skill_id,
                "name": _clip(skill.get("name", ""), 120),
                "description": _clip(skill.get("description", ""), 260),
                "category": _clip(skill.get("category", "custom"), 80),
                "adapter": _clip(skill.get("adapter", ""), 120),
                "parameters": parameters,
                "requiredParameters": required,
                "expectedInputs": [
                    str(item)
                    for item in (skill.get("expectedInputs", []) or [])
                    if str(item or "").strip()
                ][:12],
                "intentTags": [
                    str(item)
                    for item in (skill.get("intentTags", []) or [])
                    if str(item or "").strip()
                ][:18],
                "stepCapabilities": list(dict.fromkeys(step_capabilities)),
                "stepCount": int(skill.get("stepCount", 0) or 0),
                "latencyClass": _clip(skill.get("latencyClass", ""), 40),
                "selectionPriority": int(skill.get("selectionPriority", 0) or 0),
                "requiresConfirmation": bool(skill.get("requiresConfirmation", False)),
                "whenToUse": _string_list(skill.get("whenToUse"), 8) or [
                    _clip(skill.get("description", ""), 220)
                ],
                "whenNotToUse": _string_list(skill.get("whenNotToUse"), 6) or [
                    "Katalogdaki workflow kullanıcı hedefiyle bire bir uyuşmuyorsa primitive capability zinciri kur."
                ],
                "inputContract": _object_value(skill.get("inputContract")) or {
                    "requiredPayloadFields": required,
                    "acceptedPayloadFields": parameters,
                },
                "outputContract": _object_value(skill.get("outputContract")) or {
                    "kind": "run_skill",
                    "adapter": adapter,
                    "stepCapabilities": list(dict.fromkeys(step_capabilities)),
                    "outputFormats": output_formats,
                },
                "verificationPlan": _string_list(skill.get("verificationPlan"), 6) or [
                    "Skill id katalogda bulunmalı.",
                    "Payload her requiredParameter alanını içermeli.",
                    "Son adım sonucu boş olmamalı.",
                ],
                "liveNarration": _string_list(skill.get("liveNarration"), 6) or [
                    "Hazır beceri seçiliyor.",
                    "Beceri adımları yürütülüyor.",
                    "Sonuç doğrulanıyor.",
                ],
                "failureModes": _string_list(skill.get("failureModes"), 8, 80) or [
                    "UNKNOWN_SKILL",
                    "MISSING_PAYLOAD_FIELD",
                    "STEP_FAILED",
                ],
                "fewShots": [
                    dict(item)
                    for item in (skill.get("fewShots", []) or [])
                    if isinstance(item, dict)
                ][:3],
            }
        )
    entries.sort(key=lambda item: (-int(item["selectionPriority"]), str(item["id"])))
    return entries


def render_capability_typescript(entries: list[dict[str, object]]) -> str:
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
        "  whenToUse: string[];\n"
        "  whenNotToUse: string[];\n"
        "  inputContract: Record<string, unknown>;\n"
        "  outputContract: Record<string, unknown>;\n"
        "  artifactContract: Record<string, unknown>;\n"
        "  verificationPlan: string[];\n"
        "  liveNarration: string[];\n"
        "  failureModes: string[];\n"
        "  fewShots: Array<Record<string, unknown>>;\n"
        "  privacyClass: string;\n"
        "  skillAffinity: string[];\n"
        "};\n\n"
        f"export const DESKTOP_CAPABILITY_MANIFEST: DesktopCapabilityManifestEntry[] = {payload};\n"
    )


def render_skill_typescript(entries: list[dict[str, object]]) -> str:
    payload = json.dumps(entries, ensure_ascii=False, indent=2)
    return (
        "// ÜRETİLEN DOSYA — ELLE DÜZENLEME.\n"
        "// Kaynak: elyan-desktop runtime/skill_catalog.builtin_skill_manifests().\n"
        "// Yeniden üretim: venv/bin/python scripts/export_capability_manifest.py <capability.ts> <bu dosya>\n"
        "// Sunucu-materyalize planlayıcı skill kataloğunu yalnız planlama kelime\n"
        "// dağarcığı olarak kullanır. Skill yürütme desktop'ta run_skill capability'si\n"
        "// üzerinden, desktop güvenlik/onay sınırları korunarak yapılır.\n\n"
        "export type DesktopSkillManifestEntry = {\n"
        "  id: string;\n"
        "  name: string;\n"
        "  description: string;\n"
        "  category: string;\n"
        "  adapter: string;\n"
        "  parameters: string[];\n"
        "  requiredParameters: string[];\n"
        "  expectedInputs: string[];\n"
        "  intentTags: string[];\n"
        "  stepCapabilities: string[];\n"
        "  stepCount: number;\n"
        "  latencyClass: string;\n"
        "  selectionPriority: number;\n"
        "  requiresConfirmation: boolean;\n"
        "  whenToUse: string[];\n"
        "  whenNotToUse: string[];\n"
        "  inputContract: Record<string, unknown>;\n"
        "  outputContract: Record<string, unknown>;\n"
        "  verificationPlan: string[];\n"
        "  liveNarration: string[];\n"
        "  failureModes: string[];\n"
        "  fewShots: Array<Record<string, unknown>>;\n"
        "};\n\n"
        f"export const DESKTOP_SKILL_MANIFEST: DesktopSkillManifestEntry[] = {payload};\n"
    )


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print(
            "kullanım: export_capability_manifest.py <capability .ts yolu> [skill .ts yolu]",
            file=sys.stderr,
        )
        return 2
    output = Path(sys.argv[1]).expanduser()
    entries = build_capability_manifest()
    output.write_text(render_capability_typescript(entries), encoding="utf-8")
    print(f"{len(entries)} yetenek yazıldı → {output}")
    if len(sys.argv) == 3:
        skill_output = Path(sys.argv[2]).expanduser()
        skills = build_skill_manifest()
        skill_output.write_text(render_skill_typescript(skills), encoding="utf-8")
        print(f"{len(skills)} skill yazıldı → {skill_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
