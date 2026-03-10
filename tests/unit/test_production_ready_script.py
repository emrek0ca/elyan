from pathlib import Path


def test_production_ready_script_uses_current_benchmark_gate_and_workflow_pack():
    script = Path("/Users/emrekoca/Desktop/bot/scripts/production_ready.sh").read_text(encoding="utf-8")
    assert "run_production_path_benchmarks.py" in script
    assert "--require-perfect" in script
    assert "--min-pass-count" in script
    assert "run_emre_workflow_pack.py" in script


def test_start_product_script_uses_dashboard_cli_entrypoint():
    script = Path("/Users/emrekoca/Desktop/bot/scripts/start_product.sh").read_text(encoding="utf-8")
    assert "python3 -m cli.main gateway start --daemon" in script
    assert "python3 -m cli.main dashboard" in script
    assert "--port \"$PORT\"" in script
