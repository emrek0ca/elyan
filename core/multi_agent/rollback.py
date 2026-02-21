"""
core/multi_agent/rollback.py
─────────────────────────────────────────────────────────────────────────────
Rollback Manager for Autonomous Operations.
Provides a safety net using Git. It snapshots the workspace before agent operations 
and reverts if the agent enters an unrecoverable failure state.
"""

import os
import asyncio
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("rollback_manager")

class RollbackManager:
    def __init__(self, workspace_dir: str):
        self.workspace = Path(workspace_dir).expanduser().resolve()
        
    async def _run_git(self, *args) -> tuple[bool, str]:
        cmd = ["git"] + list(args)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        success = process.returncode == 0
        output = stdout.decode().strip() if success else stderr.decode().strip()
        return success, output

    async def ensure_initialized(self) -> bool:
        """Ensures the workspace is a git repository."""
        if not (self.workspace / ".git").exists():
            logger.info(f"Initializing Git repository in {self.workspace} for Rollback capability.")
            success, err = await self._run_git("init")
            if not success:
                logger.error(f"Failed to init git: {err}")
                return False
            # Create initial commit so stashing works reliably
            await self._run_git("add", ".")
            await self._run_git("commit", "-m", "Initial commit for Elyan Rollback Manager", "--allow-empty")
        return True

    async def create_snapshot(self) -> str:
        """
        Takes a snapshot of current uncommitted changes.
        Returns the stash hash or identifier.
        """
        await self.ensure_initialized()
        
        # Stage everything to ensure untracked files are also stashed
        await self._run_git("add", ".")
        timestamp = asyncio.get_event_loop().time()
        stash_msg = f"elyan_auto_snapshot_{timestamp}"
        
        success, out = await self._run_git("stash", "push", "-m", stash_msg)
        if not success:
            logger.warning(f"Could not create snapshot: {out}")
            return ""
            
        logger.info(f"Created rollback snapshot: {stash_msg}")
        # Return the commit hash of the stash for precise targeting, or just rely on 'stash@{0}'
        # If there were no changes, git stash push returns success but doesn't create a stash.
        if "No local changes to save" in out:
            return "NO_CHANGES"
            
        return "stash@{0}"

    async def restore_snapshot(self, stash_ref: str = "stash@{0}") -> bool:
        """
        Reverts the workspace to the given snapshot, destroying intermediate agent changes.
        """
        if stash_ref == "NO_CHANGES":
            # Just do a hard reset to HEAD to wipe any weird untracked files that might have snuck in (though unlikely if there were no changes before)
            await self._run_git("reset", "--hard", "HEAD")
            await self._run_git("clean", "-fd")
            logger.info("Restored snapshot (wiped new changes to return to clean state).")
            return True
            
        logger.warning(f"Initiating Rollback to {stash_ref}...")
        # Hard reset first to kill any half-committed or staged messes
        await self._run_git("reset", "--hard", "HEAD")
        await self._run_git("clean", "-fd")
        
        # Pop the stash
        success, out = await self._run_git("stash", "pop", stash_ref)
        if success:
            logger.info("Rollback successful.")
            return True
        else:
            logger.error(f"Rollback failed: {out}")
            return False

    async def clear_snapshot(self, stash_ref: str = "stash@{0}") -> bool:
        """
        Deletes the snapshot. Called when the job was completely successful 
        so we don't pollute the user's git stash list.
        """
        if stash_ref == "NO_CHANGES":
            return True
            
        success, out = await self._run_git("stash", "drop", stash_ref)
        if success:
            logger.info("Cleared temporary snapshot (Job Successful).")
            return True
        return False
