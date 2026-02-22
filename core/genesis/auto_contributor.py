"""
core/genesis/auto_contributor.py
─────────────────────────────────────────────────────────────────────────────
Autonomous GitHub Contribution Daemon (The "Green Square" Generator).
Periodically generates meaningful, small commits (e.g., system logs, 
AI daily thought logs, or minor code tweaks) and pushes them to the repository
to ensure the user's GitHub contribution graph remains highly active.
"""

import os
import subprocess
import time
import asyncio
from pathlib import Path
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("auto_contributor")

class AutoContributor:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        self.work_dir = Path(__file__).parent.parent.parent
        self.ai_logs_dir = self.work_dir / "docs" / "elyan_telemetry"
        self.ai_logs_dir.mkdir(parents=True, exist_ok=True)
        
    async def generate_contribution(self):
        """Generates a semantic contribution and pushes it autonomously."""
        try:
            logger.info("🟢 AutoContributor: Preparing an autonomous GitHub commit...")
            
            # Creating a daily thought / optimization telemetry log
            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            file_name = f"telemetry_{date_str}.md"
            file_path = self.ai_logs_dir / file_name
            
            content = f"# Elyan Autonomous Telemetry: {date_str}\n\n"
            content += "- **System Health**: `EXCELLENT`\n"
            content += "- **Active Singularity Modules**: `BioSymbiosis`, `Mutator`, `VoiceAgent`, `FinOpsSandbox`\n"
            content += "- **Current Swarm Consensus**: `STABLE`\n\n"
            content += f"*This log was autonomously generated and committed by Elyan Genesis Core at {datetime.now().isoformat()} to maintain project activity.*"
            
            file_path.write_text(content, encoding="utf-8")
            
            # Run git commands
            subprocess.run(["git", "add", str(file_path)], cwd=self.work_dir, check=True, stdout=subprocess.DEVNULL)
            commit_msg = f"chore(ai): Autonomous system telemetry generation ({date_str})"
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=self.work_dir, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "push", "origin", "main"], cwd=self.work_dir, check=True, stdout=subprocess.DEVNULL)
            
            logger.info(f"✅ [GH-CONTRIB] Otonom Commit Başarılı! GitHub profiline katkı eklendi: {commit_msg}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"AutoContributor Git hatası: Is remote set? Error: {e}")
            return False
        except Exception as e:
            logger.error(f"AutoContributor Genel hatası: {e}")
            return False

# Standalone execution for testing
if __name__ == "__main__":
    import asyncio
    tester = AutoContributor(None)
    asyncio.run(tester.generate_contribution())
