from __future__ import annotations

import asyncio

from core.planning.htn_planner import HTNPlanner, Method, Task


def test_known_task_uses_method_library():
    planner = HTNPlanner()
    plan = asyncio.run(planner.plan("research_topic", {}))
    assert [task.name for task in plan][:2] == ["web_search", "extract_key_facts"]


def test_unknown_task_falls_back_to_llm():
    planner = HTNPlanner()
    plan = asyncio.run(planner.plan("totally_new_task", {}))
    assert len(plan) == 1 and plan[0].is_primitive is True


def test_successful_plan_gets_cached():
    planner = HTNPlanner()
    first = asyncio.run(planner.plan("summarize document", {}))
    second = asyncio.run(planner.plan("summarize document", {}))
    assert first[0].name == second[0].name


def test_parallel_ordering_respected():
    planner = HTNPlanner()
    planner.method_library["parallel_task"] = [Method("parallel_task", subtasks=[Task("a", is_primitive=True), Task("b", is_primitive=True)], ordering="parallel")]
    plan = asyncio.run(planner.plan("parallel_task", {}))
    assert [task.name for task in plan] == ["a", "b"]


def test_recursive_decomposition_works():
    planner = HTNPlanner()
    planner.method_library["outer"] = [Method("outer", subtasks=[Task("inner", is_primitive=False)])]
    plan = asyncio.run(planner.plan("outer", {}))
    assert plan


def test_semantic_hash_maps_similar_tasks():
    planner = HTNPlanner()
    assert planner._semantic_hash("X hakkında bilgi ver") == planner._semantic_hash("x araştır")


def test_precondition_check_filters_methods():
    planner = HTNPlanner()
    planner.method_library["guarded"] = [Method("guarded", preconditions=["allowed"], subtasks=[Task("a", is_primitive=True)])]
    plan = asyncio.run(planner.plan("guarded", {"allowed": False}))
    assert plan[0].name == "guarded"
