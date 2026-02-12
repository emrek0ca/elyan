"""
Email Integration Tools
Send, receive, and manage emails through bot
"""

import asyncio
import smtplib
import imaplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from typing import Dict, List, Any, Optional
from pathlib import Path
from utils.logger import get_logger
import os

logger = get_logger("email_tools")


class EmailManager:
    """Manages email operations (send, receive, search)"""

    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.imap_server = os.getenv("IMAP_SERVER", "imap.gmail.com")
        self.email_address = os.getenv("EMAIL_ADDRESS", "")
        self.email_password = os.getenv("EMAIL_PASSWORD", "")

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[Path]] = None
    ) -> Dict[str, Any]:
        """Send an email"""
        try:
            if not self.email_address or not self.email_password:
                return {
                    "success": False,
                    "error": "Email credentials not configured"
                }

            # Create message
            msg = MIMEMultipart()
            msg["From"] = self.email_address
            msg["To"] = to
            msg["Subject"] = subject

            if cc:
                msg["Cc"] = ", ".join(cc)

            # Add body
            msg.attach(MIMEText(body, "plain"))

            # Add attachments
            if attachments:
                for att_path in attachments:
                    if att_path.exists():
                        with open(att_path, "rb") as att:
                            from email.mime.base import MIMEBase
                            from email import encoders

                            part = MIMEBase("application", "octet-stream")
                            part.set_payload(att.read())
                            encoders.encode_base64(part)
                            part.add_header(
                                "Content-Disposition",
                                f"attachment; filename= {att_path.name}"
                            )
                            msg.attach(part)

            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_address, self.email_password)

                recipients = [to]
                if cc:
                    recipients.extend(cc)
                if bcc:
                    recipients.extend(bcc)

                server.sendmail(self.email_address, recipients, msg.as_string())

            logger.info(f"Email sent to {to}")
            return {
                "success": True,
                "message": f"Email sent to {to}",
                "timestamp": str(__import__('datetime').datetime.now())
            }

        except Exception as e:
            logger.error(f"Email send error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_emails(
        self,
        folder: str = "INBOX",
        limit: int = 10,
        search_query: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve emails from mailbox"""
        try:
            if not self.email_address or not self.email_password:
                return {
                    "success": False,
                    "error": "Email credentials not configured"
                }

            with imaplib.IMAP4_SSL(self.imap_server) as imap:
                imap.login(self.email_address, self.email_password)
                imap.select(folder)

                # Search for emails
                search_criteria = search_query or "ALL"
                status, messages = imap.search(None, search_criteria)

                email_ids = messages[0].split()[-limit:]
                emails = []

                for email_id in reversed(email_ids):
                    status, msg_data = imap.fetch(email_id, "(RFC822)")
                    msg = __import__('email').message_from_bytes(msg_data[0][1])

                    # Decode subject
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8")

                    emails.append({
                        "from": msg["From"],
                        "subject": subject,
                        "date": msg["Date"],
                        "preview": msg.get_payload()[:200] if msg.get_payload() else ""
                    })

            logger.info(f"Retrieved {len(emails)} emails")
            return {
                "success": True,
                "emails": emails,
                "count": len(emails)
            }

        except Exception as e:
            logger.error(f"Email retrieval error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_unread_count(self) -> Dict[str, Any]:
        """Get count of unread emails"""
        try:
            if not self.email_address or not self.email_password:
                return {
                    "success": False,
                    "error": "Email credentials not configured"
                }

            with imaplib.IMAP4_SSL(self.imap_server) as imap:
                imap.login(self.email_address, self.email_password)
                imap.select("INBOX")

                status, messages = imap.search(None, "UNSEEN")
                unread_count = len(messages[0].split())

            return {
                "success": True,
                "unread_count": unread_count
            }

        except Exception as e:
            logger.error(f"Unread count error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def search_emails(
        self,
        query: str,
        folder: str = "INBOX",
        limit: int = 10
    ) -> Dict[str, Any]:
        """Search emails by criteria"""
        try:
            if not self.email_address or not self.email_password:
                return {
                    "success": False,
                    "error": "Email credentials not configured"
                }

            # Convert query to IMAP search format
            imap_query = f'(FROM "{query}" OR SUBJECT "{query}" OR BODY "{query}")'

            with imaplib.IMAP4_SSL(self.imap_server) as imap:
                imap.login(self.email_address, self.email_password)
                imap.select(folder)

                status, messages = imap.search(None, imap_query)
                email_ids = messages[0].split()[-limit:]

                results = []
                for email_id in reversed(email_ids):
                    status, msg_data = imap.fetch(email_id, "(RFC822)")
                    msg = __import__('email').message_from_bytes(msg_data[0][1])

                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8")

                    results.append({
                        "from": msg["From"],
                        "subject": subject,
                        "date": msg["Date"]
                    })

            logger.info(f"Found {len(results)} emails matching '{query}'")
            return {
                "success": True,
                "results": results,
                "count": len(results)
            }

        except Exception as e:
            logger.error(f"Email search error: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# Global manager instance
_email_manager: Optional[EmailManager] = None


def get_email_manager() -> EmailManager:
    global _email_manager
    if _email_manager is None:
        _email_manager = EmailManager()
    return _email_manager


# Tool functions
async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    attachments: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Send an email"""
    manager = get_email_manager()
    att_paths = [Path(a) for a in (attachments or [])]
    return await manager.send_email(to, subject, body, cc, bcc, att_paths)


async def get_emails(
    folder: str = "INBOX",
    limit: int = 10
) -> Dict[str, Any]:
    """Get emails from inbox"""
    manager = get_email_manager()
    return await manager.get_emails(folder, limit)


async def get_unread_emails() -> Dict[str, Any]:
    """Get unread email count"""
    manager = get_email_manager()
    return await manager.get_unread_count()


async def search_emails(query: str, limit: int = 10) -> Dict[str, Any]:
    """Search emails"""
    manager = get_email_manager()
    return await manager.search_emails(query, limit=limit)
