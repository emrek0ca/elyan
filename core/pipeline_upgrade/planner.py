from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class PlanCacheEntry:
    value: list[dict[str, Any]]
    expires_at: float


class PlanCache:
    def __init__(self) -> None:
        self._store: dict[str, PlanCacheEntry] = {}

    def get(self, key: str) -> list[dict[str, Any]] | None:
        entry = self._store.get(key)
        now = time.time()
        if not entry:
            return None
        if now >= entry.expires_at:
            self._store.pop(key, None)
            return None
        return [dict(x) for x in entry.value]

    def set(self, key: str, value: list[dict[str, Any]], ttl_s: int = 300) -> None:
        ttl = max(30, min(3600, int(ttl_s or 300)))
        self._store[key] = PlanCacheEntry(value=[dict(x) for x in value], expires_at=time.time() + ttl)


_PLAN_CACHE = PlanCache()


def make_plan_cache_key(*, intent: dict[str, Any], job_type: str, context_fingerprint: str) -> str:
    payload = {
        "intent": intent,
        "job_type": str(job_type or "communication"),
        "context_fingerprint": str(context_fingerprint or ""),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def get_plan_cache() -> PlanCache:
    return _PLAN_CACHE


def build_skeleton_plan(job_type: str, user_input: str) -> list[dict[str, Any]]:
    j = str(job_type or "communication").strip().lower() or "communication"
    templates: dict[str, list[tuple[str, str]]] = {
        "file_operations": [
            ("analyze_request", "Girdi ve hedef dosya yolunu netleştir"),
            ("prepare_workspace", "Çalışma dizinini hazırla"),
            ("execute_files", "Dosya/klasör işlemlerini uygula"),
            ("verify_artifacts", "Oluşan dosyaları doğrula"),
            ("summarize", "Sonuç ve kanıtı raporla"),
        ],
        "code_project": [
            ("analyze_requirements", "Gereksinimleri çıkar"),
            ("create_or_patch_code", "Kod değişikliklerini uygula"),
            ("run_quality_gates", "Lint/test/typecheck kapılarını çalıştır"),
            ("verify_entrypoint", "Entrypoint ve çalıştırılabilirliği doğrula"),
            ("summarize", "Sonuç ve eksikleri raporla"),
        ],
        "api_integration": [
            ("extract_endpoint", "Endpoint ve methodu belirle"),
            ("prepare_request", "İstek parametrelerini hazırla"),
            ("execute_api_call", "API çağrısını yap"),
            ("verify_response", "Yanıtı beklenen şemaya göre doğrula"),
            ("summarize", "Sonucu kanıt ile yaz"),
        ],
        "system_automation": [
            ("set_goal", "Hedefi adımlara böl"),
            ("execute_steps", "Desktop adımlarını uygula"),
            ("collect_proof", "Ekran görüntüsü/evidence topla"),
            ("verify_outcome", "Hedefin gerçekleştiğini doğrula"),
            ("summarize", "Operasyon raporu sun"),
        ],
        "research": [
            ("define_scope", "Araştırma kapsamını sınırla"),
            ("collect_sources", "Kaynakları topla"),
            ("map_claims", "İddia-kaynak eşlemesi yap"),
            ("list_unknowns", "Belirsizlikleri listele"),
            ("summarize", "Güven notu ile sonuç yaz"),
        ],
    }
    steps = templates.get(j, [
        ("analyze", "İsteği analiz et"),
        ("plan", "Uygulanabilir plan çıkar"),
        ("execute", "Gerekli adımları uygula"),
        ("verify", "Sonucu doğrula"),
        ("summarize", "Teslim et"),
    ])

    out = []
    for i, (action, title) in enumerate(steps[:7], start=1):
        out.append({
            "id": f"sk_{i}",
            "title": title,
            "description": f"{title} | input={str(user_input or '')[:120]}",
            "action": action,
            "depends_on": [f"sk_{i-1}"] if i > 1 else [],
            "params": {},
            "skeleton": True,
        })
    return out


def build_step_specs_from_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    toolish = {
        "execute_api_call", "execute_files", "create_or_patch_code", "execute_steps", "verify_response", "run_quality_gates",
        "verify_entrypoint", "collect_proof", "verify_outcome", "execute",
    }
    specs: list[dict[str, Any]] = []
    for step in plan or []:
        action = str(step.get("action") or "").strip()
        if not action:
            continue
        requires_tool = action in toolish or action.startswith("tool_")
        if not requires_tool:
            continue
        specs.append(
            {
                "id": str(step.get("id") or ""),
                "action": action,
                "requires_tool": True,
                "params_schema": {"type": "object"},
                "expected_output": {"type": "object"},
            }
        )
    return specs
