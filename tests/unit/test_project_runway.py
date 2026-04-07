from core.db import DbManager
from core.project.runway import ProjectArtifact, ProjectBrief, ProjectRunner


def test_project_runway_scaffold_and_verify(tmp_path, monkeypatch):
    runtime_db = DbManager(db_path=tmp_path / "runtime.sqlite3")
    monkeypatch.setattr("core.project.runway.get_db_manager", lambda: runtime_db)
    artifact_file = tmp_path / "artifact.txt"
    artifact_file.write_text("hello", encoding="utf-8")
    runner = ProjectRunner(base_path=tmp_path / "projects")
    brief = ProjectBrief(project_id="proj-1", title="Project", objective="Ship it")
    scaffold = runner.scaffold(brief, artifact_type="file", file_path=str(artifact_file), manifest={"kind": "text"})
    artifact = ProjectArtifact(**scaffold["artifact"])
    verify = runner.verify(artifact)
    assert scaffold["ok"] is True
    assert verify["ok"] is True


def test_project_runway_deliver_writes_json(tmp_path, monkeypatch):
    runtime_db = DbManager(db_path=tmp_path / "runtime.sqlite3")
    monkeypatch.setattr("core.project.runway.get_db_manager", lambda: runtime_db)
    runner = ProjectRunner(base_path=tmp_path / "projects")
    brief = ProjectBrief(project_id="proj-2")
    result = runner.deliver(brief)
    assert result["ok"] is True
    assert (tmp_path / "projects" / "proj-2" / "deliver.json").exists()
