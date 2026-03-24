"""Evidence Recording Module

Record and manage evidence from computer use tasks:
- Screenshots
- Action traces
- Video recordings (optional)
- Audit logs
"""

from .recorder import ComputerUseRecorder, get_evidence_recorder

__all__ = [
    "ComputerUseRecorder",
    "get_evidence_recorder",
]
