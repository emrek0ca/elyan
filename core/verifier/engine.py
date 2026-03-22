import pathlib
from typing import Any, Dict, List, Optional
from core.protocol.shared_types import VerificationStatus
from core.observability.logger import get_structured_logger

slog = get_structured_logger("verification_engine")

class VerificationEngine:
    """
    Verifies that capability actions actually performed their intended work.
    """
    async def verify_action(self, capability: str, action: str, params: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs verification logic for a completed action.
        """
        if result.get("status") != "success":
            return {"status": VerificationStatus.FAILED, "reason": "Action reported failure"}

        if capability == "filesystem":
            return await self._verify_filesystem(action, params, result)
        
        if capability == "terminal":
            return await self._verify_terminal(action, params, result)

        return {"status": VerificationStatus.INCONCLUSIVE, "reason": "No verification logic for this capability"}

    async def _verify_filesystem(self, action: str, params: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path")
        if not path:
            return {"status": VerificationStatus.INCONCLUSIVE, "reason": "No path provided in params"}

        p = pathlib.Path(path).expanduser().resolve()
        
        if action == "write_file":
            if p.exists() and p.is_file():
                # We could also check content hash/size here
                return {"status": VerificationStatus.PASSED, "evidence": {"path_exists": True, "size": p.stat().st_size}}
            else:
                return {"status": VerificationStatus.FAILED, "reason": f"File {path} does not exist after write"}

        if action == "trash_file":
            if not p.exists():
                return {"status": VerificationStatus.PASSED, "evidence": {"path_removed": True}}
            else:
                return {"status": VerificationStatus.FAILED, "reason": f"File {path} still exists after trash"}

        return {"status": VerificationStatus.INCONCLUSIVE}

    async def _verify_terminal(self, action: str, params: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        exit_code = result.get("exit_code")
        if exit_code == 0:
            return {"status": VerificationStatus.PASSED, "evidence": {"exit_code": 0}}
        else:
            return {"status": VerificationStatus.FAILED, "reason": f"Command exited with code {exit_code}"}

# Global instance
verification_engine = VerificationEngine()
