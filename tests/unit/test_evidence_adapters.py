from pathlib import Path

from core.evidence.adapters import adapt_evidence, fs_evidence


def test_adapt_evidence_set_wallpaper_uses_proof_path(tmp_path):
    shot = tmp_path / "proof.png"
    shot.write_bytes(b"png")
    result = {
        "success": True,
        "_proof": {"screenshot": str(shot)},
        "path": str(tmp_path / "wallpaper.jpg"),
    }
    evidence = adapt_evidence("set_wallpaper", result)
    assert evidence["exists"] is True
    assert Path(evidence["path"]) == shot
    assert evidence.get("sha256")


def test_adapt_evidence_set_wallpaper_falls_back_to_path(tmp_path):
    image = tmp_path / "wallpaper.jpg"
    image.write_bytes(b"jpg")
    evidence = adapt_evidence("set_wallpaper", {"success": True, "path": str(image)})
    assert evidence["exists"] is True
    assert Path(evidence["path"]) == image


def test_adapt_evidence_api_health_has_results_hash():
    result = {
        "success": True,
        "total": 1,
        "healthy": 1,
        "unhealthy": 0,
        "results": {"https://httpbin.org/get": {"healthy": True, "status_code": 200, "duration_ms": 120}},
    }
    evidence = adapt_evidence("api_health_check", result)
    assert evidence["total"] == 1
    assert evidence["healthy"] == 1
    assert evidence.get("results_sha256")


def test_fs_evidence_directory_has_no_file_hash(tmp_path):
    folder = tmp_path / "a"
    folder.mkdir()
    evidence = fs_evidence(str(folder))
    assert evidence["exists"] is True
    assert evidence["is_dir"] is True
    assert "sha256" not in evidence
