"""Compatibility wrapper around the canonical computer-use engine."""

from elyan.computer_use.engine import (
    ComputerAction,
    ComputerUseEngine as ComputerUseTool,
    ComputerUseTask,
    get_computer_use_engine,
)


def get_computer_use_tool(max_steps: int = 25) -> ComputerUseTool:
    return get_computer_use_engine(max_steps=max_steps)


__all__ = ["ComputerAction", "ComputerUseTask", "ComputerUseTool", "get_computer_use_tool"]
