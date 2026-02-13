"""
Multimodal tools for Elyan:
- speech-to-text
- text-to-speech
- visual asset generation packs
- vision + voice fused outputs
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.voice import get_stt_service, get_tts_service
from core.voice import WHISPER_AVAILABLE, TTS_AVAILABLE
from security.validator import validate_path
from utils.logger import get_logger
from .vision_tools import analyze_image

logger = get_logger("tools.multimodal")


def _slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", " ") else " " for ch in str(value or "elyan"))
    return "_".join(cleaned.strip().split())[:80] or "elyan"


def _quality_report(*, passed: bool, issues: list[str], checks: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": bool(passed),
        "issues": issues,
        "checks": checks,
    }


async def transcribe_audio_file(audio_file: str, language: str = "tr", model_name: str = "base") -> dict[str, Any]:
    """
    Transcribe an audio file with local Whisper.
    """
    try:
        audio_path = Path(audio_file).expanduser().resolve()
        if not audio_path.exists():
            return {"success": False, "error": f"Audio dosyası bulunamadı: {audio_file}"}

        stt = get_stt_service(model_name=model_name)
        if not stt:
            return {
                "success": False,
                "error": "Whisper servisi hazır değil. Kurulum: pip install openai-whisper",
            }

        result = await stt.transcribe(str(audio_path), language=language, task="transcribe")
        if not result.get("success"):
            return result

        text = str(result.get("text", "")).strip()
        duration = float(result.get("duration", 0) or 0)
        word_count = len(text.split())
        min_chars = 8 if duration > 3 else 0
        min_words = 3 if duration > 8 else 0
        issues: list[str] = []
        if min_chars and len(text) < min_chars:
            issues.append("transcript_too_short")
        if min_words and word_count < min_words:
            issues.append("transcript_too_few_words")
        passed = not issues
        report = _quality_report(
            passed=passed,
            issues=issues,
            checks={
                "duration_sec": duration,
                "char_count": len(text),
                "word_count": word_count,
                "min_chars": min_chars,
                "min_words": min_words,
            },
        )
        if not passed:
            return {
                "success": False,
                "error": "Kalite kapısı: transkript yetersiz",
                "quality_report": report,
            }
        return {
            "success": True,
            "text": text,
            "language": result.get("language", language),
            "segments": result.get("segments", []),
            "duration": duration,
            "quality_report": report,
            "message": "Ses metne dönüştürüldü.",
        }
    except Exception as e:
        logger.error(f"transcribe_audio_file error: {e}")
        return {"success": False, "error": str(e)}


async def speak_text_local(
    text: str,
    output_file: str = "",
    voice_mode: str = "default",
) -> dict[str, Any]:
    """
    Speak text using local TTS and optionally save to file.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return {"success": False, "error": "Boş metin konuşmaya dönüştürülemez."}

        tts = get_tts_service()
        if not tts:
            return {
                "success": False,
                "error": "TTS servisi hazır değil. Kurulum: pip install pyttsx3",
            }

        out_path = ""
        if output_file:
            out = Path(output_file).expanduser().resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            out_path = str(out)

        ok = await tts.synthesize(t, output_file=out_path or None)
        if not ok:
            return {"success": False, "error": "Konuşma üretimi başarısız."}

        output_ok = True
        size_bytes = 0
        if out_path:
            try:
                size_bytes = Path(out_path).stat().st_size
                output_ok = size_bytes > 256
            except Exception:
                output_ok = False

        issues: list[str] = []
        if out_path and not output_ok:
            issues.append("audio_output_missing_or_too_small")

        report = _quality_report(
            passed=not issues,
            issues=issues,
            checks={
                "spoken_chars": len(t),
                "output_file": out_path or None,
                "output_size_bytes": size_bytes,
            },
        )
        if issues:
            return {
                "success": False,
                "error": "Kalite kapısı: ses çıktısı doğrulanamadı",
                "quality_report": report,
            }

        return {
            "success": True,
            "voice_mode": voice_mode,
            "output_file": out_path,
            "spoken_chars": len(t),
            "quality_report": report,
            "message": "Metin konuşma çıktısına dönüştürüldü.",
        }
    except Exception as e:
        logger.error(f"speak_text_local error: {e}")
        return {"success": False, "error": str(e)}


async def create_visual_asset_pack(
    project_name: str,
    brief: str = "",
    style: str = "cinematic editorial",
    output_dir: str = "~/Desktop",
) -> dict[str, Any]:
    """
    Create a reproducible visual generation package:
    prompt packs, style guide, shot list, and generation recipe.
    """
    try:
        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        slug = _slug(project_name)
        pack_dir = (base_dir / f"{slug}_visual_asset_pack").resolve()
        pack_dir.mkdir(parents=True, exist_ok=True)

        created_at = datetime.now().isoformat()
        brief_text = str(brief or f"{project_name} için premium görsel üretim paketi")

        prompt_pack = f"""# Prompt Pack

Project: {project_name}
Created: {created_at}
Style Direction: {style}

## Master Prompt
{brief_text}. High fidelity, detailed textures, brand-consistent color strategy, production-ready framing.

## Variants
1. Hero frame: cinematic composition, controlled highlights, clean typography areas.
2. Product context: medium shot, realistic materials, neutral yet premium background.
3. Social crop: high-contrast focal point, readable negative space.
4. Detail macro: texture emphasis, shallow depth of field.

## Negative Prompt
low quality, artifacts, watermark, over-saturated skin tones, distorted anatomy, unreadable text
"""

        shot_list = """# Shot List

| ID | Shot | Purpose | Aspect |
|---|---|---|---|
| S1 | Hero | Ana kampanya görseli | 16:9 |
| S2 | Product Scene | Ürünü kullanım bağlamında göster | 4:5 |
| S3 | Social Variant | Sosyal medya dağıtımı | 1:1 |
| S4 | Detail Close-up | Doku / kalite vurgusu | 3:2 |
"""

        style_profile = """{
  "visual_style": "cinematic editorial",
  "lighting": "soft key + directional accent",
  "color_palette": ["#0F172A", "#334155", "#E2E8F0", "#F8FAFC"],
  "texture_policy": "high detail, realistic material response",
  "brand_alignment": ["clean", "premium", "professional"],
  "consistency_rules": [
    "Konu merkezli kompozisyon",
    "Aynı renk ailesi korunmalı",
    "Tipografik boşluk bırakılmalı"
  ]
}
"""

        generation_recipe = """{
  "pipeline": [
    "brief_refinement",
    "master_prompt_creation",
    "variant_expansion",
    "seed_control",
    "upscale_pass",
    "quality_review"
  ],
  "quality_gates": [
    "style_consistency",
    "reproducibility",
    "brand_alignment",
    "artifact_cleanliness"
  ],
  "recommended_iterations": 4
}
"""

        files = {
            pack_dir / "PROMPT_PACK.md": prompt_pack,
            pack_dir / "SHOT_LIST.md": shot_list,
            pack_dir / "STYLE_PROFILE.json": style_profile,
            pack_dir / "GENERATION_RECIPE.json": generation_recipe,
        }
        outputs: list[str] = []
        for path, content in files.items():
            path.write_text(content, encoding="utf-8")
            outputs.append(str(path))

        return {
            "success": True,
            "project_name": project_name,
            "pack_dir": str(pack_dir),
            "files_created": outputs,
            "message": "Visual asset pack oluşturuldu.",
        }
    except Exception as e:
        logger.error(f"create_visual_asset_pack error: {e}")
        return {"success": False, "error": str(e)}


async def analyze_and_narrate_image(
    image_path: str,
    prompt: str = "Görseli profesyonel bir operatör gibi analiz et ve kısa özet üret.",
    language: str = "tr",
    speak: bool = False,
    output_audio_file: str = "",
) -> dict[str, Any]:
    """
    Analyze an image and optionally synthesize the resulting summary as speech.
    """
    try:
        analysis = await analyze_image(image_path=image_path, prompt=prompt, language=language)
        if not analysis.get("success"):
            return analysis

        text = str(analysis.get("analysis", "")).strip()
        min_chars = 40
        issues: list[str] = []
        if len(text) < min_chars:
            issues.append("analysis_too_short")
        report = _quality_report(
            passed=not issues,
            issues=issues,
            checks={
                "char_count": len(text),
                "min_chars": min_chars,
            },
        )
        if issues:
            return {
                "success": False,
                "error": "Kalite kapısı: görsel analiz yetersiz",
                "quality_report": report,
            }

        response: dict[str, Any] = {
            "success": True,
            "analysis": text,
            "provider": analysis.get("provider", "unknown"),
            "spoken": False,
            "quality_report": report,
            "message": "Görsel analiz tamamlandı.",
        }

        if speak and text:
            speech = await speak_text_local(text=text[:800], output_file=output_audio_file)
            response["spoken"] = bool(speech.get("success"))
            response["speech"] = speech
            if speech.get("success"):
                response["message"] = "Görsel analiz tamamlandı ve seslendirildi."
        return response
    except Exception as e:
        logger.error(f"analyze_and_narrate_image error: {e}")
        return {"success": False, "error": str(e)}


async def get_multimodal_capability_report() -> dict[str, Any]:
    """
    Return local capability health for vision/speech stack.
    """
    try:
        stt_ready = get_stt_service() is not None
        tts_ready = get_tts_service() is not None
        return {
            "success": True,
            "capabilities": {
                "vision_analysis": True,  # vision tool exists; runtime provider checked per call
                "speech_to_text": stt_ready,
                "text_to_speech": tts_ready,
                "whisper_installed": bool(WHISPER_AVAILABLE),
                "pyttsx3_installed": bool(TTS_AVAILABLE),
            },
            "message": "Multimodal capability raporu hazır.",
        }
    except Exception as e:
        logger.error(f"get_multimodal_capability_report error: {e}")
        return {"success": False, "error": str(e)}
