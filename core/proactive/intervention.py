"""
core/proactive/intervention.py
─────────────────────────────────────────────────────────────────────────────
Manages interactive decision points where the agent needs human guidance.
Enables "pause and resume" capability for risky or ambiguous tasks.
"""

from __future__ import annotations
import asyncio
import inspect
import uuid
import time
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("proactive.intervention")

class InterventionRequest:
    def __init__(self, prompt: str, context: Dict[str, Any], options: Optional[List[str]] = None):
        self.id = str(uuid.uuid4())[:8]
        self.prompt = prompt
        self.context = context
        self.options = options or ["Onayla", "İptal Et"]
        self.created_at = time.time()
        self.response: Optional[str] = None
        self.event = asyncio.Event()

class InterventionManager:
    def __init__(self):
        self._pending: Dict[str, InterventionRequest] = {}
        self._listeners: List[Any] = []

    def register_listener(self, listener: Any) -> None:
        """Register a callback notified for new intervention requests."""
        if not callable(listener):
            return
        if listener in self._listeners:
            return
        self._listeners.append(listener)

    def unregister_listener(self, listener: Any) -> None:
        """Remove a previously registered callback."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify_listeners(self, request: InterventionRequest) -> None:
        """Fan-out new intervention requests to channel bridges."""
        for listener in list(self._listeners):
            try:
                result = listener(request)
                if inspect.isawaitable(result):
                    asyncio.create_task(result)
            except Exception as exc:
                logger.debug(f"Intervention listener failed: {exc}")

    async def ask_human(self, prompt: str, context: Dict[str, Any], options: Optional[List[str]] = None) -> str:
        """Ajandan kullanıcıya soru sorar ve yanıt gelene kadar bekler."""
        request = InterventionRequest(prompt, context, options)
        self._pending[request.id] = request
        
        logger.info(f"Intervention Required [{request.id}]: {prompt}")
        self._notify_listeners(request)
        
        # Dashboard üzerinden yanıt gelene kadar bekle
        try:
            # Max 5 dakika bekleme süresi
            await asyncio.wait_for(request.event.wait(), timeout=300.0)
            return request.response or "timeout"
        except asyncio.TimeoutError:
            logger.warning(f"Intervention Timeout [{request.id}]")
            return "timeout"
        finally:
            self._pending.pop(request.id, None)

    def resolve(self, request_id: str, response: str):
        """Kullanıcı yanıtını sisteme iletir."""
        if request_id in self._pending:
            req = self._pending[request_id]
            req.response = response
            req.event.set()
            return True
        return False

    def list_pending(self) -> List[Dict[str, Any]]:
        """Bekleyen tüm müdahale isteklerini listeler."""
        return [
            {
                "id": req.id,
                "prompt": req.prompt,
                "options": req.options,
                "context": req.context,
                "ts": req.created_at
            }
            for req in self._pending.values()
        ]

_manager = InterventionManager()

def get_intervention_manager() -> InterventionManager:
    return _manager
