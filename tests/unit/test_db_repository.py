from core.db import DbManager, Repository


def test_db_manager_runs_core_migrations(tmp_path):
    manager = DbManager(db_path=tmp_path / "runtime.sqlite3")
    repo = Repository(manager)
    row = repo.fetchone("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'artifact_manifests'")
    assert row is not None
    integrity = manager.integrity_check()
    assert integrity["ok"] is True


def test_repository_execute_and_fetch(tmp_path):
    manager = DbManager(db_path=tmp_path / "runtime.sqlite3")
    repo = Repository(manager)
    repo.execute(
        """
        INSERT INTO artifact_manifests(
            artifact_id, project_id, phase, artifact_type, file_path, sha256, manifest_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("a1", "p1", "scan", "manifest", "", "", "{}", 1.0, 1.0),
    )
    row = repo.fetchone("SELECT artifact_id, project_id FROM artifact_manifests WHERE artifact_id = ?", ("a1",))
    assert row == {"artifact_id": "a1", "project_id": "p1"}
