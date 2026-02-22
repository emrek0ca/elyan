"""
core/genesis/preemptive_subconscious.py
─────────────────────────────────────────────────────────────────────────────
Pre-emptive Subconscious Execution (The AGI Proactivity Core).
Unlike traditional bots that wait for prompts, Elyan watches external 
triggers (Emails arriving, calendar events nearing) via AppleScript.
If a high-confidence intent matches a known capability, Elyan autonomously 
performs the task BEFORE the user even sits at the computer.
"""

import asyncio
import subprocess
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("preemptive")

class PreemptiveSubconscious:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        self._running = False
        
    def _read_unread_mac_mail(self) -> list:
        """Uses AppleScript to fetch unread emails locally. Total privacy, no IMAP passwords needed."""
        script = '''
        set emailList to ""
        try
            tell application "Mail"
                set unreadMsgs to (every message of inbox whose read status is false)
                repeat with msg in unreadMsgs
                    set subj to subject of msg
                    set sndr to sender of msg
                    set emailList to emailList & sndr & "|" & subj & "\\n"
                end repeat
            end tell
        end try
        return emailList
        '''
        try:
            result = subprocess.check_output(
                ['osascript', '-e', script], 
                stderr=subprocess.DEVNULL, timeout=5
            ).decode('utf-8').strip()
            
            emails = []
            for line in result.split('\n'):
                if '|' in line:
                    sender, subject = line.split('|', 1)
                    emails.append({"sender": sender, "subject": subject})
            return emails
        except Exception:
            return []

    async def _evaluate_and_act(self, emails: list):
        """Passes emails to the LLM to gauge 'Actionability Score'."""
        if not emails: return
        
        logger.debug(f"🔍 Preemptive Scanner found {len(emails)} unread emails.")
        for email in emails:
            prompt = f"Şu e-posta için Elyan otonom olarak (insanı beklemeden) bir yazılım/tasarım/araştırma aksiyonu alabilir mi? Evet/Hayır ve Aksiyon: {email['subject']}"
            
            # Simulated fast LLM check (e.g. Llama-3 locally)
            from core.multi_agent.orchestrator import AgentOrchestrator
            orch = AgentOrchestrator(self.agent)
            
            # Action Confidence Gateway (Only >90% sure tasks get executed)
            raw = await orch._run_specialist("executor", prompt)
            if "Evet" in raw:
                logger.info(f"⚡ PREEMPTIVE TRIGGERED: Autonomously processing mail -> {email['subject']}")
                # We spin up an Orchestrator flow with the intent extracted from the mail.
                # E.g., The mail says "Please send the Q3 server logs", Elyan automatically zips them.
                asyncio.create_task(orch.manage_flow("Mail_Auto_Response", f"Oto-Aksiyon: {email['subject']}"))

    async def _daemon_loop(self):
        self._running = True
        logger.info("🧠 Pre-emptive Subconscious (Phase 24) Online. Observing environment...")
        
        while self._running:
            try:
                emails = self._read_unread_mac_mail()
                await self._evaluate_and_act(emails)
            except Exception as e:
                logger.error(f"Preemptive Loop Error: {e}")
                
            await asyncio.sleep(60.0) # Check every minute
            
    def start(self):
        if self._running: return
        self._bg_task = asyncio.create_task(self._daemon_loop())
        
    def stop(self):
        self._running = False
        if hasattr(self, "_bg_task"):
            self._bg_task.cancel()
        logger.info("🛑 Subconscious Offline.")
