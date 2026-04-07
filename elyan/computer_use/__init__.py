"""
Elyan Computer Use Module

Claude Computer Use compatible local desktop control:
- Screenshot capture & VLM analysis
- Action planning & execution
- Approval workflow integration
- Full audit trail & evidence recording

Status: v0.3.0 (Preview)
"""

from .engine import ComputerUseEngine, get_computer_use_engine
from .tool import ComputerUseTool, ComputerAction, ComputerUseTask

__all__ = [
    "ComputerUseTool",
    "ComputerUseEngine",
    "ComputerAction",
    "ComputerUseTask",
    "get_computer_use_engine",
]
