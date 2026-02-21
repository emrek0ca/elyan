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
