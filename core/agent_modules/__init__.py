"""
Agent Modules — Modular decomposition of core/agent.py

This package provides a clean separation of concerns for the monolithic agent.py.
New features should be implemented as modules here rather than adding to agent.py.

Architecture:
    agent.py (facade) → agent_modules/
        ├── planner.py      — Task planning and decomposition
        ├── executor.py     — Tool execution and orchestration
        ├── verifier.py     — Output verification and quality assurance
        └── reporter.py     — Response formatting and delivery

Integration:
    The Agent class in agent.py delegates to these modules via:
        self.planner = AgentPlanner(self)
        self.executor = AgentExecutor(self)
        self.verifier = AgentVerifier(self)
        self.reporter = AgentReporter(self)
"""

from core.agent_modules.planner import AgentPlanner
from core.agent_modules.executor import AgentExecutor
from core.agent_modules.verifier import AgentVerifier
from core.agent_modules.reporter import AgentReporter

__all__ = ["AgentPlanner", "AgentExecutor", "AgentVerifier", "AgentReporter"]
