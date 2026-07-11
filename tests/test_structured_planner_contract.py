"""elyan.plan.v1 yapılandırılmış planlama sözleşmesi testleri.

Masaüstü ↔ sunucu beyni planlama iletişiminin tamamen veri (JSON) olarak
gitmesini, yanıtların şemayla doğrulanmasını ve bozuk planların güvenle
reddedilmesini garanti eder.
"""
from __future__ import annotations

import json

from runtime import structured_planner as sp


# ── İstek zarfı ────────────────────────────────────────────────────────────────


def test_planning_request_is_pure_json_data() -> None:
    request = sp.build_planning_request("safariyi aç")
    # Tamamı JSON-serileştirilebilir olmalı; prompt düz metin cümle değil,
    # bu zarfın kendisi.
    encoded = sp.planning_prompt(request)
    decoded = json.loads(encoded)
    assert decoded["type"] == "elyan.plan.request"
    assert decoded["contract"] == sp.PLAN_CONTRACT
    assert decoded["request"]["text"] == "safariyi aç"
    assert isinstance(decoded["toolCatalog"], list) and decoded["toolCatalog"]
    assert decoded["responseSchema"]["properties"]["contract"]["const"] == sp.PLAN_CONTRACT
    assert decoded["rules"]["role"] == "planner_only"


def test_tool_catalog_has_json_schema_and_execution_metadata() -> None:
    catalog = {tool["name"]: tool for tool in sp.tool_catalog(platform="darwin")}
    open_app = catalog["open_app"]
    assert open_app["parameters"]["type"] == "object"
    assert open_app["parameters"]["properties"]["app_name"]["type"] == "string"
    assert "app_name" in open_app["parameters"]["required"]
    assert open_app["sideEffect"] is True
    browser = catalog["browser_control"]
    assert sorted(browser["parameters"]["properties"]["action"]["enum"]) == [
        "open_url",
        "play_youtube",
        "search",
    ]


# ── Plan doğrulama ────────────────────────────────────────────────────────────


def _plan(steps, **extra):
    return {
        "contract": sp.PLAN_CONTRACT,
        "intent": "task",
        "goal": "test",
        "confidence": 0.9,
        "privacyClass": "local_private",
        "steps": steps,
        **extra,
    }


def test_valid_single_step_plan() -> None:
    plan, errors = sp.validate_plan(_plan([{"capability": "open_app", "args": {"app_name": "Safari"}}]))
    assert plan is not None
    assert not [e for e in errors if "zorunlu" in e]
    assert plan["steps"][0]["args"] == {"app_name": "Safari"}
    # open_app yan etkili → onay zorunlu hale gelir
    assert plan["requiresConfirmation"] is True


def test_unknown_capability_rejected() -> None:
    plan, errors = sp.validate_plan(_plan([{"capability": "rm_rf_everything", "args": {}}]))
    assert plan is None
    assert any("bilinmeyen capability" in e for e in errors)


def test_unknown_args_pruned_and_types_coerced() -> None:
    plan, _errors = sp.validate_plan(
        _plan([
            {
                "capability": "get_calendar_events",
                "args": {"query": "bugün", "limit": "5", "evil_flag": True},
            }
        ])
    )
    assert plan is not None
    args = plan["steps"][0]["args"]
    assert args["limit"] == 5          # "5" → 5
    assert "evil_flag" not in args      # bildirimde olmayan argüman budanır


def test_enum_constraint_normalized() -> None:
    plan, errors = sp.validate_plan(
        _plan([{"capability": "browser_control", "args": {"action": "OPEN_URL", "url": "https://x.com"}}])
    )
    assert plan is not None
    assert plan["steps"][0]["args"]["action"] == "open_url"
    assert not errors


def test_missing_required_arg_flagged() -> None:
    plan, errors = sp.validate_plan(_plan([{"capability": "open_app", "args": {}}]))
    assert any("zorunlu argüman eksik" in e for e in errors)
    # Tek adım ve bloklayıcı hata → plan reddedilir
    assert plan is None


def test_clarification_plan_maps_to_question() -> None:
    plan, _errors = sp.validate_plan(
        _plan([], clarification={"needed": True, "question": "Hangi dosyayı özetleyeyim?"})
    )
    assert plan is not None
    payload = sp.plan_to_semantic_payload(plan)
    assert payload["capability"] == ""
    assert payload["clarificationQuestion"] == "Hangi dosyayı özetleyeyim?"


def test_multi_step_plan_maps_to_plan_preview() -> None:
    plan, _errors = sp.validate_plan(
        _plan([
            {"capability": "web_research", "args": {"query": "kuantum"}},
            {"capability": "document_write", "args": {"prompt": "kuantum raporu"}},
        ])
    )
    assert plan is not None
    payload = sp.plan_to_semantic_payload(plan)
    assert payload["isMultiStep"] is True
    assert payload["requiresConfirmation"] is True
    steps = payload["planPreview"]["steps"]
    assert [s["capability"] for s in steps] == ["web_research", "document_write"]
    agent_plan = payload["planPreview"]["agentPlan"]
    assert agent_plan["stepCount"] == 2


def test_planning_request_declares_sequencing_rule() -> None:
    request = sp.build_planning_request("chrome'u aç ve sonra youtube'da müzik aç")
    rules = request["rules"]
    assert "sequencing" in rules
    assert "dependsOn" in rules["sequencing"]


def test_depends_on_preserved_through_validation() -> None:
    plan, _errors = sp.validate_plan(
        _plan([
            {"id": "a", "capability": "web_research", "args": {"query": "kuantum"}},
            {
                "id": "b",
                "capability": "document_write",
                "args": {"prompt": "kuantum raporu"},
                "dependsOn": ["a"],
            },
        ])
    )
    assert plan is not None
    assert plan["steps"][1]["dependsOn"] == ["a"]


def test_multi_step_reordered_by_depends_on() -> None:
    # LLM adımları ters sırada verdi: yaz(b) önce, araştır(a) sonra ama b→a bağımlı.
    plan, _errors = sp.validate_plan(
        _plan([
            {
                "id": "b",
                "capability": "document_write",
                "args": {"prompt": "rapor"},
                "dependsOn": ["a"],
            },
            {"id": "a", "capability": "web_research", "args": {"query": "kuantum"}},
        ])
    )
    assert plan is not None
    payload = sp.plan_to_semantic_payload(plan)
    steps = payload["planPreview"]["steps"]
    # Bağımlılık-doğru sıra: önce a (araştır), sonra b (yaz).
    assert [s["id"] for s in steps] == ["a", "b"]
    assert payload["capability"] == "web_research"


def test_independent_steps_keep_original_order() -> None:
    plan, _errors = sp.validate_plan(
        _plan([
            {"id": "s1", "capability": "open_app", "args": {"app_name": "Notes"}},
            {"id": "s2", "capability": "open_app", "args": {"app_name": "Safari"}},
        ])
    )
    assert plan is not None
    payload = sp.plan_to_semantic_payload(plan)
    steps = payload["planPreview"]["steps"]
    assert [s["args"]["app_name"] for s in steps] == ["Notes", "Safari"]


def test_dependency_cycle_falls_back_to_original_order() -> None:
    ordered = sp._order_steps_by_dependencies([
        {"id": "a", "capability": "web_research", "dependsOn": ["b"]},
        {"id": "b", "capability": "document_write", "dependsOn": ["a"]},
    ])
    # Döngü çözülemez → orijinal sıra korunur (plan bozulmaz).
    assert [s["id"] for s in ordered] == ["a", "b"]


def test_unknown_dependency_reference_ignored() -> None:
    ordered = sp._order_steps_by_dependencies([
        {"id": "a", "capability": "web_research", "dependsOn": ["ghost"]},
        {"id": "b", "capability": "document_write"},
    ])
    assert [s["id"] for s in ordered] == ["a", "b"]


def test_non_dict_payload_rejected() -> None:
    plan, errors = sp.validate_plan("düz metin cevap")
    assert plan is None
    assert errors


# ── Öğrenilmiş bağlam ve onarım turu ──────────────────────────────────────────


def test_intelligence_context_is_structured_records() -> None:
    state = {
        "taskIntelligence": {
            "recentSuccessfulRoutes": [
                {"query": "safariyi aç", "capability": "open_app", "intent": "open_app"},
            ],
            "recentMisroutes": [
                {"query": "notları belgele", "capability": "shell_run"},
            ],
            "confirmedPlanPatterns": [
                {"query": "araştır ve belgele", "capability": "web_research"},
            ],
        }
    }
    records = sp.intelligence_context(state)
    kinds = {record["kind"] for record in records}
    assert kinds == {"success", "misroute", "confirmed_plan"}
    for record in records:
        assert set(record) <= {"kind", "query", "capability", "intent"}
        assert record["query"]


def test_intelligence_context_empty_state() -> None:
    assert sp.intelligence_context({}) == []
    assert sp.intelligence_context({"taskIntelligence": "bozuk"}) == []


def test_build_repair_request_carries_errors_and_schema() -> None:
    envelope = sp.build_planning_request("safariyi aç")
    invalid = {"contract": sp.PLAN_CONTRACT, "steps": [{"capability": "uydurma_arac"}]}
    _plan, errors = sp.validate_plan(invalid)
    repair = sp.build_repair_request(envelope, invalid, errors)
    assert repair["type"] == "elyan.plan.repair"
    assert repair["contract"] == sp.PLAN_CONTRACT
    assert repair["invalidResponse"] == invalid
    assert repair["validationErrors"]
    assert repair["responseSchema"] == envelope["responseSchema"]
    assert "repair" in repair["rules"]


def test_planning_request_includes_recent_intents() -> None:
    envelope = sp.build_planning_request(
        "youtube'a gir",
        recent_intents=[{"kind": "success", "query": "safariyi aç", "capability": "open_app"}],
    )
    assert envelope["context"]["recentIntents"][0]["capability"] == "open_app"


def test_build_cowork_context_is_structured_labeled_json() -> None:
    context = sp.build_cowork_context(
        capabilities=["open_app", "close_app", "open_app"],
        desktop_snapshot={"platform": "darwin", "activeWindow": {"appName": "Safari"}},
        recent_intents=[{"kind": "success", "query": "safari aç"}],
        conversation_turns=[
            {"role": "system", "text": "prose talimat"},  # dışarıda bırakılmalı
            {"role": "user", "text": "  chrome  kapat  "},
            {"role": "assistant", "text": "Kapattım."},
        ],
    )
    assert context["contract"] == "elyan.cowork.v1"
    assert "platform" in context
    # yetenekler tekilleştirilip sıralanır
    assert context["capabilities"] == ["close_app", "open_app"]
    assert context["desktop"]["activeWindow"]["appName"] == "Safari"
    assert context["recentIntents"][0]["query"] == "safari aç"
    # system turu bağlam değil → dışarıda; metin normalize edilir
    roles = [t["role"] for t in context["conversationTurns"]]
    assert "system" not in roles
    assert context["conversationTurns"][0] == {"role": "user", "text": "chrome kapat"}


def test_build_cowork_context_bounds_turns_and_text() -> None:
    long_text = "x" * 5000
    turns = [{"role": "user", "text": f"m{i} {long_text}"} for i in range(30)]
    context = sp.build_cowork_context(conversation_turns=turns)
    # en fazla 12 tur, her biri 600 karaktere kırpılır
    assert len(context["conversationTurns"]) <= 12
    assert all(len(t["text"]) <= 600 for t in context["conversationTurns"])


def test_build_cowork_context_minimal_when_empty() -> None:
    context = sp.build_cowork_context()
    assert context["contract"] == "elyan.cowork.v1"
    assert "capabilities" not in context
    assert "conversationTurns" not in context


def test_build_replan_observation_is_structured() -> None:
    obs = sp.build_replan_observation({
        "reason": "tool_failure",
        "goal": "  kuantum   raporu hazırla  ",
        "failedCapability": "web_research",
        "errorCode": "NETWORK_FAILED",
        "message": "bağlantı  yok",
        "failedArgs": {"query": "kuantum", "_previousOutput": "gizli"},
        "completedOutputs": ["ilk adım çıktısı"],
        "remainingSteps": [
            {"capability": "document_write", "description": "rapor yaz"},
            {"capability": "", "description": "boş atlanır"},
        ],
    })
    assert obs["contract"] == "elyan.replan.v1"
    assert obs["goal"] == "kuantum raporu hazırla"
    assert obs["failedStep"]["capability"] == "web_research"
    assert obs["failedStep"]["errorCode"] == "NETWORK_FAILED"
    # dahili (_ ile başlayan) argümanlar gözleme sızmaz
    assert "_previousOutput" not in obs["failedStep"]["args"]
    assert obs["failedStep"]["args"]["query"] == "kuantum"
    assert obs["completedSteps"][0]["outputPreview"] == "ilk adım çıktısı"
    # yalnız geçerli yetenekli kalan adımlar
    assert [s["capability"] for s in obs["remainingSteps"]] == ["document_write"]


def test_tool_catalog_carries_skill_like_metadata() -> None:
    catalog = {tool["name"]: tool for tool in sp.tool_catalog(platform="darwin")}
    open_app = catalog["open_app"]
    # per-argument açıklama artık planlayıcıya taşınır (eskiden düşürülüyordu)
    app_name_desc = open_app["parameters"]["properties"]["app_name"].get("description", "")
    assert app_name_desc
    assert "eksiz" in app_name_desc.lower()
    # kullanım rehberi + örnekler
    assert open_app["usage"]
    assert isinstance(open_app["examples"], list) and open_app["examples"][0]["args"]["app_name"]
    # browser_control action enum + arg açıklamaları birlikte
    action_prop = catalog["browser_control"]["parameters"]["properties"]["action"]
    assert action_prop["description"]
    assert sorted(action_prop["enum"]) == ["open_url", "play_youtube", "search"]


def test_tool_catalog_examples_bounded_to_three() -> None:
    for tool in sp.tool_catalog(platform="darwin"):
        examples = tool.get("examples")
        if examples is not None:
            assert len(examples) <= 3


def test_every_catalog_tool_is_self_documenting() -> None:
    """Skill-benzeri kapsam garantisi: her yetenek usage + en az bir arg
    açıklaması taşır (parametresizler hariç). Yeni yetenek eklenince bu test
    onu da kendini-belgeleyen olmaya zorlar."""
    catalog = sp.tool_catalog(platform="darwin")
    assert catalog
    for tool in catalog:
        name = tool["name"]
        assert tool.get("usage"), f"{name}: usage eksik"
        props = tool["parameters"]["properties"]
        if props:  # parametresi olan her yeteneğin en az bir arg açıklaması olmalı
            assert any(p.get("description") for p in props.values()), f"{name}: arg açıklaması eksik"
