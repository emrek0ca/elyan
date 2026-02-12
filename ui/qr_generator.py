"""QR Code Generator for Telegram Bot Connection"""

import secrets
import time
import sys
import os
from pathlib import Path
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

logger = get_logger("ui.qr")

# QR code validity duration in seconds
QR_VALIDITY_SECONDS = 300  # 5 minutes


class QRGenerator:
    """Generate QR codes for Telegram bot connection"""

    def __init__(self, bot_username: str = None):
        self.bot_username = bot_username
        self._current_token = None
        self._token_timestamp = 0

    def generate_session_token(self) -> str:
        """Generate a one-time session token"""
        self._current_token = secrets.token_urlsafe(32)
        self._token_timestamp = time.time()
        logger.info("New session token generated")
        return self._current_token

    def is_token_valid(self, token: str) -> bool:
        """Check if the provided token is valid and not expired"""
        if not self._current_token or token != self._current_token:
            return False

        elapsed = time.time() - self._token_timestamp
        if elapsed > QR_VALIDITY_SECONDS:
            self._current_token = None
            return False

        return True

    def invalidate_token(self):
        """Invalidate the current token after use"""
        self._current_token = None
        self._token_timestamp = 0
        logger.info("Session token invalidated")

    def get_telegram_url(self) -> str:
        """Get Telegram deep link URL"""
        if not self.bot_username:
            return ""

        token = self.generate_session_token()
        # Telegram deep link format: t.me/botname?start=token
        return f"https://t.me/{self.bot_username}?start={token}"

    def generate_qr_image(
        self,
        output_path: str = None,
        size: int = 300
    ) -> dict[str, Any]:
        """Generate QR code image for Telegram connection

        Args:
            output_path: Path to save the QR image (optional)
            size: QR code size in pixels

        Returns:
            dict with success status and path or error
        """
        try:
            import qrcode
            from PIL import Image
        except ImportError:
            return {
                "success": False,
                "error": "qrcode veya pillow kurulu değil. 'pip install qrcode[pil]' çalıştırın."
            }

        url = self.get_telegram_url()
        if not url:
            return {
                "success": False,
                "error": "Bot kullanıcı adı ayarlanmamış"
            }

        try:
            # Create QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(url)
            qr.make(fit=True)

            # Create image
            img = qr.make_image(fill_color="black", back_color="white")

            # Resize if needed
            if img.size[0] != size:
                img = img.resize((size, size), Image.Resampling.LANCZOS)

            # Save or return bytes
            if output_path:
                img.save(output_path)
                logger.info(f"QR code saved to: {output_path}")
                return {
                    "success": True,
                    "path": output_path,
                    "url": url,
                    "expires_in": QR_VALIDITY_SECONDS
                }
            else:
                # Return as bytes
                import io
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                return {
                    "success": True,
                    "image_bytes": buffer.getvalue(),
                    "url": url,
                    "expires_in": QR_VALIDITY_SECONDS
                }

        except Exception as e:
            logger.error(f"QR generation error: {e}")
            return {"success": False, "error": str(e)}

    def get_token_remaining_time(self) -> int:
        """Get remaining validity time in seconds"""
        if not self._current_token:
            return 0

        elapsed = time.time() - self._token_timestamp
        remaining = QR_VALIDITY_SECONDS - elapsed
        return max(0, int(remaining))
