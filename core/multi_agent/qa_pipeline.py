"""
core/multi_agent/qa_pipeline.py
─────────────────────────────────────────────────────────────────────────────
Layered QA System: Static -> Runtime -> Visual.
Reduces cost by failing fast on static checks.
"""

import os
from pathlib import Path
from typing import Dict, Any, List, Tuple

class QAPipeline:
    def __init__(self, agent):
        self.agent = agent

    async def run_full_audit(self, workspace_dir: str, artifacts: Dict[str, Any]) -> Tuple[bool, List[str]]:
        issues = []
        
        if not artifacts:
            return False, ["SYSTEM_FAIL: Hiçbir artefact üretilmedi. Builder dökümanları oluşturamadı."]
        
        # Layer 1: Static QA (Lint & Integrity)
        for path, art in artifacts.items():
            full_path = Path(workspace_dir) / path.lstrip("/")
            if not full_path.exists():
                issues.append({"path": path, "region": "Entire File", "instruction": f"Dosya eksik. {path} dosyasını oluşturmalısın."})
                continue
            
            encoding = getattr(art, "encoding", "utf-8")
            try:
                content = full_path.read_text(encoding=encoding)
            except Exception as e:
                issues.append({"path": path, "region": "File Encoding", "instruction": f"Dosya {encoding} ile okunamıyor. Lütfen encoding hatasını düzelt."})
                continue

            if not content.strip():
                issues.append({"path": path, "region": "Entire File", "instruction": f"Dosya boş. Lütfen gereken içeriği '{path}' dosyasına ekle."})
                continue
                
            actual_size = len(content.encode(encoding))
            min_size = getattr(art, "min_size_bytes", 0)
            if min_size > 0 and actual_size < min_size:
                issues.append({"path": path, "region": "Entire File", "instruction": f"Dosya boyutu yetersiz ({actual_size} bytes < {min_size} bytes). İçeriği zenginleştirmelisin."})
                
            required = getattr(art, "required_sections", [])
            for req in required:
                if req not in content:
                    issues.append({"path": path, "region": "Anywhere", "instruction": f"Zorunlu bölüm veya etiket olan '{req}' bulunamadı. Lütfen dosyaya ekle."})
            
            if path.endswith(".html") and "</html>" not in content.lower():
                issues.append({"path": path, "region": "EOF", "instruction": "Dosyanın sonuna kapanış </html> etiketini eklemelisin."})

        if issues: return False, issues

        # Layer 2: Runtime QA (Console & Network via Playwright)
        html_files = [p for p in artifacts if p.endswith(".html")]
        if html_files:
            from tools.browser.manager import get_browser_manager
            import asyncio
            for html in html_files:
                full_path = str(Path(workspace_dir) / html.lstrip("/"))
                browser = await get_browser_manager(headless=True)
                if not browser:
                    issues.append({"path": html, "region": "Browser", "instruction": "Browser engine başlatılamadı."})
                    continue
                
                # Consume previous logs
                browser.get_and_clear_logs()
                
                nav_result = await browser.navigate(f"file://{full_path}")
                if not nav_result.get("success"):
                    issues.append({"path": html, "region": "Network", "instruction": f"Dosya açılamadı: {nav_result.get('error')}"})
                    continue
                
                await asyncio.sleep(1) # Wait for JS execution
                logs = browser.get_and_clear_logs()
                
                has_runtime_error = False
                for console_err in [l for l in logs["console"] if l["type"] == "error"]:
                    has_runtime_error = True
                    issues.append({"path": html, "region": "Console", "instruction": f"Console Hatası: {console_err['text']} - Lütfen JS kodunu inceleyip düzelt."})
                for page_err in logs["page_errors"]:
                    has_runtime_error = True
                    issues.append({"path": html, "region": "PageError", "instruction": f"Sayfa Hatası: {page_err} - JS Execution Exception'ı gider."})

                # Layer 3: Visual QA (Screenshot + Vision AI)
                # Only run if there are no runtime errors (saving API costs)
                if not has_runtime_error:
                    result = await self.agent._execute_tool("verify_visual_quality", {"file_path": full_path})
                    if not result.get("success"):
                        issues.append({"path": html, "region": "Visual API", "instruction": f"Vision servisi hata verdi: {result.get('error')}"})
                    else:
                        analysis = result.get("analysis", "").lower()
                        if "hata" in analysis or "bozuk" in analysis or "eksik" in analysis or "taşan" in analysis:
                            issues.append({"path": html, "region": "UI/Visual", "instruction": f"Görsel analizde sorun bulundu: {analysis[:200]} - Lütfen CSS/HTML yapısını düzelt."})

        return (len(issues) == 0), issues
