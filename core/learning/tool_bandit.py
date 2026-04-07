from __future__ import annotations

import json
import math
import os
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from core.events.read_model import get_run_read_model
from core.observability.logger import get_structured_logger

slog = get_structured_logger("tool_bandit")


def _default_state_path() -> Path:
    return Path(os.path.expanduser("~/.elyan/tool_bandit_state.json")).expanduser()


@dataclass
class ToolArm:
    tool_name: str
    total_reward: float = 0.0
    pull_count: int = 0
    success_count: int = 0
    avg_latency_ms: float = 0.0

    def ucb1_score(self, total_pulls: int, c: float = 2.0) -> float:
        if self.pull_count == 0:
            return float("inf")
        exploitation = self.total_reward / self.pull_count
        exploration = c * math.sqrt(math.log(max(total_pulls, 1)) / self.pull_count)
        return exploitation + exploration

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ToolSelectionBandit:
    def __init__(self, state_path: str | Path | None = None, *, exploration_constant: float = 2.0):
        self.state_path = Path(state_path or _default_state_path()).expanduser()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.exploration_constant = float(exploration_constant)
        self._lock = RLock()
        self.arms: Dict[str, Dict[str, ToolArm]] = {}
        self._dirty_count = 0
        self._load()
        self._bootstrap_from_read_model()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            for category, arms in raw.get("arms", {}).items():
                if not isinstance(arms, dict):
                    continue
                self.arms[category] = {}
                for tool_name, payload in arms.items():
                    if isinstance(payload, dict):
                        self.arms[category][tool_name] = ToolArm(
                            tool_name=str(payload.get("tool_name") or tool_name),
                            total_reward=float(payload.get("total_reward") or 0.0),
                            pull_count=int(payload.get("pull_count") or 0),
                            success_count=int(payload.get("success_count") or 0),
                            avg_latency_ms=float(payload.get("avg_latency_ms") or 0.0),
                        )
        except Exception as exc:
            slog.log_event("bandit_load_error", {"error": str(exc)}, level="warning")

    def _persist(self) -> None:
        try:
            payload = {
                "arms": {
                    category: {tool_name: arm.to_dict() for tool_name, arm in category_arms.items()}
                    for category, category_arms in self.arms.items()
                }
            }
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)
            self._dirty_count = 0
        except Exception as exc:
            slog.log_event("bandit_persist_error", {"error": str(exc)}, level="warning")

    def _bootstrap_from_read_model(self) -> None:
        try:
            perf = get_run_read_model().get_tool_performance()
        except Exception as exc:
            slog.log_event("bandit_bootstrap_error", {"error": str(exc)}, level="warning")
            return
        if not perf:
            return
        bootstrap = self.arms.setdefault("_bootstrap", {})
        for row in perf:
            tool_name = str(row.get("tool_name") or "").strip()
            if not tool_name:
                continue
            total = int(row.get("total_calls") or 0)
            success_count = int(row.get("success_count") or 0)
            failure_count = int(row.get("failure_count") or 0)
            success_rate = success_count / max(total, 1)
            reward = success_rate * max(total, 1)
            bootstrap[tool_name] = ToolArm(
                tool_name=tool_name,
                total_reward=reward,
                pull_count=total,
                success_count=success_count,
                avg_latency_ms=float(row.get("avg_latency_ms") or 0.0),
            )
            if failure_count:
                bootstrap[tool_name].total_reward -= min(failure_count * 0.25, bootstrap[tool_name].pull_count * 0.25)

    def _get_category_arms(self, task_category: str) -> Dict[str, ToolArm]:
        category = str(task_category or "default").strip().lower() or "default"
        if category not in self.arms:
            source = self.arms.get("_bootstrap", {})
            self.arms[category] = {
                name: ToolArm(
                    tool_name=arm.tool_name,
                    total_reward=arm.total_reward,
                    pull_count=arm.pull_count,
                    success_count=arm.success_count,
                    avg_latency_ms=arm.avg_latency_ms,
                )
                for name, arm in source.items()
            }
        return self.arms[category]

    def select_tool(self, task_category: str, available_tools: List[str]) -> str:
        tools = [str(tool).strip() for tool in available_tools if str(tool).strip()]
        if not tools:
            raise ValueError("available_tools cannot be empty")
        with self._lock:
            category_arms = self._get_category_arms(task_category)
            for tool in tools:
                category_arms.setdefault(tool, ToolArm(tool_name=tool))
            total_pulls = sum(arm.pull_count for arm in category_arms.values()) or 1
            scores = {
                tool: category_arms[tool].ucb1_score(total_pulls, c=self.exploration_constant)
                for tool in tools
            }
            best_score = max(scores.values())
            candidates = [tool for tool, score in scores.items() if score == best_score]
            return sorted(candidates)[0]

    def record_outcome(
        self,
        task_category: str,
        tool_name: str,
        success: bool,
        latency_ms: float,
        user_satisfaction: float = 0.5,
    ) -> None:
        category = str(task_category or "default").strip().lower() or "default"
        tool = str(tool_name or "").strip()
        if not tool:
            return
        with self._lock:
            category_arms = self._get_category_arms(category)
            arm = category_arms.setdefault(tool, ToolArm(tool_name=tool))
            speed_score = max(0.0, 1.0 - float(latency_ms or 0.0) / 10000.0)
            reward = 0.6 * float(bool(success)) + 0.2 * speed_score + 0.2 * float(user_satisfaction or 0.0)
            arm.total_reward += reward
            arm.pull_count += 1
            arm.success_count += 1 if success else 0
            arm.avg_latency_ms = 0.9 * arm.avg_latency_ms + 0.1 * float(latency_ms or 0.0)
            self._dirty_count += 1
            if self._dirty_count >= 10:
                self._persist()

    def disable_tool(self, task_category: str, tool_name: str) -> None:
        with self._lock:
            category_arms = self._get_category_arms(task_category)
            arm = category_arms.setdefault(str(tool_name), ToolArm(tool_name=str(tool_name)))
            arm.total_reward -= max(1.0, arm.pull_count * 0.5)
            arm.pull_count += 1
            self._dirty_count += 1
            if self._dirty_count >= 10:
                self._persist()

    def get_insights(self) -> Dict[str, Any]:
        with self._lock:
            insights: Dict[str, Any] = {}
            for category, arms in self.arms.items():
                if not arms:
                    continue
                total_pulls = sum(arm.pull_count for arm in arms.values()) or 1
                ranked = sorted(
                    arms.values(),
                    key=lambda arm: arm.ucb1_score(total_pulls, c=self.exploration_constant),
                    reverse=True,
                )
                best = ranked[0]
                total_calls = max(sum(arm.pull_count for arm in arms.values()), 1)
                success_total = sum(arm.success_count for arm in arms.values())
                avg_latency = sum(arm.avg_latency_ms * max(arm.pull_count, 1) for arm in arms.values()) / total_calls
                insights[category] = {
                    "best_tool": best.tool_name,
                    "success_rate": success_total / total_calls,
                    "avg_latency_ms": avg_latency,
                    "confidence": best.pull_count,
                }
            return insights

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "arms": {
                    category: {tool_name: arm.to_dict() for tool_name, arm in tools.items()}
                    for category, tools in self.arms.items()
                }
            }

    def persist(self) -> None:
        with self._lock:
            self._persist()


_tool_bandit: Optional[ToolSelectionBandit] = None


def get_tool_bandit() -> ToolSelectionBandit:
    global _tool_bandit
    if _tool_bandit is None:
        _tool_bandit = ToolSelectionBandit()
    return _tool_bandit
