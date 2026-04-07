import pathlib
from typing import Any, Dict, List, Optional
from core.execution_guard import ExecutionCheck, get_execution_guard
from core.protocol.shared_types import VerificationStatus
from core.observability.logger import get_structured_logger

slog = get_structured_logger("verification_engine")

class VerificationEngine:
    """
    Verifies that capability actions actually performed their intended work.
    """
    @staticmethod
    def _identity_from_params(params: Dict[str, Any], result: Dict[str, Any]) -> dict[str, str]:
        params = params if isinstance(params, dict) else {}
        result = result if isinstance(result, dict) else {}
        params_metadata = params.get("metadata") if isinstance(params.get("metadata"), dict) else {}
        result_metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        return {
            "workspace_id": str(
                params.get("workspace_id")
                or params_metadata.get("workspace_id")
                or result.get("workspace_id")
                or result_metadata.get("workspace_id")
                or "local-workspace"
            ).strip() or "local-workspace",
            "session_id": str(
                params.get("session_id")
                or params_metadata.get("session_id")
                or result.get("session_id")
                or result_metadata.get("session_id")
                or ""
            ).strip(),
            "run_id": str(
                params.get("run_id")
                or params_metadata.get("run_id")
                or result.get("run_id")
                or result_metadata.get("run_id")
                or ""
            ).strip(),
            "actor_id": str(
                params.get("actor_id")
                or params.get("user_id")
                or params_metadata.get("actor_id")
                or result.get("actor_id")
                or result_metadata.get("actor_id")
                or ""
            ).strip(),
        }

    def _observe_guard(
        self,
        *,
        capability: str,
        action: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
        verification: Dict[str, Any],
        level: str = "info",
    ) -> None:
        identity = self._identity_from_params(params, result)
        status = verification.get("status")
        normalized_status = status.value if hasattr(status, "value") else str(status or "").strip().lower()
        get_execution_guard().observe_shadow(
            action=f"{str(capability or '').strip().lower()}.{str(action or '').strip().lower()}",
            phase="verification_result",
            allowed=normalized_status != VerificationStatus.FAILED.value,
            workspace_id=identity["workspace_id"],
            actor_id=identity["actor_id"],
            session_id=identity["session_id"],
            run_id=identity["run_id"],
            reason=str(verification.get("reason") or ""),
            checks=[
                ExecutionCheck(
                    name="verification_result",
                    allowed=normalized_status == VerificationStatus.PASSED.value,
                    reason=str(verification.get("reason") or ""),
                    metadata={
                        "status": normalized_status,
                        "capability": str(capability or "").strip().lower(),
                        "action": str(action or "").strip().lower(),
                    },
                )
            ],
            metadata={
                "verification": verification,
                "result_status": str(result.get("status") or ""),
            },
            level=level,
        )

    async def verify_action(self, capability: str, action: str, params: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs verification logic for a completed action.
        """
        if result.get("status") != "success":
            verification = {"status": VerificationStatus.FAILED, "reason": "Action reported failure"}
            self._observe_guard(
                capability=capability,
                action=action,
                params=params,
                result=result,
                verification=verification,
                level="warning",
            )
            return verification

        if capability == "filesystem":
            verification = await self._verify_filesystem(action, params, result)
            self._observe_guard(
                capability=capability,
                action=action,
                params=params,
                result=result,
                verification=verification,
                level="warning" if verification.get("status") == VerificationStatus.FAILED else "info",
            )
            return verification
        
        if capability == "terminal":
            verification = await self._verify_terminal(action, params, result)
            self._observe_guard(
                capability=capability,
                action=action,
                params=params,
                result=result,
                verification=verification,
                level="warning" if verification.get("status") == VerificationStatus.FAILED else "info",
            )
            return verification

        verification = {"status": VerificationStatus.INCONCLUSIVE, "reason": "No verification logic for this capability"}
        self._observe_guard(
            capability=capability,
            action=action,
            params=params,
            result=result,
            verification=verification,
            level="debug",
        )
        return verification

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
