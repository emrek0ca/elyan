from core.intelligent_planner import IntelligentPlanner
import pytest


def test_planner_extract_first_json_payload_handles_fenced_array():
    raw = """Cevap:
```json
[{"id":"task_1","name":"API health","action":"api_health_check","params":{"urls":["https://httpbin.org/get"]},"depends_on":[]}]
```"""
    payload = IntelligentPlanner._extract_first_json_payload(raw)
    assert isinstance(payload, list)
    assert payload[0]["action"] == "api_health_check"


def test_planner_parse_subtasks_from_dict_steps_payload():
    planner = IntelligentPlanner()
    raw = (
        '{"steps":['
        '{"id":"task_1","name":"Araştır","action":"advanced_research","params":{"topic":"KVKK"}},'
        '{"id":"task_2","name":"Kaydet","action":"write_file","params":{"path":"~/Desktop/out.md"},"depends_on":["task_1"]}'
        "]} "
    )
    subtasks = planner._parse_subtasks_from_response(raw, "kvkk araştır", limit=5)
    assert len(subtasks) == 2
    assert subtasks[0].action == "advanced_research"
    assert subtasks[1].dependencies == ["task_1"]


def test_planner_infer_domain_from_request_prefers_api():
    domain = IntelligentPlanner._infer_domain_from_request(
        "httpbin endpoint health check yap ve GET at",
        preferred_tools=["http_request"],
        context={},
    )
    assert domain == "api"


@pytest.mark.asyncio
async def test_planner_web_prompt_requests_multi_phase_plan():
    planner = IntelligentPlanner()
    captured = {"prompt": ""}

    class _LLM:
        async def generate(self, prompt, **kwargs):
            _ = kwargs
            captured["prompt"] = prompt
            return '[{"id":"task_1","name":"Scaffold","action":"create_web_project_scaffold","params":{"project_name":"x"}}]'

    await planner.decompose_task(
        "github portfolyo sitesi yap, animasyonlu olsun",
        llm_client=_LLM(),
        use_llm=True,
        preferred_tools=["create_web_project_scaffold"],
    )
    assert "Plan 6-12 executable steps" in captured["prompt"]
    assert "Mandatory phases" in captured["prompt"]
