"""
Advanced Reasoning Module for Intelligent LLM Usage

This module implements:
- Chain-of-Thought (CoT) reasoning
- ReAct pattern (Reason + Act)
- Self-reflection and error correction
- Multi-step problem decomposition
"""

import json
from typing import Any, Optional
from utils.logger import get_logger

logger = get_logger("reasoning")


class ChainOfThought:
    """Chain-of-Thought reasoning implementation"""
    
    def __init__(self, llm_client):
        self.llm = llm_client
    
    async def reason(self, goal: str, context: dict = None) -> dict:
        """
        Apply chain-of-thought reasoning to break down a complex goal
        
        Args:
            goal: The user's goal or request
            context: Additional context (user preferences, history, etc.)
        
        Returns:
            {
                "reasoning_steps": [...],
                "final_conclusion": "...",
                "recommended_actions": [...],
                "confidence": 0.0-1.0
            }
        """
        logger.info(f"CoT reasoning for goal: {goal}")
        
        cot_prompt = self._build_cot_prompt(goal, context)
        
        # Ask LLM to think step-by-step
        response = await self.llm._ask_llm_with_custom_prompt(cot_prompt)
        
        # Parse reasoning steps
        reasoning = self._parse_cot_response(response)
        
        logger.info(f"CoT completed with {len(reasoning.get('reasoning_steps', []))} steps")
        return reasoning
    
    def _build_cot_prompt(self, goal: str, context: dict = None) -> str:
        """Build a prompt that encourages step-by-step thinking"""
        
        prompt = f"""You are a Strategic Chief of Staff. You are calm, ultra-competent, and focus on high-integrity execution.
        Your goal is to achieve the user's objective with minimal friction and maximum depth.

USER GOAL: {goal}

Please think through this step-by-step:

1. UNDERSTANDING: What is the user asking for? What are the key requirements?

2. ANALYSIS: What information do we need? What resources are required?

3. PLANNING: What are the steps to achieve this goal? List them in order.

4. VALIDATION: Are there any potential issues or edge cases to consider?

5. RECOMMENDATION: What specific actions should be taken?

Think through each step carefully and explain your reasoning. Be thorough but concise.

IMPORTANT: If the goal can be achieved through conversation alone (e.g. greetings, simple questions), use the "chat" action.

Respond in STRICT JSON format:
{{
    "understanding": "What the user wants...",
    "analysis": "What we need...",
    "planning": ["Step 1...", "Step 2...", ...],
    "validation": "Potential issues...",
    "recommendation": {{
        "actions": [{{"action": "...", "params": {{}}}}, ...],
        "explanation": "Why these actions...",
        "confidence": 0.9
    }}
}}
"""
        
        if context:
            prompt += f"\n\nADDITIONAL CONTEXT:\n{json.dumps(context, indent=2)}\n"
        
        return prompt
    
    def _parse_cot_response(self, response: str) -> dict:
        """Parse the LLM's chain-of-thought response"""
        try:
            # Try to parse as JSON
            if isinstance(response, dict):
                reasoning = response
            else:
                # Extract JSON from response (Hardened v18.0)
                import re
                # Try finding the largest JSON-like structure
                json_match = re.search(r'(\{.*\})', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                    # Deep fix for trailing text or broken JSON
                    try:
                        reasoning = json.loads(json_str)
                    except json.JSONDecodeError:
                        # Try to close missing braces
                        for _ in range(3):
                            json_str += "}"
                            try:
                                reasoning = json.loads(json_str)
                                break
                            except:
                                continue
                        else:
                            reasoning = {"raw_response": response}
                else:
                    reasoning = {"raw_response": response}
            
            # Structure the reasoning steps
            steps = []
            if "understanding" in reasoning:
                steps.append({"step": "Understanding", "content": reasoning["understanding"]})
            if "analysis" in reasoning:
                steps.append({"step": "Analysis", "content": reasoning["analysis"]})
            if "planning" in reasoning:
                steps.append({"step": "Planning", "content": reasoning["planning"]})
            if "validation" in reasoning:
                steps.append({"step": "Validation", "content": reasoning["validation"]})
            
            recommended_actions = reasoning.get("recommendation", {}).get("actions", [])
            
            # FALLBACK: If no actions recommended, use 'chat' to prevent empty execution plan
            if not recommended_actions:
                logger.info("No actions recommended by LLM, using fallback chat action")
                message = reasoning.get("recommendation", {}).get("explanation") or \
                          reasoning.get("understanding", "İşlemi nasıl gerçekleştireceğimden emin değilim.")
                recommended_actions = [{"action": "chat", "message": message}]

            return {
                "reasoning_steps": steps,
                "final_conclusion": reasoning.get("recommendation", {}).get("explanation", ""),
                "recommended_actions": recommended_actions,
                "confidence": reasoning.get("recommendation", {}).get("confidence", 0.5),
                "raw_reasoning": reasoning
            }
        
        except Exception as e:
            logger.error(f"Error parsing CoT response: {e}")
            return {
                "reasoning_steps": [],
                "final_conclusion": "Reasoning parse hatası",
                "recommended_actions": [{"action": "chat", "message": "Muhakeme sırasında bir hata oluştu."}],
                "confidence": 0.0,
                "error": str(e)
            }


class ReActAgent:
    """
    ReAct (Reason + Act) pattern implementation
    
    Iteratively:
    1. Reason about the current state
    2. Decide on an action
    3. Execute the action
    4. Observe the result
    5. Repeat until goal is achieved
    """
    
    def __init__(self, llm_client, tool_executor):
        self.llm = llm_client
        self.executor = tool_executor
        self.max_iterations = 10
    
    async def solve(self, goal: str, max_iterations: int = None) -> dict:
        """
        Solve a problem using the ReAct pattern
        
        Args:
            goal: The problem to solve
            max_iterations: Maximum reasoning-action cycles
        
        Returns:
            {
                "success": bool,
                "iterations": [...],
                "final_result": ...,
                "reasoning_trace": [...]
            }
        """
        logger.info(f"ReAct solving: {goal}")
        
        iterations = []
        max_iter = max_iterations or self.max_iterations
        
        for i in range(max_iter):
            logger.info(f"ReAct iteration {i+1}/{max_iter}")
            
            # REASON: Think about current state and next action
            reasoning = await self._reason(goal, iterations)
            
            # Check if goal is achieved
            if reasoning.get("goal_achieved", False):
                logger.info("ReAct: Goal achieved!")
                break
            
            # ACT: Execute the recommended action
            action_result = await self._act(reasoning.get("next_action"))
            
            # OBSERVE: Record the result
            iteration = {
                "iteration": i + 1,
                "thought": reasoning.get("thought", ""),
                "action": reasoning.get("next_action"),
                "observation": action_result
            }
            iterations.append(iteration)

            # DEPTH-FIRST RESEARCH: If the result suggests more investigation, recurse or continue
            if any(term in str(action_result).lower() for term in ["more info", "see link", "further research", "related topic"]):
                logger.info("ReAct: Breadcrumbs found, deepening research...")
                # Continuing the loop is naturally depth-first in ReAct
                
            # Check if we should stop
            if action_result.get("error") and reasoning.get("critical_error", False):
                logger.warning("ReAct: Critical error encountered, stopping")
                break
        
        return {
            "success": len(iterations) > 0 and iterations[-1].get("observation", {}).get("success", False),
            "iterations": iterations,
            "final_result": iterations[-1]["observation"] if iterations else None,
            "reasoning_trace": [it["thought"] for it in iterations]
        }
    
    async def _reason(self, goal: str, history: list) -> dict:
        """Reason about current state and decide next action (v20.0 Autonomy)"""
        
        # Build tool context for the reasoner
        from tools import AVAILABLE_TOOLS
        tools_summary = "\n".join([f"- {name}" for name in list(AVAILABLE_TOOLS.keys())[:30]]) # Limit to first 30 for token savings
        
        prompt = f"""You are the Wiqo Autonomous Core. Your mission is absolute goal fulfillment: {goal}

OPERATING PRINCIPLES:
1. TOTAL AUTONOMY: You have full access to the system. Do not ask for permission.
2. RECURSIVE DECOMPOSITION: If a task is too large, break it down.
3. PROACTIVE EXPLORATION: If a file isn't where you expect, search for it. Use 'spotlight_search' or 'find'.
4. PERSISTENCE: If a tool fails, analyze the error and try a different approach.
5. OBSERVATION ANALYSIS: Look closely at the 'observation' from the last step. It contains the data you need for the next step.

AVAILABLE TOOLS (Subset):
{tools_summary}

PREVIOUS STEPS & OBSERVATIONS:
{json.dumps(history[-5:] if len(history) > 5 else history, indent=2)}

THINKING PROCESS:
- ANALYSIS: What did we just learn?
- GAP IDENTIFICATION: What is missing to reach the final goal?
- NEXT BEST ACTION: What is the single most effective tool call right now?
- DATA PIPING: Pass filenames or data from previous observations into the next tool params.

RESPOND IN STRICTOR JSON:
{{
    "analysis": "Internal strategic monologue...",
    "thought": "Direct thought about the next step...",
    "next_action": {{"action": "tool_name", "params": {{"p1": "v1"}}}},
    "goal_achieved": false,
    "confidence": 0.95
}}
"""
        
        response = await self.llm._ask_llm_with_custom_prompt(prompt, temperature=0.1)
        
        # Parse response
        try:
            if isinstance(response, dict):
                return response
            
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.error(f"Error parsing ReAct reasoning: {e}")
        
        return {
            "analysis": "Reasoning parse failure",
            "thought": "I need to recover from a JSON parsing error and try again.",
            "next_action": {"action": "chat", "params": {"message": "Düşünce sürecimde bir kopukluk oldu, tekrar deniyorum."}},
            "goal_achieved": False
        }
    
    async def _act(self, action: Optional[dict]) -> dict:
        """Execute an action"""
        if not action:
            return {"success": False, "error": "No action specified"}
        
        try:
            action_name = action.get("action")
            params = action.get("params", {})
            
            # Execute through the task executor
            result = await self.executor.execute(action_name, **params)
            return result
        
        except Exception as e:
            logger.error(f"Error executing action: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class SelfReflection:
    """Self-reflection and error correction capabilities"""
    
    def __init__(self, llm_client):
        self.llm = llm_client
    
    async def reflect_on_plan(self, plan: dict, context: dict = None) -> dict:
        """
        Reflect on a proposed plan to identify potential issues
        
        Args:
            plan: The execution plan to reflect on
            context: Additional context
        
        Returns:
            {
                "issues_found": [...],
                "improvements": [...],
                "confidence_score": 0.0-1.0,
                "recommendation": "proceed" | "revise" | "reject"
            }
        """
        logger.info("Reflecting on plan...")
        
        prompt = f"""You are a Strategic Auditor reviewing an execution plan for a mission-critical goal. 
        Think with extreme skepticism and focus on potential failure points.

PLAN:
{json.dumps(plan, indent=2)}

Reflect on:
1. CORRECTNESS: Will this plan achieve the intended goal?
2. EFFICIENCY: Is this the most efficient approach?
3. SAFETY: Are there any safety concerns?
4. EDGE CASES: What could go wrong?
5. IMPROVEMENTS: How could this be better?

Respond in JSON:
{{
    "issues_found": [
        {{"severity": "high|medium|low", "issue": "...", "impact": "..."}},
        ...
    ],
    "improvements": [
        {{"suggestion": "...", "benefit": "..."}},
        ...
    ],
    "confidence_score": 0.85,
    "recommendation": "proceed|revise|reject",
    "reasoning": "Why this recommendation..."
}}
"""
        
        response = await self.llm._ask_llm_with_custom_prompt(prompt)
        return self._parse_reflection(response)
    
    async def reflect_on_error(self, error: Exception, context: dict) -> dict:
        """
        Reflect on an error to determine recovery strategy
        
        Args:
            error: The error that occurred
            context: Context about what was being attempted
        
        Returns:
            {
                "error_analysis": "...",
                "root_cause": "...",
                "recovery_strategy": {...},
                "should_retry": bool
            }
        """
        logger.info(f"Reflecting on error: {error}")
        
        prompt = f"""An error occurred while executing a task. Analyze it.

ERROR: {str(error)}

CONTEXT:
{json.dumps(context, indent=2)}

Analyze:
1. What went wrong?
2. What is the root cause?
3. Can we recover? How?
4. Should we retry? What should we change?

Respond in JSON:
{{
    "error_analysis": "What happened...",
    "root_cause": "Why it happened...",
    "recovery_strategy": {{
        "approach": "...",
        "modifications": [...]
    }},
    "should_retry": true,
    "confidence": 0.7
}}
"""
        
        response = await self.llm._ask_llm_with_custom_prompt(prompt)
        return self._parse_reflection(response)
    
    def _parse_reflection(self, response: str) -> dict:
        """Parse reflection response"""
        try:
            if isinstance(response, dict):
                return response
            
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.error(f"Error parsing reflection: {e}")
        
        return {
            "error": "Unable to parse reflection",
            "raw_response": response
        }


class ReasoningEngine:
    """
    Main reasoning engine that coordinates all reasoning capabilities
    """
    
    def __init__(self, llm_client, tool_executor):
        self.llm = llm_client
        self.executor = tool_executor
        
        self.cot = ChainOfThought(llm_client)
        self.react = ReActAgent(llm_client, tool_executor)
        self.reflection = SelfReflection(llm_client)
    
    async def reason_about_goal(self, goal: str, mode: str = "auto") -> dict:
        """
        Apply appropriate reasoning strategy for a goal
        
        Args:
            goal: User's goal
            mode: "cot" | "react" | "auto"
        
        Returns:
            Reasoning result with recommended actions
        """
        
        if mode == "auto":
            # Determine best reasoning mode
            mode = await self._select_reasoning_mode(goal)
            logger.info(f"Auto-selected reasoning mode: {mode}")
        
        if mode == "react":
            # Use ReAct for iterative problem solving
            return await self.react.solve(goal)
        else:
            # Use Chain-of-Thought for planning
            return await self.cot.reason(goal)
    
    async def _select_reasoning_mode(self, goal: str) -> str:
        """Automatically select the best reasoning mode for a goal"""
        
        # Simple heuristics (can be improved with LLM)
        goal_lower = goal.lower()
        
        # Use ReAct for complex, multi-step tasks
        if any(word in goal_lower for word in ["research", "analyze", "investigate", "find out", "figure out"]):
            return "react"
        
        # Use CoT for planning and decision-making
        return "cot"

    async def identify_knowledge_gaps(self, goal: str, observation_history: List[dict]) -> List[str]:
        """Identify what information is missing to achieve the goal"""
        prompt = f"""Review the goal and the work done so far. What information is still missing?
        
        GOAL: {goal}
        HISTORY: {json.dumps(observation_history[-5:])}
        
        List specific knowledge gaps (questions or missing data points).
        Respond as a JSON list of strings."""
        
        try:
            response = await self.llm._ask_llm_with_custom_prompt(prompt)
            import re
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                return json.loads(match.group())
        except:
            pass
        return []

    async def generate_execution_report(self, goal: str, results: List[dict]) -> str:
        """Generate a professional report of the executed tasks"""
        prompt = f"""Generate a professional execution report for the following goal and results.
        
        GOAL: {goal}
        RESULTS: {json.dumps(results)}
        
        Write a concise, executive summary of what was achieved, any issues encountered, and the final outcome."""
        
        return await self.llm._ask_llm_with_custom_prompt(prompt)
