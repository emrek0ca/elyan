from __future__ import annotations

from types import SimpleNamespace

from cli.commands import packs


def test_packs_list_prints_catalog(capsys):
    code = packs.run(SimpleNamespace(action="list", pack="all", json=False))
    captured = capsys.readouterr()

    assert code == 0
    assert "Pack kataloğu:" in captured.out
    assert "Quivr" in captured.out
    assert "Cloudflare Agents" in captured.out
    assert "OpenGauss" in captured.out
    assert "elyan packs scaffold quivr --path ./quivr" in captured.out


def test_packs_status_all_prints_readiness(monkeypatch, capsys):
    async def fake_status_all(path=""):
        _ = path
        return {
            "success": True,
            "status": "success",
            "packs": [
                {
                    "pack": "quivr",
                    "label": "Quivr",
                    "status": "ready",
                    "success": True,
                    "project": {"name": "Quivr", "root": "/tmp/quivr"},
                    "bundle": {"id": "bundle-quivr"},
                    "readiness": "partial",
                    "readiness_percent": 40,
                    "feature_count": 4,
                    "missing_features": ["retrieval_config", "query_loop"],
                    "recommended_command": "elyan packs scaffold quivr --path ./quivr",
                    "message": "ready",
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr(packs, "pack_status_all", fake_status_all)

    code = packs.run(SimpleNamespace(action="status", pack="all", json=False))
    captured = capsys.readouterr()

    assert code == 0
    assert "readiness: partial (40%)" in captured.out
    assert "features: 4" in captured.out
    assert "missing: retrieval_config, query_loop" in captured.out
    assert "recommended: elyan packs scaffold quivr --path ./quivr" in captured.out


def test_packs_scaffold_dispatches_to_opengauss(monkeypatch, capsys):
    called = {}

    async def fake_scaffold(**kwargs):
        called.update(kwargs)
        return {
            "success": True,
            "status": "success",
            "project": {"name": kwargs.get("name"), "root": kwargs.get("path")},
            "message": "ready",
        }

    monkeypatch.setattr(packs, "opengauss_scaffold", fake_scaffold)

    code = packs.run(
        SimpleNamespace(
            action="scaffold",
            pack="opengauss",
            path="/tmp/opengauss-demo",
            name="Demo DB",
            text=[],
            backend="docker",
            include_samples=True,
            include_chat=True,
            include_workflows=True,
            include_mcp=True,
            force=False,
            dry_run=False,
            question="",
            retrieval_config="",
            file_paths=[],
            use_llm=False,
            image="opengauss/opengauss-server:latest",
            database="appdb",
            user="root",
            password="OpenGauss@123",
            port=5432,
            sql="",
            execute=False,
            allow_mutation=False,
            timeout=30,
            json=False,
        )
    )
    captured = capsys.readouterr()

    assert code == 0
    assert called["path"] == "/tmp/opengauss-demo"
    assert called["name"] == "Demo DB"
    assert "OpenGauss: success" in captured.out
