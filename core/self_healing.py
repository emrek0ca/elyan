"""
core/self_healing.py
─────────────────────────────────────────────────────────────────────────────
Autonomous error diagnosis and recovery strategies for Elyan.
Analyzes failures and suggests or executes healing actions.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("self_healing")

class RecoveryStrategy:
    def __init__(self, name: str, pattern: str, recovery_action: str, description: str):
        self.name = name
        self.pattern = pattern
        self.recovery_action = recovery_action
        self.description = description

class SelfHealingEngine:
    def __init__(self):
        self.strategies = [
            RecoveryStrategy(
                "permission_denied",
                r"Permission denied|PermissionError|access is denied",
                "suggest_home_path",
                "Dosya erişim izni yok. İşlemi Desktop veya Home dizininde denemeyi öner."
            ),
            RecoveryStrategy(
                "port_in_use",
                r"Address already in use|OSError: \[Errno 48\]|port is already allocated",
                "find_and_kill_process",
                "İstenen port dolu. Portu kullanan prosesi bul ve kapatmayı teklif et."
            ),
            RecoveryStrategy(
                "module_not_found",
                r"ModuleNotFoundError: No module named '([^']+)'",
                "attempt_install",
                "Eksik Python kütüphanesi bulundu. Otomatik kurulumu dene."
            ),
            RecoveryStrategy(
                "timeout",
                r"timeout|timed out|DeadlineExceeded",
                "increase_timeout_retry",
                "İşlem zaman aşımına uğradı. Kaynakları kontrol et ve süreyi artır."
            ),
            RecoveryStrategy(
                "command_not_found",
                r"command not found|sh: 1: ([^:]+): not found",
                "check_path_and_install",
                "Sistem komutu bulunamadı. PATH kontrolü yap veya brew/apt ile kurmayı öner."
            )
        ]

    def diagnose(self, error_text: str) -> Optional[RecoveryStrategy]:
        """Hata metninden uygun kurtarma stratejisini bulur."""
        for strategy in self.strategies:
            if re.search(strategy.pattern, error_text, re.IGNORECASE):
                return strategy
        return None

    async def get_healing_plan(self, strategy: RecoveryStrategy, error_text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Teşhis edilen hata için somut bir iyileştirme planı üretir."""
        tool_name = context.get("tool_name", "unknown")
        params = context.get("params", {})
        
        plan = {
            "strategy": strategy.name,
            "description": strategy.description,
            "action_type": strategy.recovery_action,
            "can_auto_fix": False,
            "suggested_params": params.copy()
        }

        if strategy.name == "permission_denied":
            # Path parametresini Desktop'a çevirerek iyileştirme öner
            if "path" in params:
                from pathlib import Path
                old_path = Path(params["path"])
                new_path = str(Path.home() / "Desktop" / old_path.name)
                plan["suggested_params"]["path"] = new_path
                plan["can_auto_fix"] = True
                plan["message"] = f"Erişim engellendi. Dosyayı şuraya yazmayı deniyorum: {new_path}"

        elif strategy.name == "module_not_found":
            match = re.search(strategy.pattern, error_text)
            module = match.group(1) if match else "unknown"
            plan["module"] = module
            plan["message"] = f"Eksik '{module}' kütüphanesi tespit edildi. Kurulması gerekiyor."
            # Sadece belirli güvenli araçlar için otomatik kuruluma izin verilebilir
            if tool_name in ["write_word", "write_excel"]:
                plan["can_auto_fix"] = True
                plan["fix_command"] = f"pip install {module}"

        return plan

_healing_engine = SelfHealingEngine()

def get_healing_engine() -> SelfHealingEngine:
    return _healing_engine
