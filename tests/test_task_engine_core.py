import asyncio

from core.task_engine import TaskEngine, TaskDefinition


def test_is_chat_message_and_action_message():
    engine = TaskEngine()

    assert engine._is_chat_message("selam") is True
    assert engine._is_chat_message("teşekkür ederim") is True
    assert engine._is_chat_message("safari aç") is False
    assert engine._is_chat_message("ekran görüntüsü al") is False


def test_summarize_results_uses_data_results_contract():
    engine = TaskEngine()
    tasks = [
        TaskDefinition(id="task_1", action="open_app", params={}, description="open"),
        TaskDefinition(id="task_2", action="read_file", params={}, description="read"),
    ]

    execution_result = {
        "success": False,
        "succeeded": 1,
        "failed": 1,
        "data": {
            "results": [
                {"task_id": "task_1", "success": True},
                {"task_id": "task_2", "success": False, "error": "file missing"},
            ]
        },
    }

    summary = engine._summarize_results(execution_result, tasks)
    assert "Tamamlanan: 1/2" in summary
    assert "Basarisiz: 1" in summary
    assert "task_2" in summary
    assert "file missing" in summary

def test_non_tool_actions_fall_back_to_chat():
    engine = TaskEngine()

    async def run_case():
        async def fake_analyze_intent(user_input, context):
            return {"type": "ACTION", "confidence": 0.1}

        async def fake_decompose_tasks(user_input, intent, context):
            return [
                TaskDefinition(
                    id="task_1",
                    action="chat",
                    params={},
                    description="not a real tool",
                )
            ]

        async def fake_generate_chat_response(user_input, context):
            return "chat fallback ok"

        engine._analyze_intent = fake_analyze_intent
        engine._decompose_tasks = fake_decompose_tasks
        engine._generate_chat_response = fake_generate_chat_response

        return await engine.execute_task("bunu acikla", user_id=None)

    result = asyncio.run(run_case())
    assert result.success is True
    assert result.message == "chat fallback ok"
    assert result.metadata.get("type") == "chat_fallback"


def test_order_tasks_by_dependency_topological():
    engine = TaskEngine()
    tasks = [
        TaskDefinition(id="task_2", action="read_file", params={}, description="read", dependencies=["task_1"]),
        TaskDefinition(id="task_1", action="list_files", params={}, description="list", dependencies=[]),
        TaskDefinition(id="task_3", action="summarize_document", params={}, description="sum", dependencies=["task_2"]),
    ]
    ordered = engine._order_tasks_by_dependency(tasks)
    assert [t.id for t in ordered] == ["task_1", "task_2", "task_3"]


def test_build_task_definitions_with_dependencies():
    engine = TaskEngine()
    actions = [
        {"id": "task_1", "action": "list_files", "params": {}, "description": "list"},
        {
            "id": "task_2",
            "action": "read_file",
            "params": {"path": "{{task_1.result}}"},
            "description": "read",
            "depends_on": ["task_1"],
        },
    ]
    tasks = engine._build_task_definitions(actions, max_steps=5)
    assert len(tasks) == 2
    assert tasks[1].dependencies == ["task_1"]


def test_multi_task_bypass_executes_declared_tasks():
    engine = TaskEngine()

    async def run_case():
        async def fake_analyze_intent(user_input, context):
            return {
                "type": "MULTI_TASK",
                "action": "multi_task",
                "confidence": 1.0,
                "tasks": [
                    {"id": "task_1", "action": "create_folder", "params": {"path": "~/Desktop/x"}, "description": "mk"},
                    {
                        "id": "task_2",
                        "action": "write_file",
                        "params": {"path": "~/Desktop/x/index.html", "content": "ok"},
                        "description": "write",
                        "depends_on": ["task_1"],
                    },
                ],
            }

        async def fake_execute_tasks(tasks, notify_callback=None, user_id=None, pipeline_id=None):
            assert len(tasks) == 2
            assert tasks[0].action == "create_folder"
            assert tasks[1].action == "write_file"
            return {
                "success": True,
                "succeeded": 2,
                "failed": 0,
                "skipped": 0,
                "data": {"results": [{"task_id": "task_1", "success": True}, {"task_id": "task_2", "success": True}]},
            }

        engine._analyze_intent = fake_analyze_intent
        engine._security_check = lambda tasks, user_id: {"allowed": True}
        engine._execute_tasks = fake_execute_tasks

        return await engine.execute_task("site olustur", user_id=None)

    result = asyncio.run(run_case())
    assert result.success is True
    assert "Tum islemler tamamlandi" in result.message


def test_security_allows_write_file_html_content():
    engine = TaskEngine()
    tasks = [
        TaskDefinition(
            id="task_html",
            action="write_file",
            params={"path": "~/Desktop/test.html", "content": "<div>ok</div>"},
            description="write html"
        )
    ]
    check = engine._security_check(tasks, user_id=None)
    assert check["allowed"] is True


def test_planner_max_steps_respected():
    engine = TaskEngine()
    engine.settings.set("planner_max_steps", 5)

    class DummyTask:
        def __init__(self, i):
            self.task_id = f"t{i}"
            self.action = "list_files"
            self.params = {}
            self.name = f"task{i}"
            self.depends_on = []
            self.state = None
            self.retry_count = 0

    class DummyPlan:
        def __init__(self):
            self.subtasks = [DummyTask(i) for i in range(10)]

    async def async_create_plan(self, goal, context=None):
        return DummyPlan()

    def eval_quality(self, subtasks, goal):
        return {"safe_to_run": True}

    engine.intelligent_planner = type("P", (), {
        "create_plan": async_create_plan,
        "evaluate_plan_quality": eval_quality,
        "max_depth": 0,
    })()

    tasks = asyncio.run(engine._plan_with_intelligent_planner("dummy", {"type": "UNKNOWN"}, {}))
    assert len(tasks) == 5


def test_should_force_planning_false_for_high_confidence_direct_intent():
    engine = TaskEngine()
    intent = {"action": "open_app", "confidence": 1.0, "type": "OPEN_APP"}
    assert engine._should_force_planning("safariyi ac", intent) is False
