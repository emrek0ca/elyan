"""
Visual QA Tools - Automated visual verification using Browser + Vision AI
"""

import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from .manager import get_browser_manager
from tools.vision_tools import analyze_image
from utils.logger import get_logger

logger = get_logger("visual_qa")

async def verify_visual_quality(
    file_path: str,
    prompt: str = "Bu web sayfasını görsel olarak denetle. Herhangi bir tasarım hatası, bozuk resim, taşan metin veya eksik içerik var mı? Yanıtını profesyonel bir QA uzmanı gibi ver.",
    headless: bool = True
) -> Dict[str, Any]:
    """
    Opens a local file in browser, takes a screenshot, and analyzes it with Vision AI.
    
    Args:
        file_path: Path to the HTML file
        prompt: Specific instruction for the visual analysis
        headless: Run browser headlessly
    """
    try:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"Dosya bulunamadı: {file_path}"}

        # 1. Start browser and navigate to local file
        browser = await get_browser_manager(headless=headless)
        if not browser:
            return {"success": False, "error": "Browser başlatılamadı (Playwright kurulu mu?)"}

        # Navigation for local files needs file:// protocol
        url = f"file://{path}"
        nav_result = await browser.navigate(url)
        if not nav_result.get("success"):
            return nav_result

        # Wait a bit for images/styles to load
        await asyncio.sleep(1)

        # 2. Take screenshot
        screenshot_path = f"/tmp/visual_qa_{int(time.time())}.png"
        saved_path = await browser.screenshot(path=screenshot_path)
        if not saved_path:
            return {"success": False, "error": "Ekran görüntüsü alınamadı"}

        # 3. Analyze with Vision AI
        logger.info(f"Analyzing visual quality for: {file_path}")
        vision_result = await analyze_image(
            image_path=saved_path,
            prompt=prompt
        )

        # Cleanup screenshot
        if os.path.exists(saved_path):
            os.remove(saved_path)

        return {
            "success": vision_result.get("success", False),
            "analysis": vision_result.get("analysis", ""),
            "provider": vision_result.get("provider", ""),
            "file_checked": str(path),
            "message": "Görsel kalite denetimi tamamlandı."
        }

    except Exception as e:
        logger.error(f"Visual QA error: {e}")
        return {"success": False, "error": str(e)}

import asyncio # Ensure asyncio is available for sleep
