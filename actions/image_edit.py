from __future__ import annotations

from typing import Any

from actions._gemini_image import (
    image_status,
    normalize_aspect_ratio,
    normalize_image_size,
    resolve_source_paths,
    run_image_operation,
)


def image_edit_status() -> dict[str, Any]:
    return image_status(editing=True)


def image_edit(
    prompt: str,
    sourcePath: str = "",
    sourcePaths: list[str] | None = None,
    outputPath: str = "",
    title: str = "",
    aspectRatio: str = "",
    imageSize: str = "",
    overwrite: bool = False,
    _selectedPaths: list[str] | None = None,
) -> dict[str, Any]:
    resolved_sources = resolve_source_paths(sourcePath, sourcePaths, _selectedPaths)
    return run_image_operation(
        prompt=prompt,
        output_path=outputPath,
        title=title,
        aspect_ratio=normalize_aspect_ratio(aspectRatio, allow_empty=True),
        image_size=normalize_image_size(imageSize),
        overwrite=overwrite,
        source_paths=resolved_sources,
    )
