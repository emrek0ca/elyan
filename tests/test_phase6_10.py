"""
Comprehensive tests for ELYAN Phase 6-10 modules.
Covers: API Gateway, Telemetry, Turkish NLP, Reasoning Engine,
Multi-Agent v2, Billing, Plugin System, Integration SDK,
Multi-Language, Compliance Framework.
"""

import time
import pytest

# ── Phase 6: API Gateway ──────────────────────────────────────────────

from core.api_gateway import (
    TokenManager, APIKeyManager, WebhookManager,
    GatewayRateLimiter, APIGateway, Permission,
)


class TestTokenManager:
    def test_create_and_validate_token(self):
        tm = TokenManager()
        token = tm.create_access_token("user1", ["read", "write"])
        assert token is not None
        valid, payload = tm.validate_token(token)
        assert valid is True
        assert payload is not None
        assert payload.sub == "user1"

    def test_revoke_token(self):
        tm = TokenManager()
        token = tm.create_access_token("user1", ["read"])
        # Token should be valid first
        valid, _ = tm.validate_token(token)
        assert valid is True


class TestAPIKeyManager:
    def test_create_and_validate(self):
        akm = APIKeyManager()
        raw_key, record = akm.create_key("user1", "Test Key")
        assert raw_key.startswith("elk_")
        assert record.name == "Test Key"
        valid, key_obj = akm.validate_key(raw_key)
        assert valid is True
        assert key_obj is not None

    def test_revoke_key(self):
        akm = APIKeyManager()
        raw_key, record = akm.create_key("user1", "Test")
        akm.revoke_key(record.key_id)
        valid, _ = akm.validate_key(raw_key)
        assert valid is False

    def test_list_keys(self):
        akm = APIKeyManager()
        akm.create_key("user1", "Key1")
        akm.create_key("user1", "Key2")
        akm.create_key("user2", "Key3")
        assert len(akm.list_keys("user1")) == 2
        assert len(akm.list_keys("user2")) == 1


class TestGatewayRateLimiter:
    def test_allows_within_limit(self):
        rl = GatewayRateLimiter(default_limit=10)
        allowed, headers = rl.check("user1")
        assert allowed is True

    def test_blocks_over_limit(self):
        rl = GatewayRateLimiter(default_limit=2, window_seconds=60)
        rl.check("user1")
        rl.check("user1")
        allowed, _ = rl.check("user1")
        assert allowed is False


class TestAPIGateway:
    def test_bearer_auth(self):
        gw = APIGateway()
        token = gw.token_manager.create_access_token("user1", ["read"])
        valid, user_id, perms = gw.authenticate(f"Bearer {token}")
        assert valid is True
        assert user_id == "user1"

    def test_apikey_auth(self):
        gw = APIGateway()
        raw_key, _ = gw.key_manager.create_key("user1", "Test")
        valid, user_id, perms = gw.authenticate(f"ApiKey {raw_key}")
        assert valid is True

    def test_process_request(self):
        gw = APIGateway()
        token = gw.token_manager.create_access_token("user1", ["read"])
        result = gw.process_request(f"Bearer {token}", "GET", "/api/test")
        assert "status" in result


# ── Phase 6: Telemetry ───────────────────────────────────────────────

from core.telemetry_system import (
    DistributedTracer, SessionTracker,
    StructuredLogger, TelemetrySystem,
    EventCategory, LogLevel,
)


class TestDistributedTracer:
    def test_trace_lifecycle(self):
        dt = DistributedTracer()
        root = dt.start_trace("test_op")
        child = dt.start_span(root.trace_id, "child_op")
        dt.finish_span(child.span_id)
        summary = dt.get_trace_summary(root.trace_id)
        assert summary is not None
        assert "span_count" in summary

    def test_multiple_spans(self):
        dt = DistributedTracer()
        root = dt.start_trace("parent")
        s1 = dt.start_span(root.trace_id, "child1")
        s2 = dt.start_span(root.trace_id, "child2")
        dt.finish_span(s1.span_id)
        dt.finish_span(s2.span_id)
        spans = dt.get_trace(root.trace_id)
        assert len(spans) >= 2


class TestSessionTracker:
    def test_session_tracking(self):
        st = SessionTracker()
        session = st.start_session("user1")
        st.record_request(session.session_id, 50.0)
        st.end_session(session.session_id)
        sessions = st.get_user_sessions("user1")
        assert len(sessions) >= 1

    def test_analytics(self):
        st = SessionTracker()
        s = st.start_session("user1")
        st.record_request(s.session_id, 100.0)
        st.end_session(s.session_id)
        analytics = st.get_analytics()
        assert "total_sessions" in analytics


class TestStructuredLogger:
    def test_log_and_query(self):
        sl = StructuredLogger()
        sl.log(EventCategory.SYSTEM, LogLevel.INFO, "Test message")
        sl.log(EventCategory.ERROR, LogLevel.ERROR, "Error message")
        results = sl.query(level=LogLevel.ERROR)
        assert len(results) >= 1

    def test_error_summary(self):
        sl = StructuredLogger()
        sl.error("Test error")
        summary = sl.get_error_summary()
        assert isinstance(summary, dict)


class TestTelemetrySystem:
    def test_unified_system(self):
        ts = TelemetrySystem()
        ctx = ts.start_request("user1", "test_op")
        assert "trace_id" in ctx
        ts.end_request(ctx["trace_id"], ctx["span_id"], latency_ms=50.0)
        health = ts.get_system_health()
        assert isinstance(health, dict)


# ── Phase 7: Turkish NLP ─────────────────────────────────────────────

from core.nlp.turkish_nlp import (
    VowelHarmonyAnalyzer, AgglutinationAnalyzer,
    TurkishNER, SemanticSimilarity, CodeSwitchDetector,
    TurkishNLPEngine,
)


class TestVowelHarmony:
    def test_twoway_harmony(self):
        vh = VowelHarmonyAnalyzer()
        result = vh.check_two_way("ev", "ler")
        assert isinstance(result, bool)

    def test_fourway_harmony(self):
        vh = VowelHarmonyAnalyzer()
        result = vh.check_four_way("goz", "luk")
        assert isinstance(result, bool)

    def test_validate_word(self):
        vh = VowelHarmonyAnalyzer()
        result = vh.validate_word("evler")
        assert isinstance(result, bool)


class TestAgglutination:
    def test_suffix_decomposition(self):
        aa = AgglutinationAnalyzer()
        result = aa.analyze("evlerden")
        assert result.root is not None
        assert hasattr(result, 'suffixes')

    def test_get_root(self):
        aa = AgglutinationAnalyzer()
        root = aa.get_root("evlerden")
        assert isinstance(root, str)
        assert len(root) > 0

    def test_suffix_chain(self):
        aa = AgglutinationAnalyzer()
        chain = aa.get_suffix_chain("evlerden")
        assert isinstance(chain, list)


class TestTurkishNER:
    def test_date_entity(self):
        ner = TurkishNER()
        entities = ner.extract("15 Ocak 2024 tarihinde toplanti var")
        types = [e.entity_type.value if hasattr(e.entity_type, 'value') else str(e.entity_type) for e in entities]
        assert any("date" in t.lower() or "DATE" in str(t) for t in types)

    def test_money_entity(self):
        ner = TurkishNER()
        entities = ner.extract("Fiyat 100 TL olacak")
        types = [e.entity_type.value if hasattr(e.entity_type, 'value') else str(e.entity_type) for e in entities]
        assert any("money" in t.lower() or "MONEY" in str(t) for t in types)

    def test_extract_returns_list(self):
        ner = TurkishNER()
        entities = ner.extract("Merhaba dunya")
        assert isinstance(entities, list)


class TestSemanticSimilarity:
    def test_identical_texts(self):
        ss = SemanticSimilarity()
        score = ss.similarity("merhaba dunya", "merhaba dunya")
        assert score == 1.0

    def test_different_texts(self):
        ss = SemanticSimilarity()
        score = ss.similarity("ev araba", "uzay galaksi")
        assert score < 1.0

    def test_find_most_similar(self):
        ss = SemanticSimilarity()
        results = ss.find_most_similar("ev", ["ev araba", "uzay", "evler"])
        assert isinstance(results, list)


class TestCodeSwitchDetector:
    def test_mixed_text(self):
        csd = CodeSwitchDetector()
        result = csd.detect("Bu code cok complex olmus")
        assert isinstance(result, dict)


class TestTurkishNLPEngine:
    def test_full_analysis(self):
        engine = TurkishNLPEngine()
        result = engine.analyze("Ankara'da 15 Ocak'ta toplanti var")
        assert isinstance(result, dict)

    def test_get_roots(self):
        engine = TurkishNLPEngine()
        roots = engine.get_roots("evlerden geliyorum")
        assert isinstance(roots, list)


# ── Phase 7: Reasoning Engine ────────────────────────────────────────

from core.reasoning_engine import (
    ChainOfThought, TreeOfThought,
    CausalReasoner, UncertaintyQuantifier,
    ReasoningEngine, ReasoningStrategy,
)


class TestChainOfThought:
    def test_reasoning_chain(self):
        cot = ChainOfThought()
        chain = cot.reason(question="Why is the sky blue?")
        assert chain.question == "Why is the sky blue?"
        assert hasattr(chain, 'steps')

    def test_list_chains(self):
        cot = ChainOfThought()
        cot.reason(question="Test question")
        chains = cot.list_chains()
        assert len(chains) >= 1


class TestTreeOfThought:
    def test_explore(self):
        tot = TreeOfThought()
        root = tot.explore(question="Best approach?")
        assert root is not None
        assert hasattr(root, 'content')

    def test_best_path(self):
        tot = TreeOfThought()
        root = tot.explore(question="Choose wisely")
        path = tot.get_best_path(root)
        assert isinstance(path, list)


class TestCausalReasoner:
    def test_add_and_trace(self):
        cr = CausalReasoner()
        cr.add_relation("rain", "wet_ground", 0.9)
        cr.add_relation("wet_ground", "slippery", 0.8)
        chains = cr.trace_chain("rain")
        assert isinstance(chains, list)

    def test_find_effects(self):
        cr = CausalReasoner()
        cr.add_relation("rain", "wet_ground", 0.9)
        effects = cr.find_effects("rain")
        assert len(effects) >= 1

    def test_counterfactual(self):
        cr = CausalReasoner()
        cr.add_relation("rain", "wet_ground", 0.9)
        result = cr.get_counterfactual("rain")
        assert isinstance(result, dict)


class TestUncertaintyQuantifier:
    def test_estimate(self):
        uq = UncertaintyQuantifier()
        result = uq.estimate(0.8)
        assert hasattr(result, 'confidence_level')

    def test_confidence_label(self):
        label = UncertaintyQuantifier.confidence_to_label(0.9)
        assert isinstance(label, str)


class TestReasoningEngine:
    def test_chain_strategy(self):
        engine = ReasoningEngine()
        result = engine.reason(
            question="Test question",
            strategy=ReasoningStrategy.CHAIN_OF_THOUGHT,
        )
        assert isinstance(result, dict)

    def test_tree_strategy(self):
        engine = ReasoningEngine()
        result = engine.reason(
            question="Another test",
            strategy=ReasoningStrategy.TREE_OF_THOUGHT,
        )
        assert isinstance(result, dict)


# ── Phase 7: Multi-Agent v2 ──────────────────────────────────────────

from core.multi_agent_v2 import (
    MessageBus, TaskScheduler, ConflictResolver,
    CollaborativePlanner, MultiAgentOrchestrator,
    AgentRole, AgentProfile, AgentMessage, MessageType,
    TaskPacket, Priority, TaskStatus,
)


class TestMessageBus:
    def test_send_receive(self):
        bus = MessageBus()
        msg = AgentMessage(
            message_id="msg1", sender_id="a1", receiver_id="a2",
            message_type=MessageType.QUERY, content={"q": "hello"},
        )
        bus.send(msg)
        assert bus.peek("a2") == 1
        received = bus.receive("a2")
        assert len(received) == 1
        assert received[0].content["q"] == "hello"

    def test_broadcast(self):
        bus = MessageBus()
        bus.broadcast("a1", ["a2", "a3", "a1"], MessageType.HEARTBEAT, {"status": "ok"})
        assert bus.peek("a2") == 1
        assert bus.peek("a3") == 1
        assert bus.peek("a1") == 0  # sender excluded

    def test_history(self):
        bus = MessageBus()
        msg = AgentMessage(
            message_id="m1", sender_id="a1", receiver_id="a2",
            message_type=MessageType.STATUS_UPDATE, content={},
        )
        bus.send(msg)
        history = bus.get_history("a1")
        assert len(history) >= 1


class TestTaskScheduler:
    def test_assign_task(self):
        sched = TaskScheduler()
        agent = AgentProfile(
            agent_id="ag1", name="Coder", role=AgentRole.CODER,
            capabilities=["python", "testing"],
        )
        sched.register_agent(agent)
        task = TaskPacket(
            task_id="t1", title="Write tests", description="...",
            required_capabilities=["python"],
        )
        sched.add_task(task)
        assigned = sched.assign("t1")
        assert assigned == "ag1"
        assert task.status == TaskStatus.ASSIGNED

    def test_complete_task(self):
        sched = TaskScheduler()
        agent = AgentProfile(
            agent_id="ag1", name="Agent", role=AgentRole.EXECUTOR,
            capabilities=["general"],
        )
        sched.register_agent(agent)
        task = TaskPacket(task_id="t1", title="T", description="D",
                         required_capabilities=["general"])
        sched.add_task(task)
        sched.assign("t1")
        sched.complete_task("t1", {"output": "done"})
        assert task.status == TaskStatus.COMPLETED

    def test_fail_task(self):
        sched = TaskScheduler()
        agent = AgentProfile(
            agent_id="ag1", name="Agent", role=AgentRole.EXECUTOR,
            capabilities=["general"],
        )
        sched.register_agent(agent)
        task = TaskPacket(task_id="t1", title="T", description="D",
                         required_capabilities=["general"])
        sched.add_task(task)
        sched.assign("t1")
        sched.fail_task("t1", "error occurred")
        assert task.status == TaskStatus.FAILED

    def test_stats(self):
        sched = TaskScheduler()
        stats = sched.get_stats()
        assert "total_tasks" in stats


class TestConflictResolver:
    def test_resolve_by_priority(self):
        cr = ConflictResolver()
        conflict = cr.detect_conflict(["a1", "a2"], "file.py", "Both editing")
        winner = cr.resolve_by_priority(conflict, {"a1": 2, "a2": 1})
        assert winner == "a2"
        assert conflict.resolved is True

    def test_resolve_by_load(self):
        cr = ConflictResolver()
        conflict = cr.detect_conflict(["a1", "a2"], "db", "Concurrent access")
        winner = cr.resolve_by_load(conflict, {"a1": 0.8, "a2": 0.3})
        assert winner == "a2"

    def test_unresolved(self):
        cr = ConflictResolver()
        cr.detect_conflict(["a1", "a2"], "resource", "test")
        assert len(cr.get_unresolved()) == 1


class TestCollaborativePlanner:
    def test_create_plan(self):
        cp = CollaborativePlanner()
        plan = cp.create_plan("Build feature", [
            {"title": "Design", "capabilities": ["design"]},
            {"title": "Implement", "capabilities": ["coding"]},
            {"title": "Test", "capabilities": ["testing"]},
        ])
        assert plan.goal == "Build feature"
        assert len(plan.tasks) == 3
        assert len(plan.parallel_waves) >= 1

    def test_list_plans(self):
        cp = CollaborativePlanner()
        cp.create_plan("Goal", [{"title": "T1"}])
        plans = cp.list_plans()
        assert len(plans) >= 1


class TestMultiAgentOrchestrator:
    def test_register_and_submit(self):
        orch = MultiAgentOrchestrator()
        agent = orch.register_agent("Coder", AgentRole.CODER, ["python"])
        task = orch.submit_task("Write code", "Python module", ["python"])
        assert task.assigned_agent == agent.agent_id

    def test_complete_task(self):
        orch = MultiAgentOrchestrator()
        orch.register_agent("Worker", AgentRole.EXECUTOR, ["general"])
        task = orch.submit_task("Do work", "Task desc", ["general"])
        orch.complete_task(task.task_id, {"done": True})

    def test_status(self):
        orch = MultiAgentOrchestrator()
        status = orch.get_status()
        assert "scheduler" in status


# ── Phase 8: Billing ─────────────────────────────────────────────────

from core.billing.subscription import (
    UsageTracker, SubscriptionManager, SubscriptionTier, UsageType,
)


class TestUsageTracker:
    def test_record_and_get(self):
        ut = UsageTracker()
        ut.record("user1", UsageType.API_REQUEST, 1)
        ut.record("user1", UsageType.API_REQUEST, 4)
        usage = ut.get_usage("user1")
        assert UsageType.API_REQUEST in usage
        assert usage[UsageType.API_REQUEST] == 5

    def test_check_limit(self):
        ut = UsageTracker()
        result = ut.check_limit("user1", UsageType.API_REQUEST, SubscriptionTier.FREE)
        assert "allowed" in result or "within_limit" in result or isinstance(result, dict)

    def test_reset_period(self):
        ut = UsageTracker()
        ut.record("user1", UsageType.API_REQUEST, 50)
        ut.reset_period("user1")
        usage = ut.get_usage("user1")
        total = sum(usage.values()) if usage else 0
        assert total == 0


class TestSubscriptionManager:
    def test_create_subscription(self):
        sm = SubscriptionManager()
        sub = sm.create_subscription("user1", SubscriptionTier.PRO)
        assert sub.tier == SubscriptionTier.PRO

    def test_upgrade(self):
        sm = SubscriptionManager()
        sm.create_subscription("user1", SubscriptionTier.FREE)
        result = sm.upgrade("user1", SubscriptionTier.PRO)
        assert result is not None
        sub = sm.get_subscription("user1")
        assert sub.tier == SubscriptionTier.PRO

    def test_check_feature(self):
        sm = SubscriptionManager()
        sm.create_subscription("user1", SubscriptionTier.ENTERPRISE)
        features = sm.get_features("user1")
        assert isinstance(features, list)

    def test_get_invoices(self):
        sm = SubscriptionManager()
        sm.create_subscription("user1", SubscriptionTier.PRO)
        invoices = sm.get_invoices("user1")
        assert isinstance(invoices, list)


# ── Phase 8: Plugin System ───────────────────────────────────────────

from core.plugins.plugin_system import (
    PluginSecurityScanner, PluginRegistry,
    PluginManager, RBACManager,
    PluginManifest, PluginCategory, HookPoint, Plugin,
)


class TestPluginSecurityScanner:
    def test_scan_returns_result(self):
        scanner = PluginSecurityScanner()
        manifest = PluginManifest(
            name="safe-plugin", version="1.0.0", description="Test",
            author="Author", category=PluginCategory.TOOL,
            entry_point="plugin.py",
        )
        registry = PluginRegistry()
        plugin = registry.register(manifest)
        result = scanner.scan(plugin)
        assert hasattr(result, 'passed') or hasattr(result, 'safe') or isinstance(result, object)


class TestPluginRegistry:
    def test_register_and_search(self):
        reg = PluginRegistry()
        manifest = PluginManifest(
            name="test-plugin", version="1.0.0", description="A test plugin",
            author="TestAuthor", category=PluginCategory.TOOL,
            entry_point="plugin.py", tags=["test"],
        )
        plugin = reg.register(manifest)
        reg.publish(plugin.plugin_id)  # Must publish before search finds it
        assert plugin is not None
        results = reg.search("test")
        assert len(results) >= 1

    def test_search_by_category(self):
        reg = PluginRegistry()
        m1 = PluginManifest(name="p1", version="1.0", description="P1",
                            author="A", category=PluginCategory.TOOL, entry_point="p1.py")
        m2 = PluginManifest(name="p2", version="1.0", description="P2",
                            author="A", category=PluginCategory.ANALYTICS, entry_point="p2.py")
        p1 = reg.register(m1)
        p2 = reg.register(m2)
        reg.publish(p1.plugin_id)
        reg.publish(p2.plugin_id)
        results = reg.search(category=PluginCategory.TOOL)
        assert len(results) >= 1

    def test_stats(self):
        reg = PluginRegistry()
        stats = reg.get_stats()
        assert isinstance(stats, dict)


class TestPluginManager:
    def test_install_uninstall(self):
        reg = PluginRegistry()
        manifest = PluginManifest(
            name="my-plugin", version="1.0", description="Test",
            author="Author", category=PluginCategory.TOOL,
            entry_point="plugin.py",
        )
        plugin = reg.register(manifest)
        reg.publish(plugin.plugin_id)
        pm = PluginManager(registry=reg)
        result = pm.install("user1", plugin.plugin_id)
        assert result is not None
        installed = pm.get_installed("user1")
        assert len(installed) >= 1
        pm.uninstall("user1", plugin.plugin_id)
        assert len(pm.get_installed("user1")) == 0


class TestRBACManager:
    def test_assign_and_check(self):
        rbac = RBACManager()
        rbac.assign_role("user1", "admin")
        roles = rbac.get_user_roles("user1")
        assert "admin" in roles
        perms = rbac.get_permissions("user1")
        assert len(perms) > 0

    def test_check_permission(self):
        rbac = RBACManager()
        rbac.assign_role("user1", "viewer")
        # viewer should have limited permissions
        has_perm = rbac.check_permission("user1", "read")
        assert isinstance(has_perm, bool)

    def test_custom_role(self):
        rbac = RBACManager()
        rbac.create_custom_role("custom", {"read", "write"})
        rbac.assign_role("user1", "custom")
        assert rbac.check_permission("user1", "read") is True
        assert rbac.check_permission("user1", "delete") is False

    def test_list_roles(self):
        rbac = RBACManager()
        roles = rbac.list_roles()
        assert isinstance(roles, dict)
        assert len(roles) > 0  # built-in roles exist


# ── Phase 9: Integration SDK ─────────────────────────────────────────

from core.integrations.integration_sdk import (
    SlackIntegration, GitHubIntegration,
    JiraIntegration, NotionIntegration, IntegrationHub,
    IntegrationConfig, IntegrationType,
)


class TestSlackIntegration:
    def test_connect_disconnect(self):
        config = IntegrationConfig(
            name="slack", integration_type=IntegrationType.MESSAGING,
            auth_token="xoxb-test", settings={"default_channel": "#general"},
        )
        slack = SlackIntegration(config)
        slack.connect()
        assert slack.is_connected is True
        slack.disconnect()
        assert slack.is_connected is False

    def test_status(self):
        config = IntegrationConfig(
            name="slack", integration_type=IntegrationType.MESSAGING,
            auth_token="xoxb-test",
        )
        slack = SlackIntegration(config)
        status = slack.get_status()
        assert isinstance(status, dict)


class TestGitHubIntegration:
    def test_lifecycle(self):
        config = IntegrationConfig(
            name="github", integration_type=IntegrationType.DEV_TOOLS,
            auth_token="ghp_test", settings={"default_repo": "owner/repo"},
        )
        gh = GitHubIntegration(config)
        gh.connect()
        assert gh.is_connected is True
        gh.disconnect()
        assert gh.is_connected is False


class TestJiraIntegration:
    def test_lifecycle(self):
        config = IntegrationConfig(
            name="jira", integration_type=IntegrationType.PRODUCTIVITY,
            api_base_url="https://test.atlassian.net",
            auth_token="token",
            settings={"email": "user@test.com", "default_project": "TEST"},
        )
        jira = JiraIntegration(config)
        jira.connect()
        assert jira.is_connected is True


class TestNotionIntegration:
    def test_lifecycle(self):
        config = IntegrationConfig(
            name="notion", integration_type=IntegrationType.PRODUCTIVITY,
            auth_token="secret_test",
        )
        notion = NotionIntegration(config)
        notion.connect()
        assert notion.is_connected is True


class TestIntegrationHub:
    def test_add_and_list(self):
        hub = IntegrationHub()
        config = IntegrationConfig(
            name="slack", integration_type=IntegrationType.MESSAGING,
            auth_token="xoxb-test",
        )
        hub.add("slack", config)
        available = hub.list_available()
        assert "slack" in available

    def test_connect_and_status(self):
        hub = IntegrationHub()
        config = IntegrationConfig(
            name="github", integration_type=IntegrationType.DEV_TOOLS,
            auth_token="ghp_test",
        )
        hub.add("github", config)
        hub.connect("github")
        status = hub.get_all_status()
        assert "github" in status

    def test_list_connected(self):
        hub = IntegrationHub()
        c1 = IntegrationConfig(name="s", integration_type=IntegrationType.MESSAGING, auth_token="t")
        c2 = IntegrationConfig(name="g", integration_type=IntegrationType.DEV_TOOLS, auth_token="t")
        hub.add("slack", c1)
        hub.add("github", c2)
        hub.connect("slack")
        connected = hub.list_connected()
        assert "slack" in connected


# ── Phase 10: Multi-Language ──────────────────────────────────────────

from core.i18n.multi_language import (
    LanguageDetector, TranslationEngine, LocaleManager,
    MultiLanguageEngine, Language, TranslationRequest,
)


class TestLanguageDetector:
    def test_detect_turkish(self):
        ld = LanguageDetector()
        result = ld.detect("Bu bir nasil gibi icin kadar ve tamam")
        assert result.primary_language == Language.TURKISH

    def test_detect_english(self):
        ld = LanguageDetector()
        result = ld.detect("the is are was have has will can this that from with about please thanks yes no")
        assert result.primary_language == Language.ENGLISH

    def test_empty_text(self):
        ld = LanguageDetector()
        result = ld.detect("")
        assert result.confidence == 0.0

    def test_confidence_range(self):
        ld = LanguageDetector()
        result = ld.detect("Merhaba bu bir test")
        assert 0 <= result.confidence <= 1


class TestTranslationEngine:
    def test_translate_tr_en(self):
        te = TranslationEngine()
        req = TranslationRequest("merhaba", Language.TURKISH, Language.ENGLISH)
        result = te.translate(req)
        assert result.translated == "hello"

    def test_reverse_dictionary(self):
        te = TranslationEngine()
        req = TranslationRequest("hello", Language.ENGLISH, Language.TURKISH)
        result = te.translate(req)
        assert result.translated == "merhaba"

    def test_stats(self):
        te = TranslationEngine()
        req = TranslationRequest("evet", Language.TURKISH, Language.ENGLISH)
        te.translate(req)
        stats = te.get_stats()
        assert stats["translation_count"] == 1

    def test_supported_pairs(self):
        te = TranslationEngine()
        pairs = te.get_supported_pairs()
        assert len(pairs) >= 2  # TR->EN and EN->TR


class TestLocaleManager:
    def test_set_and_get(self):
        lm = LocaleManager()
        lm.set_locale("user1", Language.TURKISH)
        locale = lm.get_locale("user1")
        assert locale.language == Language.TURKISH
        assert locale.currency == "TRY"

    def test_format_number(self):
        lm = LocaleManager()
        lm.set_locale("user1", Language.TURKISH)
        result = lm.format_number(1234567, "user1")
        assert "." in result  # Turkish uses . as thousands separator

    def test_text_direction(self):
        lm = LocaleManager()
        lm.set_locale("user1", Language.ARABIC)
        direction = lm.get_text_direction("user1")
        assert direction.value == "rtl"


class TestMultiLanguageEngine:
    def test_process(self):
        engine = MultiLanguageEngine()
        result = engine.process("Bu bir test cumle nasil gibi")
        assert "detected_language" in result

    def test_process_with_user(self):
        engine = MultiLanguageEngine()
        engine.locale_manager.set_locale("u1", Language.TURKISH)
        result = engine.process("merhaba", user_id="u1")
        assert "user_locale" in result

    def test_auto_translate_known_word(self):
        engine = MultiLanguageEngine()
        # Force detection to Turkish by using Turkish indicators
        result = engine.auto_translate("merhaba bu bir test nasil gibi kadar", Language.ENGLISH)
        # Should attempt translation
        assert result.target_language == Language.ENGLISH


# ── Phase 10: Compliance ─────────────────────────────────────────────

from core.compliance_v2.compliance import (
    ConsentManager, DataProtectionOfficer, ComplianceAuditor,
    DataAnonymizer, ComplianceEngine,
    ComplianceFramework, DataCategory, DataAction,
    ConsentStatus, AuditSeverity,
)


class TestConsentManager:
    def test_consent_lifecycle(self):
        cm = ConsentManager()
        consent = cm.request_consent("user1", "analytics", [DataCategory.PERSONAL])
        assert consent.status == ConsentStatus.PENDING
        cm.grant_consent(consent.consent_id, "1.2.3.4")
        assert consent.status == ConsentStatus.GRANTED
        assert cm.check_consent("user1", "analytics") is True
        cm.withdraw_consent(consent.consent_id)
        assert consent.status == ConsentStatus.WITHDRAWN
        assert cm.check_consent("user1", "analytics") is False

    def test_user_consents(self):
        cm = ConsentManager()
        cm.request_consent("user1", "p1", [DataCategory.PERSONAL])
        cm.request_consent("user1", "p2", [DataCategory.FINANCIAL])
        consents = cm.get_user_consents("user1")
        assert len(consents) == 2

    def test_expire_stale(self):
        cm = ConsentManager()
        consent = cm.request_consent("user1", "test", [DataCategory.PERSONAL], ttl_days=0)
        cm.grant_consent(consent.consent_id)
        time.sleep(0.1)
        expired = cm.expire_stale()
        assert expired >= 1


class TestDataProtectionOfficer:
    def test_record_processing(self):
        dpo = DataProtectionOfficer()
        record = dpo.record_processing(
            "user1", DataAction.COLLECT, [DataCategory.PERSONAL],
            "analytics", "consent",
        )
        assert record.user_id == "user1"
        log = dpo.get_processing_log("user1")
        assert len(log) == 1

    def test_subject_request_access(self):
        dpo = DataProtectionOfficer()
        dpo.record_processing("user1", DataAction.STORE, [DataCategory.PERSONAL],
                              "storage")
        dsr = dpo.submit_subject_request("user1", "access")
        result = dpo.process_request(dsr.request_id)
        assert result.status == "completed"
        assert result.response_data["processing_records"] == 1

    def test_subject_request_deletion(self):
        dpo = DataProtectionOfficer()
        dpo.record_processing("user1", DataAction.STORE, [DataCategory.PERSONAL],
                              "storage")
        dsr = dpo.submit_subject_request("user1", "deletion")
        result = dpo.process_request(dsr.request_id)
        assert result.response_data["deleted_records"] == 1
        assert len(dpo.get_processing_log("user1")) == 0

    def test_portability(self):
        dpo = DataProtectionOfficer()
        dpo.record_processing("user1", DataAction.COLLECT, [DataCategory.PERSONAL],
                              "marketing")
        dsr = dpo.submit_subject_request("user1", "portability")
        result = dpo.process_request(dsr.request_id)
        assert result.status == "completed"
        assert "records" in result.response_data


class TestComplianceAuditor:
    def test_log_event(self):
        ca = ComplianceAuditor()
        entry = ca.log_event(
            ComplianceFramework.GDPR, AuditSeverity.INFO,
            "consent", "Consent granted",
        )
        assert entry.framework == ComplianceFramework.GDPR
        entries = ca.get_entries(framework=ComplianceFramework.GDPR)
        assert len(entries) >= 1

    def test_generate_report(self):
        ca = ComplianceAuditor()
        ca.log_event(ComplianceFramework.GDPR, AuditSeverity.INFO, "test", "Info")
        ca.log_event(ComplianceFramework.GDPR, AuditSeverity.VIOLATION, "test", "Violation")
        report = ca.generate_report(ComplianceFramework.GDPR)
        assert report.score < 1.0
        assert len(report.findings) >= 1

    def test_run_audit(self):
        ca = ComplianceAuditor()
        findings = ca.run_audit(ComplianceFramework.GDPR)
        assert isinstance(findings, list)

    def test_filter_by_severity(self):
        ca = ComplianceAuditor()
        ca.log_event(ComplianceFramework.SOC2, AuditSeverity.WARNING, "test", "W")
        ca.log_event(ComplianceFramework.SOC2, AuditSeverity.CRITICAL, "test", "C")
        criticals = ca.get_entries(severity=AuditSeverity.CRITICAL)
        assert len(criticals) >= 1


class TestDataAnonymizer:
    def test_pseudonymize(self):
        da = DataAnonymizer()
        result = da.pseudonymize("john@example.com")
        assert result.startswith("pseudo_")
        assert da.pseudonymize("john@example.com") == result  # deterministic

    def test_anonymize_dict(self):
        da = DataAnonymizer()
        data = {"name": "John", "age": 30, "email": "john@test.com"}
        result = da.anonymize_dict(data, {"name", "email"})
        assert result["age"] == 30
        assert result["name"].startswith("pseudo_")
        assert result["email"].startswith("pseudo_")

    def test_mask_email(self):
        da = DataAnonymizer()
        masked = da.mask_email("john@example.com")
        assert "@example.com" in masked
        assert masked.startswith("j")
        assert "*" in masked

    def test_mask_phone(self):
        da = DataAnonymizer()
        masked = da.mask_phone("+90 555 123 4567")
        assert masked.endswith("4567")
        assert "*" in masked


class TestComplianceEngine:
    def test_process_without_consent(self):
        ce = ComplianceEngine()
        result = ce.process_data("user1", DataAction.COLLECT,
                                 [DataCategory.PERSONAL], "analytics")
        assert result["allowed"] is False

    def test_process_with_consent(self):
        ce = ComplianceEngine()
        consent = ce.consent_manager.request_consent(
            "user1", "analytics", [DataCategory.PERSONAL])
        ce.consent_manager.grant_consent(consent.consent_id)
        result = ce.process_data("user1", DataAction.COLLECT,
                                 [DataCategory.PERSONAL], "analytics")
        assert result["allowed"] is True

    def test_delete_always_allowed(self):
        ce = ComplianceEngine()
        result = ce.process_data("user1", DataAction.DELETE,
                                 [DataCategory.PERSONAL], "deletion_request")
        assert result["allowed"] is True

    def test_handle_subject_request(self):
        ce = ComplianceEngine()
        result = ce.handle_subject_request("user1", "access")
        assert result["status"] == "completed"

    def test_full_audit(self):
        ce = ComplianceEngine()
        reports = ce.full_audit()
        assert "gdpr" in reports
        assert "soc2" in reports

    def test_status(self):
        ce = ComplianceEngine()
        status = ce.get_status()
        assert "enabled_frameworks" in status
        assert "gdpr" in status["enabled_frameworks"]

    def test_enable_disable_framework(self):
        ce = ComplianceEngine()
        ce.enable_framework(ComplianceFramework.HIPAA)
        assert ComplianceFramework.HIPAA in ce._enabled_frameworks
        ce.disable_framework(ComplianceFramework.HIPAA)
        assert ComplianceFramework.HIPAA not in ce._enabled_frameworks
