import asyncio
import pytest

from core.scheduler import routine_engine as re_mod


class _AgentOK:
    async def process(self, prompt: str):
        return f"done: {prompt[:40]}"


class _AgentFail:
    async def process(self, prompt: str):
        raise RuntimeError("boom")


class _ToolAgent:
    async def process(self, prompt: str):
        return "fallback-ok"

    async def _execute_tool(self, tool_name: str, params: dict, **kwargs):
        if tool_name == "open_url":
            return {"success": True, "url": params.get("url")}
        if tool_name == "fetch_page":
            return {
                "success": True,
                "url": params.get("url"),
                "title": "Panel",
                "content": "Yeni sipariş var",
            }
        if tool_name == "write_excel":
            return {"success": True, "path": params.get("path")}
        if tool_name == "web_search":
            return {
                "success": True,
                "results": [{"title": "Sonuç", "url": "https://example.com", "snippet": "örnek"}],
            }
        if tool_name == "take_screenshot":
            return {"success": True, "path": "/tmp/shot.png"}
        return {"success": True}


class _ToolAgentFetchFail(_ToolAgent):
    async def _execute_tool(self, tool_name: str, params: dict, **kwargs):
        if tool_name == "fetch_page":
            return {"success": False, "error": "timeout"}
        return await super()._execute_tool(tool_name, params, **kwargs)


class _ToolAgentReportFail(_ToolAgent):
    async def _execute_tool(self, tool_name: str, params: dict, **kwargs):
        if tool_name in {"write_excel", "write_file"}:
            return {"success": False, "error": "disk full"}
        return await super()._execute_tool(tool_name, params, **kwargs)


def test_add_and_list_routine(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()

    item = engine.add_routine(
        name="Sabah Kontrol",
        expression="0 9 * * *",
        steps=["Adım 1", "Adım 2"],
        report_channel="telegram",
        report_chat_id="123",
    )
    assert item["id"]
    listed = engine.list_routines()
    assert len(listed) == 1
    assert listed[0]["name"] == "Sabah Kontrol"
    assert listed[0]["expression"] == "0 9 * * *"


@pytest.mark.asyncio
async def test_run_routine_success_records_history(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()
    item = engine.add_routine(
        name="Run OK",
        expression="*/5 * * * *",
        steps="step1;step2",
    )

    out = await engine.run_routine(item["id"], _AgentOK())
    assert out["success"] is True
    hist = engine.get_history(item["id"])
    assert len(hist) >= 1
    assert hist[0]["success"] is True


@pytest.mark.asyncio
async def test_run_routine_failure(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()
    item = engine.add_routine(
        name="Run FAIL",
        expression="*/5 * * * *",
        steps=["x"],
    )

    out = await engine.run_routine(item["id"], _AgentFail())
    assert out["success"] is False
    hist = engine.get_history(item["id"])
    assert hist[0]["success"] is False


def test_create_from_template(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()

    item = engine.create_from_template(
        template_id="ecommerce-daily",
        expression="0 9 * * *",
        report_channel="telegram",
        report_chat_id="100",
        panels=["seller.example.com", "mail.example.com"],
    )
    assert item["template_id"] == "ecommerce-daily"
    assert item["panels"] == ["https://seller.example.com", "https://mail.example.com"]
    assert len(item["steps"]) >= 5


def test_routine_id_prefix_resolution(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()
    item = engine.add_routine(
        name="Prefix Test",
        expression="0 9 * * *",
        steps=["Adım 1"],
    )
    prefix = item["id"][:6]
    resolved = engine.get_routine(prefix)
    assert resolved is not None
    assert resolved["id"] == item["id"]


@pytest.mark.asyncio
async def test_run_routine_deterministic_tools(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    monkeypatch.setattr(re_mod, "ROUTINE_REPORT_DIR", tmp_path / "reports")
    engine = re_mod.RoutineEngine()
    item = engine.add_routine(
        name="Template-like",
        expression="0 9 * * *",
        steps=[
            "Tarayıcıyı aç",
            "Belirlenen panellere giriş yap",
            "Yeni veri var mı kontrol et",
            "Excel / tablo oluştur",
            "Özet rapor hazırla",
            "Telegram / WhatsApp gönder",
        ],
        panels=["https://seller.example.com"],
    )
    out = await engine.run_routine(item["id"], _ToolAgent())
    assert out["success"] is True
    assert out["report_path"]
    assert len(out["steps"]) == 6
    assert any(step["success"] for step in out["steps"])


def test_suggest_from_text_detects_template_schedule_and_channel(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()

    suggestion = engine.suggest_from_text(
        "Her gün saat 09:15 e-ticaret panelini kontrol et, excel oluştur ve telegram gönder"
    )
    assert suggestion["template_id"] == "ecommerce-daily"
    assert suggestion["expression"] == "15 9 * * *"
    assert suggestion["report_channel"] == "telegram"
    assert len(suggestion["steps"]) >= 5


def test_suggest_from_text_detects_weekday_schedule(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()

    suggestion = engine.suggest_from_text("Hafta içi saat 18:30 panel raporu gönder")
    assert suggestion["expression"] == "30 18 * * 1-5"


def test_create_from_text_uses_template_when_detected(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()

    routine = engine.create_from_text(
        text="Her gün saat 09:00 e-ticaret siparişlerini kontrol et ve telegram gönder",
        created_by="unit-test",
    )
    assert routine["template_id"] == "ecommerce-daily"
    assert routine["expression"] == "0 9 * * *"
    assert routine["created_by"] == "unit-test"


def test_suggest_from_text_detects_personal_daily_summary_template(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()

    suggestion = engine.suggest_from_text("Her sabah saat 09:00 günlük özet gönder")
    assert suggestion["template_id"] == "personal-daily-summary"
    assert suggestion["expression"] == "0 9 * * *"


@pytest.mark.asyncio
async def test_run_personal_daily_summary_collects_runtime_context(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    monkeypatch.setattr(re_mod, "ROUTINE_REPORT_DIR", tmp_path / "reports")
    engine = re_mod.RoutineEngine()

    class _AuthSessions:
        def get_latest_session(self, *, user_ref="", workspace_id=""):
            _ = (user_ref, workspace_id)
            return {"workspace_id": "workspace-a", "user_id": "user-1"}

    class _Conversations:
        def list_recent_turns(self, *, workspace_id, actor_id, limit):
            _ = (workspace_id, actor_id, limit)
            return [
                {"user_message": "Dünkü toplantıyı özetle", "bot_response": "Ödeme akışı kapanacak."},
                {"user_message": "Slack botunu bağla", "bot_response": "Token eksik."},
            ]

    class _Approvals:
        def list_pending(self, *, limit=100):
            _ = limit
            return [{"workspace_id": "workspace-a", "action_type": "execute_shell", "reason": "Deploy için onay bekleniyor"}]

    class _Learning:
        def list_preference_updates(self, *, workspace_id, user_id, limit):
            _ = (workspace_id, user_id, limit)
            return [{"preference_key": "response_style"}]

        def list_skill_drafts(self, *, workspace_id, user_id, limit):
            _ = (workspace_id, user_id, limit)
            return [{"name_hint": "slack_sync", "description": "Slack senkronu"}]

        def list_routine_drafts(self, *, workspace_id, user_id, limit):
            _ = (workspace_id, user_id, limit)
            return [{"name_hint": "daily_summary", "description": "Sabah özeti"}]

    fake_runtime_db = type(
        "_FakeRuntimeDB",
        (),
        {
            "auth_sessions": _AuthSessions(),
            "conversations": _Conversations(),
            "approvals": _Approvals(),
            "learning": _Learning(),
        },
    )()
    monkeypatch.setattr("core.persistence.get_runtime_database", lambda: fake_runtime_db)

    item = engine.create_from_text(
        text="Her sabah saat 09:00 günlük özet gönder",
        created_by="unit-test",
        metadata={"workspace_id": "workspace-a", "actor_id": "user-1"},
    )
    out = await engine.run_routine(item["id"], _ToolAgent())

    assert out["success"] is True
    assert any("Son konuşma: 2 kayıt" in step["output"] for step in out["steps"])
    assert "Bekleyen onay: 1" in out["report"]


def test_suggest_from_text_detects_interval_hours(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()

    suggestion = engine.suggest_from_text("Her 2 saatte bir stok kontrol et ve rapor gönder")
    assert suggestion["expression"] == "0 */2 * * *"


def test_suggest_from_text_detects_evening_time_without_clock(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()

    suggestion = engine.suggest_from_text("Her akşam paneli kontrol et ve whatsapp gönder")
    assert suggestion["expression"] == "0 20 * * *"
    assert suggestion["report_channel"] == "whatsapp"


def test_suggest_from_text_detects_hour_suffix_da(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    engine = re_mod.RoutineEngine()

    suggestion = engine.suggest_from_text("Her gün 9'da rapor gönder")
    assert suggestion["expression"] == "0 9 * * *"


@pytest.mark.asyncio
async def test_run_routine_fails_when_all_panel_fetches_fail(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    monkeypatch.setattr(re_mod, "ROUTINE_REPORT_DIR", tmp_path / "reports")
    engine = re_mod.RoutineEngine()
    item = engine.add_routine(
        name="Panel strict fail",
        expression="0 9 * * *",
        steps=["Yeni veri var mı kontrol et"],
        panels=["https://seller.example.com"],
    )

    out = await engine.run_routine(item["id"], _ToolAgentFetchFail())
    assert out["success"] is False
    assert out["steps"][0]["success"] is False
    assert "okunabilir veri alınamadı" in out["steps"][0]["output"].lower()


@pytest.mark.asyncio
async def test_run_routine_fails_when_report_artifacts_cannot_be_written(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    monkeypatch.setattr(re_mod, "ROUTINE_REPORT_DIR", tmp_path / "reports")
    engine = re_mod.RoutineEngine()
    item = engine.add_routine(
        name="Report strict fail",
        expression="0 9 * * *",
        steps=["Excel / tablo oluştur"],
    )

    out = await engine.run_routine(item["id"], _ToolAgentReportFail())
    assert out["success"] is False
    assert out["steps"][0]["success"] is False
    assert "excel raporu oluşturulamadı" in out["steps"][0]["output"].lower()


@pytest.mark.asyncio
async def test_tool_batch_executes_in_parallel_with_cap(tmp_path, monkeypatch):
    path = tmp_path / "routines.json"
    monkeypatch.setattr(re_mod, "ROUTINE_PERSIST_PATH", path)
    monkeypatch.setenv("ELYAN_ROUTINE_MAX_PARALLEL", "3")
    engine = re_mod.RoutineEngine()

    active = {"value": 0, "max": 0}

    async def _fake_run_tool(agent, tool_name, params, *, user_input, step_name):
        _ = (agent, tool_name, params, user_input, step_name)
        active["value"] += 1
        active["max"] = max(active["max"], active["value"])
        await asyncio.sleep(0.05)
        active["value"] -= 1
        return True, "ok", {"success": True}

    monkeypatch.setattr(engine, "_run_tool", _fake_run_tool)
    rows = await engine._run_tool_batch(
        _ToolAgent(),
        tool_name="fetch_page",
        targets=[{"url": f"https://example.com/{i}"} for i in range(6)],
        user_input="test",
        step_name="batch_test",
    )

    assert len(rows) == 6
    assert all(row[0] for row in rows)
    assert active["max"] >= 2
    assert active["max"] <= 3
