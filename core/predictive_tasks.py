"""
Predictive Task Readiness & Prefetching Engine
Analyzes execution context to predict next probable steps and prefetch dependencies/assets.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

from core.intelligent_planner import SubTask, ExecutionPlan
from core.llm_client import LLMClient
from utils.logger import get_logger

logger = get_logger("predictive_tasks")

class PredictionConfidence(Enum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2

@dataclass
class TaskPrediction:
    """Represents a predicted future task"""
    action: str
    params: Dict[str, Any]
    confidence: PredictionConfidence
    reasoning: str
    prefetched_data: Optional[Any] = None

class PredictiveTaskEngine:
    """
    Engine for predicting and preparing for future tasks.
    """
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self._predictions_cache: Dict[str, List[TaskPrediction]] = {}

    async def predict_next_steps(self, current_step: SubTask, plan: Optional[ExecutionPlan] = None) -> List[TaskPrediction]:
        """
        Predicts probable next steps based on the current step and the overall plan.
        """
        predictions = []
        
        # 1. Heuristic Rules (Fast)
        heuristic_preds = self._apply_heuristic_rules(current_step)
        predictions.extend(heuristic_preds)

        # 2. Plan-Context Analysis (Deterministic)
        if plan:
            next_task = self._get_next_planned_task(plan, current_step)
            if next_task:
                predictions.append(TaskPrediction(
                    action=next_task.action,
                    params=next_task.params,
                    confidence=PredictionConfidence.HIGH,
                    reasoning=f"Explicitly planned step: {next_task.name}"
                ))

        # 3. LLM-Based Prediction (Slow but Smart)
        # Only use LLM if we don't have high confidence predictions yet, to save tokens/time
        if not any(p.confidence == PredictionConfidence.HIGH for p in predictions) and self.llm:
             try:
                 llm_preds = await self._predict_with_llm(current_step)
                 predictions.extend(llm_preds)
             except Exception as e:
                 logger.warning(f"LLM prediction failed: {e}")

        return predictions

    def _get_next_planned_task(self, plan: ExecutionPlan, current_step: SubTask) -> Optional[SubTask]:
        """Finds the next pending task in the linear sequence of the plan."""
        found_current = False
        for task in plan.subtasks:
            if found_current:
                # Return the immediate next task
                return task
            if task.task_id == current_step.task_id:
                found_current = True
        return None

    async def _predict_with_llm(self, current_step: SubTask) -> List[TaskPrediction]:
        """Asks LLM to predict the next logical step."""
        if not self.llm:
            return []

        prompt = f"""Analyze the current executed action and predict the single most likely next tool action.
Current Action: {current_step.action}
Params: {current_step.params}

Available Tools: write_file, read_file, web_search, run_code, open_app, send_message.

Return JSON only:
{{
  "action": "tool_name",
  "params": {{ "key": "value" }},
  "confidence": "MEDIUM",
  "reasoning": "explanation"
}}
"""
        try:
            response = await self.llm.generate(prompt, max_tokens=200)
            # Extract JSON from response
            match = re.search(r"\{[\s\S]*\}", response)
            if not match:
                return []
            
            data = json.loads(match.group(0))
            conf_str = data.get("confidence", "LOW").upper()
            confidence = PredictionConfidence[conf_str] if conf_str in PredictionConfidence.__members__ else PredictionConfidence.LOW
            
            return [TaskPrediction(
                action=data.get("action", ""),
                params=data.get("params", {}),
                confidence=confidence,
                reasoning=data.get("reasoning", "LLM prediction")
            )]
        except Exception:
            return []

    def _apply_heuristic_rules(self, step: SubTask) -> List[TaskPrediction]:
        """Apply static rules to predict next steps."""
        preds = []
        action = str(step.action or "").lower()
        
        # Rule: Research -> Report/Document
        if action in ("advanced_research", "web_search", "deep_research"):
            preds.append(TaskPrediction(
                action="write_file",
                params={"path": "report.md", "content": "{{last_output}}"}, # Placeholder
                confidence=PredictionConfidence.HIGH,
                reasoning="Research is usually followed by documenting findings."
            ))
            preds.append(TaskPrediction(
                action="write_word",
                params={"path": "report.docx"},
                confidence=PredictionConfidence.MEDIUM,
                reasoning="Research often leads to formal documentation."
            ))

        # Rule: Coding Project Scaffold -> Implementation/Open IDE
        if action in ("create_web_project_scaffold", "create_software_project_pack"):
             preds.append(TaskPrediction(
                action="open_project_in_ide",
                params={"project_path": step.params.get("output_dir", "")}, 
                confidence=PredictionConfidence.HIGH,
                reasoning="Creating a project usually implies opening it."
            ))

        # Rule: Plan -> Execute (Generic)
        if action == "create_plan":
             preds.append(TaskPrediction(
                action="execute_plan", # Hypothetical action
                params={}, 
                confidence=PredictionConfidence.HIGH,
                reasoning="Planning is followed by execution."
            ))

        return preds

    async def prefetch_dependencies(self, predictions: List[TaskPrediction]):
        """
        Executes low-cost preparatory actions for high-confidence predictions.
        """
        # Lazy import for push_activity
        try:
            from core.gateway.server import push_activity
        except ImportError:
            push_activity = None

        for pred in predictions:
            if pred.confidence == PredictionConfidence.HIGH:
                logger.info(f"Prefetching for predicted action: {pred.action} ({pred.reasoning})")
                
                if push_activity:
                    push_activity(
                        "prediction", 
                        "brain", 
                        f"Hazırlanıyor: {pred.action} ({pred.reasoning})", 
                        success=True
                    )
                
                # Check tool availability (simple check)
                from tools import AVAILABLE_TOOLS
                if pred.action not in AVAILABLE_TOOLS:
                    logger.debug(f"Predicted tool {pred.action} not available, skipping prefetch.")
                    continue

                # Generate draft content if applicable
                if pred.action in ("write_file", "write_word") and self.llm:
                    draft = await self._generate_draft_content(pred)
                    if draft:
                        pred.prefetched_data = {"content": draft}
                        self._predictions_cache[pred.action] = [pred] # Simple cache keying by action
                        logger.info(f"Draft content generated for {pred.action}")

    async def _generate_draft_content(self, prediction: TaskPrediction) -> Optional[str]:
        """Generates a quick draft for file writing tasks."""
        if not self.llm:
            return None
            
        try:
            # Contextual prompt for draft generation
            prompt = (
                f"Prepare a draft content for a file. \n"
                f"Action: {prediction.action}\n"
                f"Context: {prediction.reasoning}\n"
                f"Params: {prediction.params}\n"
                "Return ONLY the file content, no markdown code blocks unless it's code."
            )
            # Use a faster/cheaper model logic if available, here just standard generate
            return await self.llm.generate(prompt, max_tokens=1000)
        except Exception as e:
            logger.warning(f"Failed to generate draft: {e}")
            return None

    def get_prefetched_content(self, action: str) -> Optional[str]:
        """Retrieve prefetched content for a given action."""
        preds = self._predictions_cache.get(action)
        if preds:
            # Return the first available draft and clear it (one-time use)
            for pred in preds:
                if pred.prefetched_data and "content" in pred.prefetched_data:
                    content = pred.prefetched_data["content"]
                    # Cleanup used prediction
                    self._predictions_cache[action].remove(pred)
                    return content
        return None

# Global instance
_predictive_engine = None

def get_predictive_task_engine() -> PredictiveTaskEngine:
    global _predictive_engine
    if _predictive_engine is None:
        try:
            from core.kernel import kernel
            client = kernel.llm
        except ImportError:
            client = None
        _predictive_engine = PredictiveTaskEngine(llm_client=client)
    return _predictive_engine
