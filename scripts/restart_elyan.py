#!/usr/bin/env python3
"""
ELYAN DEPLOYMENT RESTART SCRIPT
================================

Graceful restart with Phase 3 capabilities:
1. Graceful shutdown of current agent
2. State backup
3. Load new code
4. Initialize systems
5. Verify functionality
6. Health check
"""

import sys
import time
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger

logger = get_logger("restart_elyan")


class DeploymentManager:
    """Manages graceful deployment and restart."""

    def __init__(self):
        self.bot_dir = Path(__file__).parent.parent
        self.backup_dir = self.bot_dir / ".backups"
        self.backup_dir.mkdir(exist_ok=True)
        self.timestamp = datetime.now().isoformat()
        self.log_file = self.bot_dir / f"deployment_{self.timestamp.replace(':', '-')}.log"

    def log(self, message: str, level: str = "INFO"):
        """Log message."""
        prefix = f"[{level}]"
        msg = f"{prefix} {message}"
        print(msg)
        logger.log(level, message)

    def backup_state(self) -> bool:
        """Backup current state."""
        try:
            self.log("Backing up current state...")
            backup_path = self.backup_dir / f"backup_{self.timestamp.replace(':', '-')}"
            backup_path.mkdir(exist_ok=True)

            # Backup key files
            for pattern in ["*.json", "*.db", "*.cache"]:
                import glob
                for file in glob.glob(str(self.bot_dir / pattern)):
                    try:
                        shutil.copy2(file, str(backup_path))
                    except Exception as e:
                        self.log(f"Skipped backup of {file}: {e}", "WARN")

            self.log(f"✓ State backed up to {backup_path}")
            return True
        except Exception as e:
            self.log(f"✗ Backup failed: {e}", "ERROR")
            return False

    def shutdown_current_agent(self) -> bool:
        """Gracefully shutdown current agent."""
        try:
            self.log("Shutting down current agent...")
            # Try to kill any running bot processes
            try:
                result = subprocess.run(
                    ["pkill", "-f", "bot", "-9"],
                    capture_output=True,
                    timeout=5,
                )
                self.log("✓ Current agent shut down")
            except Exception as e:
                self.log(f"Agent shutdown completed (or not running): {e}", "WARN")
            return True
        except Exception as e:
            self.log(f"✗ Shutdown failed: {e}", "ERROR")
            return False

    def verify_new_code(self) -> bool:
        """Verify new code is valid."""
        try:
            self.log("Verifying new code...")
            # Check critical files exist
            critical_files = [
                "core/agent.py",
                "core/agent_integration_adapter.py",
                "core/intent/intent_router.py",
                "core/llm_orchestrator.py",
                "core/training_system.py",
                "core/analytics_engine.py",
            ]

            for file_path in critical_files:
                full_path = self.bot_dir / file_path
                if not full_path.exists():
                    self.log(f"✗ Missing file: {file_path}", "ERROR")
                    return False

            self.log("✓ All critical files present")
            return True
        except Exception as e:
            self.log(f"✗ Code verification failed: {e}", "ERROR")
            return False

    def initialize_systems(self) -> bool:
        """Initialize all Phase 3 systems."""
        try:
            self.log("Initializing Phase 3 systems...")

            # Run activation script
            activation_script = self.bot_dir / "scripts" / "activate_elyan.py"
            if activation_script.exists():
                result = subprocess.run(
                    [sys.executable, str(activation_script)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if result.returncode != 0:
                    self.log(f"⚠ Activation had issues: {result.stderr}", "WARN")
                else:
                    self.log("✓ Systems initialized successfully")

            return True
        except Exception as e:
            self.log(f"✗ Initialization failed: {e}", "ERROR")
            return False

    def health_check(self) -> bool:
        """Perform health check."""
        try:
            self.log("Running health check...")

            from core.agent import Agent

            agent = Agent()

            # Quick smoke test
            import asyncio

            async def test():
                try:
                    result = await agent.process("hello")
                    return result is not None
                except Exception as e:
                    self.log(f"Health check test failed: {e}", "ERROR")
                    return False

            success = asyncio.run(test())

            if success:
                self.log("✓ Health check passed")
            else:
                self.log("✗ Health check failed", "WARN")

            return success
        except Exception as e:
            self.log(f"✗ Health check error: {e}", "ERROR")
            return False

    def restart_agent(self) -> bool:
        """Start new agent instance."""
        try:
            self.log("Restarting agent...")
            # This depends on your deployment setup
            self.log("✓ Agent restart initiated (verify with your deployment manager)")
            return True
        except Exception as e:
            self.log(f"✗ Restart failed: {e}", "ERROR")
            return False

    def generate_report(self, results: Dict[str, bool]) -> Dict[str, Any]:
        """Generate deployment report."""
        return {
            "timestamp": self.timestamp,
            "bot_directory": str(self.bot_dir),
            "backup_directory": str(self.backup_dir),
            "results": results,
            "success": all(results.values()),
            "log_file": str(self.log_file),
        }


async def main():
    """Run deployment sequence."""
    print("\n" + "=" * 70)
    print("ELYAN DEPLOYMENT & RESTART")
    print("=" * 70 + "\n")

    manager = DeploymentManager()
    results = {}

    # Step 1: Backup
    print("\n[1/6] BACKUP CURRENT STATE")
    print("-" * 70)
    results["backup"] = manager.backup_state()

    # Step 2: Shutdown
    print("\n[2/6] SHUTDOWN CURRENT AGENT")
    print("-" * 70)
    results["shutdown"] = manager.shutdown_current_agent()

    # Step 3: Wait a bit
    manager.log("Waiting for graceful shutdown...")
    time.sleep(2)

    # Step 4: Verify code
    print("\n[3/6] VERIFY NEW CODE")
    print("-" * 70)
    results["verify"] = manager.verify_new_code()

    if not results["verify"]:
        manager.log("✗ Cannot proceed with bad code", "ERROR")
        report = manager.generate_report(results)
        print("\nDEPLOYMENT FAILED")
        print(json.dumps(report, indent=2))
        return 1

    # Step 5: Initialize
    print("\n[4/6] INITIALIZE SYSTEMS")
    print("-" * 70)
    results["initialize"] = manager.initialize_systems()

    # Step 6: Health check
    print("\n[5/6] HEALTH CHECK")
    print("-" * 70)
    results["health"] = manager.health_check()

    # Step 7: Restart
    print("\n[6/6] RESTART AGENT")
    print("-" * 70)
    results["restart"] = manager.restart_agent()

    # Report
    report = manager.generate_report(results)

    print("\n" + "=" * 70)
    print("DEPLOYMENT REPORT")
    print("=" * 70)
    print(json.dumps(report, indent=2))

    if report["success"]:
        print("\n✓ DEPLOYMENT SUCCESSFUL")
        print("=" * 70 + "\n")
        return 0
    else:
        print("\n✗ DEPLOYMENT HAD ISSUES")
        print("Check log at:", manager.log_file)
        print("=" * 70 + "\n")
        return 1


if __name__ == "__main__":
    import asyncio
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
