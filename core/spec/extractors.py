"""
Domain-seçici TaskSpec extractor dispatcher.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _fs_fewshot() -> List[Dict[str, Any]]:
    return [
        {
            "user": "1) ~/Desktop/elyan-test/a klasörü oluştur 2) not.txt yaz 3) içeriği doğrula 4) artifact yollarını ver",
            "intent": "filesystem_batch",
            "steps": [
                {"action": "mkdir", "path": "~/Desktop/elyan-test/a", "parents": True},
                {"action": "write_file", "path": "~/Desktop/elyan-test/a/not.txt", "content": "Görev özeti: ..."},
                {"action": "verify_file", "path": "~/Desktop/elyan-test/a/not.txt", "expect_contains": "..."},
                {"action": "report_artifacts", "path": "~/Desktop/elyan-test/a"},
            ],
        }
    ]


def _api_fewshot() -> List[Dict[str, Any]]:
    return [
        {
            "user": "https://httpbin.org/get için health check yap, sonra GET at, sonucu result.json ve summary.txt kaydet",
            "intent": "api_batch",
            "steps": [
                {"action": "api_health_check", "params": {"urls": ["https://httpbin.org/get"]}},
                {"action": "http_request", "params": {"method": "GET", "url": "https://httpbin.org/get"}},
                {"action": "write_file", "path": "~/Desktop/elyan-test/api/result.json", "content": "{...json...}"},
                {"action": "write_file", "path": "~/Desktop/elyan-test/api/summary.txt", "content": "Özet"},
            ],
        }
    ]


def _research_fewshot() -> List[Dict[str, Any]]:
    return [
        {
            "user": "Türkiye'de KVKK uyumlu yerel LLM yaklaşımını araştır, kısa yönetici özeti çıkar",
            "intent": "research_batch",
            "steps": [
                {"action": "advanced_research", "params": {"topic": "KVKK uyumlu yerel LLM", "depth": "comprehensive"}},
                {"action": "generate_report", "params": {"title": "KVKK Uyumlu Yerel LLM Özeti", "format": "markdown"}},
                {"action": "write_file", "path": "~/Desktop/elyan-test/research/summary.txt", "content": "..."},
            ],
        }
    ]


def _code_fewshot() -> List[Dict[str, Any]]:
    return [
        {
            "user": "FastAPI tabanlı basit todo servisi oluştur, sonra smoke test çalıştır",
            "intent": "coding_batch",
            "steps": [
                {"action": "mkdir", "path": "~/Desktop/todo-api"},
                {"action": "write_file", "path": "~/Desktop/todo-api/main.py", "content": "..."},
                {"action": "run_safe_command", "params": {"command": "python -m pytest -q"}},
                {"action": "read_file", "path": "~/Desktop/todo-api/main.py"},
            ],
        }
    ]


def _office_fewshot() -> List[Dict[str, Any]]:
    return [
        {
            "user": "Toplantı notlarını özetle, aksiyon listesi çıkar ve dosyaya kaydet",
            "intent": "office_batch",
            "steps": [
                {"action": "read_file", "path": "~/Desktop/toplanti-notlari.txt"},
                {"action": "summarize_text", "params": {"text": "..."}},
                {"action": "write_file", "path": "~/Desktop/aksiyonlar.txt", "content": "..."},
            ],
        }
    ]


def _automation_fewshot() -> List[Dict[str, Any]]:
    return [
        {
            "user": "Her gün 09:00'da satış raporunu özetle görevi kur",
            "intent": "automation_batch",
            "steps": [
                {
                    "action": "create_automation",
                    "params": {
                        "name": "Satis Raporu Ozeti",
                        "schedule": "daily 09:00",
                        "prompt": "Satis raporunu ozetle ve kritik trendleri cikar",
                    },
                },
            ],
        }
    ]


def get_domain_fewshot(domain: str) -> List[Dict[str, Any]]:
    domain = str(domain or "").lower()
    if domain in {"fs", "filesystem"}:
        return _fs_fewshot()
    if domain in {"api", "http"}:
        return _api_fewshot()
    if domain in {"research", "analysis"}:
        return _research_fewshot()
    if domain in {"code", "coding", "software", "dev"}:
        return _code_fewshot()
    if domain in {"office", "document"}:
        return _office_fewshot()
    if domain in {"automation", "cron", "scheduler"}:
        return _automation_fewshot()
    return []


__all__ = ["get_domain_fewshot"]
