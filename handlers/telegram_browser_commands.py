"""
Telegram browser automation commands (Phase 14)
"""

from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import get_logger

logger = get_logger("telegram_browser")


async def cmd_browser_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open URL in browser"""
    try:
        if not context.args:
            await update.message.reply_text(
                "**Kullanım:**\n"
                "`/browser_open <url>`\n\n"
                "**Örnek:**\n"
                "`/browser_open google.com`",
                parse_mode='Markdown'
            )
            return
        
        url = context.args[0]
        
        await update.message.reply_text(" Açılıyor...")
        
        from tools.browser import browser_open
        result = await browser_open(url)
        
        if result.get("success"):
            await update.message.reply_text(
                f" **Açıldı:**\n"
                f" {result['url']}\n"
                f"📄 {result['title'][:100]}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f" {result.get('error')}")
    
    except Exception as e:
        logger.error(f"browser_open error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_browser_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Take screenshot of current page"""
    try:
        from tools.browser import browser_screenshot
        
        await update.message.reply_text(" Screenshot alınıyor...")
        
        selector = context.args[0] if context.args else None
        path = await browser_screenshot(selector=selector)
        
        if path:
            await update.message.reply_photo(
                photo=open(path, 'rb'),
                caption=" Screenshot"
            )
        else:
            await update.message.reply_text(" Screenshot alınamadı. Browser açık mı?")
    
    except Exception as e:
        logger.error(f"browser_screenshot error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_browser_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Click element"""
    try:
        if not context.args:
            await update.message.reply_text(
                "**Kullanım:**\n"
                "`/browser_click <selector>`\n\n"
                "**Örnek:**\n"
                "`/browser_click button.submit`",
                parse_mode='Markdown'
            )
            return
        
        selector = ' '.join(context.args)
        
        from tools.browser import browser_click
        result = await browser_click(selector)
        
        if result.get("success"):
            await update.message.reply_text(f" Tıklandı: `{selector}`", parse_mode='Markdown')
        else:
            await update.message.reply_text(f" {result.get('error')}")
    
    except Exception as e:
        logger.error(f"browser_click error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_browser_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Type text into element"""
    try:
        if len(context.args) < 2:
            await update.message.reply_text(
                "**Kullanım:**\n"
                "`/browser_type <selector> <text>`\n\n"
                "**Örnek:**\n"
                "`/browser_type input#search hello world`",
                parse_mode='Markdown'
            )
            return
        
        selector = context.args[0]
        text = ' '.join(context.args[1:])
        
        from tools.browser import browser_type
        result = await browser_type(selector, text)
        
        if result.get("success"):
            await update.message.reply_text(f" Yazıldı: `{text[:50]}`", parse_mode='Markdown')
        else:
            await update.message.reply_text(f" {result.get('error')}")
    
    except Exception as e:
        logger.error(f"browser_type error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_browser_extract(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extract text from element"""
    try:
        if not context.args:
            await update.message.reply_text(
                "**Kullanım:**\n"
                "`/browser_extract <selector>`\n\n"
                "**Örnek:**\n"
                "`/browser_extract h1.title`",
                parse_mode='Markdown'
            )
            return
        
        selector = ' '.join(context.args)
        
        from tools.browser import browser_get_text
        text = await browser_get_text(selector)
        
        if text:
            await update.message.reply_text(
                f" **Extracted:**\n```\n{text[:1000]}\n```",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(" Element bulunamadı")
    
    except Exception as e:
        logger.error(f"browser_extract error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_browser_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get browser status"""
    try:
        from tools.browser import browser_status
        status = await browser_status()
        
        if status.get("running"):
            await update.message.reply_text(
                f" **Browser Aktif**\n\n"
                f" URL: {status['url']}\n"
                f"📄 Title: {status['title']}\n"
                f"🔑 Session: `{status['session_id']}`\n"
                f"👁️ Headless: {status['headless']}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(" Browser kapalı")
    
    except Exception as e:
        logger.error(f"browser_status error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_browser_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close browser"""
    try:
        from tools.browser import browser_close
        result = await browser_close()
        
        if result.get("success"):
            await update.message.reply_text(" Browser kapatıldı")
        else:
            await update.message.reply_text(f" {result.get('error')}")
    
    except Exception as e:
        logger.error(f"browser_close error: {e}")
        await update.message.reply_text(f" Hata: {e}")


async def cmd_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scrape page content"""
    try:
        if not context.args:
            await update.message.reply_text(
                "**Kullanım:**\n"
                "`/scrape <url>`\n\n"
                "**Örnek:**\n"
                "`/scrape example.com`",
                parse_mode='Markdown'
            )
            return
        
        url = context.args[0]
        
        await update.message.reply_text("🕷️ Scraping...")
        
        from tools.browser import scrape_page
        result = await scrape_page(url)
        
        if result.get("success"):
            data = result['data']
            text = data.get('text', '')
            
            await update.message.reply_text(
                f" **Scraped:**\n"
                f" {data['url']}\n"
                f"📄 {data['title']}\n\n"
                f"```\n{text[:800]}\n```",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f" {result.get('error')}")
    
    except Exception as e:
        logger.error(f"scrape error: {e}")
        await update.message.reply_text(f" Hata: {e}")
