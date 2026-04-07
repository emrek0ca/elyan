from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent


def test_production_ready_script_uses_current_benchmark_gate_and_workflow_pack():
    script = (_REPO / "scripts/production_ready.sh").read_text(encoding="utf-8")
    assert "run_production_path_benchmarks.py" in script
    assert "--require-perfect" in script
    assert "--min-pass-count" in script
    assert "run_emre_workflow_pack.py" in script


def test_start_product_script_uses_desktop_cli_entrypoint():
    script = (_REPO / "scripts/start_product.sh").read_text(encoding="utf-8")
    assert "python3 -m cli.main gateway start --daemon" in script
    assert "python3 -m cli.main desktop" in script
    assert "--port \"$PORT\"" in script
