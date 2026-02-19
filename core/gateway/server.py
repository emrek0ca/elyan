import asyncio
import time
import json
from datetime import datetime
from aiohttp import web, WSMsgType
from typing import Optional, Set
from .router import GatewayRouter
from .response import UnifiedResponse
from core.scheduler.cron_engine import CronEngine
from core.scheduler.heartbeat import HeartbeatManager
from core.scheduler.routine_engine import routine_engine
from core.skills.manager import skill_manager
from core.tool_usage import get_tool_usage_snapshot
from config.elyan_config import elyan_config
from security.tool_policy import tool_policy
from tools import AVAILABLE_TOOLS
from utils.logger import get_logger

logger = get_logger("gateway_server")

# Global WebSocket client registry for dashboard push
_dashboard_ws_clients: Set[web.WebSocketResponse] = set()
_activity_log: list = []  # Rolling buffer of last 50 events
_start_time: float = time.time()


def push_activity(event_type: str, channel: str, detail: str, success: bool = True):
    """Push an activity event to all connected dashboard WebSocket clients."""
    entry = {
        "ts": time.strftime("%H:%M:%S"),
        "type": event_type,
        "channel": channel,
        "detail": detail[:80],
        "ok": success,
    }
    _activity_log.append(entry)
    if len(_activity_log) > 50:
        _activity_log.pop(0)
    # Fire-and-forget broadcast
    asyncio.ensure_future(_broadcast_activity(entry))


async def _broadcast_activity(entry: dict):
    dead = set()
    for ws in list(_dashboard_ws_clients):
        try:
            await ws.send_json({"event": "activity", "data": entry})
        except Exception:
            dead.add(ws)
    _dashboard_ws_clients.difference_update(dead)


def _mask_sensitive_fields(data):
    """Mask secret-like keys before returning API responses."""
    sensitive_markers = ("token", "secret", "password", "api_key", "apikey", "key")
    if isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            if any(marker in str(k).lower() for marker in sensitive_markers):
                masked[k] = "***" if v not in (None, "") else ""
            else:
                masked[k] = _mask_sensitive_fields(v)
        return masked
    if isinstance(data, list):
        return [_mask_sensitive_fields(item) for item in data]
    return data


def _get_runtime_model_info() -> dict:
    """Resolve active (router) and configured (default) model/provider consistently."""
    configured_provider = elyan_config.get("models.default.provider", "—")
    configured_model = elyan_config.get("models.default.model", "—")
    active_provider = configured_provider
    active_model = configured_model
    source = "config"

    try:
        from core.neural_router import neural_router

        routed = neural_router.get_model_for_role("inference") or {}
        rp = routed.get("provider")
        rm = routed.get("model")
        if rp or rm:
            active_provider = rp or active_provider
            active_model = rm or active_model
            source = "router"
    except Exception:
        pass

    return {
        "active_provider": active_provider or "—",
        "active_model": active_model or "—",
        "configured_provider": configured_provider or "—",
        "configured_model": configured_model or "—",
        "model_source": source,
        "model_consistent": (
            str(active_provider or "").lower() == str(configured_provider or "").lower()
            and str(active_model or "").lower() == str(configured_model or "").lower()
        ),
    }


def _default_model_for_provider(provider: str) -> str:
    p = str(provider or "").strip().lower()
    defaults = {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-latest",
        "google": "gemini-2.0-flash",
        "groq": "llama-3.3-70b-versatile",
        "ollama": "llama3.1:8b",
    }
    return defaults.get(p, "gpt-4o")


def _unique_clean(items, default):
    if not isinstance(items, list):
        items = list(default)
    out = []
    seen = set()
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _get_policy_lists() -> tuple[list[str], list[str], list[str]]:
    default_allow = [
        "group:fs",
        "group:web",
        "group:ui",
        "group:runtime",
        "group:messaging",
        "group:automation",
        "group:memory",
        "browser",
    ]
    allow = _unique_clean(elyan_config.get("tools.allow", default_allow), default_allow)
    deny = _unique_clean(elyan_config.get("tools.deny", []), [])
    require = elyan_config.get("tools.requireApproval", None)
    if require is None:
        require = elyan_config.get("tools.require_approval", ["exec", "delete_file"])
    require = _unique_clean(require, ["exec", "delete_file"])
    return allow, deny, require


class ElyanGatewayServer:
    """Main HTTP/WebSocket server for the Elyan Gateway."""

    def __init__(self, agent):
        self.agent = agent
        self.router = GatewayRouter(agent)
        self.app = web.Application(middlewares=[self._cors_middleware])
        self.webchat_adapter: Optional[object] = None
        self.cron = CronEngine(agent)
        self.heartbeat = HeartbeatManager(agent)
        self.cron.set_report_callback(self._on_cron_report)
        self._setup_routes()
        self.runner: Optional[web.AppRunner] = None

    @web.middleware
    async def _cors_middleware(self, request, handler):
        if request.method == "OPTIONS":
            return web.Response(headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            })
        resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    def _setup_routes(self):
        # ── API V1 ────────────────────────────────────────────────────────────
        self.app.router.add_post('/api/message', self.handle_external_message)
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/api/channels', self.handle_list_channels)
        self.app.router.add_get('/api/config', self.handle_get_config)
        self.app.router.add_post('/api/config', self.handle_update_config)
        self.app.router.add_get('/api/models', self.handle_models_get)
        self.app.router.add_post('/api/models', self.handle_models_update)
        self.app.router.add_get('/api/canvas/{id}', self.handle_get_canvas)

        # ── Dashboard API (new) ───────────────────────────────────────────────
        self.app.router.add_get('/api/analytics', self.handle_analytics)
        self.app.router.add_get('/api/tasks', self.handle_tasks)
        self.app.router.add_post('/api/tasks', self.handle_create_task)
        self.app.router.add_get('/api/memory/stats', self.handle_memory_stats)
        self.app.router.add_get('/api/activity', self.handle_activity_log)
        self.app.router.add_get('/api/routines', self.handle_routines)
        self.app.router.add_get('/api/routines/templates', self.handle_routine_templates)
        self.app.router.add_post('/api/routines', self.handle_routine_create)
        self.app.router.add_post('/api/routines/from-template', self.handle_routine_from_template)
        self.app.router.add_post('/api/routines/toggle', self.handle_routine_toggle)
        self.app.router.add_post('/api/routines/run', self.handle_routine_run)
        self.app.router.add_get('/api/routines/history', self.handle_routine_history)
        self.app.router.add_delete('/api/routines/{id}', self.handle_routine_remove)
        self.app.router.add_get('/api/tools', self.handle_tools)
        self.app.router.add_post('/api/tools/policy', self.handle_tools_policy)
        self.app.router.add_post('/api/tools/test', self.handle_tools_test)
        self.app.router.add_get('/api/skills', self.handle_skills)
        self.app.router.add_post('/api/skills/install', self.handle_skill_install)
        self.app.router.add_post('/api/skills/toggle', self.handle_skill_toggle)
        self.app.router.add_post('/api/skills/remove', self.handle_skill_remove)
        self.app.router.add_post('/api/skills/update', self.handle_skill_update)
        self.app.router.add_get('/api/skills/check', self.handle_skill_check)

        # ── Dashboard & Web UI ────────────────────────────────────────────────
        self.app.router.add_get('/', self.handle_dashboard_page)
        self.app.router.add_get('/dashboard', self.handle_dashboard_page)
        self.app.router.add_get('/canvas', self.handle_canvas_page)
        self.app.router.add_get('/ws/chat', self.handle_webchat_ws)
        self.app.router.add_get('/ws/dashboard', self.handle_dashboard_ws)

        # ── Webhook ───────────────────────────────────────────────────────────
        self.app.router.add_post('/hook/{event}', self.handle_webhook)

        # ── Security API ─────────────────────────────────────────────────────
        self.app.router.add_get('/api/security/events', self.handle_security_events)
        self.app.router.add_get('/api/security/pending', self.handle_pending_approvals)
        self.app.router.add_post('/api/security/approve', self.handle_approve_action)

    # ── Page handlers ─────────────────────────────────────────────────────────
    async def handle_dashboard_page(self, request):
        return web.FileResponse('ui/web/dashboard.html')

    async def handle_canvas_page(self, request):
        return web.FileResponse('ui/web/canvas/index.html')

    # ── Config ────────────────────────────────────────────────────────────────
    async def handle_get_config(self, request):
        return web.json_response(elyan_config.config.model_dump())

    async def handle_update_config(self, request):
        try:
            data = await request.json()
            for k, v in data.items():
                elyan_config.set(k, v)
            return web.json_response({"status": "updated"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_models_get(self, request):
        default = elyan_config.get("models.default", {}) or {}
        fallback = elyan_config.get("models.fallback", {}) or {}
        roles = elyan_config.get("models.roles", {}) or {}
        router_enabled = bool(elyan_config.get("router.enabled", True))
        state = {
            "default": {
                "provider": default.get("provider", "openai"),
                "model": default.get("model", "gpt-4o"),
            },
            "fallback": {
                "provider": fallback.get("provider", "openai"),
                "model": fallback.get("model", "gpt-4o"),
            },
            "roles": roles if isinstance(roles, dict) else {},
            "router_enabled": router_enabled,
            **_get_runtime_model_info(),
        }
        return web.json_response(state)

    async def handle_models_update(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        current_default = elyan_config.get("models.default", {}) or {}
        current_fallback = elyan_config.get("models.fallback", {}) or {}

        provider = str(
            data.get("provider")
            or data.get("default_provider")
            or current_default.get("provider", "openai")
        ).strip().lower()
        model = str(
            data.get("model")
            or data.get("default_model")
            or current_default.get("model", "")
        ).strip()
        if not model:
            model = _default_model_for_provider(provider)

        fallback_provider = str(
            data.get("fallback_provider")
            or current_fallback.get("provider", "openai")
        ).strip().lower()
        fallback_model = str(
            data.get("fallback_model")
            or current_fallback.get("model", "")
        ).strip()
        if not fallback_model:
            fallback_model = _default_model_for_provider(fallback_provider)

        router_enabled = data.get("router_enabled", None)
        sync_roles = bool(data.get("sync_roles", True))

        elyan_config.set("models.default.provider", provider)
        elyan_config.set("models.default.model", model)
        elyan_config.set("models.fallback.provider", fallback_provider)
        elyan_config.set("models.fallback.model", fallback_model)

        if router_enabled is not None:
            elyan_config.set("router.enabled", bool(router_enabled))

        if sync_roles:
            role_map = {
                "reasoning": {"provider": provider, "model": model},
                "inference": {"provider": provider, "model": model},
                "creative": {"provider": provider, "model": model},
                "code": {"provider": provider, "model": model},
            }
            elyan_config.set("models.roles", role_map)

        push_activity("models", "dashboard", f"default={provider}/{model}", True)
        default = elyan_config.get("models.default", {}) or {}
        fallback = elyan_config.get("models.fallback", {}) or {}
        roles = elyan_config.get("models.roles", {}) or {}
        router_enabled = bool(elyan_config.get("router.enabled", True))
        return web.json_response({
            "default": {
                "provider": default.get("provider", "openai"),
                "model": default.get("model", "gpt-4o"),
            },
            "fallback": {
                "provider": fallback.get("provider", "openai"),
                "model": fallback.get("model", "gpt-4o"),
            },
            "roles": roles if isinstance(roles, dict) else {},
            "router_enabled": router_enabled,
            **_get_runtime_model_info(),
        })

    # ── Canvas ────────────────────────────────────────────────────────────────
    async def handle_get_canvas(self, request):
        canvas_id = request.match_info.get('id')
        from core.canvas.engine import canvas_engine
        view = canvas_engine.get_view(canvas_id)
        if view:
            return web.json_response(view)
        return web.Response(status=404, text="Canvas not found")

    # ── Status ────────────────────────────────────────────────────────────────
    async def handle_status(self, request):
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        uptime_s = int(time.time() - _start_time)
        days, rem = divmod(uptime_s, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        if days:
            uptime = f"{days}d {hours}s {minutes}dk"
        elif hours:
            uptime = f"{hours}s {minutes}dk"
        elif minutes:
            uptime = f"{minutes}dk {seconds}sn"
        else:
            uptime = f"{seconds}sn"
        adapter_status = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {
            k: a.get_status() for k, a in self.router.adapters.items()
        }
        adapter_health = self.router.get_adapter_health() if hasattr(self.router, "get_adapter_health") else {}

        return web.json_response({
            "status": "online",
            "cpu": f"{cpu:.0f}%",
            "cpu_pct": round(cpu, 1),
            "ram": f"{mem.used / (1024**3):.1f} GB",
            "ram_pct": round(mem.percent, 1),
            "uptime": uptime,
            "uptime_s": uptime_s,
            "version": elyan_config.get("version", "18.0.0"),
            "adapters": adapter_status,
            "adapter_health": adapter_health,
            "cron_jobs": len(self.cron.scheduler.get_jobs()),
            **_get_runtime_model_info(),
        })

    # ── Analytics (new) ───────────────────────────────────────────────────────
    async def handle_analytics(self, request):
        """Aggregate analytics for dashboard overview cards."""
        try:
            from core.pipeline_state import get_pipeline_state
            ps = get_pipeline_state()
            summary = ps.history_summary(window_hours=24)
            total_ops = int(summary.get("recent_total", 0))
            success_rate = float(summary.get("recent_success_rate", 0.0))
        except Exception:
            total_ops, success_rate = 0, 0.0

        # Active model info (router-aware, config-consistency included)
        model_info = _get_runtime_model_info()
        model_name = model_info.get("active_model", "—")
        provider = model_info.get("active_provider", "—")

        # Pricing tracker
        cost_usd = 0.0
        total_tokens = 0
        try:
            from core.pricing_tracker import get_pricing_tracker
            pt = get_pricing_tracker()
            stats = pt.get_stats() if hasattr(pt, "get_stats") else {}
            cost_usd = float(stats.get("total_usd", 0))
            total_tokens = int(stats.get("total_tokens", 0))
        except Exception:
            pass

        # Channel/model breakdown from activity log
        from collections import Counter
        ch_counter: Counter = Counter()
        model_counter: Counter = Counter()
        for entry in _activity_log:
            ch = entry.get("channel", "")
            if ch:
                ch_counter[ch] += 1
        if model_name and model_name != "—":
            model_counter[model_name] = total_ops

        import datetime
        day_of_month = datetime.datetime.now().day
        budget_usd = float(elyan_config.get("monthly_budget_usd", 20.0))

        return web.json_response({
            "total_operations": total_ops,
            "total_tasks": total_ops,
            "success_rate": round(success_rate * 100, 1) if success_rate <= 1 else round(success_rate, 1),
            "avg_response_ms": 0,
            "avg_task_time_s": 0,
            "cost_usd": cost_usd,
            "total_cost_usd": cost_usd,
            "cost_limit_usd": float(elyan_config.get("cost_limit_usd", 50.0)),
            "budget_usd": budget_usd,
            "days_elapsed": day_of_month,
            "total_tokens": total_tokens,
            "model": model_name,
            "provider": provider,
            "configured_model": model_info.get("configured_model", "—"),
            "configured_provider": model_info.get("configured_provider", "—"),
            "model_source": model_info.get("model_source", "config"),
            "model_consistent": bool(model_info.get("model_consistent", True)),
            "active_channels": len(self.router.adapters) if hasattr(self.router, "adapters") else 0,
            "channel_breakdown": dict(ch_counter),
            "model_breakdown": dict(model_counter),
        })

    # ── Tasks (new) ───────────────────────────────────────────────────────────
    async def handle_tasks(self, request):
        """Return active + recent task history."""
        try:
            from core.pipeline_state import get_pipeline_state
            ps = get_pipeline_state()
            active = ps.list_resume_candidates()
            history = ps._state.get("history", [])[-20:]
        except Exception:
            active, history = [], []
        return web.json_response({"active": active, "history": list(reversed(history))})

    async def handle_create_task(self, request):
        """Create and enqueue a new task."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        text = (data.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "text required"}, status=400)
        asyncio.create_task(self.agent.process(text))
        push_activity("task_created", "dashboard", text[:60])
        return web.json_response({"status": "queued", "text": text})

    # ── Memory stats (new) ────────────────────────────────────────────────────
    async def handle_memory_stats(self, request):
        try:
            from core.memory import get_memory

            memory = get_memory()
            stats = memory.get_stats()
            limit = int(request.rel_url.query.get("limit", 5))
            top_users = memory.get_top_users_storage(limit=limit)

            total_items = (
                int(stats.get("conversations", 0))
                + int(stats.get("preferences", 0))
                + int(stats.get("tasks", 0))
                + int(stats.get("knowledge_items", 0))
                + int(stats.get("embeddings", 0))
            )
            size_bytes = int(stats.get("database_size_bytes", 0))
            return web.json_response({
                "total_items": total_items,
                "size_mb": round(size_bytes / (1024**2), 2),
                "size_bytes": size_bytes,
                "db_path": stats.get("database_path"),
                "default_user_limit_bytes": int(stats.get("default_user_limit_bytes", 0)),
                "top_users": top_users,
            })
        except Exception as e:
            logger.warning(f"Memory stats unavailable: {e}")
            return web.json_response({
                "total_items": 0,
                "size_mb": 0.0,
                "size_bytes": 0,
                "top_users": [],
            })

    # ── Activity log (new) ────────────────────────────────────────────────────
    async def handle_activity_log(self, request):
        return web.json_response({"events": list(reversed(_activity_log))})

    # ── Routine automation (new) ────────────────────────────────────────────
    @staticmethod
    def _routine_job_id(routine_id: str) -> str:
        return f"routine:{routine_id}"

    @staticmethod
    def _resolve_routine_id_api(raw_id: str) -> tuple[str | None, str | None]:
        rid = str(raw_id or "").strip()
        if not rid:
            return None, "id required"
        matches = routine_engine.match_routine_ids(rid)
        if not matches:
            return None, "routine not found"
        if len(matches) > 1:
            return None, f"ambiguous id prefix ({len(matches)} matches)"
        return matches[0], None

    def _routine_to_job(self, routine: dict) -> dict:
        rid = str(routine.get("id", "")).strip()
        return {
            "id": self._routine_job_id(rid),
            "expression": str(routine.get("expression", "")).strip(),
            "enabled": bool(routine.get("enabled", True)),
            "job_type": "routine",
            "routine_id": rid,
            "name": routine.get("name", f"routine-{rid}"),
            "channel": routine.get("report_channel", "telegram"),
            "channel_id": routine.get("report_chat_id", ""),
            "source": "runtime",
        }

    def _sync_all_routines_to_cron(self) -> None:
        routines = routine_engine.list_routines()
        active_ids = set()
        for routine in routines:
            rid = str(routine.get("id", "")).strip()
            if not rid:
                continue
            active_ids.add(self._routine_job_id(rid))
            self.cron.sync_job(self._routine_to_job(routine))

        # Cleanup deleted routines from cron runtime jobs.
        for job in self.cron.list_jobs():
            jid = str(job.get("id", "")).strip()
            if jid.startswith("routine:") and jid not in active_ids:
                self.cron.remove_job(jid)

    async def _on_cron_report(self, job: dict, success: bool, report: str) -> None:
        channel = str(job.get("channel", "")).strip().lower()
        chat_id = str(job.get("channel_id", "")).strip()
        job_name = str(job.get("name") or job.get("id") or "job")
        if not report:
            report = f"{job_name} tamamlandı ({'başarılı' if success else 'hatalı'})."
        # Keep channel payload compact to avoid adapter-side message limits.
        if len(report) > 3500:
            report = report[:3500] + "\n...\n[rapor kısaltıldı]"
        report = (
            f"Rutin: {job_name}\n"
            f"Durum: {'SUCCESS' if success else 'FAILED'}\n\n"
            f"{report}"
        )

        if channel and chat_id and channel in self.router.adapters:
            try:
                await self.router.send_outgoing_response(
                    channel,
                    chat_id,
                    UnifiedResponse(text=report, format="plain"),
                )
                push_activity("routine_report", channel, f"{job_name} -> delivered", success=success)
                return
            except Exception as e:
                logger.warning(f"Routine report delivery failed ({channel}/{chat_id}): {e}")

        push_activity("routine_report", "dashboard", f"{job_name} -> local log", success=success)

    async def handle_routines(self, request):
        routines = routine_engine.list_routines()
        out = []
        enabled_count = 0
        for r in routines:
            rid = str(r.get("id", "")).strip()
            if not rid:
                continue
            enabled = bool(r.get("enabled", True))
            enabled_count += 1 if enabled else 0
            item = dict(r)
            try:
                aps_job = self.cron.scheduler.get_job(self._routine_job_id(rid))
                item["next_run"] = aps_job.next_run_time.isoformat() if aps_job and aps_job.next_run_time else None
            except Exception:
                item["next_run"] = None
            out.append(item)
        templates = routine_engine.list_templates()
        return web.json_response({
            "routines": out,
            "templates": templates,
            "summary": {
                "total": len(out),
                "enabled": enabled_count,
                "disabled": len(out) - enabled_count,
                "templates": len(templates),
            },
        })

    async def handle_routine_templates(self, request):
        templates = routine_engine.list_templates()
        return web.json_response({"ok": True, "templates": templates})

    async def handle_routine_create(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        name = str(data.get("name", "")).strip()
        expression = str(data.get("expression", "")).strip()
        steps = data.get("steps", [])
        report_channel = str(data.get("report_channel", "telegram")).strip().lower() or "telegram"
        report_chat_id = str(data.get("report_chat_id", "")).strip()
        enabled = bool(data.get("enabled", True))
        created_by = str(data.get("created_by", "dashboard")).strip() or "dashboard"
        panels = data.get("panels", [])
        template_id = str(data.get("template_id", "")).strip()

        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        if not expression:
            return web.json_response({"ok": False, "error": "expression required"}, status=400)
        try:
            from apscheduler.triggers.cron import CronTrigger
            CronTrigger.from_crontab(expression)
        except Exception as e:
            return web.json_response({"ok": False, "error": f"invalid cron expression: {e}"}, status=400)

        try:
            routine = routine_engine.add_routine(
                name=name,
                expression=expression,
                steps=steps,
                report_channel=report_channel,
                report_chat_id=report_chat_id,
                enabled=enabled,
                created_by=created_by,
                tags=data.get("tags", []) if isinstance(data.get("tags"), list) else [],
                panels=panels,
                template_id=template_id,
            )
            self.cron.sync_job(self._routine_to_job(routine))
            push_activity("routine_create", "dashboard", f"{routine['name']} ({routine['id']})", True)
            return web.json_response({"ok": True, "routine": routine})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_routine_from_template(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        template_id = str(data.get("template_id", "")).strip()
        expression = str(data.get("expression", "")).strip()
        name = str(data.get("name", "")).strip()
        report_channel = str(data.get("report_channel", "telegram")).strip().lower() or "telegram"
        report_chat_id = str(data.get("report_chat_id", "")).strip()
        created_by = str(data.get("created_by", "dashboard")).strip() or "dashboard"
        enabled = bool(data.get("enabled", True))
        panels = data.get("panels", [])
        tags = data.get("tags", []) if isinstance(data.get("tags"), list) else []

        if not template_id:
            return web.json_response({"ok": False, "error": "template_id required"}, status=400)
        if not expression:
            return web.json_response({"ok": False, "error": "expression required"}, status=400)
        try:
            from apscheduler.triggers.cron import CronTrigger
            CronTrigger.from_crontab(expression)
        except Exception as e:
            return web.json_response({"ok": False, "error": f"invalid cron expression: {e}"}, status=400)

        try:
            routine = routine_engine.create_from_template(
                template_id=template_id,
                expression=expression,
                report_channel=report_channel,
                report_chat_id=report_chat_id,
                enabled=enabled,
                created_by=created_by,
                name=name,
                panels=panels,
                tags=tags,
            )
            self.cron.sync_job(self._routine_to_job(routine))
            push_activity("routine_template", "dashboard", f"{template_id} -> {routine['id']}", True)
            return web.json_response({"ok": True, "routine": routine})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_routine_toggle(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        rid_raw = str(data.get("id", "")).strip()
        enabled = bool(data.get("enabled", True))
        rid, err = self._resolve_routine_id_api(rid_raw)
        if err:
            status = 400 if "id required" in err else 404 if "not found" in err else 409
            return web.json_response({"ok": False, "error": err}, status=status)

        routine = routine_engine.set_enabled(rid, enabled)
        if not routine:
            return web.json_response({"ok": False, "error": "routine not found"}, status=404)
        if enabled:
            self.cron.sync_job(self._routine_to_job(routine))
        else:
            self.cron.disable_job(self._routine_job_id(rid))
        push_activity("routine_toggle", "dashboard", f"{rid} -> {'on' if enabled else 'off'}", True)
        return web.json_response({"ok": True, "routine": routine})

    async def handle_routine_run(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        rid_raw = str(data.get("id", "")).strip()
        rid, err = self._resolve_routine_id_api(rid_raw)
        if err:
            status = 400 if "id required" in err else 404 if "not found" in err else 409
            return web.json_response({"ok": False, "error": err}, status=status)

        job_id = self._routine_job_id(rid)
        if not self.cron.get_job(job_id):
            routine = routine_engine.get_routine(rid)
            if not routine:
                return web.json_response({"ok": False, "error": "routine not found"}, status=404)
            self.cron.sync_job(self._routine_to_job(routine))

        result = await self.cron.run_job(job_id)
        push_activity("routine_run", "dashboard", f"{rid} -> {'ok' if result.get('success') else 'fail'}", bool(result.get("success")))
        return web.json_response({"ok": True, "result": result})

    async def handle_routine_history(self, request):
        rid = str(request.rel_url.query.get("id", "")).strip()
        if not rid:
            # lightweight global snapshot
            items = []
            for routine in routine_engine.list_routines():
                r_id = str(routine.get("id", "")).strip()
                if not r_id:
                    continue
                hist = routine_engine.get_history(r_id, limit=5)
                if hist:
                    items.append({"id": r_id, "name": routine.get("name"), "history": hist})
            return web.json_response({"items": items})

        resolved_id, err = self._resolve_routine_id_api(rid)
        if err:
            status = 404 if "not found" in err else 409
            return web.json_response({"ok": False, "error": err}, status=status)
        history = routine_engine.get_history(resolved_id, limit=int(request.rel_url.query.get("limit", 20)))
        return web.json_response({"id": resolved_id, "history": history})

    async def handle_routine_remove(self, request):
        rid_raw = str(request.match_info.get("id", "")).strip()
        rid, err = self._resolve_routine_id_api(rid_raw)
        if err:
            status = 400 if "id required" in err else 404 if "not found" in err else 409
            return web.json_response({"ok": False, "error": err}, status=status)
        ok = routine_engine.remove_routine(rid)
        if not ok:
            return web.json_response({"ok": False, "error": "routine not found"}, status=404)
        self.cron.remove_job(self._routine_job_id(rid))
        push_activity("routine_remove", "dashboard", rid, True)
        return web.json_response({"ok": True})

    # ── Tools management (new) ───────────────────────────────────────────────
    async def handle_tools(self, request):
        query = (request.rel_url.query.get("q", "") or "").strip().lower()
        group_filter = (request.rel_url.query.get("group", "") or "").strip().lower()
        policy_filter = (request.rel_url.query.get("policy", "") or "").strip().lower()

        allow, deny, require_approval = _get_policy_lists()
        usage = get_tool_usage_snapshot().get("stats", {})
        reg_desc = self.agent.kernel.tools.list_tools() if hasattr(self.agent, "kernel") else {}
        if not isinstance(reg_desc, dict):
            reg_desc = {}

        tool_names = sorted(set(list(AVAILABLE_TOOLS.keys()) + list(reg_desc.keys())))
        items = []
        group_counts = {}
        total_allowed = 0
        total_denied = 0
        total_approval = 0

        for name in tool_names:
            group = tool_policy.infer_group(name) or "other"
            denied = ("*" in deny) or (name in deny) or (f"group:{group}" in deny)
            allowed = (not denied) and (("*" in allow) or (name in allow) or (f"group:{group}" in allow))
            needs_approval = (name in require_approval) or (f"group:{group}" in require_approval)

            if query and query not in name.lower():
                continue
            if group_filter and group_filter != group:
                continue
            if policy_filter == "allowed" and not allowed:
                continue
            if policy_filter == "denied" and not denied:
                continue
            if policy_filter == "approval" and not needs_approval:
                continue

            total_allowed += 1 if allowed else 0
            total_denied += 1 if denied else 0
            total_approval += 1 if needs_approval else 0
            group_counts[group] = int(group_counts.get(group, 0)) + 1

            u = usage.get(name, {})
            items.append({
                "name": name,
                "group": group,
                "description": reg_desc.get(name, ""),
                "allowed": allowed,
                "denied": denied,
                "requires_approval": needs_approval,
                "usage": {
                    "calls": int(u.get("calls", 0) or 0),
                    "success_rate": float(u.get("success_rate", 0.0) or 0.0),
                    "last_latency_ms": int(u.get("last_latency_ms", 0) or 0),
                    "avg_latency_ms": float(u.get("avg_latency_ms", 0.0) or 0.0),
                    "last_used_at": u.get("last_used_at", ""),
                    "last_success": u.get("last_success"),
                    "last_error": u.get("last_error", ""),
                },
            })

        return web.json_response({
            "tools": items,
            "summary": {
                "total": len(items),
                "allowed": total_allowed,
                "denied": total_denied,
                "approval_required": total_approval,
                "groups": group_counts,
            },
            "policy": {
                "allow": allow,
                "deny": deny,
                "requireApproval": require_approval,
            },
        })

    async def handle_tools_policy(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        allow, deny, require_approval = _get_policy_lists()

        # Full list replacement
        if isinstance(data.get("allow"), list):
            allow = _unique_clean(data.get("allow"), [])
        if isinstance(data.get("deny"), list):
            deny = _unique_clean(data.get("deny"), [])
        if isinstance(data.get("requireApproval"), list):
            require_approval = _unique_clean(data.get("requireApproval"), [])
        if isinstance(data.get("require_approval"), list):
            require_approval = _unique_clean(data.get("require_approval"), [])

        # Per-tool / per-group toggle
        target = None
        if data.get("tool"):
            target = str(data.get("tool", "")).strip()
        elif data.get("group"):
            group = str(data.get("group", "")).strip().lower().replace("group:", "")
            if group:
                target = f"group:{group}"

        if target:
            if isinstance(data.get("allow"), bool):
                if data["allow"]:
                    if target not in allow:
                        allow.append(target)
                    if target in deny:
                        deny.remove(target)
                elif target in allow:
                    allow.remove(target)

            if isinstance(data.get("deny"), bool):
                if data["deny"]:
                    if target not in deny:
                        deny.append(target)
                    if target in allow:
                        allow.remove(target)
                elif target in deny:
                    deny.remove(target)

            approval_toggle = data.get("requireApproval", data.get("require_approval"))
            if isinstance(approval_toggle, bool):
                if approval_toggle and target not in require_approval:
                    require_approval.append(target)
                if not approval_toggle and target in require_approval:
                    require_approval.remove(target)

        allow = _unique_clean(allow, [])
        deny = _unique_clean(deny, [])
        require_approval = _unique_clean(require_approval, [])

        elyan_config.set("tools.allow", allow)
        elyan_config.set("tools.deny", deny)
        # Store both keys for compatibility.
        elyan_config.set("tools.requireApproval", require_approval)
        elyan_config.set("tools.require_approval", require_approval)
        tool_policy.reload()
        push_activity("tools_policy", "dashboard", "Tool policy updated", True)

        return web.json_response({
            "ok": True,
            "policy": {
                "allow": allow,
                "deny": deny,
                "requireApproval": require_approval,
            },
        })

    async def handle_tools_test(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        tool = str(data.get("tool", "")).strip()
        params = data.get("params", {})
        execute = bool(data.get("execute", True))
        if not tool:
            return web.json_response({"ok": False, "error": "tool required"}, status=400)
        if not isinstance(params, dict):
            return web.json_response({"ok": False, "error": "params must be object"}, status=400)

        group = tool_policy.infer_group(tool)
        access = tool_policy.check_access(tool, group)
        if not access.get("allowed"):
            return web.json_response({"ok": False, "error": access.get("reason", "policy denied"), "access": access}, status=403)
        if access.get("requires_approval"):
            return web.json_response({"ok": False, "requires_approval": True, "access": access}, status=202)

        if not execute:
            return web.json_response({"ok": True, "dry_run": True, "access": access, "tool": tool, "group": group})

        # Keep dashboard-side test execution constrained to diagnostics/safe reads.
        safe_tools = {
            "list_files", "read_file", "search_files",
            "get_system_info", "get_process_info", "get_running_apps",
            "web_search", "fetch_page", "extract_text",
            "take_screenshot", "read_clipboard",
            "get_today_events", "get_reminders", "wifi_status", "get_public_ip",
        }
        if tool not in safe_tools:
            return web.json_response({
                "ok": False,
                "error": f"'{tool}' dashboard test çalıştırması için güvenli listede değil.",
                "safe_tools": sorted(safe_tools),
            }, status=400)

        started = time.perf_counter()
        try:
            result = await self.agent._execute_tool(tool, params, user_input=f"dashboard tool test: {tool}", step_name="dashboard_test")
            latency_ms = int((time.perf_counter() - started) * 1000)
            push_activity("tool_test", "dashboard", f"{tool} ({latency_ms}ms)", True)
            return web.json_response({
                "ok": True,
                "tool": tool,
                "group": group,
                "latency_ms": latency_ms,
                "formatted": self.agent._format_result_text(result),
                "result": result,
            })
        except Exception as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            push_activity("tool_test", "dashboard", f"{tool} failed ({latency_ms}ms)", False)
            return web.json_response({"ok": False, "error": str(e), "latency_ms": latency_ms}, status=500)

    # ── Skills management (new) ──────────────────────────────────────────────
    async def handle_skills(self, request):
        available = request.rel_url.query.get("available", "0") in {"1", "true", "yes"}
        enabled_only = request.rel_url.query.get("enabled", "0") in {"1", "true", "yes"}
        q = (request.rel_url.query.get("q", "") or "").strip()
        items = skill_manager.list_skills(available=available, enabled_only=enabled_only, query=q)
        installed = [s for s in items if s.get("installed")]
        enabled = [s for s in installed if s.get("enabled")]
        unhealthy = [s for s in installed if not s.get("health_ok")]
        return web.json_response({
            "skills": items,
            "summary": {
                "total": len(items),
                "installed": len(installed),
                "enabled": len(enabled),
                "issues": len(unhealthy),
            },
        })

    async def handle_skill_install(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        name = str(data.get("name", "")).strip()
        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        ok, msg, info = skill_manager.install_skill(name)
        push_activity("skill_install", "dashboard", f"{name}: {msg}", success=ok)
        return web.json_response({"ok": ok, "message": msg, "skill": info}, status=200 if ok else 400)

    async def handle_skill_toggle(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        name = str(data.get("name", "")).strip()
        enabled = bool(data.get("enabled", True))
        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        ok, msg, info = skill_manager.set_enabled(name, enabled)
        push_activity("skill_toggle", "dashboard", f"{name}: {'on' if enabled else 'off'}", success=ok)
        return web.json_response({"ok": ok, "message": msg, "skill": info}, status=200 if ok else 400)

    async def handle_skill_remove(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        name = str(data.get("name", "")).strip()
        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        ok, msg = skill_manager.remove_skill(name)
        push_activity("skill_remove", "dashboard", f"{name}: {msg}", success=ok)
        return web.json_response({"ok": ok, "message": msg}, status=200 if ok else 400)

    async def handle_skill_update(self, request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        name = str(data.get("name", "")).strip() if data.get("name") else None
        update_all = bool(data.get("all", False))
        result = skill_manager.update_skills(name=name, update_all=update_all)
        push_activity("skill_update", "dashboard", f"updated={len(result.get('updated', []))}", success=True)
        return web.json_response({"ok": True, **result})

    async def handle_skill_check(self, request):
        name = request.rel_url.query.get("name")
        result = skill_manager.check(name=name)
        return web.json_response(result)

    # ── WebSocket: Dashboard push (new) ───────────────────────────────────────
    async def handle_dashboard_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        _dashboard_ws_clients.add(ws)
        logger.info(f"Dashboard WS connected ({len(_dashboard_ws_clients)} clients)")
        # Send recent activity on connect
        await ws.send_json({"event": "history", "data": list(reversed(_activity_log[-10:]))})
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            _dashboard_ws_clients.discard(ws)
            logger.info(f"Dashboard WS disconnected ({len(_dashboard_ws_clients)} clients)")
        return ws

    # ── Security endpoints ────────────────────────────────────────────────────
    async def handle_security_events(self, request):
        """Audit log events for Security tab."""
        limit = int(request.rel_url.query.get("limit", 20))
        severity = request.rel_url.query.get("severity", "")
        events = []
        try:
            import sqlite3
            from pathlib import Path
            audit_path = Path.home() / ".elyan" / "audit.db"
            if not audit_path.exists():
                audit_path = Path(".wiqo_audit/audit.db")
            if audit_path.exists():
                conn = sqlite3.connect(audit_path)
                conn.row_factory = sqlite3.Row
                q = "SELECT timestamp, operation, risk_level, status FROM audit_log ORDER BY timestamp DESC LIMIT ?"
                params = [limit]
                rows = conn.execute(q, params).fetchall()
                conn.close()
                for row in rows:
                    ev = dict(row)
                    if severity and ev.get("risk_level", "").lower() != severity.lower():
                        continue
                    events.append(ev)
        except Exception:
            pass
        return web.json_response({"events": events, "total": len(events)})

    async def handle_pending_approvals(self, request):
        """Pending approval requests."""
        pending = []
        try:
            from security.approval import approval_manager
            if hasattr(approval_manager, "pending_requests"):
                for rid, req in approval_manager.pending_requests.items():
                    pending.append({
                        "id": rid,
                        "action": str(req.action) if hasattr(req, "action") else str(req),
                        "user_id": str(req.user_id) if hasattr(req, "user_id") else "?",
                        "ts": str(req.timestamp) if hasattr(req, "timestamp") else "",
                    })
        except Exception:
            pass
        return web.json_response({"pending": pending})

    async def handle_approve_action(self, request):
        """Approve or reject a pending action."""
        try:
            data = await request.json()
            request_id = data.get("id")
            approved = bool(data.get("approved", False))
            from security.approval import approval_manager
            if hasattr(approval_manager, "resolve"):
                approval_manager.resolve(request_id, approved)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    # ── Channels ──────────────────────────────────────────────────────────────
    async def handle_list_channels(self, request):
        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []

        status_map = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {}
        health_map = self.router.get_adapter_health() if hasattr(self.router, "get_adapter_health") else {}
        enriched = []
        for ch in channels:
            if not isinstance(ch, dict):
                continue
            safe_ch = _mask_sensitive_fields(ch)
            ctype = ch.get("type")
            status = status_map.get(ctype, "disconnected")
            health = health_map.get(ctype, {})
            recv = int(health.get("received_count", 0) or 0)
            sent = int(health.get("sent_count", 0) or 0)
            send_failures = int(health.get("send_failures", 0) or 0)
            proc_errors = int(health.get("processing_errors", 0) or 0)
            total_ops = max(1, recv + sent)
            failure_rate_pct = round(((send_failures + proc_errors) / total_ops) * 100.0, 2)

            last_activity_ts = max(
                float(health.get("last_message_in_ts") or 0),
                float(health.get("last_message_out_ts") or 0),
                float(health.get("last_connected_ts") or 0),
            )
            last_activity_iso = (
                datetime.fromtimestamp(last_activity_ts).isoformat()
                if last_activity_ts > 0
                else None
            )
            entry = {
                **safe_ch,
                "status": status,
                "connected": status == "connected",
                "failure_rate_pct": failure_rate_pct,
                "message_metrics": {
                    "received": recv,
                    "sent": sent,
                    "send_failures": send_failures,
                    "processing_errors": proc_errors,
                },
                "last_activity": last_activity_iso,
                "health": health,
            }
            enriched.append(entry)
        return web.json_response({"channels": enriched})

    # ── External message ──────────────────────────────────────────────────────
    async def handle_external_message(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        text = data.get("text")
        if not text:
            return web.json_response({"error": "text required"}, status=400)
        asyncio.create_task(self.agent.process(text))
        push_activity("message", data.get("channel", "api"), text[:60])
        return web.json_response({"status": "processing"})

    # ── Webhook ───────────────────────────────────────────────────────────────
    async def handle_webhook(self, request):
        event = request.match_info.get('event')
        try:
            data = await request.json()
            logger.info(f"Webhook received: {event}")
            asyncio.create_task(self.agent.process(f"webhook_event: {event} data: {data}"))
            push_activity("webhook", event, str(data)[:60])
            return web.json_response({"status": "ok"})
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

    # ── WebChat WS ────────────────────────────────────────────────────────────
    async def handle_webchat_ws(self, request):
        if self.webchat_adapter:
            return await self.webchat_adapter.handle_ws(request)
        return web.Response(status=404, text="WebChat not enabled")

    # ── Adapter init ──────────────────────────────────────────────────────────
    async def _init_adapters(self):
        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []
        for ch in channels:
            if not isinstance(ch, dict) or not ch.get("enabled", True):
                continue
            ctype = ch.get("type")
            try:
                if ctype == "telegram":
                    from .adapters.telegram import TelegramAdapter
                    self.router.register_adapter("telegram", TelegramAdapter(ch))
                elif ctype == "discord":
                    from .adapters.discord import DiscordAdapter
                    self.router.register_adapter("discord", DiscordAdapter(ch))
                elif ctype == "slack":
                    from .adapters.slack import SlackAdapter
                    self.router.register_adapter("slack", SlackAdapter(ch))
                elif ctype == "webchat":
                    from .adapters.webchat import WebChatAdapter
                    self.webchat_adapter = WebChatAdapter(ch)
                    self.router.register_adapter("webchat", self.webchat_adapter)
            except ImportError as e:
                logger.warning(f"Adapter {ctype} skipped: {e}")
            except Exception as e:
                logger.error(f"Adapter {ctype} init failed: {e}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    async def start(self, host="127.0.0.1", port=18789):
        global _start_time
        _start_time = time.time()
        logger.info(f"Starting Gateway Server on {host}:{port}...")
        await self._init_adapters()
        await self.router.start_all()
        await self.cron.start()
        self._sync_all_routines_to_cron()
        await self.heartbeat.start()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host, port)
        await site.start()
        logger.info(f"Gateway server ready at http://{host}:{port}")

    async def stop(self):
        logger.info("Stopping Gateway Server...")
        await self.heartbeat.stop()
        await self.cron.stop()
        if self.runner:
            await self.runner.cleanup()
        await self.router.stop_all()
