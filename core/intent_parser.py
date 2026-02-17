import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from config.settings import HOME_DIR
from .enhanced_patterns import get_enhanced_patterns

class IntentParser:
    """Türkçe ve İngilizce doğal dil komutlarını anlayan akıllı parser"""

    def __init__(self):
        self.path_aliases = {
            "masaüstü": "Desktop", "masaustu": "Desktop", "desktop": "Desktop",
            "masa üstü": "Desktop", "masaustunde": "Desktop", "masaüstünde": "Desktop",
            "belgeler": "Documents", "dökümanlar": "Documents", "dokumanlar": "Documents",
            "documents": "Documents", "dokümanlarda": "Documents", "belgelere": "Documents",
            "indirilenler": "Downloads", "downloads": "Downloads", "indirilen": "Downloads",
            "indirilenlerde": "Downloads", "download": "Downloads",
            "resimler": "Pictures", "pictures": "Pictures", "fotoğraflar": "Pictures",
            "müzik": "Music", "muzik": "Music", "music": "Music",
            "filmler": "Movies", "movies": "Movies", "videolar": "Movies",
            "projeler": "Projects", "projects": "Projects", "projelerde": "Projects",
            "kod": "Code", "code": "Code", "kodlar": "Code",
            "ana klasör": "", "home": "", "ev dizini": "", "kullanıcı": "",
        }

        self.app_aliases = {
            "safari": "Safari", "chrome": "Google Chrome", "google chrome": "Google Chrome",
            "krom": "Google Chrome", "tarayıcı": "Safari",
            "firefox": "Firefox", "finder": "Finder", "dosyalar": "Finder",
            "terminal": "Terminal", "konsol": "Terminal", "iterm": "iTerm",
            "notlar": "Notes", "notes": "Notes", "not defteri": "Notes", "not": "Notes",
            "hesap makinesi": "Calculator", "hesapmakinesi": "Calculator", "calculator": "Calculator",
            "apple music": "Music", "spotify": "Spotify", "müzik": "Music",
            "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
            "visual studio code": "Visual Studio Code", "code": "Visual Studio Code",
            "discord": "Discord", "slack": "Slack", "whatsapp": "WhatsApp",
            "telegram": "Telegram", "zoom": "zoom.us", "teams": "Microsoft Teams",
            "word": "Microsoft Word", "excel": "Microsoft Excel", "powerpoint": "Microsoft PowerPoint",
            "takvim": "Calendar", "calendar": "Calendar",
            "mail": "Mail", "eposta": "Mail", "e-posta": "Mail", "posta": "Mail",
            "mesajlar": "Messages", "messages": "Messages", "mesaj": "Messages",
            "photos": "Photos", "fotoğraflar": "Photos", "foto": "Photos",
            "ayarlar": "System Settings", "sistem tercihleri": "System Settings", "tercihler": "System Settings",
            "preview": "Preview", "önizleme": "Preview", "textedit": "TextEdit",
            "activity monitor": "Activity Monitor", "görev yöneticisi": "Activity Monitor", "etkinlik monitörü": "Activity Monitor",
        }

        self.url_aliases = {
            "google": "https://google.com", "youtube": "https://youtube.com",
            "twitter": "https://twitter.com", "x": "https://x.com", "x.com": "https://x.com",
            "facebook": "https://facebook.com", "instagram": "https://instagram.com",
            "linkedin": "https://linkedin.com", "github": "https://github.com",
            "reddit": "https://reddit.com", "amazon": "https://amazon.com",
            "netflix": "https://netflix.com", "chatgpt": "https://chat.openai.com",
            "claude": "https://claude.ai", "gmail": "https://mail.google.com",
            "drive": "https://drive.google.com", "maps": "https://maps.google.com",
            "harita": "https://maps.google.com", "haber": "https://news.google.com",
            "translate": "https://translate.google.com", "çeviri": "https://translate.google.com",
        }

        self.greetings = {
            "merhaba", "selam", "selamlar", "hey", "hi", "hello", "mrb", "slm",
            "günaydın", "iyi akşamlar", "iyi günler", "naber", "nasılsın",
            "selamün aleyküm", "as", "sa", "aleyküm selam"
        }

    def parse(self, text: str) -> dict[str, Any] | None:
        """Ana parse fonksiyonu - tüm intent'leri kontrol eder"""
        text_lower = text.lower().strip()
        text_norm = self._normalize(text_lower)

        # Try enhanced patterns first (only for categories with valid tool mappings)
        enhanced_patterns = get_enhanced_patterns()
        category = enhanced_patterns.find_category(text_lower)
        if category:
            # Only use enhanced patterns for categories that resolve to real tools
            # Other categories fall through to specific parsers below
            _TOOLABLE_CATEGORIES = {
                "research": "advanced_research",
                "screenshot": "screenshot",
                "notification": "notification",
                "chat": "chat",
            }

            action = _TOOLABLE_CATEGORIES.get(category.value)
            if action:
                patterns = enhanced_patterns.find_patterns(text_lower, category)
                params = enhanced_patterns.extract_parameters(text_lower, patterns[0]) if patterns else {}

                # Special handling for research: extract topic
                if action == "advanced_research":
                    import re
                    # Remove irrelevant params from generic extraction
                    for key in ["app_name", "numbers", "quoted_text"]:
                        params.pop(key, None)

                    topic_patterns = [
                        r'(.+?)\s+hakkında\s+(?:\w+\s+)*(?:araştırma|araştır|inceleme)',
                        r'(.+?)\s+inceleme\s+(?:yapılsın|yap\b)?',
                        r'(.+?)\s+(?:araştırma|research)(?:\s+yap\w*)?$',
                        r'(?:araştırma|inceleme|araştır)\s+yap\w*\s+(.+)',
                    ]

                    topic = None
                    for pattern in topic_patterns:
                        match = re.search(pattern, text_lower)
                        if match:
                            topic = match.group(1).strip()
                            if topic and len(topic) > 2:
                                break

                    if not topic:
                        topic = re.sub(r'\b(araştırma|arastirma|araştır|arastir|research|inceleme)\b', '', text_lower)
                        topic = re.sub(r'\s+hakkında\s+', ' ', topic)
                        topic = re.sub(r'\b(detaylı|kısa|kapsamlı|hızlı|derin)\b', '', topic)
                        topic = re.sub(r'\byap\w*\b', '', topic)
                        topic = " ".join(topic.split()).strip()

                    if topic and len(topic) > 2:
                        params["topic"] = topic

                return {
                    "action": action,
                    "params": params,
                    "confidence": 0.95,
                    "source": "enhanced_patterns"
                }

        # Öncelik sırasına göre kontrol
        checks = [
            self._parse_screenshot,
            self._parse_status_snapshot,
            self._parse_volume,
            self._parse_brightness,
            self._parse_clipboard,
            self._parse_power_control,
            self._parse_close_app,
            self._parse_notification,
            # v3.0 New Features (yüksek öncelik)
            self._parse_notes,
            self._parse_task_planning,
            self._parse_document_editing,
            self._parse_document_merging,
            self._parse_advanced_research,
            self._parse_website_builder,
            self._parse_document_generation,
            # macOS System Tools
            self._parse_dark_mode,
            self._parse_wifi,
            self._parse_calendar,
            self._parse_reminders,
            self._parse_spotlight,
            self._parse_media_play,
            # Office Document Tools
            self._parse_office_documents,
            # Web Research Tools
            self._parse_web_research,
            # Standard tools
            self._parse_create_folder,
            self._parse_browser_search,
            self._parse_random_image,
            self._parse_open_app,
            self._parse_open_url,
            self._parse_greeting,
            self._parse_system_info,
            self._parse_list_files,
            self._parse_write_file,
            self._parse_search_files,
            self._parse_read_file,
            self._parse_delete_file,
            self._parse_process_control,
            self._parse_terminal_command,
            self._parse_weather,
        ]

        for check in checks:
            result = check(text_lower, text_norm, text)
            if result:
                if "confidence" not in result:
                    result["confidence"] = 1.0 # Rule-based matches are deterministic
                return result

        return None

    # ==================== WEBSITE BUILDER ====================
    def _parse_website_builder(self, text: str, text_norm: str, original: str) -> dict | None:
        """Website generation commands -> multi-step website scaffold"""
        web_keywords = [
            "website", "web sitesi", "web sayfasi", "web sayfası",
            "site", "sitesi", "landing page", "portfolio", "portfolyo",
        ]
        build_verbs = ["yap", "oluştur", "olustur", "hazırla", "hazirla", "geliştir", "gelistir"]
        has_web_keyword = any(k in text for k in web_keywords)
        has_build_verb = any(v in text for v in build_verbs)
        has_stack_hint = any(k in text for k in ["html", "css", "js", "javascript"])
        if not ((has_web_keyword and has_build_verb) or (has_web_keyword and has_stack_hint)):
            return None

        topic = "Modern Web Sitesi"
        direct_topic_match = re.search(
            r'(?:bana\s+)?(.+?)\s+(?:website|web sitesi|site)\s+(?:yap|oluştur|olustur|hazırla|hazirla)',
            text,
            re.IGNORECASE
        )
        if direct_topic_match:
            topic = direct_topic_match.group(1).strip()

        topic_match = re.search(
            r'(?:hakkında|hakkinda|konulu|tema|temalı|temali)\s+(.+?)(?:\s+(?:website|site|web sitesi)|$)',
            text,
            re.IGNORECASE
        )
        if topic_match:
            topic = topic_match.group(1).strip()
        elif not direct_topic_match:
            alt = re.search(r'(?:website|site|web sitesi)\s+(.+)', text, re.IGNORECASE)
            if alt and alt.group(1).strip():
                topic = alt.group(1).strip()

        topic = re.sub(
            r'\b(yap|oluştur|olustur|hazırla|hazirla|bana|bir|web sitesi|website|site)\b',
            '',
            topic,
            flags=re.IGNORECASE
        )
        topic = " ".join(topic.split()).strip(" -_,.")
        if not topic or len(topic) < 2:
            topic = "Modern Web Sitesi"

        html_filename = "index.html"
        filename_match = re.search(r'([\w\-]+\.html)', text, re.IGNORECASE)
        if filename_match:
            html_filename = filename_match.group(1)

        def _slugify(value: str) -> str:
            tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
            slug = value.translate(tr_map).lower()
            slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
            return slug or "portfolio-site"

        folder_hint = None
        folder_match = re.search(
            r"(?:klasor|klasör|folder)\s+(?:adiyla|adli|adında|adinda|named)?\s*([a-zA-Z0-9\-_]+)",
            text,
            re.IGNORECASE
        )
        if folder_match:
            folder_hint = folder_match.group(1).strip()

        base_folder_name = folder_hint or f"{_slugify(topic)}-site"
        base_dir = f"~/Desktop/{base_folder_name}"
        site_title = f"{topic} | Portfolio"

        html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{site_title}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="hero">
    <nav class="nav">
      <div class="brand">{topic}</div>
      <button id="themeToggle" class="theme-btn" aria-label="Tema değiştir">Tema</button>
    </nav>
    <div class="hero-content">
      <p class="eyebrow">PORTFOLIO</p>
      <h1>{topic}</h1>
      <p>Modern, hızlı ve mobil uyumlu kişisel portfolyo sayfası.</p>
      <a class="cta" href="#projeler">Projeleri Gör</a>
    </div>
  </header>

  <main>
    <section id="hakkimda" class="section reveal">
      <h2>Hakkımda</h2>
      <p>Ürün odaklı, detaylara dikkat eden ve sürdürülebilir çözümler üreten bir geliştiriciyim.</p>
    </section>

    <section id="projeler" class="section reveal">
      <h2>Projeler</h2>
      <div class="cards">
        <article class="card">
          <h3>Proje 1</h3>
          <p>Gerçek hayatta kullanılan bir otomasyon çözümü.</p>
        </article>
        <article class="card">
          <h3>Proje 2</h3>
          <p>Performans ve ölçeklenebilirlik odaklı web uygulaması.</p>
        </article>
        <article class="card">
          <h3>Proje 3</h3>
          <p>Kullanıcı deneyimini iyileştiren arayüz çalışması.</p>
        </article>
      </div>
    </section>

    <section id="iletisim" class="section reveal">
      <h2>İletişim</h2>
      <form class="contact-form">
        <input type="text" placeholder="Ad Soyad" required>
        <input type="email" placeholder="E-posta" required>
        <textarea rows="5" placeholder="Mesajınız" required></textarea>
        <button type="submit">Gönder</button>
      </form>
    </section>
  </main>

  <footer class="footer">
    <p>© 2026 {topic}. Tüm hakları saklıdır.</p>
  </footer>

  <script src="script.js"></script>
</body>
</html>
"""

        css_content = """* {
  box-sizing: border-box;
}

:root {
  --bg: #f7f4ef;
  --bg-strong: #efe8de;
  --text: #1f2328;
  --muted: #5f6670;
  --accent: #0f766e;
  --card: #ffffff;
  --border: #dad2c7;
}

body {
  margin: 0;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at 10% 10%, #fff7e8 0%, transparent 35%),
    radial-gradient(circle at 90% 20%, #d9f3ec 0%, transparent 30%),
    var(--bg);
}

.hero {
  min-height: 72vh;
  padding: 24px clamp(20px, 6vw, 80px);
}

.nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.brand {
  font-weight: 700;
  letter-spacing: 0.4px;
}

.theme-btn {
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 999px;
  padding: 8px 14px;
  cursor: pointer;
}

.hero-content {
  margin-top: 72px;
  max-width: 720px;
}

.eyebrow {
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 1.8px;
}

h1 {
  margin: 10px 0;
  font-size: clamp(2rem, 4.5vw, 4rem);
  line-height: 1.1;
}

.cta {
  display: inline-block;
  margin-top: 16px;
  text-decoration: none;
  color: #fff;
  background: var(--accent);
  padding: 12px 18px;
  border-radius: 10px;
}

.section {
  padding: 48px clamp(20px, 6vw, 80px);
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
}

.contact-form {
  display: grid;
  gap: 10px;
  max-width: 520px;
}

.contact-form input,
.contact-form textarea {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  font: inherit;
  background: #fff;
}

.contact-form button {
  width: fit-content;
  border: none;
  border-radius: 10px;
  padding: 10px 16px;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}

.footer {
  padding: 28px;
  text-align: center;
  color: var(--muted);
}

.reveal {
  opacity: 0;
  transform: translateY(16px);
  transition: opacity 420ms ease, transform 420ms ease;
}

.reveal.visible {
  opacity: 1;
  transform: translateY(0);
}

body.dark {
  --bg: #111826;
  --bg-strong: #0e1320;
  --text: #f0f4fa;
  --muted: #b8c1cf;
  --accent: #22c55e;
  --card: #161f31;
  --border: #27334a;
}
"""

        js_content = """const revealElements = document.querySelectorAll('.reveal');

const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 });

revealElements.forEach((el) => observer.observe(el));

const themeToggle = document.getElementById('themeToggle');
themeToggle?.addEventListener('click', () => {
  document.body.classList.toggle('dark');
});

document.querySelector('.contact-form')?.addEventListener('submit', (event) => {
  event.preventDefault();
  alert('Mesajınız alındı. Teşekkürler.');
});
"""

        return {
            "action": "multi_task",
            "tasks": [
                {
                    "id": "task_1",
                    "action": "create_folder",
                    "params": {"path": base_dir},
                    "description": "Proje klasoru olustur"
                },
                {
                    "id": "task_2",
                    "action": "write_file",
                    "params": {"path": f"{base_dir}/{html_filename}", "content": html_content},
                    "description": "Ana HTML dosyasini olustur",
                    "depends_on": ["task_1"]
                },
                {
                    "id": "task_3",
                    "action": "write_file",
                    "params": {"path": f"{base_dir}/style.css", "content": css_content},
                    "description": "CSS stil dosyasini olustur",
                    "depends_on": ["task_1"]
                },
                {
                    "id": "task_4",
                    "action": "write_file",
                    "params": {"path": f"{base_dir}/script.js", "content": js_content},
                    "description": "JavaScript dosyasini olustur",
                    "depends_on": ["task_1"]
                }
            ],
            "reply": f"{topic} icin web sitesi dosyalari hazirlaniyor ({base_folder_name})."
        }

    def _normalize(self, text: str) -> str:
        """Türkçe karakterleri normalize et"""
        replacements = {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    # ==================== SCREENSHOT ====================
    def _parse_screenshot(self, text: str, text_norm: str, original: str) -> dict | None:
        # Precise triggers - avoid ssh conflicts
        triggers = [
            "ekran görüntüsü", "screenshot", "ekran resmi",
            "ekranı kaydet", "ekranı yakala", "ekran al", "görüntü al",
            "ekranın resmini", "ekran yakala", "screen capture",
            "ss al", " ss ", "ss?", " ss,"  # "ss al" should be matched precisely
        ]

        text_lower = text.lower()
        
        # Check triggers - be more precise with "ss"
        matched = False
        for trigger in triggers:
            if trigger in text_lower:
                # Skip if it looks like ssh command
                if trigger == "ss" and ("ssh" in text_lower or "@" in text_lower):
                    continue
                matched = True
                break
        
        if not matched and not ("ekran goruntusu" in text_norm or "ekran resmi" in text_norm):
            return None

        filename = None
        name_match = re.search(r'adı\s*[:\s]*(\w+)|ismi\s*[:\s]*(\w+)|olarak\s+(\w+)', text)
        if name_match:
            filename = name_match.group(1) or name_match.group(2) or name_match.group(3)

        return {
            "action": "take_screenshot",
            "params": {"filename": filename},
            "reply": "Ekran görüntüsü alınıyor..."
        }

    def _parse_status_snapshot(self, text: str, text_norm: str, original: str) -> dict | None:
        """Conversational status queries -> screenshot"""
        triggers = [
            "durum nedir", "durum ne", "ne yapiyorsun", "ne yapıyorsun",
            "su an ne yapiyorsun", "şu an ne yapıyorsun",
            "durumu goster", "durumu göster", "ekranda ne var"
        ]
        if not any(t in text for t in triggers) and not any(t in text_norm for t in ["durum nedir", "ne yapiyorsun", "durumu goster"]):
            return None

        exclusions = [
            "wifi", "bluetooth", "hava durumu", "plan durumu", "arastirma durumu",
            "araştırma durumu", "sistem durumu", "pil", "batarya", "status", "/status"
        ]
        if any(e in text for e in exclusions) or any(e in text_norm for e in ["hava durumu", "sistem durumu", "plan durumu"]):
            return None

        return {
            "action": "take_screenshot",
            "params": {"filename": "elyan_durum"},
            "reply": "Anlik durumu gostermek icin ekran goruntusu aliyorum..."
        }

    # ==================== CREATE FOLDER ====================
    def _parse_create_folder(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["klasör", "klasor", "folder"]
        verbs = ["olustur", "oluştur", "kur", "ac", "aç", "yap", "ekle"]
        if not any(t in text for t in triggers):
            return None
        if not any(v in text for v in verbs):
            return None

        # Extract folder name
        name = None
        name_patterns = [
            r"([\w\-]+)\s+(?:adında|adli|isimli|named)\s+klas[öo]r",
            r"(?:adında|adli|isimli|named)\s+([\w\-]+)\s+klas[öo]r",
            r"klas[öo]r\s+(?:adında|adli|isimli|named)\s+([\w\-]+)",
            r"([\w\-]+)\s+klas[öo]r",
            r"klas[öo]r\s+([\w\-]+)"
        ]
        for pat in name_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                name = m.group(1)
                break
        if not name or len(name) < 1:
            name = "yeni_klasor"

        # Detect base location
        base = str(self.path_aliases.get("masaüstü", "Desktop"))
        for alias, real in self.path_aliases.items():
            if alias in text:
                base = real
                break

        path = f"~/{base}/{name}"
        return {
            "action": "create_folder",
            "params": {"path": path},
            "reply": f"{base} konumunda '{name}' klasoru olusturuluyor..."
        }

    # ==================== BROWSER SEARCH ====================
    def _parse_browser_search(self, text: str, text_norm: str, original: str) -> dict | None:
        """Open Safari (if mentioned) and search query in browser"""
        # Exact token match only; avoid false positives like "kullanarak" containing "ara".
        if not re.search(r"\b(arat|ara|search)\b", text, re.IGNORECASE):
            return None

        # If user is clearly asking to build a site/project, do not treat it as browser search.
        if any(k in text.lower() for k in ["website", "web sitesi", "web sayfas", "portfolyo", "portfolio"]) and \
           any(v in text.lower() for v in ["yap", "oluştur", "olustur", "hazırla", "hazirla", "geliştir", "gelistir"]):
            return None

        lower = text.lower()
        query = None

        # "kedi resimleri arat" or "kedi ara"
        m_before = re.search(r'(.+?)\s+(?:arat|ara|search)\b', lower, re.IGNORECASE)
        if m_before:
            query = m_before.group(1).strip()

        # "ara kedi resimleri"
        if not query:
            m_after = re.search(r'(?:arat|ara|search)\s+(.+)', lower, re.IGNORECASE)
            if m_after:
                query = m_after.group(1).strip()

        cleanup_tokens = {
            "safariyi", "safari", "tarayiciyi", "tarayıcıyı", "tarayicida",
            "tarayıcıda", "aç", "ac", "ve", "lutfen", "lütfen"
        }
        cleaned_parts = []
        for part in (query or "").replace(".", " ").split():
            if part not in cleanup_tokens:
                cleaned_parts.append(part)

        query = " ".join(cleaned_parts).strip()
        if len(query) < 2:
            query = "kedi resimleri"

        url = f"https://www.google.com/search?q={quote_plus(query)}"
        random_url = self._random_image_url(lower)

        wants_safari = "safari" in text
        tasks = []
        if wants_safari:
            tasks.append({
                "id": "task_1",
                "action": "open_app",
                "params": {"app_name": "Safari"},
                "description": "Safari'yi aç"
            })
        tasks.append({
            "id": "task_2",
            "action": "open_url",
            "params": {"url": url},
            "description": f"Arama: {query}",
            "depends_on": ["task_1"] if wants_safari else []
        })
        if random_url:
            tasks.append({
                "id": "task_3",
                "action": "open_url",
                "params": {"url": random_url},
                "description": "Rastgele gorsel ac",
                "depends_on": ["task_2"]
            })

        if wants_safari:
            reply = f"Safari'de '{query}' aranıyor..."
            if random_url:
                reply = f"Safari'de '{query}' aranıyor ve rastgele gorsel aciliyor..."
            return {
                "action": "multi_task",
                "tasks": tasks,
                "reply": reply
            }
        else:
            if random_url:
                return {
                    "action": "multi_task",
                    "tasks": tasks,
                    "reply": f"'{query}' aranıyor ve rastgele gorsel aciliyor..."
                }
            return {
                "action": "open_url",
                "params": {"url": url},
                "reply": f"Tarayıcıda '{query}' aranıyor..."
            }

    # ==================== MEDIA PLAY (YouTube) ====================
    def _parse_media_play(self, text: str, text_norm: str, original: str) -> dict | None:
        """Play/open YouTube with optional song query."""
        if "youtube" not in text and "yt" not in text:
            return None

        # Extract query after 'aç', 'çal', 'play'
        query = None
        m = re.search(r"youtube.*?(?:aç|ac|çal|cal|play)\s+(.+)", text, re.IGNORECASE)
        if m:
            query = m.group(1).strip()
        if not query:
            # Fallback: try words after "youtube"
            m2 = re.search(r"(?:youtube|yt)\s+(.+)", text, re.IGNORECASE)
            if m2:
                query = m2.group(1).strip()
        query = " ".join((query or "").split())
        query = re.sub(r"^(ve|ile)\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"\b(aç|ac|çal|cal|play)\b$", "", query, flags=re.IGNORECASE).strip()
        if query.lower() in {"youtube", "yt"}:
            query = ""

        base = "https://www.youtube.com"
        if query:
            url = f"{base}/results?search_query={quote_plus(query)}"
            reply = f"YouTube'da '{query}' açılıyor..."
        else:
            url = base
            reply = "YouTube açılıyor..."

        return {
            "action": "open_url",
            "params": {"url": url},
            "reply": reply
        }

    # ==================== RANDOM IMAGE ====================
    def _random_image_url(self, text_lower: str) -> str | None:
        if not any(k in text_lower for k in ["rastgele", "random"]):
            return None

        wants_image = any(k in text_lower for k in [
            "resim", "resmi", "foto", "fotograf", "fotoğraf",
            "gorsel", "görsel", "image", "pic"
        ])
        if not wants_image:
            return None

        if any(k in text_lower for k in ["kedi", "cat"]):
            return "https://cataas.com/cat"
        if any(k in text_lower for k in ["kopek", "köpek", "dog"]):
            return "https://random.dog"
        return "https://picsum.photos/1200/800"

    def _parse_random_image(self, text: str, text_norm: str, original: str) -> dict | None:
        random_url = self._random_image_url(text.lower())
        if not random_url:
            return None

        wants_safari = "safari" in text.lower()
        if wants_safari:
            return {
                "action": "multi_task",
                "tasks": [
                    {
                        "id": "task_1",
                        "action": "open_app",
                        "params": {"app_name": "Safari"},
                        "description": "Safari'yi ac"
                    },
                    {
                        "id": "task_2",
                        "action": "open_url",
                        "params": {"url": random_url},
                        "description": "Rastgele gorsel ac",
                        "depends_on": ["task_1"]
                    }
                ],
                "reply": "Rastgele gorsel aciliyor..."
            }

        return {
            "action": "open_url",
            "params": {"url": random_url},
            "reply": "Rastgele gorsel aciliyor..."
        }

    # ==================== VOLUME CONTROL ====================
    def _parse_volume(self, text: str, text_norm: str, original: str) -> dict | None:
        # Sessize alma
        mute_triggers = ["sesi kapat", "sessize al", "sessiz yap", "mute", "sesi kıs", "ses kapat"]
        if any(t in text for t in mute_triggers):
            return {
                "action": "set_volume",
                "params": {"mute": True},
                "reply": "Ses kapatılıyor..."
            }

        # Ses açma
        unmute_triggers = ["sesi aç", "sessizden çık", "unmute", "ses aç"]
        if any(t in text for t in unmute_triggers):
            return {
                "action": "set_volume",
                "params": {"mute": False},
                "reply": "Ses açılıyor..."
            }

        # Ses seviyesi
        volume_triggers = ["ses", "volume", "ses seviyesi", "sesi"]
        if any(t in text for t in volume_triggers):
            # Yüzde ile
            level_match = re.search(r'%\s*(\d+)|(\d+)\s*%|yüzde\s*(\d+)|(\d+)\s*yap', text)
            if level_match:
                level = int(level_match.group(1) or level_match.group(2) or level_match.group(3) or level_match.group(4))
                return {
                    "action": "set_volume",
                    "params": {"level": min(100, max(0, level))},
                    "reply": f"Ses seviyesi %{level} yapılıyor..."
                }

            # Arttır/azalt
            if any(w in text for w in ["arttır", "artır", "yükselt", "aç"]):
                return {"action": "set_volume", "params": {"level": 70}, "reply": "Ses yükseltiliyor..."}
            if any(w in text for w in ["azalt", "düşür", "kıs"]):
                return {"action": "set_volume", "params": {"level": 30}, "reply": "Ses kısılıyor..."}

        return None

    # ==================== CLIPBOARD ====================
    def _parse_clipboard(self, text: str, text_norm: str, original: str) -> dict | None:
        # Pano okuma
        read_triggers = ["panoda ne var", "panodaki", "clipboard", "panoyu oku",
                        "pano içeriği", "kopyalanan", "panoda ne", "pano göster"]
        if any(t in text for t in read_triggers):
            return {
                "action": "read_clipboard",
                "params": {},
                "reply": "Pano içeriği okunuyor..."
            }

        # Panoya yazma
        write_triggers = ["panoya yaz", "panoya kopyala", "kopyala:", "bunu kopyala",
                         "şunu kopyala", "metni kopyala", "clipboard'a"]
        if any(t in text for t in write_triggers):
            # İçeriği çıkar
            content_match = re.search(r'kopyala[:\s]+(.+)|yaz[:\s]+(.+)', text, re.IGNORECASE)
            if content_match:
                content = (content_match.group(1) or content_match.group(2)).strip()
                return {
                    "action": "write_clipboard",
                    "params": {"text": content},
                    "reply": "Metin panoya kopyalanıyor..."
                }

        return None

    # ==================== POWER CONTROL ====================
    def _parse_power_control(self, text: str, text_norm: str, original: str) -> dict | None:
        if any(k in text for k in ["ekranı kilitle", "ekrani kilitle", "lock screen"]):
            return {
                "action": "lock_screen",
                "params": {},
                "reply": "Ekran kilitleniyor..."
            }

        power_subjects = [
            "bilgisayar", "sistem", "mac", "macbook", "cihaz",
            "computer", "system", "laptop"
        ]

        if not any(s in text for s in power_subjects):
            return None

        if any(k in text for k in ["yeniden başlat", "yeniden baslat", "restart", "reboot"]):
            return {
                "action": "restart_system",
                "params": {},
                "reply": "Sistem yeniden başlatılıyor..."
            }

        if any(k in text for k in ["uykuya al", "uyku modu", "sleep"]):
            return {
                "action": "sleep_system",
                "params": {},
                "reply": "Sistem uyku moduna alınıyor..."
            }

        if any(k in text for k in ["kilitle", "lock"]):
            return {
                "action": "lock_screen",
                "params": {},
                "reply": "Ekran kilitleniyor..."
            }

        if any(k in text for k in ["kapat", "shut down", "shutdown", "power off"]):
            return {
                "action": "shutdown_system",
                "params": {},
                "reply": "Sistem kapatılıyor..."
            }

        return None

    # ==================== CLOSE APP ====================
    def _parse_close_app(self, text: str, text_norm: str, original: str) -> dict | None:
        close_triggers = ["kapat", "sonlandır", "durdur", "quit", "close", "kill"]

        # "sesi kapat" gibi durumları atla
        if "sesi" in text or "ses" in text:
            return None

        # "bilgisayarı kapat" gibi güç komutlarını app kapatmaya düşürme
        if any(k in text for k in ["bilgisayar", "sistem", "mac", "macbook", "cihaz"]):
            return None

        if any(t in text for t in close_triggers):
            for alias, app in self.app_aliases.items():
                if alias in text or self._normalize(alias) in text_norm:
                    return {
                        "action": "close_app",
                        "params": {"app_name": app},
                        "reply": f"{app} kapatılıyor..."
                    }

            # Genel uygulama adı arama
            app_match = re.search(r'([\w\s]+?)(?:\'?[ıiyuü]?\s*kapat|\'?[ıiyuü]?\s*sonlandır)', text)
            if app_match:
                app_name = app_match.group(1).strip()
                if len(app_name) > 1:
                    return {
                        "action": "close_app",
                        "params": {"app_name": app_name.title()},
                        "reply": f"{app_name.title()} kapatılıyor..."
                    }

        return None

    # ==================== NOTIFICATION ====================
    def _parse_notification(self, text: str, text_norm: str, original: str) -> dict | None:
        notif_triggers = ["bildirim", "bildir", "notification", "hatırlat", "uyar", "notify"]

        if any(t in text for t in notif_triggers):
            # İçeriği çıkar
            content_match = re.search(r'bildirim[:\s]+(.+)|bildir[:\s]+(.+)|gönder[:\s]+(.+)|hatırlat[:\s]+(.+)', text, re.IGNORECASE)
            if content_match:
                content = next((g for g in content_match.groups() if g), "").strip()
                return {
                    "action": "send_notification",
                    "params": {"title": "Bot Bildirimi", "message": content},
                    "reply": "Bildirim gönderiliyor..."
                }

            return {
                "action": "send_notification",
                "params": {"title": "Bot Bildirimi", "message": "Bildirim"},
                "reply": "Bildirim gönderiliyor..."
            }

        return None

    # ==================== OPEN APP ====================
    def _parse_open_app(self, text: str, text_norm: str, original: str) -> dict | None:
        open_triggers = ["aç", "başlat", "çalıştır", "open", "run", "start", "launch"]

        # "dosya aç", "url aç" gibi durumları atla
        if any(w in text for w in ["dosya", "klasör", "http", ".com", ".org"]):
            return None

        if any(t in text for t in open_triggers):
            for alias, app in self.app_aliases.items():
                if alias in text or self._normalize(alias) in text_norm:
                    return {
                        "action": "open_app",
                        "params": {"app_name": app},
                        "reply": f"{app} açılıyor..."
                    }

            # URL olarak algılanabilecek siteleri kontrol et
            for alias, url in self.url_aliases.items():
                if alias in text_norm:
                    return {
                        "action": "open_url",
                        "params": {"url": url},
                        "reply": f"{alias.capitalize()} açılıyor..."
                    }

        return None

    # ==================== OPEN URL ====================
    def _parse_open_url(self, text: str, text_norm: str, original: str) -> dict | None:
        # Direkt URL
        url_match = re.search(r'(https?://[^\s]+|www\.[^\s]+|\w+\.(com|org|net|io|ai|co|tr)[^\s]*)', text)
        if url_match:
            url = url_match.group()
            if not url.startswith("http"):
                url = "https://" + url
            return {"action": "open_url", "params": {"url": url}, "reply": "URL açılıyor..."}

        # Site adı ile
        goto_triggers = ["aç", "git", "gir", "gitmek", "götür", "open", "go to"]
        if any(t in text for t in goto_triggers):
            for alias, url in self.url_aliases.items():
                if alias in text_norm or alias in text:
                    return {
                        "action": "open_url",
                        "params": {"url": url},
                        "reply": f"{alias.capitalize()} açılıyor..."
                    }

        return None

    # ==================== GREETING ====================
    def _parse_greeting(self, text: str, text_norm: str, original: str) -> dict | None:
        words = text.split()
        if len(words) > 5:
            return None

        first_word = words[0] if words else ""

        if first_word in self.greetings or text in self.greetings:
            return {
                "action": "chat",
                "params": {},
                "reply": "Merhaba, ben Elyan. Stratejik kararlarınızda ve günlük görevlerinizde size yardımcı olmaya hazırım. Dosya yönetimi, sistem kontrolleri veya derin araştırmalar için bana komut verebilirsiniz. Size nasıl yardımcı olabilirim?"
            }

        return None

    # ==================== SYSTEM INFO ====================
    def _parse_system_info(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["sistem", "cpu", "ram", "bellek", "disk", "pil", "batarya",
                   "işlemci", "hafıza", "depolama", "system info", "performans"]

        if any(w in text for w in triggers):
            if "dosya" not in text and "klasör" not in text:
                return {"action": "get_system_info", "params": {}, "reply": "Sistem bilgileri getiriliyor..."}

        return None

    # ==================== LIST FILES ====================
    def _parse_list_files(self, text: str, text_norm: str, original: str) -> dict | None:
        list_triggers = ["ne var", "neler var", "göster", "listele", "bak", "içeriği",
                        "hangi dosya", "hangi klasör", "dosyalar neler", "klasörler neler",
                        "içindekiler", "neleri var", "dosyaları göster"]

        if any(t in text for t in list_triggers):
            path = self._extract_path(text)
            if not path:
                if any(w in text for w in ["bura", "şu an", "mevcut", "şurada"]):
                    path = str(HOME_DIR / "Desktop")
                elif any(w in text for w in ["masaüstü", "desktop", "masa"]):
                    path = str(HOME_DIR / "Desktop")
                else:
                    path = str(HOME_DIR / "Desktop")  # Default

            folder_name = Path(path).name or "Ana klasör"
            return {
                "action": "list_files",
                "params": {"path": path},
                "reply": f"{folder_name} klasörü listeleniyor..."
            }

        return None

    # ==================== WRITE FILE ====================
    def _parse_write_file(self, text: str, text_norm: str, original: str) -> dict | None:
        write_triggers = ["not yaz", "dosya oluştur", "kaydet", "yaz:", "not oluştur",
                         "liste yaz", "dosya yaz", "metin kaydet", "not al"]

        if any(t in text for t in write_triggers):
            # İçerik çıkarma
            content_match = re.search(r'yaz[:\s]+(.+)|oluştur[:\s]+(.+)|kaydet[:\s]+(.+)|içeriği[:\s]+(.+)', text, re.IGNORECASE)
            content = ""
            if content_match:
                content = (content_match.group(1) or content_match.group(2) or content_match.group(3) or content_match.group(4) or "").strip()

            # Dosya adı çıkarma
            filename = "not.txt"
            name_match = re.search(r'adı\s*[:\s]*(\w+)|(\w+)\s*dosyası|(\w+)\s*olarak', text)
            if name_match:
                name = name_match.group(1) or name_match.group(2) or name_match.group(3)
                if name and name not in ["yaz", "oluştur", "kaydet", "dosya", "not"]:
                    filename = name + ".txt"

            path = str(HOME_DIR / "Desktop" / filename)

            return {
                "action": "write_file",
                "params": {"path": path, "content": content},
                "reply": f"{filename} oluşturuluyor..."
            }

        return None

    # ==================== SEARCH FILES ====================
    def _parse_search_files(self, text: str, text_norm: str, original: str) -> dict | None:
        search_triggers = ["ara", "bul", "search", "find", "tara"]

        if any(t in text for t in search_triggers):
            pattern_match = re.search(r'\*\.(\w+)', text)
            if pattern_match:
                pattern = f"*.{pattern_match.group(1)}"
            else:
                ext_map = {
                    "pdf": "*.pdf", "resim": "*.{jpg,png,gif}", "foto": "*.{jpg,png}",
                    "video": "*.{mp4,mov}", "müzik": "*.{mp3,m4a}", "python": "*.py",
                    "belge": "*.{doc,docx,pdf,txt}", "excel": "*.xlsx", "word": "*.docx"
                }
                pattern = None
                for kw, pat in ext_map.items():
                    if kw in text:
                        pattern = pat
                        break

                if not pattern:
                    word_match = re.search(r'(\w+)\s*(dosya|file)', text)
                    if word_match:
                        pattern = f"*{word_match.group(1)}*"
                    else:
                        return None

            directory = self._extract_path(text) or str(HOME_DIR)
            return {
                "action": "search_files",
                "params": {"pattern": pattern, "directory": directory},
                "reply": f"{pattern} dosyaları aranıyor..."
            }

        return None

    # ==================== READ FILE ====================
    def _parse_read_file(self, text: str, text_norm: str, original: str) -> dict | None:
        read_triggers = ["oku", "içeriğini göster", "ne yazıyor", "aç ve göster", "içeriği"]

        if any(t in text for t in read_triggers):
            file_match = re.search(r'[\w\-]+\.\w+', text)
            if file_match:
                filename = file_match.group()
                path = self._extract_path(text)
                full_path = str(Path(path) / filename) if path else str(HOME_DIR / "Desktop" / filename)
                return {
                    "action": "read_file",
                    "params": {"path": full_path},
                    "reply": f"{filename} okunuyor..."
                }

        return None

    # ==================== DELETE FILE ====================
    def _parse_delete_file(self, text: str, text_norm: str, original: str) -> dict | None:
        delete_triggers = ["sil", "kaldir", "kaldır", "delete", "remove", "israf"]

        if any(t in text for t in delete_triggers):
            # "silme" gibi değişkenleri atla
            if any(w in text for w in ["silme işlemi", "silme işlemini", "silinmesini", "silinir"]):
                return None

            # Dosya adını bul
            file_match = re.search(r'[\w\-]+\.\w+', text)
            if file_match:
                filename = file_match.group()
                path = self._extract_path(text)
                full_path = str(Path(path) / filename) if path else str(HOME_DIR / "Desktop" / filename)
                return {
                    "action": "delete_file",
                    "params": {"path": full_path, "force": False},
                    "reply": f"{filename} siliniyor..."
                }

        return None

    # ==================== PROCESS CONTROL ====================
    def _parse_process_control(self, text: str, text_norm: str, original: str) -> dict | None:
        # Process listesi sorgusu
        list_triggers = ["process", "çalışan", "uygulamalar", "memory", "cpu"]
        query_words = ["kaç", "neler", "hangileri", "listele", "göster", "hangi", "what", "which"]
        
        # Doğrudan "Hangi uygulamalar çalışıyor?" veya similar pattern
        if "hangi" in text and "uygulamalar" in text and "çalışıyor" in text:
            return {
                "action": "get_process_info",
                "params": {},
                "reply": "Çalışan uygulamalar listeleniyor..."
            }
        
        if any(t in text for t in list_triggers) and any(w in text for w in query_words):
            return {
                "action": "get_process_info",
                "params": {},
                "reply": "Çalışan uygulamalar listeleniyor..."
            }

        # Process sonlandırma
        kill_triggers = ["sonlandır", "terminate", "kill", "exit", "quit"]
        if any(t in text for t in kill_triggers):
            # Uygulamayı adıyla bul
            for alias, app in [("chrome", "Chrome"), ("safari", "Safari"), ("python", "Python")]:
                if alias in text:
                    return {
                        "action": "kill_process",
                        "params": {"process_name": alias},
                        "reply": f"{app} process'i sonlandırılıyor..."
                    }

        return None

    # ==================== DARK MODE ====================
    # ==================== BRIGHTNESS ====================
    def _parse_brightness(self, text: str, text_norm: str, original: str) -> dict | None:
        # Gate: check normalized form (parlakl covers parlaklık/parlaklığı/parlaklig/parlakligi)
        if "parlakl" not in text_norm and "brightness" not in text_norm:
            return None

        # Kapatma
        if "kapat" in text_norm:
            return {"action": "set_brightness", "params": {"level": 10}, "reply": "Parlaklık düşürülüyor..."}

        # Açma / Artırma
        if any(w in text_norm for w in [" ac", "artir", "yukselt"]):
            return {"action": "set_brightness", "params": {"level": 75}, "reply": "Parlaklık artırılıyor..."}

        # Azalt / Düşür
        if any(w in text_norm for w in ["azalt", "dusur", " kis"]):
            return {"action": "set_brightness", "params": {"level": 30}, "reply": "Parlaklık azaltılıyor..."}

        # Yüzde ile (check against text_norm: yüzde→yuzde)
        level_match = re.search(r'%\s*(\d+)|(\d+)\s*%|yuzde\s*(\d+)|(\d+)\s*yap', text_norm)
        if level_match:
            level = int(level_match.group(1) or level_match.group(2) or level_match.group(3) or level_match.group(4))
            return {"action": "set_brightness", "params": {"level": min(100, max(0, level))}, "reply": f"Parlaklık %{level} yapılıyor..."}

        # Sadece parlaklık sorgusu → oku
        return {"action": "get_brightness", "params": {}, "reply": "Parlaklık okunuyor..."}

    # ==================== DARK MODE ====================
    def _parse_dark_mode(self, text: str, text_norm: str, original: str) -> dict | None:
        dark_triggers = [
            "karanlık mod", "karanlik mod", "dark mode", "gece modu",
            "karanlık tema", "karanlik tema", "dark tema"
        ]
        light_triggers = [
            "aydınlık mod", "aydinlik mod", "light mode", "gündüz modu",
            "aydınlık tema", "açık tema", "acik tema"
        ]

        # Toggle dark mode
        if any(t in text for t in dark_triggers) or any(t in text_norm for t in ["karanlik mod", "dark mode"]):
            return {
                "action": "toggle_dark_mode",
                "params": {},
                "reply": "Karanlık mod değiştiriliyor..."
            }

        if any(t in text for t in light_triggers):
            return {
                "action": "toggle_dark_mode",
                "params": {},
                "reply": "Aydınlık moda geçiliyor..."
            }

        return None

    # ==================== WIFI CONTROL ====================
    def _parse_wifi(self, text: str, text_norm: str, original: str) -> dict | None:
        # WiFi status query
        status_triggers = ["wifi durumu", "wifi durum", "wifi ne durumda", "wifi bagli mi",
                          "wifi bağlı mı", "internet durumu", "wifi status"]

        if any(t in text for t in status_triggers) or any(t in text_norm for t in ["wifi durumu", "wifi bagli"]):
            return {
                "action": "wifi_status",
                "params": {},
                "reply": "WiFi durumu kontrol ediliyor..."
            }

        # WiFi toggle
        wifi_off_triggers = ["wifi kapat", "wifi'yı kapat", "wifi'yi kapat", "interneti kapat",
                            "wifi off", "wifi kapali", "wifi kapalı"]
        wifi_on_triggers = ["wifi aç", "wifi'yı aç", "wifi'yi aç", "interneti aç",
                           "wifi on", "wifi açık", "wifi acik"]

        if any(t in text for t in wifi_off_triggers) or any(t in text_norm for t in ["wifi kapat", "interneti kapat"]):
            return {
                "action": "wifi_toggle",
                "params": {"enable": False},
                "reply": "WiFi kapatılıyor..."
            }

        if any(t in text for t in wifi_on_triggers) or any(t in text_norm for t in ["wifi ac", "interneti ac"]):
            return {
                "action": "wifi_toggle",
                "params": {"enable": True},
                "reply": "WiFi açılıyor..."
            }

        return None

    # ==================== CALENDAR ====================
    def _parse_calendar(self, text: str, text_norm: str, original: str) -> dict | None:
        # Get today's events
        today_triggers = [
            "bugünkü etkinlikler", "bugunku etkinlikler", "bugün ne var",
            "takvimde ne var", "toplantilarim", "toplantılarım",
            "bugünkü toplantı", "bugunku toplanti", "today events",
            "takvim etkinlik", "etkinliklerim", "günün programı"
        ]

        if any(t in text for t in today_triggers) or any(t in text_norm for t in ["bugunku etkinlik", "toplanti", "takvim"]):
            # Make sure it's a query, not creation
            if not any(w in text for w in ["ekle", "oluştur", "olustur", "yaz", "kaydet", "create"]):
                return {
                    "action": "get_today_events",
                    "params": {},
                    "reply": "Bugünün etkinlikleri getiriliyor..."
                }

        # Create event
        create_triggers = ["etkinlik ekle", "etkinlik oluştur", "toplantı ekle", "toplanti ekle",
                          "takvime ekle", "takvime kaydet", "create event", "add event"]

        if any(t in text for t in create_triggers) or any(t in text_norm for t in ["etkinlik ekle", "takvime ekle"]):
            # Extract title
            title = ""
            title_match = re.search(r'ekle[:\s]+(.+)|oluştur[:\s]+(.+)|toplantı[:\s]+(.+)', text, re.IGNORECASE)
            if title_match:
                title = (title_match.group(1) or title_match.group(2) or title_match.group(3) or "").strip()

            # Extract time
            time_match = re.search(r'(\d{1,2})[:\.](\d{2})|saat\s*(\d{1,2})', text)
            start_time = None
            if time_match:
                if time_match.group(1) and time_match.group(2):
                    start_time = f"{time_match.group(1)}:{time_match.group(2)}"
                elif time_match.group(3):
                    start_time = f"{time_match.group(3)}:00"

            return {
                "action": "create_event",
                "params": {"title": title or "Etkinlik", "start_time": start_time},
                "reply": "Etkinlik oluşturuluyor..."
            }

        return None

    # ==================== REMINDERS ====================
    def _parse_reminders(self, text: str, text_norm: str, original: str) -> dict | None:
        # Get reminders
        list_triggers = ["anımsatıcılar", "animsaticilar", "hatırlatıcılar", "reminders",
                        "anımsatıcılarım", "hatırlatmalar", "ne hatırlatacak"]

        if any(t in text for t in list_triggers):
            if not any(w in text for w in ["ekle", "oluştur", "olustur", "yaz", "hatırlat", "hatirlat"]):
                return {
                    "action": "get_reminders",
                    "params": {},
                    "reply": "Anımsatıcılar getiriliyor..."
                }

        # Create reminder
        create_triggers = [
            "hatırlat", "hatirlat", "anımsat", "animsat",
            "hatırlatıcı ekle", "anımsatıcı ekle", "remind me",
            "bana hatırlat", "not düş"
        ]

        if any(t in text for t in create_triggers):
            # Extract what to remind
            title = ""
            # Pattern: "hatırlat: xxx" or "hatırlat xxx" or "yarın xxx hatırlat"
            content_match = re.search(
                r'hatırlat[:\s]+(.+)|hatirlat[:\s]+(.+)|anımsat[:\s]+(.+)|animsat[:\s]+(.+)',
                text, re.IGNORECASE
            )
            if content_match:
                title = (content_match.group(1) or content_match.group(2) or
                        content_match.group(3) or content_match.group(4) or "").strip()

            # Extract date/time
            due_date = None
            due_time = None

            # Tomorrow
            if any(w in text for w in ["yarın", "yarin"]):
                from datetime import datetime, timedelta
                tomorrow = datetime.now() + timedelta(days=1)
                due_date = tomorrow.strftime("%Y-%m-%d")

            # Time extraction
            time_match = re.search(r'(\d{1,2})[:\.](\d{2})|saat\s*(\d{1,2})', text)
            if time_match:
                if time_match.group(1) and time_match.group(2):
                    due_time = f"{time_match.group(1)}:{time_match.group(2)}"
                elif time_match.group(3):
                    due_time = f"{time_match.group(3)}:00"

            # Clean title from date/time words
            if title:
                title = re.sub(r'(yarın|yarin|bugün|bugun|saat\s*\d+|\d+[:\.]?\d*)', '', title).strip()

            return {
                "action": "create_reminder",
                "params": {"title": title or "Hatırlatıcı", "due_date": due_date, "due_time": due_time},
                "reply": "Anımsatıcı oluşturuluyor..."
            }

        return None

    # ==================== OFFICE DOCUMENTS ====================
    def _parse_office_documents(self, text: str, text_norm: str, original: str) -> dict | None:
        # Detect file extension in text
        docx_match = re.search(r'([\w\-\.]+\.docx?)', text, re.IGNORECASE)
        xlsx_match = re.search(r'([\w\-\.]+\.xlsx?)', text, re.IGNORECASE)
        pdf_match = re.search(r'([\w\-\.]+\.pdf)', text, re.IGNORECASE)

        # Read Word document
        word_read_triggers = ["word oku", "docx oku", "word dosyası oku", "word'ü oku",
                             "word dosyasını oku", "belgeyi oku"]
        if docx_match or any(t in text for t in word_read_triggers):
            if any(w in text for w in ["oku", "read", "göster", "aç", "içeriğini"]):
                filename = docx_match.group(1) if docx_match else None
                path = self._extract_path(text)
                if filename and path:
                    full_path = str(Path(path) / filename)
                elif filename:
                    full_path = str(HOME_DIR / "Desktop" / filename)
                else:
                    full_path = ""

                return {
                    "action": "read_word",
                    "params": {"path": full_path},
                    "reply": f"Word dosyası okunuyor..."
                }

        # Write Word document
        word_write_triggers = ["word oluştur", "word olustur", "word yaz", "docx oluştur", "docx olustur",
                              "word dosyası yaz", "word dosyasi yaz",
                              "word olarak kaydet", "word belgesi oluştur", "word belgesi olustur",
                              "word belgesi yaz"]
        if any(t in text for t in word_write_triggers):
            # Extract content
            content = ""
            content_match = re.search(r'içerik[:\s]+(.+)|yaz[:\s]+(.+)|kaydet[:\s]+(.+)', text, re.IGNORECASE)
            if content_match:
                content = (content_match.group(1) or content_match.group(2) or content_match.group(3) or "").strip()

            # Extract filename
            filename = docx_match.group(1) if docx_match else "belge.docx"
            path = str(HOME_DIR / "Desktop" / filename)

            return {
                "action": "write_word",
                "params": {"path": path, "content": content},
                "reply": f"Word dosyası oluşturuluyor..."
            }

        # Read Excel
        excel_read_triggers = ["excel oku", "xlsx oku", "tablo oku", "excel dosyası oku",
                              "excel'i oku", "tabloyu oku"]
        if xlsx_match or any(t in text for t in excel_read_triggers):
            if any(w in text for w in ["oku", "read", "göster", "aç", "içeriğini"]):
                filename = xlsx_match.group(1) if xlsx_match else None
                path = self._extract_path(text)
                if filename and path:
                    full_path = str(Path(path) / filename)
                elif filename:
                    full_path = str(HOME_DIR / "Desktop" / filename)
                else:
                    full_path = ""

                return {
                    "action": "read_excel",
                    "params": {"path": full_path},
                    "reply": f"Excel dosyası okunuyor..."
                }

        # Write Excel
        excel_write_triggers = ["excel oluştur", "excel olustur", "excel yaz", "xlsx oluştur", "xlsx olustur",
                               "tablo oluştur", "tablo olustur",
                               "excel olarak kaydet", "excel dosyası yaz", "excel dosyasi yaz"]
        if any(t in text for t in excel_write_triggers):
            filename = xlsx_match.group(1) if xlsx_match else "tablo.xlsx"
            path = str(HOME_DIR / "Desktop" / filename)

            return {
                "action": "write_excel",
                "params": {"path": path, "data": []},
                "reply": f"Excel dosyası oluşturuluyor..."
            }

        # Read PDF
        pdf_read_triggers = ["pdf oku", "pdf'i oku", "pdf dosyası oku", "pdf içeriği",
                           "pdf'yi oku", "pdf aç"]
        if pdf_match or any(t in text for t in pdf_read_triggers):
            if any(w in text for w in ["oku", "read", "göster", "aç", "içeriğini", "içeriği"]):
                filename = pdf_match.group(1) if pdf_match else None
                path = self._extract_path(text)

                # Check for page range
                pages = None
                page_match = re.search(r'(\d+)[\-–](\d+)\s*sayfa|sayfa\s*(\d+)[\-–](\d+)|ilk\s*(\d+)', text)
                if page_match:
                    if page_match.group(1) and page_match.group(2):
                        pages = f"{page_match.group(1)}-{page_match.group(2)}"
                    elif page_match.group(3) and page_match.group(4):
                        pages = f"{page_match.group(3)}-{page_match.group(4)}"
                    elif page_match.group(5):
                        pages = f"1-{page_match.group(5)}"

                if filename and path:
                    full_path = str(Path(path) / filename)
                elif filename:
                    full_path = str(HOME_DIR / "Desktop" / filename)
                else:
                    full_path = ""

                return {
                    "action": "read_pdf",
                    "params": {"path": full_path, "pages": pages},
                    "reply": f"PDF okunuyor..."
                }

        # PDF Info
        pdf_info_triggers = ["pdf bilgisi", "pdf info", "pdf hakkında", "pdf detayları"]
        if any(t in text for t in pdf_info_triggers):
            filename = pdf_match.group(1) if pdf_match else None
            path = self._extract_path(text)
            if filename and path:
                full_path = str(Path(path) / filename)
            elif filename:
                full_path = str(HOME_DIR / "Desktop" / filename)
            else:
                full_path = ""

            return {
                "action": "get_pdf_info",
                "params": {"path": full_path},
                "reply": f"PDF bilgisi alınıyor..."
            }

        # Summarize document
        summarize_triggers = ["özetle", "ozetle", "özet çıkar", "ozet cikar", "summarize",
                            "belgeyi özetle", "dosyayı özetle", "kısaca anlat"]
        if any(t in text for t in summarize_triggers):
            # Find any document file
            doc_path = None
            if docx_match:
                doc_path = docx_match.group(1)
            elif xlsx_match:
                doc_path = xlsx_match.group(1)
            elif pdf_match:
                doc_path = pdf_match.group(1)

            if doc_path:
                path = self._extract_path(text)
                if path:
                    full_path = str(Path(path) / doc_path)
                else:
                    full_path = str(HOME_DIR / "Desktop" / doc_path)

                # Determine style
                style = "brief"
                if any(w in text for w in ["detaylı", "detayli", "ayrıntılı", "detailed"]):
                    style = "detailed"
                elif any(w in text for w in ["madde", "liste", "bullet"]):
                    style = "bullets"

                return {
                    "action": "summarize_document",
                    "params": {"path": full_path, "style": style},
                    "reply": f"Belge özetleniyor..."
                }

        return None

    # ==================== WEB RESEARCH ====================
    def _parse_web_research(self, text: str, text_norm: str, original: str) -> dict | None:
        # Web search
        web_search_triggers = [
            "internette ara", "web'de ara", "webde ara", "google'da ara",
            "internetten bul", "online ara", "internet ara", "web search",
            "araştır:", "arastir:", "google'da", "googleda"
        ]

        if any(t in text for t in web_search_triggers):
            # Extract query
            query = ""
            
            # Pattern 1: "google'da X ara"
            google_match = re.search(r"google'da\s+(.+?)(?:\s+ara|\s+bul|$)", text, re.IGNORECASE)
            if google_match:
                query = google_match.group(1).strip()
            
            # Pattern 2: "X ara" or "araştır: X"
            if not query:
                query_match = re.search(r'araştır[:\s]+(.+)|arastir[:\s]+(.+)|ara[:\s]+(.+)', text, re.IGNORECASE)
                if query_match:
                    query = (query_match.group(1) or query_match.group(2) or query_match.group(3) or "").strip()

            if not query:
                # Try to extract after trigger
                for trigger in web_search_triggers:
                    if trigger in text:
                        parts = text.split(trigger)
                        if len(parts) > 1 and parts[1].strip():
                            query = parts[1].strip()
                            break

            if query:
                # Clean query from "ara", "bul" if they remain at the end
                query = re.sub(r'\s+(ara|bul|bak|search)$', '', query, flags=re.IGNORECASE).strip()
                
                return {
                    "action": "web_search",
                    "params": {"query": query},
                    "reply": f"'{query}' internette aranıyor..."
                }

        # Fetch specific URL
        fetch_triggers = ["sayfayı oku", "sayfayi oku", "url oku", "sayfa içeriği",
                        "web sayfası", "fetch page"]
        url_pattern = re.search(r'https?://[^\s]+', text)

        if url_pattern and any(t in text for t in fetch_triggers + ["oku", "getir", "içeriğini"]):
            url = url_pattern.group()
            return {
                "action": "fetch_page",
                "params": {"url": url},
                "reply": "Sayfa içeriği alınıyor..."
            }

        # Research status check (before general research triggers — "araştırma durumu" contains "araştır")
        status_triggers = ["araştırma durumu", "arastirma durumu", "research status"]
        if any(t in text for t in status_triggers):
            # Extract task ID
            task_id_match = re.search(r'research_\d+_\d+', text)
            task_id = task_id_match.group() if task_id_match else ""

            return {
                "action": "get_research_status",
                "params": {"task_id": task_id},
                "reply": "Araştırma durumu kontrol ediliyor..."
            }

        # Start research
        research_triggers = [
            "araştırma yap", "arastirma yap", "araştır", "arastir",
            "detaylı araştır", "research", "araştırma başlat"
        ]

        if any(t in text for t in research_triggers):
            # Skip simple web search phrases
            if any(t in text for t in ["internette ara", "web'de ara", "google"]):
                return None

            # Extract topic - try multiple patterns
            topic = ""

            # Pattern 1: "X hakkında araştırma yap" veya "X konusunda araştır"
            topic_match = re.search(
                r'(.+?)\s+(?:hakkında|hakkinda|konusunda|konusunu|üzerine|uzerine)\s+(?:araştır|arastir|araştırma)',
                text, re.IGNORECASE
            )
            if topic_match:
                topic = topic_match.group(1).strip()

            # Pattern 2: "araştırma yap: X" veya "araştır: X"
            if not topic:
                topic_match = re.search(r'(?:araştır|arastir|araştırma|arastirma)[:\s]+(.+?)(?:\s+yap|\s+hakkında|$)', text, re.IGNORECASE)
                if topic_match:
                    candidate = topic_match.group(1).strip()
                    # Strip "yap:" artifacts before accepting
                    candidate = re.sub(r'^yap\s*', '', candidate, flags=re.IGNORECASE).strip().strip(':').strip()
                    if candidate:
                        topic = candidate

            # Pattern 3: Split by trigger and take after
            if not topic:
                for trigger in research_triggers:
                    if trigger in text:
                        parts = text.split(trigger)
                        # "yap" dan önceki kısım veya sonraki kısım
                        if len(parts) > 0 and parts[0].strip():
                            candidate = parts[0].strip()
                            # "hakkında" gibi kelimeleri temizle
                            candidate = re.sub(r'\s*(hakkında|hakkinda|konusunda|konusunu)\s*$', '', candidate).strip()
                            if candidate and len(candidate) > 2:
                                topic = candidate
                                break
                        if len(parts) > 1 and parts[1].strip():
                            topic = parts[1].strip().strip(':').strip()
                            break

            # Gereksiz kelimeleri temizle
            if topic:
                topic = re.sub(r'^(bir|bu|su|şu)\s+', '', topic, flags=re.IGNORECASE)
                topic = re.sub(r'^yap\s*', '', topic, flags=re.IGNORECASE)
                topic = topic.strip().strip(':').strip()

            # Determine depth
            depth = "basic"
            if any(w in text for w in ["detaylı", "detayli", "derin", "kapsamlı", "deep"]):
                depth = "deep"
            elif any(w in text for w in ["orta", "moderate"]):
                depth = "moderate"

            if topic:
                return {
                    "action": "start_research",
                    "params": {"topic": topic, "depth": depth},
                    "reply": f"'{topic}' arastiriliyor..."
                }

        return None

    # ==================== SPOTLIGHT SEARCH ====================
    def _parse_spotlight(self, text: str, text_norm: str, original: str) -> dict | None:
        spotlight_triggers = [
            "bilgisayarda ara", "sistemde ara", "spotlight",
            "dosya bul", "bul:", "search:", "mdfind",
            "bilgisayarımda", "sistemde bul"
        ]

        # Check for spotlight-style search
        if any(t in text for t in spotlight_triggers):
            # Extract search query
            query = ""
            query_match = re.search(r'ara[:\s]+(.+)|bul[:\s]+(.+)|search[:\s]+(.+)', text, re.IGNORECASE)
            if query_match:
                query = (query_match.group(1) or query_match.group(2) or query_match.group(3) or "").strip()

            if not query:
                # Try to extract any word after the trigger
                for trigger in spotlight_triggers:
                    if trigger in text:
                        parts = text.split(trigger)
                        if len(parts) > 1 and parts[1].strip():
                            query = parts[1].strip()
                            break

            # Detect file type
            file_type = None
            type_keywords = {
                "pdf": ["pdf"],
                "word": ["word", "docx", "doc"],
                "excel": ["excel", "xlsx", "xls"],
                "image": ["resim", "foto", "fotoğraf", "image", "jpg", "png"],
                "video": ["video", "film", "mp4", "mov"],
                "audio": ["müzik", "muzik", "mp3", "ses", "audio"]
            }

            for ftype, keywords in type_keywords.items():
                if any(kw in text for kw in keywords):
                    file_type = ftype
                    # Remove file type from query
                    for kw in keywords:
                        query = query.replace(kw, "").strip()
                    break

            if query:
                return {
                    "action": "spotlight_search",
                    "params": {"query": query, "file_type": file_type},
                    "reply": f"'{query}' aranıyor..."
                }

        return None

    # ==================== HELPERS ====================
    def _extract_path(self, text: str) -> str | None:
        text_norm = self._normalize(text)

        for alias, folder in self.path_aliases.items():
            alias_norm = self._normalize(alias)
            if alias_norm in text_norm or alias in text:
                if folder:
                    return str(HOME_DIR / folder)
                return str(HOME_DIR)

        path_match = re.search(r'[~/][a-zA-Z0-9_/\-\.]+', text)
        if path_match:
            path = path_match.group()
            if path.startswith("~"):
                path = str(HOME_DIR) + path[1:]
            return path

        return None

    def _parse_terminal_command(self, text: str, text_norm: str, original: str) -> dict | None:
        """Terminal komutu çalıştırma komutlarını parse et"""
        # Terminal komutu trigger'ları
        terminal_triggers = [
            "terminal", "komut", "çalıştır", "run", "execute", "bash", "shell"
        ]

        # Komut çalıştırma pattern'leri
        command_patterns = [
            r"(?:terminal|komut|çalıştır|run|execute)\s+(?:komutunu?|bunu|şunu)\s*[:\-]?\s*(.+)",
            r"(.+?)\s+(?:komutunu?|çalıştır)",
            r"run\s+(.+)",
            r"execute\s+(.+)",
        ]

        # Trigger kontrolü
        has_trigger = any(trigger in text for trigger in terminal_triggers)

        if has_trigger:
            # Komut çıkarımı
            command = None

            for pattern in command_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    command = match.group(1).strip()
                    break

            # Basit çıkarım fallback
            if not command:
                # "terminal ls" gibi direkt komutlar
                words = text.split()
                for i, word in enumerate(words):
                    if word in terminal_triggers and i + 1 < len(words):
                        command = " ".join(words[i+1:])
                        break

            if command:
                # Güvenli komut kontrolü (temel)
                safe_commands = ["date", "uptime", "whoami", "pwd", "ls", "df", "du", "ping", "python", "node", "git"]
                base_cmd = command.split()[0]

                if base_cmd in safe_commands:
                    return {
                        "action": "run_safe_command",
                        "params": {"command": command},
                        "reply": f"Terminal komutu çalıştırılıyor: {command}"
                    }
                else:
                    return {
                        "action": "run_safe_command",
                        "params": {"command": command},
                        "reply": f"Güvenli komut kontrol ediliyor: {command}"
                    }

        return None

    # ========================================
    # v3.0 NEW PARSERS
    # ========================================

    # ==================== NOTES ====================
    def _parse_notes(self, text: str, text_norm: str, original: str) -> dict | None:
        """Not alma komutlarını parse et"""

        # Not oluşturma
        create_triggers = [
            "not oluştur", "not olustur", "yeni not", "not al", "not ekle",
            "create note", "new note", "add note", "take note"
        ]

        if any(t in text for t in create_triggers):
            # Başlık ve içerik çıkar
            title = ""
            content = ""

            # Pattern: "not oluştur: başlık" veya "not oluştur başlık: içerik"
            title_match = re.search(
                r'(?:not oluştur|not olustur|yeni not|create note|new note)[:\s]+([^:]+?)(?::|$)',
                text, re.IGNORECASE
            )
            if title_match:
                title = title_match.group(1).strip()

            # İçerik ayrı belirtilmişse
            content_match = re.search(r'içerik[:\s]+(.+)|content[:\s]+(.+)', text, re.IGNORECASE)
            if content_match:
                content = (content_match.group(1) or content_match.group(2) or "").strip()

            # Etiketler
            tags = []
            tags_match = re.search(r'etiket(?:ler)?[:\s]+([^,]+(?:,[^,]+)*)|tags?[:\s]+([^,]+(?:,[^,]+)*)', text, re.IGNORECASE)
            if tags_match:
                tags_str = tags_match.group(1) or tags_match.group(2) or ""
                tags = [t.strip() for t in tags_str.split(",") if t.strip()]

            # Kategori
            category = "general"
            if any(w in text for w in ["iş", "is", "work"]):
                category = "work"
            elif any(w in text for w in ["kişisel", "kisisel", "personal"]):
                category = "personal"
            elif any(w in text for w in ["fikir", "idea"]):
                category = "ideas"
            elif any(w in text for w in ["yapılacak", "yapilacak", "todo"]):
                category = "todo"

            return {
                "action": "create_note",
                "params": {
                    "title": title or "Yeni Not",
                    "content": content,
                    "tags": tags,
                    "category": category
                },
                "reply": "Not oluşturuluyor..."
            }

        # Notları listeleme
        list_triggers = [
            "notlarım", "notlarim", "notları listele", "notlari listele",
            "notlarımı göster", "notlarimi goster", "my notes", "list notes",
            "show notes", "tüm notlar", "tum notlar"
        ]

        if any(t in text for t in list_triggers):
            category = None
            if "iş" in text or "work" in text:
                category = "work"
            elif "kişisel" in text or "personal" in text:
                category = "personal"

            return {
                "action": "list_notes",
                "params": {"category": category},
                "reply": "Notlar listeleniyor..."
            }

        # Notlarda arama
        search_triggers = [
            "notlarda ara", "notlarda bul", "not ara", "not bul",
            "search notes", "find note", "search in notes"
        ]

        if any(t in text for t in search_triggers):
            query = ""
            query_match = re.search(
                r'(?:notlarda ara|notlarda bul|not ara|search notes?|find note)[:\s]+(.+)',
                text, re.IGNORECASE
            )
            if query_match:
                query = query_match.group(1).strip()

            if query:
                return {
                    "action": "search_notes",
                    "params": {"query": query},
                    "reply": f"Notlarda '{query}' aranıyor..."
                }

        # Not silme
        delete_triggers = ["not sil", "notu sil", "delete note", "remove note"]

        if any(t in text for t in delete_triggers):
            note_id = ""
            id_match = re.search(r'(?:not sil|notu sil|delete note)[:\s]+(.+)', text, re.IGNORECASE)
            if id_match:
                note_id = id_match.group(1).strip()

            if note_id:
                return {
                    "action": "delete_note",
                    "params": {"note_id": note_id, "permanent": "kalıcı" in text or "permanent" in text},
                    "reply": "Not siliniyor..."
                }

        return None

    # ==================== TASK PLANNING ====================
    def _parse_task_planning(self, text: str, text_norm: str, original: str) -> dict | None:
        """Görev planlama komutlarını parse et"""

        # Çoklu görev algılama - "önce X, sonra Y" pattern'i
        multi_task_patterns = [
            r"önce\s+(.+?)\s*,?\s*sonra\s+(.+)",
            r"once\s+(.+?)\s*,?\s*sonra\s+(.+)",
            r"first\s+(.+?)\s*,?\s*then\s+(.+)",
            r"(.+?)\s+ve\s+sonra\s+(.+)",
            r"(.+?)\s+ardından\s+(.+)",
        ]

        for pattern in multi_task_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                task1 = match.group(1).strip()
                task2 = match.group(2).strip()

                # Basit görev planı oluştur
                return {
                    "action": "create_plan",
                    "params": {
                        "name": "Otomatik Plan",
                        "description": f"{task1}, sonra {task2}",
                        "tasks": [
                            {"id": "task_1", "name": task1, "action": "auto", "params": {"text": task1}},
                            {"id": "task_2", "name": task2, "action": "auto", "params": {"text": task2}, "depends_on": ["task_1"]}
                        ],
                        "execution_mode": "dependency"
                    },
                    "reply": "Görev planı oluşturuluyor..."
                }

        # Plan oluşturma
        create_triggers = ["plan oluştur", "plan olustur", "yeni plan", "create plan", "new plan"]

        if any(t in text for t in create_triggers):
            name = ""
            name_match = re.search(r'(?:plan oluştur|plan olustur|create plan)[:\s]+(.+)', text, re.IGNORECASE)
            if name_match:
                name = name_match.group(1).strip()

            return {
                "action": "create_plan",
                "params": {"name": name or "Yeni Plan", "description": "", "tasks": []},
                "reply": "Plan oluşturuluyor..."
            }

        # Plan listesi
        list_triggers = ["planlar", "planlarım", "planlarim", "list plans", "my plans"]

        if any(t in text for t in list_triggers):
            return {
                "action": "list_plans",
                "params": {},
                "reply": "Planlar listeleniyor..."
            }

        # Plan durumu
        status_triggers = ["plan durumu", "plan status", "plan nasıl"]

        if any(t in text for t in status_triggers):
            plan_id = ""
            id_match = re.search(r'plan_\w+', text)
            if id_match:
                plan_id = id_match.group()

            return {
                "action": "get_plan_status",
                "params": {"plan_id": plan_id},
                "reply": "Plan durumu kontrol ediliyor..."
            }

        return None

    # ==================== DOCUMENT EDITING ====================
    def _parse_document_editing(self, text: str, text_norm: str, original: str) -> dict | None:
        """Belge düzenleme komutlarını parse et"""

        # Metin dosyası düzenleme
        edit_triggers = [
            "düzenle", "duzenle", "değiştir", "degistir",
            "bul ve değiştir", "bul ve degistir", "find and replace",
            "edit file", "modify file"
        ]

        # Dosya adı kontrolü
        file_match = re.search(r'([\w\-\.]+\.(?:txt|md|py|js|json|xml|html|css|csv))', text, re.IGNORECASE)

        if file_match and any(t in text for t in edit_triggers):
            filename = file_match.group(1)

            # Bul ve değiştir
            replace_match = re.search(
                r"['\"](.+?)['\"].*(?:yerine|ile|with|to)\s*['\"](.+?)['\"]",
                text, re.IGNORECASE
            )

            operations = []
            if replace_match:
                find_text = replace_match.group(1)
                replace_text = replace_match.group(2)
                operations.append({
                    "type": "replace",
                    "find": find_text,
                    "replace": replace_text,
                    "all": True
                })

            path = self._extract_path(text)
            full_path = str(Path(path) / filename) if path else str(HOME_DIR / "Desktop" / filename)

            return {
                "action": "edit_text_file",
                "params": {
                    "path": full_path,
                    "operations": operations,
                    "create_backup": True
                },
                "reply": f"{filename} düzenleniyor..."
            }

        # Word düzenleme
        word_match = re.search(r'([\w\-\.]+\.docx?)', text, re.IGNORECASE)

        if word_match and any(t in text for t in edit_triggers):
            filename = word_match.group(1)

            replace_match = re.search(
                r"['\"](.+?)['\"].*(?:yerine|ile|with|to)\s*['\"](.+?)['\"]",
                text, re.IGNORECASE
            )

            operations = []
            if replace_match:
                find_text = replace_match.group(1)
                replace_text = replace_match.group(2)
                operations.append({
                    "type": "replace_text",
                    "find": find_text,
                    "replace": replace_text
                })

            path = self._extract_path(text)
            full_path = str(Path(path) / filename) if path else str(HOME_DIR / "Desktop" / filename)

            return {
                "action": "edit_word_document",
                "params": {
                    "path": full_path,
                    "operations": operations,
                    "create_backup": True
                },
                "reply": f"{filename} düzenleniyor..."
            }

        return None

    # ==================== DOCUMENT MERGING ====================
    def _parse_document_merging(self, text: str, text_norm: str, original: str) -> dict | None:
        """Belge birleştirme komutlarını parse et"""

        merge_triggers = [
            "birleştir", "birlestir", "merge", "combine", "concat",
            "dosyaları birleştir", "dosyalari birlestir",
            "pdf birleştir", "pdf birlestir", "merge pdf",
            "word birleştir", "word birlestir", "merge word"
        ]

        if any(t in text for t in merge_triggers):
            # Dosyaları bul
            pdf_files = re.findall(r'([\w\-\.]+\.pdf)', text, re.IGNORECASE)
            word_files = re.findall(r'([\w\-\.]+\.docx?)', text, re.IGNORECASE)

            input_files = []
            output_format = "auto"

            if pdf_files:
                input_files = pdf_files
                output_format = "pdf"
            elif word_files:
                input_files = word_files
                output_format = "docx"

            if len(input_files) >= 2:
                # Path'leri oluştur
                path = self._extract_path(text) or str(HOME_DIR / "Desktop")
                input_paths = [str(Path(path) / f) for f in input_files]

                # Çıktı dosyası
                output_name = f"merged_{input_files[0]}"
                output_match = re.search(r'(?:çıktı|cikti|output|olarak)[:\s]+(\S+)', text, re.IGNORECASE)
                if output_match:
                    output_name = output_match.group(1)

                output_path = str(Path(path) / output_name)

                if output_format == "pdf":
                    return {
                        "action": "merge_pdfs",
                        "params": {
                            "input_paths": input_paths,
                            "output_path": output_path
                        },
                        "reply": f"{len(input_files)} PDF birleştiriliyor..."
                    }
                else:
                    return {
                        "action": "merge_word_documents",
                        "params": {
                            "input_paths": input_paths,
                            "output_path": output_path
                        },
                        "reply": f"{len(input_files)} Word dosyası birleştiriliyor..."
                    }

        return None

    # ==================== ADVANCED RESEARCH ====================
    def _parse_advanced_research(self, text: str, text_norm: str, original: str) -> dict | None:
        """Gelişmiş araştırma komutlarını parse et"""

        # Derinlik seviyeleri
        depth_keywords = {
            "quick": ["hızlı", "hizli", "quick", "kısa", "kisa"],
            "standard": ["standart", "normal", "standard"],
            "comprehensive": ["kapsamlı", "kapsamli", "detaylı", "detayli", "comprehensive", "detailed"],
            "expert": ["uzman", "akademik", "expert", "academic", "derin"]
        }

        # Gelişmiş araştırma trigger'ları
        advanced_triggers = [
            "kapsamlı araştırma", "kapsamli arastirma",
            "detaylı araştırma", "detayli arastirma",
            "derin araştırma", "comprehensive research",
            "deep research", "expert research",
            "akademik araştırma"
        ]

        if any(t in text for t in advanced_triggers):
            topic = ""
            
            # Pattern 1: "X hakkında kapsamlı araştırma yap" - en yaygın kullanım
            topic_match = re.search(
                r'(.+?)\s+(?:hakkında|hakkinda|konusunda|konusunu|üzerine|uzerine)\s+(?:kapsamlı|kapsamli|detaylı|detayli|derin|akademik)',
                text, re.IGNORECASE
            )
            if topic_match:
                topic = topic_match.group(1).strip()
            
            # Pattern 2: "kapsamlı araştırma yap: X" veya "X araştır"
            if not topic:
                topic_match = re.search(
                    r'(?:kapsamlı|kapsamli|detaylı|detayli|derin)\s+(?:araştırma|arastirma)\s+(?:yap)?[:\s]*(.+?)(?:\s+yap)?$',
                    text, re.IGNORECASE
                )
                if topic_match:
                    topic = topic_match.group(1).strip()
            
            # Pattern 3: Trigger'dan önceki metin (fallback)
            if not topic:
                for trigger in advanced_triggers:
                    if trigger in text:
                        idx = text.find(trigger)
                        if idx > 0:
                            candidate = text[:idx].strip()
                            # "hakkında", "konusunda" gibi ekleri temizle
                            candidate = re.sub(r'\s*(hakkında|hakkinda|konusunda|konusunu|üzerine|uzerine)\s*$', '', candidate, flags=re.IGNORECASE).strip()
                            if candidate and len(candidate) > 2:
                                topic = candidate
                                break
                        
                        # Trigger'dan sonrası
                        after = text[idx + len(trigger):].strip()
                        after = re.sub(r'^\s*yap\s*', '', after).strip()
                        if after and len(after) > 2:
                            topic = after
                            break

            # Gereksiz kelimeleri temizle
            if topic:
                topic = re.sub(r'^(bir|bu|su|şu)\s+', '', topic, flags=re.IGNORECASE)
                topic = re.sub(r'\s+(yap|araştır|arastir)$', '', topic, flags=re.IGNORECASE)
                topic = topic.strip()

            # Derinlik belirleme
            depth = "comprehensive"
            for level, keywords in depth_keywords.items():
                if any(kw in text for kw in keywords):
                    depth = level
                    break

            if topic:
                return {
                    "action": "advanced_research",
                    "params": {
                        "topic": topic,
                        "depth": depth,
                        "include_evaluation": True
                    },
                    "reply": f"'{topic}' hakkında {depth} araştırma yapılıyor..."
                }

        # Kaynak değerlendirme
        eval_triggers = ["kaynağı değerlendir", "kaynagi degerlendir", "evaluate source", "source reliability"]

        if any(t in text for t in eval_triggers):
            url_match = re.search(r'https?://[^\s]+', text)
            if url_match:
                return {
                    "action": "evaluate_source",
                    "params": {"url": url_match.group()},
                    "reply": "Kaynak değerlendiriliyor..."
                }

        # Araştırma raporu oluşturma
        report_triggers = [
            "araştırma raporu", "arastirma raporu",
            "research report", "rapor oluştur", "rapor olustur"
        ]

        if any(t in text for t in report_triggers):
            topic = ""

            # "X konusunda araştırma raporu oluştur"
            topic_match = re.search(r'(.+?)\s+(?:konusunda|hakkında|hakkinda)\s+(?:araştırma|arastirma)?\s*rapor', text, re.IGNORECASE)
            if topic_match:
                topic = topic_match.group(1).strip()

            if not topic:
                topic_match = re.search(r'(?:rapor|report)[:\s]+(.+?)(?:oluştur|olustur|create|$)', text, re.IGNORECASE)
                if topic_match:
                    topic = topic_match.group(1).strip()

            return {
                "action": "create_research_report",
                "params": {
                    "topic": topic or "Araştırma Raporu",
                    "output_format": "markdown"
                },
                "reply": "Araştırma raporu oluşturuluyor..."
            }

        # Derin araştırma (deep_research)
        deep_research_triggers = [
            "derin araştırma", "derin arastirma", "deep research",
            "çok kaynaklı araştırma", "cok kaynakli arastirma",
            "multi-source research", "akademik düzeyde araştırma"
        ]

        if any(t in text for t in deep_research_triggers):
            topic = ""

            # Topic extraction
            topic_match = re.search(
                r'(.+?)\s+(?:hakkında|hakkinda|konusunda|üzerine)\s+(?:derin|deep|çok kaynaklı)',
                text, re.IGNORECASE
            )
            if topic_match:
                topic = topic_match.group(1).strip()

            if not topic:
                for trigger in deep_research_triggers:
                    if trigger in text:
                        parts = text.split(trigger)
                        if parts[0].strip():
                            topic = parts[0].strip()
                            topic = re.sub(r'\s*(hakkında|hakkinda|konusunda)\s*$', '', topic)
                        elif len(parts) > 1 and parts[1].strip():
                            topic = parts[1].strip()
                        break

            # Depth selection
            depth = "standard"
            if any(w in text for w in ["hızlı", "hizli", "quick"]):
                depth = "quick"
            elif any(w in text for w in ["kapsamlı", "kapsamli", "comprehensive"]):
                depth = "comprehensive"
            elif any(w in text for w in ["akademik", "academic"]):
                depth = "academic"

            if topic:
                return {
                    "action": "deep_research",
                    "params": {
                        "topic": topic,
                        "depth": depth,
                        "language": "tr",
                        "include_academic": True
                    },
                    "reply": f"'{topic}' hakkında derin araştırma başlatılıyor..."
                }

        return None

    # ==================== DOCUMENT GENERATION ====================
    def _parse_document_generation(self, text: str, text_norm: str, original: str) -> dict | None:
        """Belge oluşturma komutlarını parse et"""

        # Belge oluşturma trigger'ları
        doc_gen_triggers = [
            "belge oluştur", "belge olustur", "dokuman oluştur", "dokuman olustur",
            "generate document", "create document",
            "rapor belge", "araştırmayı belgeye", "arastirmayi belgeye",
            "word olarak kaydet", "pdf olarak kaydet", "markdown olarak kaydet",
            "html olarak kaydet"
        ]

        if any(t in text for t in doc_gen_triggers):
            # Format detection
            doc_format = "docx"
            if "pdf" in text:
                doc_format = "pdf"
            elif "html" in text:
                doc_format = "html"
            elif "markdown" in text or "md" in text:
                doc_format = "markdown"
            elif "txt" in text or "metin" in text:
                doc_format = "txt"

            # Title extraction
            title = None
            title_match = re.search(r'başlık[:\s]+(.+?)(?:\s+olarak|\s+format|$)', text, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()

            # Template detection
            template = "research_report"
            if any(w in text for w in ["özet", "ozet", "summary", "yönetici"]):
                template = "executive_summary"
            elif any(w in text for w in ["akademik", "academic", "makale"]):
                template = "academic_paper"
            elif any(w in text for w in ["iş", "is", "business"]):
                template = "business_report"

            return {
                "action": "generate_research_document",
                "params": {
                    "format": doc_format,
                    "template": template,
                    "custom_title": title,
                    "language": "tr"
                },
                "reply": f"{doc_format.upper()} belgesi oluşturuluyor..."
            }

    # ==================== WEATHER ====================
    def _parse_weather(self, text: str, text_norm: str, original: str) -> dict | None:
        weather_triggers = ["hava durumu", "hava nasıl", "sıcaklık", "hava kac derece", "gökyüzü", "yağmur", "weather"]
        
        if any(t in text for t in weather_triggers) or any(t in text_norm for t in ["hava durumu", "hava nasil"]):
            return {
                "action": "get_weather",
                "params": {},
                "reply": "Hava durumu bilgileri getiriliyor..."
            }
        return None
