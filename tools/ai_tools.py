import asyncio
from typing import Any, Dict, List
from core.model_catalog import normalize_model_name
from core.dependencies import get_system_dependency_runtime
from utils.ollama_helper import OllamaHelper
from utils.logger import get_logger

logger = get_logger("ai_tools")


def _ensure_ollama_runtime(allow_install: bool = True) -> bool:
    try:
        if OllamaHelper.ensure_available(allow_install=allow_install, start_service=True):
            return True
    except Exception as exc:
        logger.debug("Ollama helper ensure_available failed: %s", exc)
    try:
        record = get_system_dependency_runtime().ensure_binary(
            "ollama",
            allow_install=allow_install,
            skill_name="ai_tools",
            tool_name="ollama",
        )
        return str(record.status).lower() in {"ready", "installed"}
    except Exception as exc:
        logger.debug("System ollama ensure failed: %s", exc)
        return False

async def ollama_list_models() -> Dict[str, Any]:
    """List all installed Ollama models"""
    try:
        if not _ensure_ollama_runtime():
            return {"success": False, "error": "Ollama runtime hazir degil.", "error_code": "ollama_runtime_missing"}
        process = await asyncio.create_subprocess_exec(
            "ollama", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            return {"success": False, "error": stderr.decode().strip()}
            
        output = stdout.decode().strip()
        lines = output.split('\n')
        models = []
        
        if len(lines) > 1: # Skip header
            for line in lines[1:]:
                parts = line.split()
                if parts:
                    models.append({
                        "name": parts[0],
                        "id": parts[1] if len(parts) > 1 else "unknown",
                        "size": parts[2] if len(parts) > 2 else "unknown",
                        "modified": " ".join(parts[3:]) if len(parts) > 3 else "unknown"
                    })
                    
        return {
            "success": True,
            "models": models,
            "count": len(models),
            "message": f"{len(models)} model bulundu."
        }
    except Exception as e:
        logger.error(f"Ollama list error: {e}")
        return {"success": False, "error": str(e)}

async def ollama_pull_model(model_name: str) -> Dict[str, Any]:
    """Pull (download) a specific Ollama model"""
    try:
        model_name = normalize_model_name("ollama", model_name)
        logger.info(f"Pulling Ollama model: {model_name}")
        if not _ensure_ollama_runtime():
            return {"success": False, "error": "Ollama runtime hazir degil.", "error_code": "ollama_runtime_missing"}
        process = await asyncio.create_subprocess_exec(
            "ollama", "pull", model_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            return {"success": False, "error": stderr.decode().strip()}
            
        return {
            "success": True,
            "model": model_name,
            "message": f"Model {model_name} başarıyla indirildi."
        }
    except Exception as e:
        logger.error(f"Ollama pull error: {e}")
        return {"success": False, "error": str(e)}

async def ollama_remove_model(model_name: str) -> Dict[str, Any]:
    """Remove a specific Ollama model"""
    try:
        model_name = normalize_model_name("ollama", model_name)
        if not _ensure_ollama_runtime():
            return {"success": False, "error": "Ollama runtime hazir degil.", "error_code": "ollama_runtime_missing"}
        process = await asyncio.create_subprocess_exec(
            "ollama", "rm", model_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            return {"success": False, "error": stderr.decode().strip()}
            
        return {
            "success": True,
            "model": model_name,
            "message": f"Model {model_name} başarıyla kaldırıldı."
        }
    except Exception as e:
        logger.error(f"Ollama remove error: {e}")
        return {"success": False, "error": str(e)}
