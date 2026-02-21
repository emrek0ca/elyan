"""
Turkish Few-Shot Examples for Natural Language Understanding

Provides examples for LLM to understand Turkish conversational commands.
"""

from typing import List, Dict, Any


FEW_SHOT_EXAMPLES: List[Dict[str, Any]] = [
    # App Control
    {
        "input": "chrome'u aç",
        "output": {"action": "open_app", "params": {"app_name": "chrome"}, "message": ""}
    },
    {
        "input": "spotify'ı başlat",
        "output": {"action": "open_app", "params": {"app_name": "spotify"}, "message": ""}
    },
    {
        "input": "safari kapat",
        "output": {"action": "close_app", "params": {"app_name": "safari"}, "message": ""}
    },
    
    # File Operations
    {
        "input": "masaüstündeki dosyaları göster",
        "output": {"action": "list_files", "params": {"path": "~/Desktop"}, "message": ""}
    },
    {
        "input": "masaüstündeki fotoğrafları listele",
        "output": {"action": "list_files", "params": {"path": "~/Desktop", "pattern": "*.{jpg,png,jpeg,gif}"}, "message": ""}
    },
    {
        "input": "dökümanlar klasöründeki pdf'leri göster",
        "output": {"action": "list_files", "params": {"path": "~/Documents", "pattern": "*.pdf"}, "message": ""}
    },
    
    # Web Search & Browse
    {
        "input": "google'da python tutorial ara",
        "output": {"action": "web_search", "params": {"query": "python tutorial"}, "message": ""}
    },
    {
        "input": "yapay zeka hakkında araştırma yap",
        "output": {"action": "web_search", "params": {"query": "yapay zeka"}, "message": ""}
    },
    {
        "input": "google.com'u aç",
        "output": {"action": "open_url", "params": {"url": "https://google.com"}, "message": ""}
    },
    
    # Screenshot
    {
        "input": "ekran görüntüsü al",
        "output": {"action": "take_screenshot", "params": {}, "message": ""}
    },
    {
        "input": "screenshot al",
        "output": {"action": "take_screenshot", "params": {}, "message": ""}
    },
    {
        "input": "ss al",
        "output": {"action": "take_screenshot", "params": {}, "message": ""}
    },
    
    # System Control
    {
        "input": "ses 50 yap",
        "output": {"action": "set_volume", "params": {"level": 50}, "message": ""}
    },
    {
        "input": "ses kapat",
        "output": {"action": "set_volume", "params": {"level": 0}, "message": ""}
    },
    {
        "input": "wifi'yi kapat",
        "output": {"action": "wifi_toggle", "params": {"state": "off"}, "message": ""}
    },
    {
        "input": "wifi aç",
        "output": {"action": "wifi_toggle", "params": {"state": "on"}, "message": ""}
    },
    {
        "input": "karanlık mod",
        "output": {"action": "toggle_dark_mode", "params": {}, "message": ""}
    },
    {
        "input": "parlaklık 80",
        "output": {"action": "set_brightness", "params": {"level": 80}, "message": ""}
    },
    
    # Calendar & Reminders
    {
        "input": "bugün ne var",
        "output": {"action": "get_today_events", "params": {}, "message": ""}
    },
    {
        "input": "yarın saat 9'da toplantı hatırlat",
        "output": {"action": "create_reminder", "params": {"title": "toplantı", "time": "tomorrow 09:00"}, "message": ""}
    },
    {
        "input": "bugün hava nasıl",
        "output": {"action": "get_weather", "params": {}, "message": ""}
    },
    
    # Greetings (Chat)
    {
        "input": "merhaba",
        "output": {"action": "chat", "message": "Merhaba! Size nasıl yardımcı olabilirim?"}
    },
    {
        "input": "naber",
        "output": {"action": "chat", "message": "İyiyim, sen nasılsın? Ne yapabilirim?"}
    },
    {
        "input": "teşekkürler",
        "output": {"action": "chat", "message": "Rica ederim! 😊"}
    },
    
    # System Info
    {
        "input": "sistem bilgisi",
        "output": {"action": "get_system_info", "params": {}, "message": ""}
    },
    {
        "input": "disk durumu",
        "output": {"action": "get_system_info", "params": {"info_type": "disk"}, "message": ""}
    },
    
    # Browser Automation
    {
        "input": "tarayıcıda github.com'u aç",
        "output": {"action": "browser_open", "params": {"url": "github.com"}, "message": ""}
    },
    {
        "input": "browserin screenshot'unu al",
        "output": {"action": "browser_screenshot", "params": {}, "message": ""}
    },
]


def get_few_shot_prompt() -> str:
    """Generate few-shot examples prompt"""
    examples = []
    
    for i, example in enumerate(FEW_SHOT_EXAMPLES[:15], 1):  # First 15 for prompt
        examples.append(f"{i}. Kullanıcı: \"{example['input']}\"")
        examples.append(f"   Yanıt: {json.dumps(example['output'], ensure_ascii=False)}")
    
    return "\n".join(examples)


# Import for JSON serialization
import json
