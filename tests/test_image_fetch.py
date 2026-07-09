from __future__ import annotations

from pathlib import Path

import pytest

from actions import image_fetch
from runtime.capability_registry import SafeCapabilityError


def test_resolve_destination_defaults_to_desktop(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(image_fetch.Path, "home", classmethod(lambda cls: tmp_path))
    directory, label = image_fetch._resolve_destination_dir("")
    assert directory == (tmp_path / "Desktop").resolve()
    assert directory.exists()
    assert label == "masaüstüne"


def test_resolve_destination_rejects_outside_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(image_fetch.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(SafeCapabilityError) as exc:
        image_fetch._resolve_destination_dir("/etc/passwd_dir")
    assert exc.value.code == "ACCESS_DENIED"


def test_sniff_extension_magic_bytes() -> None:
    assert image_fetch._sniff_extension(b"\xff\xd8\xff\xe0rest") == ".jpg"
    assert image_fetch._sniff_extension(b"\x89PNG\r\n\x1a\nrest") == ".png"
    assert image_fetch._sniff_extension(b"GIF89a...") == ".gif"
    assert image_fetch._sniff_extension(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"
    assert image_fetch._sniff_extension(b"not an image") == ""


def test_extension_for_prefers_content_type_then_sniff_then_url() -> None:
    assert image_fetch._extension_for("image/png", "https://x/a", b"garbage") == ".png"
    assert image_fetch._extension_for("application/octet-stream", "https://x/a", b"\xff\xd8\xff") == ".jpg"
    assert image_fetch._extension_for("", "https://x/photo.webp", b"garbage") == ".webp"
    assert image_fetch._extension_for("", "https://x/noext", b"garbage") == ".jpg"


def test_unique_path_avoids_collision(tmp_path) -> None:
    first = image_fetch._unique_path(tmp_path, "cat", ".jpg", overwrite=False)
    first.write_bytes(b"x")
    second = image_fetch._unique_path(tmp_path, "cat", ".jpg", overwrite=False)
    assert first.name == "cat.jpg"
    assert second.name == "cat-2.jpg"
    overwritten = image_fetch._unique_path(tmp_path, "cat", ".jpg", overwrite=True)
    assert overwritten.name == "cat.jpg"


def test_image_fetch_saves_downloaded_image(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(image_fetch.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        image_fetch,
        "_search_openverse",
        lambda query, count: [
            {"url": "https://example.test/cat.jpg", "thumbnail": "", "title": "Cat",
             "creator": "someone", "license": "by", "landing": "https://example.test/page",
             "provider": "openverse"}
        ],
    )
    monkeypatch.setattr(image_fetch, "_search_wikimedia", lambda query, count: [])
    monkeypatch.setattr(
        image_fetch,
        "_download_bytes",
        lambda url: (b"\xff\xd8\xff\xe0payload", "image/jpeg"),
    )

    result = image_fetch.image_fetch("cat", destination="", count=1)
    assert result["result"]["kind"] == "image_fetch"
    assert result["result"]["savedCount"] == 1
    saved = Path(result["result"]["images"][0]["outputPath"])
    assert saved.exists()
    assert saved.parent == (tmp_path / "Desktop").resolve()
    assert saved.suffix == ".jpg"
    assert result["artifacts"][0]["name"] == saved.name


def test_image_fetch_raises_when_no_results(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(image_fetch.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(image_fetch, "_search_openverse", lambda query, count: [])
    monkeypatch.setattr(image_fetch, "_search_wikimedia", lambda query, count: [])
    with pytest.raises(SafeCapabilityError) as exc:
        image_fetch.image_fetch("nonexistent-subject", destination="", count=1)
    assert exc.value.code == "IMAGE_NOT_FOUND"


def test_image_fetch_raises_when_download_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(image_fetch.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        image_fetch,
        "_search_openverse",
        lambda query, count: [{"url": "https://example.test/cat.jpg", "thumbnail": "", "provider": "openverse"}],
    )
    monkeypatch.setattr(image_fetch, "_search_wikimedia", lambda query, count: [])
    monkeypatch.setattr(image_fetch, "_download_bytes", lambda url: None)
    with pytest.raises(SafeCapabilityError) as exc:
        image_fetch.image_fetch("cat", destination="", count=1)
    assert exc.value.code == "IMAGE_DOWNLOAD_FAILED"


def test_image_fetch_requires_query() -> None:
    with pytest.raises(SafeCapabilityError) as exc:
        image_fetch.image_fetch("   ", destination="")
    assert exc.value.code == "INVALID_ARGUMENT"
