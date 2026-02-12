import asyncio
from typing import Any, Dict, List
from utils.logger import get_logger

logger = get_logger("ai_tools")

async def ollama_list_models() -> Dict[str, Any]:
    """List all installed Ollama models"""
    try:
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

async def ollama_remove_model(model_name: str) -> Dict[str, Any]:
    """Remove a specific Ollama model"""
    try:
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
