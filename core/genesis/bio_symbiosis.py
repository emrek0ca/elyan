"""
core/genesis/bio_symbiosis.py
─────────────────────────────────────────────────────────────────────────────
Bio-Digital Symbiosis Daemon.
Runs in the background continuously observing the user's active window and IDE 
context on MacOS. Feeds real-time RAG context to the NeuralRouter so that
Elyan can proactively infer intents without explicit prompt articulation.
"""

import asyncio
import time
import subprocess
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("bio_symbiosis")

class BioSymbiosis:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        self._running = False
        self.current_context = {
            "active_app": "",
            "active_window": "",
            "duration_s": 0,
            "last_seen_ts": time.time()
        }
        # Security: In a full production env, we encrypt this vector db using AES-256
        self.db_path = Path.home() / ".elyan" / "memory" / "bio_context.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.poll_interval = 5.0 # seconds

    def _get_active_mac_window(self) -> dict:
        """Uses AppleScript to extract the currently focused App and Window Title."""
        script = '''
        global frontApp, frontAppName, windowTitle
        set windowTitle to ""
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set frontAppName to name of frontApp
            tell process frontAppName
                tell (1st window whose value of attribute "AXMain" is true)
                    set windowTitle to value of attribute "AXTitle"
                end tell
            end tell
        end tell
        return {frontAppName, windowTitle}
        '''
        try:
            result = subprocess.check_output(
                ['osascript', '-e', script], 
                stderr=subprocess.DEVNULL, timeout=2
            ).decode('utf-8').strip()
            
            parts = [p.strip() for p in result.split(",")]
            if len(parts) >= 2:
                return {"app": parts[0], "title": parts[1]}
            elif len(parts) == 1:
                return {"app": parts[0], "title": ""}
        except Exception:
            pass
        return {"app": "Unknown", "title": "Unknown"}

    async def _update_context_loop(self):
        self._running = True
        logger.info("🧠 Bio-Digital Symbiosis (Mac Context Mapper) Started.")
        
        while self._running:
            try:
                active_data = self._get_active_mac_window()
                app = active_data["app"]
                title = active_data["title"]
                
                # If focus changed
                if app != self.current_context["active_app"] or title != self.current_context["active_window"]:
                    logger.debug(f"👁️ Context Shift -> [{app}] {title}")
                    
                    self.current_context = {
                        "active_app": app,
                        "active_window": title,
                        "duration_s": 0,
                        "last_seen_ts": time.time()
                    }
                    
                    # PROACTIVE HOOK
                    # If user is staring at an IDE error for >30s, we inject a proactive suggestion.
                    # Handled downstream in routine engine or via neural router.
                else:
                    self.current_context["duration_s"] = time.time() - self.current_context["last_seen_ts"]
                    
            except Exception as e:
                logger.error(f"BioSymbiosis error: {e}")
                
            await asyncio.sleep(self.poll_interval)
            
    def start(self):
        if self._running: return
        self._bg_task = asyncio.create_task(self._update_context_loop())
        
    def stop(self):
        self._running = False
        if hasattr(self, "_bg_task"):
            self._bg_task.cancel()
        logger.info("🛑 Bio-Digital Symbiosis Offline.")
        
    def get_context_injection(self) -> str:
        """Called by NeuralRouter to append silent context to user requests."""
        if not self.current_context["active_app"]: return ""
        return f"\n[GİZLİ BAĞLAM (Zero-Egress): Kullanıcı şu an '{self.current_context['active_app']}' uygulamasında '{self.current_context['active_window']}' sekmesinde çalışıyor.]"

bio_context = None

def init_bio_symbiosis(agent) -> BioSymbiosis:
    global bio_context
    if bio_context is None:
        bio_context = BioSymbiosis(agent)
    return bio_context
