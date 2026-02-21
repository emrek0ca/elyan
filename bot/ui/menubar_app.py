"""Menubar Application - rumps-based macOS menubar app"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

logger = get_logger("ui.menubar")


def check_rumps() -> bool:
    """Check if rumps is available"""
    try:
        import rumps
        return True
    except ImportError:
        return False


class MenubarApp:
    """macOS Menubar application for quick access"""

    def __init__(self, settings=None, on_quit=None):
        self.settings = settings
        self.on_quit_callback = on_quit
        self._app = None
        self._status = "idle"

    def _ensure_rumps(self):
        """Ensure rumps is available"""
        if not check_rumps():
            raise ImportError(
                "rumps kurulu değil. 'pip install rumps' çalıştırın."
            )

    def create_app(self):
        """Create the menubar application"""
        self._ensure_rumps()
        import rumps

        class CDACMenubarApp(rumps.App):
            def __init__(self, outer, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.outer = outer

            @rumps.clicked(" Durum")
            def status_clicked(self, _):
                self.outer._show_status()

            @rumps.clicked(" Ayarlar")
            def settings_clicked(self, _):
                self.outer._show_settings()

            @rumps.clicked(" QR ile Bağlan")
            def qr_clicked(self, _):
                self.outer._show_qr()

            @rumps.clicked("� Sistem Bilgisi")
            def system_info_clicked(self, _):
                self.outer._show_system_info()

            @rumps.clicked(" Dosya Yönetimi")
            def file_management_clicked(self, _):
                self.outer._show_file_management()

            @rumps.clicked(" Yeniden Başlat")
            def restart_clicked(self, _):
                self.outer._restart_bot()

            @rumps.clicked(" İstatistikler")
            def stats_clicked(self, _):
                self.outer._show_stats()

            @rumps.clicked(" Çıkış")
            def quit_clicked(self, _):
                self.outer._quit()

        bot_name = self.settings.bot_name if self.settings else "CDACS Bot"
        self._app = CDACMenubarApp(
            self,
            name=bot_name,
            title="",
            quit_button=None  # Custom quit
        )

        return self._app

    def update_status(self, status: str):
        """Update the status display"""
        self._status = status
        if self._app:
            status_icons = {
                "idle": "",
                "running": "🟢",
                "busy": "🟡",
                "error": "🔴",
                "connected": ""
            }
            self._app.title = status_icons.get(status, "")

    def _show_status(self):
        """Show status notification"""
        self._ensure_rumps()
        import rumps

        status_messages = {
            "idle": "Bot beklemede",
            "running": "Bot çalışıyor",
            "busy": "İşlem devam ediyor",
            "error": "Hata oluştu",
            "connected": "Telegram bağlı"
        }

        message = status_messages.get(self._status, "Durum bilinmiyor")
        rumps.notification(
            title="CDACS Bot Durumu",
            subtitle=message,
            message=""
        )

    def _show_settings(self):
        """Show settings (open main window)"""
        logger.info("Settings requested from menubar")
        # This would open the main window to settings tab

    def _show_system_info(self):
        """Show system information"""
        logger.info("System info requested from menubar")
        self._ensure_rumps()
        import rumps

        # Get system info (simplified)
        import platform
        import psutil

        try:
            cpu = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            system = platform.system()

            rumps.notification(
                title="Sistem Bilgisi",
                subtitle=f"{system} - CPU: {cpu}%, RAM: {memory.percent}%",
                message=""
            )
        except:
            rumps.notification(
                title="Sistem Bilgisi",
                subtitle="Bilgi alınamadı",
                message=""
            )

    def _show_file_management(self):
        """Show file management options"""
        logger.info("File management requested from menubar")
        # This would open file management window

    def _show_stats(self):
        """Show bot statistics"""
        logger.info("Statistics requested from menubar")
        self._ensure_rumps()
        import rumps

        # Mock stats - in real implementation, get from bot
        rumps.notification(
            title="Bot İstatistikleri",
            subtitle="Toplam görev: 42, Başarı: 95%",
            message=""
        )

    def run(self):
        """Run the menubar application"""
        if self._app is None:
            self.create_app()
        self._app.run()
