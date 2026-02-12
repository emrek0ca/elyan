"""
Email Inbox Triage - Read-only IMAP integration

Provides:
- IMAP connection and email fetching (read-only)
- Email categorization and priority scoring
- LLM-powered email summaries
- Unread email monitoring
"""

import imaplib
import email
from email.header import decode_header
from typing import Dict, List, Any, Optional
from datetime import datetime
import asyncio
from utils.logger import get_logger
from core.llm_client import LLMClient

logger = get_logger("email_triage")


class EmailTriageService:
    """
    Read-only email monitoring and triage system.
    
    Features:
    - IMAP read-only connection
    - Unread email counting
    - Email summarization with LLM
    - Priority scoring
    """
    
    def __init__(self, imap_server: str, email_address: str, password: str):
        """
        Initialize email triage service.
        
        Args:
            imap_server: IMAP server address (e.g., 'imap.gmail.com')
            email_address: Email address
            password: Email password or app-specific password
        """
        self.imap_server = imap_server
        self.email_address = email_address
        self.password = password
        self.imap: Optional[imaplib.IMAP4_SSL] = None
        self.llm = LLMClient()
    
    def connect(self) -> bool:
        """
        Connect to IMAP server.
        
        Returns:
            True if connected successfully
        """
        try:
            logger.info(f"Connecting to {self.imap_server}...")
            self.imap = imaplib.IMAP4_SSL(self.imap_server)
            self.imap.login(self.email_address, self.password)
            logger.info("IMAP connection established")
            return True
        except Exception as e:
            logger.error(f"IMAP connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from IMAP server"""
        try:
            if self.imap:
                self.imap.logout()
                logger.info("IMAP disconnected")
        except Exception as e:
            logger.error(f"IMAP disconnect error: {e}")
    
    def get_unread_count(self) -> Dict[str, Any]:
        """
        Get count of unread emails (read-only).
        
        Returns:
            Dict with unread count and status
        """
        try:
            if not self.imap:
                if not self.connect():
                    return {"success": False, "error": "Connection failed"}
            
            # Select inbox in read-only mode
            status, messages = self.imap.select('INBOX', readonly=True)
            
            if status != 'OK':
                return {"success": False, "error": "Failed to select inbox"}
            
            # Search for unseen emails
            status, data = self.imap.search(None, 'UNSEEN')
            
            if status != 'OK':
                return {"success": False, "error": "Search failed"}
            
            email_ids = data[0].split()
            unread_count = len(email_ids)
            
            logger.info(f"Unread emails: {unread_count}")
            
            return {
                "success": True,
                "unread_count": unread_count,
                "total_messages": int(messages[0])
            }
        
        except Exception as e:
            logger.error(f"Failed to get unread count: {e}")
            return {"success": False, "error": str(e)}
    
    def fetch_recent_emails(self, limit: int = 5, unread_only: bool = True) -> Dict[str, Any]:
        """
        Fetch recent emails (read-only).
        
        Args:
            limit: Maximum number of emails to fetch
            unread_only: Only fetch unread emails
        
        Returns:
            Dict with email list
        """
        try:
            if not self.imap:
                if not self.connect():
                    return {"success": False, "error": "Connection failed", "emails": []}
            
            # Select inbox in read-only mode
            self.imap.select('INBOX', readonly=True)
            
            # Search criteria
            search_criteria = 'UNSEEN' if unread_only else 'ALL'
            status, data = self.imap.search(None, search_criteria)
            
            if status != 'OK':
                return {"success": False, "error": "Search failed", "emails": []}
            
            email_ids = data[0].split()
            
            # Get last N emails
            recent_ids = email_ids[-limit:] if len(email_ids) > limit else email_ids
            
            emails = []
            for email_id in reversed(recent_ids):  # Newest first
                try:
                    # Fetch email
                    status, msg_data = self.imap.fetch(email_id, '(RFC822)')
                    
                    if status != 'OK':
                        continue
                    
                    # Parse email
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    
                    # Extract subject
                    subject = self._decode_email_header(msg.get('Subject', ''))
                    
                    # Extract sender
                    sender = self._decode_email_header(msg.get('From', ''))
                    
                    # Extract date
                    date_str = msg.get('Date', '')
                    
                    # Extract body (plain text)
                    body = self._get_email_body(msg)
                    
                    emails.append({
                        "id": email_id.decode(),
                        "subject": subject,
                        "from": sender,
                        "date": date_str,
                        "body_preview": body[:200] + "..." if len(body) > 200 else body
                    })
                
                except Exception as e:
                    logger.error(f"Failed to parse email {email_id}: {e}")
                    continue
            
            return {
                "success": True,
                "emails": emails,
                "count": len(emails)
            }
        
        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            return {"success": False, "error": str(e), "emails": []}
    
    async def get_inbox_summary(self) -> Dict[str, Any]:
        """
        Get AI-powered inbox summary.
        
        Returns:
            Dict with summary and recommendations
        """
        try:
            # Get unread count
            unread_info = self.get_unread_count()
            
            if not unread_info.get("success"):
                return {"success": False, "error": "Failed to get unread count"}
            
            unread_count = unread_info["unread_count"]
            
            if unread_count == 0:
                return {
                    "success": True,
                    "summary": "📬 Inbox temiz! Okunmamış email yok.",
                    "unread_count": 0,
                    "priority_emails": []
                }
            
            # Fetch recent unread emails
            emails_data = self.fetch_recent_emails(limit=min(unread_count, 10), unread_only=True)
            
            if not emails_data.get("success"):
                return {"success": False, "error": "Failed to fetch emails"}
            
            emails = emails_data["emails"]
            
            # Generate LLM summary
            summary_text = await self._generate_inbox_summary(emails, unread_count)
            
            return {
                "success": True,
                "summary": summary_text,
                "unread_count": unread_count,
                "recent_emails": emails[:5]  # Top 5
            }
        
        except Exception as e:
            logger.error(f"Failed to generate inbox summary: {e}")
            return {"success": False, "error": str(e)}
    
    async def _generate_inbox_summary(self, emails: List[Dict], total_unread: int) -> str:
        """Generate LLM-powered inbox summary"""
        if not emails:
            return f"📬 {total_unread} okunmamış email var."
        
        # Prepare email context
        email_context = "\n\n".join([
            f"From: {e['from']}\nSubject: {e['subject']}\nPreview: {e['body_preview']}"
            for e in emails[:5]  # Top 5
        ])
        
        prompt = f"""Kullanıcının inbox'ında {total_unread} okunmamış email var.
İşte en son 5 tanesi:

{email_context}

GÖREV:
1. Önemli/acil görünen emailleri vurgula
2. Genel bir özet ver (iş, kişisel, spam vb.)
3. Öncelikli okunması gerekenleri belirt
4. Kısa ve öz ol (max 10 satır)
5. Markdown format (emojiler, bold)

ÖZET:"""
        
        try:
            summary = await self.llm.generate(prompt)
            return summary
        except:
            # Fallback summary
            return f"📬 **{total_unread} okunmamış email**\n\nİlk 5:\n" + "\n".join([
                f"• {e['from']}: {e['subject'][:50]}"
                for e in emails[:5]
            ])
    
    def _decode_email_header(self, header: str) -> str:
        """Decode email header (handles encoding)"""
        if not header:
            return ""
        
        decoded_parts = []
        for part, encoding in decode_header(header):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or 'utf-8', errors='ignore'))
            else:
                decoded_parts.append(str(part))
        
        return ' '.join(decoded_parts)
    
    def _get_email_body(self, msg: email.message.Message) -> str:
        """Extract plain text body from email"""
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                
                if content_type == 'text/plain':
                    try:
                        body = part.get_payload(decode=True).decode(errors='ignore')
                        break
                    except:
                        continue
        else:
            try:
                body = msg.get_payload(decode=True).decode(errors='ignore')
            except:
                body = ""
        
        return body.strip()


# Global service instance
_email_triage_service: Optional[EmailTriageService] = None


def get_email_triage_service(imap_server: str = None, email_address: str = None, password: str = None) -> Optional[EmailTriageService]:
    """
    Get singleton email triage service instance.
    
    Args:
        imap_server: IMAP server (required on first call)
        email_address: Email address (required on first call)
        password: Password (required on first call)
    
    Returns:
        EmailTriageService instance or None if not configured
    """
    global _email_triage_service
    
    if _email_triage_service is None:
        if imap_server and email_address and password:
            _email_triage_service = EmailTriageService(imap_server, email_address, password)
        else:
            logger.warning("Email triage not configured")
            return None
    
    return _email_triage_service
