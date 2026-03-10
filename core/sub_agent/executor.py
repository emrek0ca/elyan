from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Tuple

from core.intelligent_planner import IntelligentPlanner

from .session import SessionState, SubAgentResult, SubAgentSession


class SubAgentExecutor:
    """Execute a sub-agent task with restricted tool scope and iterative reasoning."""

    def __init__(self, agent: Any, max_iterations: int = 5):
        self.agent = agent
        self.max_iterations = max(1, min(10, int(max_iterations or 5)))

    def _normalize_action_params(self, action: str, params: Any) -> Tuple[str, Dict[str, Any]]:
        act = str(action or "").strip()
        pr = params if isinstance(params, dict) else {}
        return act, dict(pr)

    @staticmethod
    def _extract_json_block(text: str) -> Dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        candidates = [raw]
        fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
        candidates.extend(fenced)
        for c in candidates:
            s = str(c or "").strip()
            if not s:
                continue
            if not (s.startswith("{") and s.endswith("}")):
                m = re.search(r"\{[\s\S]*\}", s)
                if not m:
                    continue
                s = m.group(0).strip()
            try:
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
        return None

    def _parse_llm_directive(self, text: Any) -> Tuple[str, Dict[str, Any], str, bool]:
        if isinstance(text, dict):
            payload = text
        else:
            payload = self._extract_json_block(str(text or "")) or {}

        action = str(payload.get("action") or payload.get("tool") or payload.get("tool_name") or "").strip()
        if isinstance(payload.get("params"), dict):
            params = dict(payload.get("params") or {})
        elif isinstance(payload.get("arguments"), dict):
            params = dict(payload.get("arguments") or {})
        elif isinstance(payload.get("tool_input"), dict):
            params = dict(payload.get("tool_input") or {})
        else:
            params = {}
        for key in (
            "path",
            "file_path",
            "output_path",
            "url",
            "query",
            "method",
            "content",
            "command",
            "code",
            "text",
            "combo",
            "key",
        ):
            if key not in params and payload.get(key) is not None:
                params[key] = payload.get(key)
        final_text = str(
            payload.get("final")
            or payload.get("answer")
            or payload.get("output")
            or payload.get("message")
            or ""
        ).strip()
        done = self._coerce_done(
            payload.get("done", payload.get("is_final", payload.get("final_answer", False)))
        )

        if action:
            return action, dict(params), final_text, done

        if isinstance(text, str):
            stripped = text.strip()
            if stripped and len(stripped) > 8:
                return "", {}, stripped, True
        return "", {}, final_text, done

    @staticmethod
    def _coerce_done(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        low = str(value).strip().lower()
        if low in {"true", "1", "yes", "y", "done", "final"}:
            return True
        if low in {"false", "0", "no", "n", ""}:
            return False
        return False

    def _build_iteration_prompt(
        self,
        session: SubAgentSession,
        *,
        iteration: int,
        last_result: Any,
        notes: List[str],
    ) -> str:
        allowed = ", ".join(sorted(session.allowed_tools)) if session.allowed_tools else "any"
        task_desc = str(session.task.description or session.task.name or "").strip()
        objective = str(session.task.objective or task_desc).strip()
        success_criteria = "; ".join(str(x) for x in (session.task.success_criteria or [])[:5]) or "somut çıktı üret"
        obs = str(last_result)[:1400] if last_result is not None else "none"
        note_txt = "; ".join(notes[-5:]) if notes else "none"
        return (
            f"Sen bir '{session.specialist_key}' sub-agent'isin.\n"
            f"Görev: {task_desc}\n"
            f"Amaç: {objective}\n"
            f"Başarı ölçütü: {success_criteria}\n"
            f"İterasyon: {iteration}/{self.max_iterations}\n"
            f"İzinli tool'lar: {allowed}\n"
            f"Son gözlem: {obs}\n"
            f"Notlar: {note_txt}\n\n"
            "Yalnızca JSON dön.\n"
            '{"action":"tool_name","params":{},"done":false}\n'
            "veya\n"
            '{"final":"kısa sonuç özeti","done":true}\n'
        )

    @staticmethod
    def _llm_role_for_specialist(specialist_key: str) -> str:
        token = str(specialist_key or "").strip().lower()
        mapping = {
            "lead": "planning",
            "researcher": "research_worker",
            "builder": "code_worker",
            "ops": "worker",
            "qa": "qa",
            "communicator": "creative",
        }
        return mapping.get(token, "reasoning")

    async def _call_llm_for_next_action(
        self,
        session: SubAgentSession,
        *,
        iteration: int,
        last_result: Any,
        notes: List[str],
    ) -> Tuple[str, Dict[str, Any], str, bool]:
        llm = getattr(self.agent, "llm", None)
        if llm is None:
            return "", {}, "", False
        prompt = self._build_iteration_prompt(
            session,
            iteration=iteration,
            last_result=last_result,
            notes=notes,
        )
        try:
            uid = str(getattr(self.agent, "current_user_id", "local") or "local")
            try:
                resp = await llm.generate(
                    prompt,
                    role=self._llm_role_for_specialist(getattr(session, "specialist_key", "")),
                    user_id=uid,
                )
            except TypeError:
                resp = await llm.generate(prompt, user_id=uid)
            return self._parse_llm_directive(resp)
        except Exception as exc:
            notes.append(f"llm_error:{exc}")
            return "", {}, "", False

    @staticmethod
    def _collect_artifacts(raw: Any) -> List[str]:
        artifacts: List[str] = []
        if isinstance(raw, dict):
            for key in ("path", "file_path", "output_path", "screenshot", "image_path"):
                val = raw.get(key)
                if isinstance(val, str) and val.strip():
                    artifacts.append(val.strip())
            for key in ("paths", "files", "artifacts"):
                val = raw.get(key)
                if isinstance(val, list):
                    artifacts.extend(str(x).strip() for x in val if isinstance(x, str) and str(x).strip())
        return list(dict.fromkeys(artifacts))

    async def _execute_tool_call(
        self,
        session: SubAgentSession,
        action: str,
        params: Dict[str, Any],
        *,
        iteration: int,
    ) -> Any:
        return await self.agent._execute_tool(
            action,
            params,
            user_input=session.task.description or session.task.name,
            step_name=f"{session.task.name}:{iteration}",
            pipeline_state=session.pipeline_state,
        )

    async def _planner_fallback_directive(self, session: SubAgentSession) -> Tuple[str, Dict[str, Any]]:
        desc = str(session.task.description or session.task.name or "").strip()
        if not desc:
            return "", {}
        try:
            planner = IntelligentPlanner()
            plan = await planner.create_plan(
                description=desc,
                use_llm=False,
                preferred_tools=list(session.allowed_tools) if session.allowed_tools else None,
            )
            subtasks = list(getattr(plan, "subtasks", []) or [])
            for step in subtasks:
                action = str(getattr(step, "action", "") or "").strip()
                if not action:
                    continue
                if session.allowed_tools and action not in session.allowed_tools:
                    continue
                params = getattr(step, "params", {}) if isinstance(getattr(step, "params", {}), dict) else {}
                return action, dict(params)
        except Exception:
            return "", {}
        return "", {}

    async def run(self, session: SubAgentSession) -> SubAgentResult:
        t0 = time.perf_counter()
        session.state = SessionState.RUNNING
        notes: List[str] = []
        artifacts: List[str] = []
        last_result: Any = None
        final_text = ""
        executed = False
        seen_directives: set[str] = set()

        base_action, base_params = self._normalize_action_params(
            session.task.action or "chat",
            session.task.params,
        )
        try:
            if session.workspace_path:
                session.pipeline_state.store("workspace_path", session.workspace_path)
            if session.memory_path:
                session.pipeline_state.store("memory_path", session.memory_path)
        except Exception:
            pass

        try:
            for i in range(1, self.max_iterations + 1):
                # First iteration honors explicit task action.
                run_base_action = bool(
                    i == 1
                    and base_action
                    and (
                        base_action != "chat"
                        or not session.allowed_tools
                        or "chat" in session.allowed_tools
                    )
                )
                if run_base_action:
                    action = base_action
                    params = dict(base_params or {})
                    done = False
                else:
                    action, params, maybe_final, done = await self._call_llm_for_next_action(
                        session,
                        iteration=i,
                        last_result=last_result,
                        notes=notes,
                    )
                    if maybe_final and done:
                        final_text = maybe_final
                        break
                    if not action:
                        # Deterministic fallback for tasks where LLM does not return tool JSON.
                        infer = getattr(self.agent, "_infer_general_tool_intent", None)
                        if callable(infer):
                            guess = infer(session.task.description or session.task.name or "")
                            if isinstance(guess, dict):
                                action = str(guess.get("action") or "").strip()
                                g_params = guess.get("params", {})
                                if isinstance(g_params, dict):
                                    for k, v in g_params.items():
                                        params.setdefault(k, v)
                        if not action:
                            p_action, p_params = await self._planner_fallback_directive(session)
                            if p_action:
                                action = p_action
                                for k, v in p_params.items():
                                    params.setdefault(k, v)
                        if not action:
                            final_text = maybe_final or str(last_result or "").strip()
                            if final_text:
                                break
                            notes.append("no_progress")
                            continue
                    directive_key = f"{action}:{json.dumps(params, sort_keys=True, default=str)}"
                    if directive_key in seen_directives:
                        notes.append(f"repeated_directive:{action}")
                        if executed:
                            p_action, p_params = await self._planner_fallback_directive(session)
                            if p_action and f"{p_action}:{json.dumps(p_params, sort_keys=True, default=str)}" not in seen_directives:
                                action = p_action
                                params = p_params
                            else:
                                break
                    else:
                        seen_directives.add(directive_key)

                if session.allowed_tools and action not in session.allowed_tools:
                    notes.append(f"blocked_tool:{action}")
                    if executed:
                        continue
                    result = SubAgentResult(
                        status="failed",
                        result={"success": False, "error": f"Tool not allowed: {action}"},
                        notes=notes,
                        artifacts=[],
                        execution_time_ms=int((time.perf_counter() - t0) * 1000),
                        token_usage={"prompt": 0, "completion": 0, "cost_usd": 0.0},
                    )
                    session.result = result
                    session.state = SessionState.FAILED
                    session.completed_at = time.time()
                    return result

                raw = await self._execute_tool_call(session, action, params, iteration=i)
                executed = True
                last_result = raw
                artifacts.extend(self._collect_artifacts(raw))

                if isinstance(raw, dict) and raw.get("success") is False:
                    notes.append(f"tool_failed:{action}")
                    continue

                # Explicit first-step action can complete in one iteration.
                if i == 1 and base_action and (
                    base_action != "chat" or getattr(self.agent, "llm", None) is None
                ):
                    break

                # If tool produced clear final text, stop.
                if isinstance(raw, dict):
                    candidate = raw.get("output") or raw.get("message") or raw.get("summary")
                    if isinstance(candidate, str) and candidate.strip():
                        final_text = candidate.strip()
                        break

            artifacts = list(dict.fromkeys(a for a in artifacts if a))
            elapsed = int((time.perf_counter() - t0) * 1000)

            if isinstance(last_result, dict) and last_result.get("success") is False and not final_text:
                status = "failed"
                session.state = SessionState.FAILED
                payload = last_result
            elif executed:
                status = "success" if not notes else "partial"
                session.state = SessionState.COMPLETED if status == "success" else SessionState.FAILED
                payload = last_result if last_result is not None else {"success": True, "output": final_text}
            elif final_text:
                status = "success"
                session.state = SessionState.COMPLETED
                payload = {"success": True, "output": final_text}
            else:
                status = "failed"
                session.state = SessionState.FAILED
                payload = {"success": False, "error": "Sub-agent failed to produce output"}

            result = SubAgentResult(
                status=status,
                result=payload,
                notes=notes[:12],
                artifacts=artifacts,
                execution_time_ms=elapsed,
                token_usage={"prompt": 0, "completion": 0, "cost_usd": 0.0},
            )
            session.result = result
            session.completed_at = time.time()
            return result
        except Exception as exc:
            session.state = SessionState.FAILED
            session.completed_at = time.time()
            result = SubAgentResult(
                status="failed",
                result={"success": False, "error": str(exc)},
                notes=["executor_exception", *notes],
                artifacts=[],
                execution_time_ms=int((time.perf_counter() - t0) * 1000),
                token_usage={"prompt": 0, "completion": 0, "cost_usd": 0.0},
            )
            session.result = result
            return result


__all__ = ["SubAgentExecutor"]
