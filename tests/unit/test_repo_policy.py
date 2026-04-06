from core.repo_policy import find_disallowed_markdown_paths, is_allowed_markdown_path


def test_repo_policy_allows_only_progress_markdown():
    assert is_allowed_markdown_path("PROGRESS.md") is True
    assert is_allowed_markdown_path("README.md") is True  # standard project file
    assert is_allowed_markdown_path("CONTRIBUTING.md") is True
    assert is_allowed_markdown_path("venv/lib/python/site-packages/pkg/README.md") is True
    assert is_allowed_markdown_path(".venv/lib/python/site-packages/pkg/LICENSE.md") is True
    assert is_allowed_markdown_path("docs/guide.md") is False
    assert is_allowed_markdown_path("random/notes.md") is False


def test_repo_policy_collects_disallowed_markdown_paths():
    blocked = find_disallowed_markdown_paths(
        [
            "PROGRESS.md",
            "docs/guide.md",
            "README.md",
            "venv/lib/python/site-packages/pkg/README.md",
            "random/notes.md",
        ]
    )

    assert blocked == ["docs/guide.md", "random/notes.md"]
