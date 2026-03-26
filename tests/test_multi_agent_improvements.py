"""
tests/test_multi_agent_improvements.py
─────────────────────────────────────────────────────────────────────────────
17 tests for multi-agent improvements:
  - CDG parallel dispatch with waves (6 tests)
  - Role-aware LLM selection (4 tests)
  - GoldenMemory TF-IDF fallback (4 tests)
  - AgentBus singleton (3 tests)
"""

import asyncio
import math
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.cdg_engine import CDGEngine, DAGNode, CDGPlan, NodeState
from core.performance.async_executor import AsyncExecutor, AsyncTask, TaskPriority
from core.intelligent_planner import IntelligentPlanner, _DOMAIN_TO_ROLE
from core.multi_agent.golden_memory import GoldenMemory
from core.sub_agent import get_agent_bus, reset_agent_bus, TeamMessageBus, TeamMessage


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: CDG Parallel Dispatch (6 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestCDGWaves:
    """Test topological wave sorting for parallel execution."""

    def test_cdg_waves_independent_nodes(self):
        """Two independent nodes should be in the same wave."""
        engine = CDGEngine()
        nodes = [
            DAGNode(id="n1", name="Step 1", action="web_search", depends_on=[]),
            DAGNode(id="n2", name="Step 2", action="read_file", depends_on=[]),
        ]
        waves = engine._topological_sort_waves(nodes)
        assert len(waves) == 1, "Independent nodes should be in one wave"
        assert set(waves[0]) == {"n1", "n2"}, "Both nodes should be in the same wave"

    def test_cdg_waves_linear_chain(self):
        """A → B → C should produce three separate waves."""
        engine = CDGEngine()
        nodes = [
            DAGNode(id="a", name="Step A", action="web_search", depends_on=[]),
            DAGNode(id="b", name="Step B", action="read_file", depends_on=["a"]),
            DAGNode(id="c", name="Step C", action="write_file", depends_on=["b"]),
        ]
        waves = engine._topological_sort_waves(nodes)
        assert len(waves) == 3, "Linear chain should produce 3 waves"
        assert waves[0] == ["a"], f"Wave 0 should be [a], got {waves[0]}"
        assert waves[1] == ["b"], f"Wave 1 should be [b], got {waves[1]}"
        assert waves[2] == ["c"], f"Wave 2 should be [c], got {waves[2]}"

    def test_cdg_waves_diamond_pattern(self):
        """Diamond dependency pattern: A → {B,C} → D."""
        engine = CDGEngine()
        nodes = [
            DAGNode(id="a", name="Start", action="web_search", depends_on=[]),
            DAGNode(id="b", name="Branch B", action="read_file", depends_on=["a"]),
            DAGNode(id="c", name="Branch C", action="read_file", depends_on=["a"]),
            DAGNode(id="d", name="Merge", action="write_file", depends_on=["b", "c"]),
        ]
        waves = engine._topological_sort_waves(nodes)
        assert len(waves) == 3, f"Diamond should have 3 waves, got {len(waves)}"
        assert waves[0] == ["a"], "Wave 0: A"
        assert set(waves[1]) == {"b", "c"}, f"Wave 1 should be {{b,c}}, got {set(waves[1])}"
        assert waves[2] == ["d"], "Wave 2: D"

    @pytest.mark.asyncio
    async def test_cdg_execute_concurrent(self):
        """Execute plan with parallel waves — total time < sum of individual times."""
        engine = CDGEngine()

        # Create nodes with artificial delays
        n1 = DAGNode(id="n1", name="Search Web", action="web_search", depends_on=[])
        n2 = DAGNode(id="n2", name="Read File", action="read_file", depends_on=[])
        # Both n1 and n2 are independent, should run in parallel

        plan = CDGPlan(job_id="test_parallel", job_type="test", user_input="test")
        plan.nodes = [n1, n2]

        async def mock_executor(node):
            await asyncio.sleep(0.1)  # Simulate 100ms work per node
            return {"output": f"done_{node.id}"}

        start = time.time()
        result = await engine.execute(plan, mock_executor)
        elapsed = time.time() - start

        # If sequential: 0.1 + 0.1 = 0.2s
        # If parallel: ~0.1s + overhead
        # We allow 0.15s to account for overhead; parallel should be < 0.15s
        assert elapsed < 0.15, f"Parallel execution should be faster, got {elapsed:.3f}s"
        assert result.status == "passed"
        assert n1.state == NodeState.PASSED
        assert n2.state == NodeState.PASSED

    @pytest.mark.asyncio
    async def test_cdg_execute_respects_deps(self):
        """Node B must wait for A to complete before running."""
        engine = CDGEngine()

        n1 = DAGNode(id="a", name="Step A", action="web_search", depends_on=[])
        n2 = DAGNode(id="b", name="Step B", action="read_file", depends_on=["a"])

        plan = CDGPlan(job_id="test_deps", job_type="test", user_input="test")
        plan.nodes = [n1, n2]

        execution_order = []

        async def mock_executor(node):
            execution_order.append(node.id)
            await asyncio.sleep(0.01)
            return {"output": f"done_{node.id}"}

        await engine.execute(plan, mock_executor)

        # A must execute before B
        assert execution_order.index("a") < execution_order.index("b"), \
            f"A should execute before B, got order: {execution_order}"

    @pytest.mark.asyncio
    async def test_async_executor_gather_parallelism(self):
        """AsyncExecutor with asyncio.gather should run tasks concurrently."""
        executor = AsyncExecutor(max_concurrent=3)

        task_times = []

        async def slow_task():
            start = time.time()
            await asyncio.sleep(0.05)
            elapsed = time.time() - start
            task_times.append(elapsed)
            return "result"

        # Submit 3 tasks
        for i in range(3):
            await executor.submit(
                f"task_{i}",
                slow_task,
                priority=TaskPriority.NORMAL
            )

        start = time.time()
        results = await executor.execute_all()
        total_elapsed = time.time() - start

        # If sequential: 0.05 * 3 = 0.15s
        # If parallel: ~0.05s + overhead
        assert total_elapsed < 0.12, \
            f"3 concurrent tasks should take < 0.12s, got {total_elapsed:.3f}s"
        assert len(results) == 3
        assert all(r["status"] == "success" for r in results.values())


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: Role-Aware LLM Selection (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestRoleAwareLLM:
    """Test domain-aware LLM role selection."""

    def test_domain_to_role_mapping_exists(self):
        """_DOMAIN_TO_ROLE dict should have expected mappings."""
        assert "code" in _DOMAIN_TO_ROLE
        assert "research" in _DOMAIN_TO_ROLE
        assert "api" in _DOMAIN_TO_ROLE
        assert _DOMAIN_TO_ROLE["code"] == "code"
        assert _DOMAIN_TO_ROLE["research"] == "research_worker"
        assert _DOMAIN_TO_ROLE["api"] == "code_worker"

    @pytest.mark.asyncio
    async def test_decompose_task_default_role_is_planning(self):
        """decompose_task should default to 'planning' role."""
        planner = IntelligentPlanner()

        # Mock client
        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value='[{"id":"t1","name":"Task","action":"web_search","params":{},"depends_on":[]}]')

        subtasks = await planner.decompose_task(
            "Generic task",
            llm_client=mock_client,
            use_llm=True
        )

        # Check that generate was called with role parameter
        assert mock_client.generate.called
        call_kwargs = mock_client.generate.call_args[1]
        assert "role" in call_kwargs
        assert call_kwargs["role"] == "planning"

    @pytest.mark.asyncio
    async def test_decompose_task_code_domain_uses_code_role(self):
        """Code domain should use 'code' role."""
        planner = IntelligentPlanner()

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value='[{"id":"t1","name":"Task","action":"execute_python_code","params":{},"depends_on":[]}]')

        subtasks = await planner.decompose_task(
            "Write Python code to process data",
            llm_client=mock_client,
            use_llm=True,
            preferred_tools=["execute_python_code"]
        )

        # Should use 'code' role for code domain
        call_kwargs = mock_client.generate.call_args[1]
        assert call_kwargs["role"] == "code"

    @pytest.mark.asyncio
    async def test_decompose_task_research_domain_uses_research_worker(self):
        """Research domain should use 'research_worker' role."""
        planner = IntelligentPlanner()

        mock_client = AsyncMock()
        mock_client.generate = AsyncMock(return_value='[{"id":"t1","name":"Task","action":"advanced_research","params":{},"depends_on":[]}]')

        subtasks = await planner.decompose_task(
            "Research machine learning trends",
            llm_client=mock_client,
            use_llm=True,
            preferred_tools=["advanced_research"]
        )

        # Should use 'research_worker' role for research domain
        call_kwargs = mock_client.generate.call_args[1]
        assert call_kwargs["role"] == "research_worker"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: GoldenMemory TF-IDF Fallback (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestGoldenMemoryTFIDF:
    """Test TF-IDF fallback for zero-vector embeddings."""

    def test_tfidf_identical_text(self):
        """TF-IDF of identical text should be ~1.0."""
        similarity = GoldenMemory._tfidf_similarity("hello world", "hello world")
        assert abs(similarity - 1.0) < 1e-6, f"Identical text should have similarity ~1.0, got {similarity}"

    def test_tfidf_disjoint_text(self):
        """TF-IDF of completely different text should be 0.0."""
        similarity = GoldenMemory._tfidf_similarity("apple banana", "xyz abc")
        assert similarity == 0.0, f"Disjoint text should have similarity 0.0, got {similarity}"

    def test_tfidf_partial_overlap(self):
        """TF-IDF of partially overlapping text should be between 0 and 1."""
        similarity = GoldenMemory._tfidf_similarity("hello world test", "hello earth example")
        assert 0.0 < similarity < 1.0, \
            f"Partial overlap should be between 0 and 1, got {similarity}"
        # "hello" is the only common word
        expected_min = 0.25  # At least one word match
        assert similarity >= expected_min, \
            f"Should have non-trivial overlap, got {similarity}"

    @pytest.mark.asyncio
    async def test_golden_memory_tfidf_cold_start(self):
        """GoldenMemory should fall back to TF-IDF when embedding is zero-vector."""
        import tempfile
        import sqlite3

        memory = GoldenMemory()

        # Insert recipes with different intents
        with sqlite3.connect(memory.db_path) as conn:
            conn.execute(
                "INSERT INTO recipes (intent, template_id, embedding, audit_zip, duration_s) VALUES (?, ?, ?, ?, ?)",
                ("web portfolio with modern design", "web_template_1", '[]', "audit_1.zip", 10.5)
            )
            conn.execute(
                "INSERT INTO recipes (intent, template_id, embedding, audit_zip, duration_s) VALUES (?, ?, ?, ?, ?)",
                ("python api backend service", "code_template_2", '[]', "audit_2.zip", 20.0)
            )
            conn.commit()

        # Find closest template using TF-IDF (agent=None → zero-vector)
        result = await memory.find_closest_template("create web portfolio", agent=None)

        # Should match web_template_1 due to "web" and "portfolio" overlap
        assert result == "web_template_1", \
            f"Should match web_template_1 via TF-IDF, got {result}"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: AgentBus Singleton (3 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentBusSingleton:
    """Test process-level singleton AgentBus."""

    def teardown_method(self):
        """Clean up singleton after each test."""
        reset_agent_bus()

    def test_agent_bus_is_singleton(self):
        """get_agent_bus() should return the same instance."""
        bus1 = get_agent_bus()
        bus2 = get_agent_bus()
        assert bus1 is bus2, "get_agent_bus() should return same instance"

    def test_agent_bus_reset(self):
        """reset_agent_bus() should clear the singleton."""
        bus1 = get_agent_bus()
        assert bus1 is not None
        reset_agent_bus()
        bus2 = get_agent_bus()
        assert bus1 is not bus2, "After reset, should get new instance"

    @pytest.mark.asyncio
    async def test_agent_bus_send_receive(self):
        """AgentBus should allow send/receive between agents."""
        reset_agent_bus()
        bus = get_agent_bus()

        msg = TeamMessage(
            from_agent="agent_a",
            to_agent="agent_b",
            body="Hello Agent B",
            payload={"data": "test"}
        )

        await bus.send("agent_a", "agent_b", msg)
        received = await bus.receive("agent_b", timeout=1)

        assert received is not None
        assert received.from_agent == "agent_a"
        assert received.body == "Hello Agent B"
        assert received.payload["data"] == "test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
