from __future__ import annotations

from core.coding_runtime import (
    build_coding_contract,
    build_evidence_bundle,
    detect_repo_snapshot,
    evaluate_coding_gate_state,
    prepare_contract_first_coding,
    run_adapter_verification_gates,
    select_language_adapter,
)


def _base_coding_spec() -> dict:
    return {
        "task_id": "coding_task_1",
        "intent": "coding_batch",
        "version": "1.2",
        "goal": "Bir proje oluştur",
        "user_goal": "Bir proje oluştur",
        "entities": {"topic": "cats"},
        "deliverables": [{"name": "project", "kind": "directory", "required": True}],
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["create_coding_project"],
        "tool_candidates": ["create_coding_project"],
        "priority": "normal",
        "risk_level": "low",
        "success_criteria": ["task_completed"],
        "timeouts": {"step_timeout_s": 60, "run_timeout_s": 600},
        "retries": {"max_attempts": 1},
        "steps": [
            {
                "id": "s1",
                "action": "create_coding_project",
                "params": {"project_name": "cat-site", "brief": "cats website"},
            }
        ],
    }


def test_detect_repo_snapshot_finds_broken_vanilla_web_repo(tmp_path):
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head>'
        '<body><script src="main.js"></script></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "styles.css").write_text("body { color: #222; }", encoding="utf-8")
    (tmp_path / "script.js").write_text("console.log('ok');", encoding="utf-8")
    (tmp_path / "styles").mkdir()
    (tmp_path / "styles" / "main.css").write_text("body { margin: 0; }", encoding="utf-8")

    snapshot = detect_repo_snapshot(str(tmp_path))

    assert snapshot.repo_type == "vanilla_web"
    assert any(item.startswith("missing_local_ref:index.html->main.js") for item in snapshot.issues)
    assert any(item.startswith("entrypoint_mismatch:index.html->main.js") for item in snapshot.issues)
    assert "multi_skeleton_repo" in snapshot.issues


def test_prepare_contract_first_coding_enriches_greenfield_web_spec(tmp_path):
    prepared = prepare_contract_first_coding(
        user_input="html css js ile kediler hakkinda modern bir website yap",
        task_spec=_base_coding_spec(),
        workspace_path=str(tmp_path),
        runtime_policy={
            "coding": {"style_lock": True, "max_repair_loops": 2},
            "security": {"denied_roots": []},
        },
    )

    assert prepared["failure"] == {}
    assert prepared["coding_contract"]["adapter_id"] == "vanilla_web"
    assert prepared["task_spec"]["execution_mode"] == "contract_first_coding"
    assert prepared["task_spec"]["repo_snapshot"]["repo_type"] == "greenfield"
    assert prepared["task_spec"]["style_intent"]["visual_direction"] != ""
    assert "template_hero_with_three_cards" in prepared["task_spec"]["style_intent"]["forbidden_patterns"]
    assert prepared["task_spec"]["allowed_write_paths"]


def test_select_language_adapter_unknown_stack_fails(tmp_path):
    (tmp_path / "Makefile").write_text("all:\n\t@echo ok\n", encoding="utf-8")
    snapshot = detect_repo_snapshot(str(tmp_path))

    adapter, failure = select_language_adapter(snapshot, user_input="bir uygulama yap")

    assert adapter is None
    assert failure is not None
    assert failure.code == "unsupported_stack"


def test_build_evidence_bundle_and_gate_state_respect_claim_policy():
    bundle = build_evidence_bundle(
        tool_results=[{"artifact_paths": ["/tmp/project/index.html"]}],
        qa_results={"code_gate": {"failed": []}},
        contract={
            "required_gates": ["smoke"],
            "claim_policy": {"require_evidence": True, "require_verified_gates": False},
        },
        final_response="site hazır",
    )

    gate_state = evaluate_coding_gate_state(
        {"required_gates": ["smoke"], "claim_policy": {"require_evidence": True, "require_verified_gates": False}},
        bundle,
    )

    assert bundle.artifact_paths == ["/tmp/project/index.html"]
    assert gate_state["ok"] is True
    assert gate_state["claim_blocked_reason"] == ""


def test_detect_repo_snapshot_uses_cache_on_second_read(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><html><body></body></html>", encoding="utf-8")
    first = detect_repo_snapshot(str(tmp_path))
    second = detect_repo_snapshot(str(tmp_path))

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.fingerprint == first.fingerprint


def test_build_coding_contract_greenfield_scope_uses_project_output_dir(tmp_path):
    output_dir = tmp_path / "deliveries"
    task_spec = _base_coding_spec()
    task_spec["artifacts_expected"] = [{"path": str(output_dir / "cat-site"), "type": "directory", "must_exist": False}]
    task_spec["steps"][0]["params"]["output_dir"] = str(output_dir)
    task_spec["steps"][0]["params"]["project_name"] = "cat-site"

    snapshot, contract, _style_intent, failure = build_coding_contract(
        user_input="html css js ile kedi sitesi yap",
        task_spec=task_spec,
        workspace_path=str(tmp_path),
        runtime_policy={"coding": {"style_lock": True}, "security": {"denied_roots": []}},
    )

    assert failure is None
    assert snapshot.is_greenfield is True
    assert str(output_dir) in contract.allowed_write_paths
    assert str(output_dir / "cat-site") in contract.allowed_write_paths


def test_run_adapter_verification_gates_checks_dom_and_style_for_vanilla_web(tmp_path):
    (tmp_path / "index.html").write_text(
        """
        <!doctype html>
        <html>
        <body>
          <main id="content" class="hero"></main>
          <button id="theme-toggle">Tema</button>
          <script src="script.js"></script>
        </body>
        </html>
        """,
        encoding="utf-8",
    )
    (tmp_path / "styles.css").write_text(
        """
        :root {
          --bg: #fff8f1;
          --text: #2a1d17;
          --accent: #d46a2e;
        }
        body { color: var(--text); }
        """,
        encoding="utf-8",
    )
    (tmp_path / "script.js").write_text(
        """
        const content = document.getElementById("content");
        const toggle = document.getElementById("theme-toggle");
        console.log(content, toggle);
        """,
        encoding="utf-8",
    )

    snapshot = detect_repo_snapshot(str(tmp_path))
    adapter, failure = select_language_adapter(snapshot, user_input="html css js ile site yap")

    assert failure is None
    assert adapter is not None

    evidence = run_adapter_verification_gates(
        snapshot=snapshot,
        contract={
            "adapter_id": adapter.adapter_id,
            "execution_adapter": adapter.adapter_id,
            "required_gates": ["smoke", "dom_contract", "style"],
            "style_lock": {
                "canonical_file_set": ["index.html", "styles.css", "script.js"],
                "forbidden_patterns": ["placeholder_copy"],
            },
        },
        artifact_paths=[str(tmp_path)],
    )

    assert [row["gate"] for row in evidence.gate_results] == ["smoke", "dom_contract", "style"]
    assert all(row["ok"] is True for row in evidence.gate_results)


def test_run_adapter_verification_gates_uses_command_runner_for_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    snapshot = detect_repo_snapshot(str(tmp_path))
    adapter, failure = select_language_adapter(snapshot, user_input="python proje düzelt")

    assert failure is None
    assert adapter is not None

    seen: list[str] = []

    def _runner(command: str, cwd: str) -> dict:
        seen.append(f"{cwd}:{command}")
        return {"ok": True, "stdout": "ok", "stderr": "", "exit_code": 0}

    evidence = run_adapter_verification_gates(
        snapshot=snapshot,
        contract={
            "adapter_id": adapter.adapter_id,
            "execution_adapter": adapter.adapter_id,
            "required_gates": ["format", "lint", "test"],
        },
        artifact_paths=[str(tmp_path)],
        command_runner=_runner,
    )

    assert any("python -m pytest" in row for row in seen)
    assert all(row["ok"] is True for row in evidence.gate_results)
