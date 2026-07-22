from __future__ import annotations

from typing import Any

from actions._gemini_image import (
    GeminiImageError,
    _workspace_root as _gemini_workspace_root,
    image_status,
    normalize_aspect_ratio,
    normalize_image_size,
    request_image,
    run_image_operation,
)


_workspace_root = _gemini_workspace_root
_ProviderImageError = GeminiImageError
_generate_image_bytes = request_image


def image_generate_status() -> dict[str, Any]:
    return image_status(editing=False)


def image_generate(
    prompt: str = "",
    outputPath: str = "",
    title: str = "",
    aspectRatio: str = "",
    imageSize: str = "",
    overwrite: bool = False,
    size: str = "",
    quality: str = "",
    background: str = "auto",
    **kwargs: Any,
) -> dict[str, Any]:
    if not str(prompt or "").strip():
        for key in ("imagePrompt", "image_prompt", "description", "visualDescription", "visual_description", "subject", "query", "text"):
            candidate = kwargs.get(key)
            if str(candidate or "").strip():
                prompt = str(candidate)
                break
    if not str(outputPath or "").strip():
        outputPath = str(kwargs.get("output_path", "") or kwargs.get("outputPath", "") or "")
    if not str(aspectRatio or "").strip():
        aspectRatio = str(kwargs.get("aspect_ratio", "") or kwargs.get("aspectRatio", "") or "")
    if not str(imageSize or "").strip():
        imageSize = str(kwargs.get("image_size", "") or kwargs.get("imageSize", "") or "")
    return run_image_operation(
        prompt=prompt,
        output_path=outputPath,
        title=title,
        aspect_ratio=normalize_aspect_ratio(aspectRatio, legacy_size=size),
        image_size=normalize_image_size(imageSize, legacy_quality=quality),
        overwrite=overwrite,
        background=background,
        request_fn=_generate_image_bytes,
        root_resolver=_workspace_root,
    )
