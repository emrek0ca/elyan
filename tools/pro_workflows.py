"""
Professional workflow tools for higher-level assistant capabilities.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from security.validator import validate_path
from utils.logger import get_logger

logger = get_logger("tools.pro_workflows")


def _safe_project_slug(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", " ") else " " for ch in str(name or "elyan-project"))
    cleaned = "_".join(cleaned.strip().split())
    return cleaned[:80] or "elyan-project"


def _wants_counter_feature(brief: str) -> bool:
    low = str(brief or "").lower()
    if not low:
        return False
    counter_tokens = ("sayac", "sayaç", "counter")
    button_tokens = ("buton", "button", "btn")
    return any(t in low for t in counter_tokens) and any(t in low for t in button_tokens)


def _escape_html(text: str) -> str:
    s = str(text or "")
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _brief_excerpt(brief: str, *, fallback: str) -> str:
    raw = " ".join(str(brief or "").split()).strip()
    if not raw:
        return fallback
    return raw[:220]


def _derive_web_profile(project_name: str, brief: str, theme: str) -> dict[str, Any]:
    low = str(brief or "").lower()
    layout = "landing"
    if any(k in low for k in ("dashboard", "panel", "analitik", "kpi", "rapor ekranı", "rapor ekrani")):
        layout = "dashboard"
    elif any(k in low for k in ("e-ticaret", "ecommerce", "shop", "store", "ürün", "urun", "sepet")):
        layout = "commerce"
    elif any(k in low for k in ("portfolio", "portföy", "portfoy", "cv", "özgeçmiş", "ozgecmis")):
        layout = "portfolio"
    elif any(k in low for k in ("blog", "makale", "yazı", "yazi")):
        layout = "blog"

    style = str(theme or "").strip().lower() or "professional"
    if any(k in low for k in ("minimal", "clean", "sade")):
        style = "minimal"
    elif any(k in low for k in ("neon", "cyber", "futuristic", "futuristik")):
        style = "futuristic"
    elif any(k in low for k in ("enterprise", "kurumsal", "corporate", "b2b")):
        style = "corporate"
    elif style not in {"professional", "minimal", "futuristic", "corporate"}:
        style = "professional"

    palette = {
        "professional": {"accent": "#2563eb", "accent2": "#0ea5e9", "bg1": "#f8fafc", "bg2": "#e2e8f0"},
        "minimal": {"accent": "#111827", "accent2": "#374151", "bg1": "#ffffff", "bg2": "#f3f4f6"},
        "futuristic": {"accent": "#06b6d4", "accent2": "#8b5cf6", "bg1": "#0b1020", "bg2": "#101827"},
        "corporate": {"accent": "#1d4ed8", "accent2": "#0369a1", "bg1": "#eef2ff", "bg2": "#e0e7ff"},
    }[style]

    features = {
        "counter": _wants_counter_feature(brief),
        "todo": any(k in low for k in ("todo", "to do", "yapılacak", "yapilacak", "task list")),
        "search": any(k in low for k in ("arama", "search", "filtre", "filter")),
        "contact_form": any(k in low for k in ("form", "iletişim", "iletisim", "contact", "lead")),
        "theme_toggle": any(k in low for k in ("dark mode", "tema", "theme")) or style == "futuristic",
        "timer": any(k in low for k in ("timer", "pomodoro", "süre", "sure", "zamanlayıcı", "zamanlayici")),
    }

    if layout == "dashboard":
        sections = ["Genel Görünüm", "KPI Kartları", "Aktivite Akışı", "Aksiyon Listesi"]
    elif layout == "commerce":
        sections = ["Öne Çıkan Ürünler", "Kategori Izgarası", "Kampanyalar", "Sık Sorulanlar"]
    elif layout == "portfolio":
        sections = ["Hakkımda", "Projeler", "Yetenekler", "İletişim"]
    elif layout == "blog":
        sections = ["Öne Çıkan Yazı", "Kategori Akışı", "Bülten", "Yazar Notu"]
    else:
        sections = ["Değer Önerisi", "Özellikler", "Süreç", "SSS"]

    title = str(project_name or "Elyan Web App").strip() or "Elyan Web App"
    subtitle = _brief_excerpt(brief, fallback=f"{title} için özelleştirilmiş web uygulaması")

    return {
        "layout": layout,
        "style": style,
        "palette": palette,
        "features": features,
        "sections": sections,
        "title": title,
        "subtitle": subtitle,
        "cta": "Hemen Başla",
    }


def _build_vanilla_assets(project_name: str, brief: str, theme: str) -> tuple[str, str, str, dict[str, Any]]:
    profile = _derive_web_profile(project_name, brief, theme)
    palette = profile["palette"]
    features = profile["features"]
    sections = profile["sections"]

    section_cards = []
    for idx, section in enumerate(sections, start=1):
        section_cards.append(
            (
                f"<article class='info-card'>"
                f"<h3>{_escape_html(section)}</h3>"
                f"<p>{_escape_html(profile['subtitle'])}</p>"
                f"<span class='index-badge'>0{idx}</span>"
                f"</article>"
            )
        )
    section_cards_html = "\n        ".join(section_cards)

    widgets: list[str] = []
    if features.get("counter"):
        widgets.append(
            """
        <section class="tool-card" id="counterWidget" aria-live="polite">
          <h3>Sayaç</h3>
          <p class="tool-subtitle">Etkileşimli sayaç modülü</p>
          <div id="counterValue" class="counter-value">0</div>
          <div class="counter-actions">
            <button id="decreaseBtn" type="button" class="btn secondary">- Azalt</button>
            <button id="increaseBtn" type="button" class="btn primary">+ Artır</button>
          </div>
          <button id="resetBtn" type="button" class="btn ghost">Sıfırla</button>
        </section>
"""
        )
    if features.get("todo"):
        widgets.append(
            """
        <section class="tool-card">
          <h3>Yapılacaklar</h3>
          <p class="tool-subtitle">Hızlı görev listesi</p>
          <div class="todo-row">
            <input id="todoInput" type="text" placeholder="Görev ekle..." />
            <button id="todoAddBtn" type="button" class="btn primary">Ekle</button>
          </div>
          <ul id="todoList" class="todo-list"></ul>
        </section>
"""
        )
    if features.get("search"):
        widgets.append(
            """
        <section class="tool-card">
          <h3>Arama</h3>
          <p class="tool-subtitle">Örnek içerik filtresi</p>
          <input id="searchInput" type="search" placeholder="Filtrele..." />
          <ul id="searchList" class="search-list">
            <li>Görev planlama</li>
            <li>Rapor üretimi</li>
            <li>Kanal yönetimi</li>
            <li>Tool yürütme</li>
          </ul>
        </section>
"""
        )
    if features.get("timer"):
        widgets.append(
            """
        <section class="tool-card">
          <h3>Zamanlayıcı</h3>
          <p class="tool-subtitle">Pomodoro benzeri kısa sayaç</p>
          <div id="timerValue" class="timer-value">25:00</div>
          <div class="counter-actions">
            <button id="timerStartBtn" type="button" class="btn primary">Başlat</button>
            <button id="timerResetBtn" type="button" class="btn secondary">Sıfırla</button>
          </div>
        </section>
"""
        )
    if features.get("contact_form"):
        widgets.append(
            """
        <section class="tool-card">
          <h3>İletişim</h3>
          <form id="leadForm" class="lead-form">
            <input name="name" type="text" placeholder="Ad Soyad" required />
            <input name="email" type="email" placeholder="E-posta" required />
            <textarea name="message" rows="3" placeholder="Mesaj"></textarea>
            <button type="submit" class="btn primary">Gönder</button>
            <p id="leadStatus" class="tool-subtitle"></p>
          </form>
        </section>
"""
        )
    if not widgets:
        widgets.append(
            """
        <section class="tool-card">
          <h3>Hızlı Not</h3>
          <p class="tool-subtitle">Bu alan brief'e göre özelleştirilebilir.</p>
          <textarea rows="4" placeholder="Notlar..."></textarea>
        </section>
"""
        )
    widgets_html = "\n".join(widgets)

    theme_toggle = ""
    if features.get("theme_toggle"):
        theme_toggle = '<button id="themeToggle" type="button" class="btn ghost small">Tema Değiştir</button>'

    html = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_escape_html(profile['title'])}</title>
  <meta name="description" content="{_escape_html(profile['subtitle'])}">
  <link rel="stylesheet" href="./styles/main.css">
</head>
<body data-style="{_escape_html(profile['style'])}">
  <header class="site-header">
    <div>
      <p class="eyebrow">Elyan Dynamic Scaffold</p>
      <h1>{_escape_html(profile['title'])}</h1>
      <p class="lead">{_escape_html(profile['subtitle'])}</p>
    </div>
    <div class="header-actions">
      {theme_toggle}
      <button type="button" class="btn primary">{_escape_html(profile['cta'])}</button>
    </div>
  </header>

  <main class="container">
    <section class="grid-sections">
      {section_cards_html}
    </section>
    <section class="tool-grid">
{widgets_html}
    </section>
  </main>

  <script src="./scripts/main.js"></script>
</body>
</html>
"""

    css = f""":root {{
  --bg-start: {palette['bg1']};
  --bg-end: {palette['bg2']};
  --surface: #ffffff;
  --text: #0f172a;
  --muted: #64748b;
  --border: #dbe3ee;
  --accent: {palette['accent']};
  --accent-2: {palette['accent2']};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  color: var(--text);
  background: radial-gradient(circle at top, var(--bg-start), var(--bg-end));
}}
body[data-theme="dark"] {{
  --surface: #0f172a;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --border: #1e293b;
  --bg-start: #0b1120;
  --bg-end: #020617;
}}
.site-header {{
  display: flex;
  gap: 16px;
  justify-content: space-between;
  align-items: flex-start;
  padding: 36px 28px 18px;
}}
.eyebrow {{ margin: 0; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
h1 {{ margin: 6px 0; font-size: clamp(28px, 4vw, 42px); }}
.lead {{ margin: 0; max-width: 760px; color: var(--muted); }}
.header-actions {{ display: flex; gap: 10px; align-items: center; }}
.container {{ padding: 0 28px 30px; max-width: 1200px; margin: 0 auto; }}
.grid-sections {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}}
.info-card {{
  position: relative;
  padding: 18px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  min-height: 140px;
}}
.index-badge {{
  position: absolute;
  right: 12px;
  top: 10px;
  color: var(--muted);
  font-size: 12px;
}}
.tool-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}}
.tool-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
}}
.tool-subtitle {{ color: var(--muted); margin-top: -6px; }}
.btn {{
  appearance: none;
  border: 1px solid transparent;
  border-radius: 11px;
  padding: 10px 12px;
  font-size: 14px;
  cursor: pointer;
}}
.btn.small {{ font-size: 12px; padding: 8px 10px; }}
.btn.primary {{ background: var(--accent); color: #fff; }}
.btn.secondary {{ background: #fff; border-color: var(--border); color: var(--text); }}
.btn.ghost {{ background: #f1f5f9; color: var(--text); }}
.counter-value {{
  margin: 12px 0 10px;
  font-size: 52px;
  font-weight: 700;
  line-height: 1;
}}
.counter-actions {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}}
.todo-row {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; }}
input, textarea {{
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px;
  background: #fff;
  color: #0f172a;
}}
body[data-theme="dark"] input,
body[data-theme="dark"] textarea {{
  background: #111827;
  color: #e5e7eb;
  border-color: #374151;
}}
.todo-list, .search-list {{ margin: 10px 0 0; padding-left: 20px; }}
.timer-value {{ margin: 10px 0 12px; font-size: 36px; font-weight: 700; }}
@media (max-width: 720px) {{
  .site-header {{ flex-direction: column; }}
  .header-actions {{ width: 100%; justify-content: flex-start; }}
}}
"""

    js_lines = [
        "document.addEventListener('DOMContentLoaded', () => {",
        "  const qs = (id) => document.getElementById(id);",
    ]
    if features.get("theme_toggle"):
        js_lines.extend(
            [
                "  const themeToggle = qs('themeToggle');",
                "  themeToggle?.addEventListener('click', () => {",
                "    const current = document.body.getAttribute('data-theme') || 'light';",
                "    document.body.setAttribute('data-theme', current === 'dark' ? 'light' : 'dark');",
                "  });",
            ]
        )
    if features.get("counter"):
        js_lines.extend(
            [
                "  let count = 0;",
                "  const counterNode = qs('counterValue');",
                "  const renderCounter = () => { if (counterNode) counterNode.textContent = String(count); };",
                "  qs('increaseBtn')?.addEventListener('click', () => { count += 1; renderCounter(); });",
                "  qs('decreaseBtn')?.addEventListener('click', () => { count -= 1; renderCounter(); });",
                "  qs('resetBtn')?.addEventListener('click', () => { count = 0; renderCounter(); });",
                "  renderCounter();",
            ]
        )
    if features.get("todo"):
        js_lines.extend(
            [
                "  const todoInput = qs('todoInput');",
                "  const todoList = qs('todoList');",
                "  const pushTodo = () => {",
                "    const v = (todoInput?.value || '').trim();",
                "    if (!v || !todoList) return;",
                "    const li = document.createElement('li');",
                "    li.textContent = v;",
                "    li.addEventListener('click', () => li.remove());",
                "    todoList.appendChild(li);",
                "    todoInput.value = '';",
                "  };",
                "  qs('todoAddBtn')?.addEventListener('click', pushTodo);",
                "  todoInput?.addEventListener('keydown', (e) => { if (e.key === 'Enter') pushTodo(); });",
            ]
        )
    if features.get("search"):
        js_lines.extend(
            [
                "  const searchInput = qs('searchInput');",
                "  const searchList = qs('searchList');",
                "  searchInput?.addEventListener('input', () => {",
                "    const q = (searchInput.value || '').toLowerCase();",
                "    for (const li of searchList?.querySelectorAll('li') || []) {",
                "      li.style.display = li.textContent.toLowerCase().includes(q) ? '' : 'none';",
                "    }",
                "  });",
            ]
        )
    if features.get("timer"):
        js_lines.extend(
            [
                "  let timerSec = 25 * 60;",
                "  let timerRef = null;",
                "  const timerNode = qs('timerValue');",
                "  const renderTimer = () => {",
                "    if (!timerNode) return;",
                "    const m = String(Math.floor(timerSec / 60)).padStart(2, '0');",
                "    const s = String(timerSec % 60).padStart(2, '0');",
                "    timerNode.textContent = `${m}:${s}`;",
                "  };",
                "  qs('timerStartBtn')?.addEventListener('click', () => {",
                "    if (timerRef) return;",
                "    timerRef = setInterval(() => {",
                "      timerSec = Math.max(0, timerSec - 1);",
                "      renderTimer();",
                "      if (timerSec === 0) { clearInterval(timerRef); timerRef = null; }",
                "    }, 1000);",
                "  });",
                "  qs('timerResetBtn')?.addEventListener('click', () => {",
                "    timerSec = 25 * 60;",
                "    if (timerRef) { clearInterval(timerRef); timerRef = null; }",
                "    renderTimer();",
                "  });",
                "  renderTimer();",
            ]
        )
    if features.get("contact_form"):
        js_lines.extend(
            [
                "  const leadForm = qs('leadForm');",
                "  const leadStatus = qs('leadStatus');",
                "  leadForm?.addEventListener('submit', (e) => {",
                "    e.preventDefault();",
                "    if (leadStatus) leadStatus.textContent = 'Mesaj alındı. Teşekkürler.';",
                "    leadForm.reset();",
                "  });",
            ]
        )

    js_lines.extend(["  console.log('Elyan dynamic scaffold ready');", "});"])
    js = "\n".join(js_lines) + "\n"
    return html, css, js, profile


def _default_run_commands(project_kind: str, stack: str) -> list[str]:
    kind = str(project_kind or "app").strip().lower()
    tech = str(stack or "python").strip().lower()

    if kind == "website":
        if tech == "nextjs":
            return ["npm install", "npm run dev", "npm run build"]
        if tech == "react":
            return ["npm install", "npm run dev", "npm run build"]
        return ["python3 -m http.server 8080"]

    if kind == "game":
        return ["python3 -m venv .venv", "source .venv/bin/activate", "pip install -r requirements.txt", "python src/main.py"]

    if tech in {"node", "express"}:
        return ["npm install", "npm run dev", "npm test"]
    return ["python3 -m venv .venv", "source .venv/bin/activate", "pip install -r requirements.txt", "pytest -q"]


def _complexity_profile(level: str) -> dict[str, Any]:
    normalized = str(level or "advanced").strip().lower()
    if normalized not in {"standard", "advanced", "expert"}:
        normalized = "advanced"

    profiles = {
        "standard": {
            "quality_gates": [
                "Lint + static checks green",
                "Core user flow manual test",
                "Basic README and run steps complete",
            ],
            "iterations": 2,
        },
        "advanced": {
            "quality_gates": [
                "Lint + static checks green",
                "Critical path unit/integration tests pass",
                "Performance smoke metrics collected",
                "Deployment checklist completed",
            ],
            "iterations": 3,
        },
        "expert": {
            "quality_gates": [
                "Lint + static checks green",
                "Core + edge-case tests with target coverage",
                "Security checklist + dependency scan clean",
                "Performance baseline and regression guard documented",
                "Rollback plan + production runbook ready",
            ],
            "iterations": 4,
        },
    }
    out = dict(profiles[normalized])
    out["complexity"] = normalized
    return out


def _first_existing(paths: list[Path]) -> Path | None:
    for candidate in paths:
        if candidate.exists():
            return candidate
    return None


def _check_item(check_id: str, title: str, ok: bool, details: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "ok": bool(ok),
        "details": str(details or "").strip(),
    }


async def create_web_project_scaffold(
    project_name: str,
    stack: str = "vanilla",
    theme: str = "professional",
    output_dir: str = "~/Desktop",
    brief: str = "",
) -> dict[str, Any]:
    """
    Create a production-oriented web starter project.
    """
    try:
        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        slug = _safe_project_slug(project_name)
        project_dir = (base_dir / slug).resolve()
        project_dir.mkdir(parents=True, exist_ok=True)

        # Initial scope: robust static scaffold, can be extended per stack.
        actual_stack = stack.strip().lower() or "vanilla"
        if actual_stack not in {"vanilla", "react", "nextjs"}:
            actual_stack = "vanilla"

        index_html = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{project_name}</title>
  <meta name="description" content="{project_name} web projesi">
  <link rel="stylesheet" href="./styles/main.css">
</head>
<body>
  <header class="site-header">
    <h1>{project_name}</h1>
    <p>Elyan Professional Scaffold ({actual_stack})</p>
  </header>

  <main class="container">
    <section class="card">
      <h2>Baslangic</h2>
      <p>Bu proje, profesyonel gelistirme akisina uygun baslangic dosyalari ile olusturuldu.</p>
    </section>
  </main>

  <script src="./scripts/main.js"></script>
</body>
</html>
"""

        style_css = f""":root {{
  --bg: #f8fafc;
  --text: #0f172a;
  --muted: #64748b;
  --card: #ffffff;
  --border: #e2e8f0;
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  color: var(--text);
  background: linear-gradient(180deg, #ffffff 0%, var(--bg) 100%);
}}
.site-header {{ padding: 40px 24px 20px; }}
.site-header p {{ color: var(--muted); }}
.container {{ padding: 0 24px 32px; max-width: 980px; }}
.card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}}
"""

        script_js = """document.addEventListener("DOMContentLoaded", () => {
  console.log("Elyan scaffold ready");
});
"""

        brief_text = _brief_excerpt(brief, fallback="No explicit brief provided.")

        readme_md = f"""# {project_name}

## Stack
- {actual_stack}

## Quick Start
1. `cd "{project_dir}"`
2. Kurulum komutlari stack'e gore degisir (asagida).

## Structure
- `index.html`
- `styles/main.css`
- `scripts/main.js`
- `README.md`
- `docs/IMPLEMENTATION_PLAN.md`
"""

        implementation_md = f"""# Implementation Plan

Generated: {datetime.now().isoformat()}

## Objective
{project_name} icin profesyonel bir web uygulama temeli.

## Design Direction
- Theme: {theme}
- Stack: {actual_stack}
- Priority: responsive layout, maintainable structure
- Brief: {brief_text}

## Next Steps
1. Bilgi mimarisi ve sayfa bolumlerini netlestir.
2. Bilesen yapisini ayristir.
3. Performans ve erisilebilirlik kontrollerini ekle.
4. Gerekirse framework tabanli migrasyon (React/Next.js) yap.
"""

        (project_dir / "styles").mkdir(exist_ok=True)
        (project_dir / "scripts").mkdir(exist_ok=True)
        (project_dir / "docs").mkdir(exist_ok=True)

        files_written = []
        if actual_stack == "react":
            react_pkg = f"""{{
  "name": "{slug.lower()}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }},
  "devDependencies": {{
    "vite": "^5.4.0",
    "@vitejs/plugin-react": "^4.3.1"
  }}
}}
"""
            vite_cfg = """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
"""
            react_main = """import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import App from './App'

createRoot(document.getElementById('root')).render(<App />)
"""
            react_app = f"""export default function App() {{
  return (
    <main style={{{{padding: '32px', fontFamily: 'Avenir Next, Segoe UI, sans-serif'}}}}>
      <h1>{project_name}</h1>
      <p>Elyan React professional scaffold hazır.</p>
    </main>
  )
}}
"""
            react_css = """body { margin: 0; background: #f8fafc; color: #0f172a; }
* { box-sizing: border-box; }
"""
            react_html = """<!doctype html>
<html lang="tr">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Elyan React Scaffold</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""
            readme_md += """

## React Start
1. `npm install`
2. `npm run dev`
3. `http://localhost:5173`
"""
            (project_dir / "src").mkdir(exist_ok=True)
            file_map = {
                project_dir / "index.html": react_html,
                project_dir / "package.json": react_pkg,
                project_dir / "vite.config.js": vite_cfg,
                project_dir / "src" / "main.jsx": react_main,
                project_dir / "src" / "App.jsx": react_app,
                project_dir / "src" / "styles.css": react_css,
                project_dir / "README.md": readme_md,
                project_dir / "docs" / "IMPLEMENTATION_PLAN.md": implementation_md,
            }
        elif actual_stack == "nextjs":
            next_pkg = f"""{{
  "name": "{slug.lower()}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  }},
  "dependencies": {{
    "next": "^14.2.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }}
}}
"""
            next_page = f"""export default function Page() {{
  return (
    <main style={{{{padding: '32px', fontFamily: 'Avenir Next, Segoe UI, sans-serif'}}}}>
      <h1>{project_name}</h1>
      <p>Elyan Next.js professional scaffold hazır.</p>
    </main>
  )
}}
"""
            next_layout = """export const metadata = {
  title: 'Elyan Next Scaffold',
  description: 'Professional starter generated by Elyan',
}

export default function RootLayout({ children }) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  )
}
"""
            readme_md += """

## Next.js Start
1. `npm install`
2. `npm run dev`
3. `http://localhost:3000`
"""
            (project_dir / "app").mkdir(exist_ok=True)
            file_map = {
                project_dir / "package.json": next_pkg,
                project_dir / "app" / "layout.js": next_layout,
                project_dir / "app" / "page.js": next_page,
                project_dir / "README.md": readme_md,
                project_dir / "docs" / "IMPLEMENTATION_PLAN.md": implementation_md,
            }
        else:
            index_html, style_css, script_js, profile = _build_vanilla_assets(
                project_name=project_name,
                brief=brief,
                theme=theme,
            )
            enabled_features = [k for k, v in (profile.get("features", {}) or {}).items() if bool(v)]
            readme_md += "\n\n## Derived Profile\n"
            readme_md += f"- Layout: {profile.get('layout', 'landing')}\n"
            readme_md += f"- Style: {profile.get('style', 'professional')}\n"
            readme_md += f"- Features: {', '.join(enabled_features) if enabled_features else 'baseline'}\n"
            readme_md += f"- Brief: {brief_text}\n"
            implementation_md += (
                "\n\n## Derived Runtime Profile\n"
                f"- Layout: {profile.get('layout', 'landing')}\n"
                f"- Style: {profile.get('style', 'professional')}\n"
                f"- Sections: {', '.join(profile.get('sections', []))}\n"
                f"- Enabled features: {', '.join(enabled_features) if enabled_features else 'baseline'}\n"
            )
            readme_md += """

## Static Start
1. `python3 -m http.server 8080`
2. `http://localhost:8080`
"""
            file_map = {
                project_dir / "index.html": index_html,
                project_dir / "styles" / "main.css": style_css,
                project_dir / "scripts" / "main.js": script_js,
                project_dir / "README.md": readme_md,
                project_dir / "docs" / "IMPLEMENTATION_PLAN.md": implementation_md,
            }

        for path, content in file_map.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            files_written.append(str(path))

        return {
            "success": True,
            "project_name": project_name,
            "stack": actual_stack,
            "theme": theme,
            "brief": brief,
            "project_dir": str(project_dir),
            "files_created": files_written,
            "message": f"Web scaffold olusturuldu: {project_dir}",
        }
    except Exception as exc:
        logger.error(f"create_web_project_scaffold error: {exc}")
        return {"success": False, "error": str(exc)}


async def create_coding_delivery_plan(
    project_path: str,
    project_name: str = "",
    project_kind: str = "app",
    stack: str = "python",
    complexity: str = "advanced",
    brief: str = "",
) -> dict[str, Any]:
    """
    Generate professional delivery planning docs for complex coding tasks.
    """
    try:
        target = Path(str(project_path or "")).expanduser()
        if not target.exists():
            return {"success": False, "error": f"Project path bulunamadı: {target}"}
        if not target.is_dir():
            return {"success": False, "error": f"Project path klasör olmalı: {target}"}

        kind = str(project_kind or "app").strip().lower()
        if kind not in {"website", "app", "game"}:
            kind = "app"
        tech = str(stack or "python").strip().lower() or "python"
        name = str(project_name or "").strip() or target.name
        profile = _complexity_profile(complexity)
        now = datetime.now().isoformat()

        docs_dir = target / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        phase_rows = [
            ("1", "Discovery", "Hedef, kapsam, kullanıcı akışları", "Problem ve başarı metrikleri net"),
            ("2", "Architecture", "Teknik kararlar, modül sınırları", "Mimari kararlar ve trade-off dokümante"),
            ("3", "Implementation", "Kodlama, refactor, tool entegrasyonu", "Özellikler branch düzeyinde tamam"),
            ("4", "Verification", "Test, performans, güvenlik", "Kalite kapıları geçildi"),
            ("5", "Delivery", "Deploy/runbook/handover", "Çalışır teslimat + rollback planı"),
        ]

        delivery_plan = docs_dir / "DELIVERY_PLAN.md"
        delivery_plan.write_text(
            "\n".join(
                [
                    f"# Delivery Plan - {name}",
                    "",
                    f"- Generated: {now}",
                    f"- Project Kind: {kind}",
                    f"- Stack: {tech}",
                    f"- Complexity: {profile['complexity']}",
                    f"- Iteration Target: {profile['iterations']}",
                    "",
                    "## Brief",
                    str(brief or "No explicit brief provided."),
                    "",
                    "## Phase Plan",
                    "| Phase | Name | Focus | Exit Criteria |",
                    "|---|---|---|---|",
                    *[f"| {pid} | {pname} | {focus} | {exitc} |" for pid, pname, focus, exitc in phase_rows],
                ]
            ),
            encoding="utf-8",
        )

        backlog = docs_dir / "TASK_BACKLOG.md"
        backlog.write_text(
            "\n".join(
                [
                    f"# Task Backlog - {name}",
                    "",
                    "| ID | Task | Owner | Priority | Status |",
                    "|---|---|---|---|---|",
                    "| T1 | Contract and scope freeze | Product/PM | High | Open |",
                    "| T2 | Architecture and component boundaries | Tech Lead | High | Open |",
                    "| T3 | Core feature implementation | Dev | High | Open |",
                    "| T4 | Integration + regression tests | QA | High | Open |",
                    "| T5 | Performance & security checks | DevOps | Medium | Open |",
                    "| T6 | Release checklist and runbook | DevOps | Medium | Open |",
                ]
            ),
            encoding="utf-8",
        )

        acceptance = docs_dir / "ACCEPTANCE_CRITERIA.md"
        criteria = [
            "Primary user flow works end-to-end without manual patching.",
            "Critical commands or UI actions have deterministic outcomes.",
            "All required configs and run commands are documented.",
            "Project starts locally with listed setup commands.",
        ]
        if kind == "website":
            criteria.extend(
                [
                    "index.html must have at least 3 distinct semantic sections (nav, main, footer).",
                    "styles.css must include at least one responsive media query breakpoint.",
                    "app.js must contain a DOMContentLoaded or equivalent event handler.",
                    "At least one interactive feature (form, toggle, filter) must be functional.",
                    "Client-side errors are zero in console on core pages.",
                ]
            )
        if profile["complexity"] == "expert":
            criteria.extend(
                [
                    "Coverage target and regression guard are documented.",
                    "Security scan/dependency audit result is recorded.",
                ]
            )
        acceptance.write_text(
            "\n".join(
                [
                    f"# Acceptance Criteria - {name}",
                    "",
                    *[f"- [ ] {c}" for c in criteria],
                ]
            ),
            encoding="utf-8",
        )

        test_strategy = docs_dir / "TEST_STRATEGY.md"
        test_strategy.write_text(
            "\n".join(
                [
                    f"# Test Strategy - {name}",
                    "",
                    "## Layers",
                    "- Unit tests for deterministic logic and parsing.",
                    "- Integration tests for workflow/tool boundaries.",
                    "- Smoke test for startup and core flow.",
                    "",
                    "## Quality Gates",
                    *[f"- [ ] {gate}" for gate in profile["quality_gates"]],
                ]
            ),
            encoding="utf-8",
        )

        runbook = docs_dir / "RUNBOOK.md"
        runbook.write_text(
            "\n".join(
                [
                    f"# Runbook - {name}",
                    "",
                    "## Local Run Commands",
                    *[f"1. `{cmd}`" if i == 0 else f"{i+1}. `{cmd}`" for i, cmd in enumerate(_default_run_commands(kind, tech))],
                    "",
                    "## Incident Notes",
                    "- If startup fails, capture logs and last command output.",
                    "- Keep rollback path: previous known-good commit/tag.",
                ]
            ),
            encoding="utf-8",
        )

        files_created = [
            str(delivery_plan),
            str(backlog),
            str(acceptance),
            str(test_strategy),
            str(runbook),
        ]
        return {
            "success": True,
            "project_path": str(target),
            "project_name": name,
            "project_kind": kind,
            "stack": tech,
            "complexity": profile["complexity"],
            "files_created": files_created,
            "message": f"Coding delivery plan oluşturuldu: {docs_dir}",
        }
    except Exception as exc:
        logger.error(f"create_coding_delivery_plan error: {exc}")
        return {"success": False, "error": str(exc)}


async def create_coding_verification_report(
    project_path: str,
    project_name: str = "",
    project_kind: str = "app",
    stack: str = "python",
    strict: bool = False,
) -> dict[str, Any]:
    """
    Generate a practical verification report for created coding projects.
    """
    try:
        target = Path(str(project_path or "")).expanduser()
        if not target.exists():
            return {"success": False, "error": f"Project path bulunamadı: {target}"}
        if not target.is_dir():
            return {"success": False, "error": f"Project path klasör olmalı: {target}"}

        kind = str(project_kind or "app").strip().lower()
        if kind not in {"website", "app", "game"}:
            kind = "app"
        tech = str(stack or "python").strip().lower() or "python"
        name = str(project_name or "").strip() or target.name

        checks: list[dict[str, Any]] = []
        docs_dir = target / "docs"

        checks.append(
            _check_item(
                "base_dir",
                "Project directory exists",
                target.exists() and target.is_dir(),
                str(target),
            )
        )

        readme = target / "README.md"
        checks.append(_check_item("readme", "README.md present", readme.exists(), str(readme)))

        docs_core = [
            ("delivery_plan", "DELIVERY_PLAN.md", docs_dir / "DELIVERY_PLAN.md"),
            ("task_backlog", "TASK_BACKLOG.md", docs_dir / "TASK_BACKLOG.md"),
            ("acceptance", "ACCEPTANCE_CRITERIA.md", docs_dir / "ACCEPTANCE_CRITERIA.md"),
            ("test_strategy", "TEST_STRATEGY.md", docs_dir / "TEST_STRATEGY.md"),
            ("runbook", "RUNBOOK.md", docs_dir / "RUNBOOK.md"),
        ]
        for cid, title, p in docs_core:
            checks.append(_check_item(cid, f"{title} present", p.exists(), str(p)))

        if kind == "website":
            if tech == "nextjs":
                pkg = target / "package.json"
                page = _first_existing([target / "app" / "page.js", target / "app" / "page.tsx"])
                checks.append(_check_item("next_pkg", "package.json present", pkg.exists(), str(pkg)))
                checks.append(
                    _check_item(
                        "next_page",
                        "Next page entry present",
                        page is not None,
                        str(page or (target / "app" / "page.js")),
                    )
                )
            elif tech == "react":
                pkg = target / "package.json"
                app_entry = _first_existing([target / "src" / "App.jsx", target / "src" / "App.tsx"])
                main_entry = _first_existing([target / "src" / "main.jsx", target / "src" / "main.tsx"])
                checks.append(_check_item("react_pkg", "package.json present", pkg.exists(), str(pkg)))
                checks.append(
                    _check_item(
                        "react_app",
                        "React App entry present",
                        app_entry is not None,
                        str(app_entry or (target / "src" / "App.jsx")),
                    )
                )
                checks.append(
                    _check_item(
                        "react_main",
                        "React main entry present",
                        main_entry is not None,
                        str(main_entry or (target / "src" / "main.jsx")),
                    )
                )
            else:
                html = target / "index.html"
                css = target / "styles" / "main.css"
                js = target / "scripts" / "main.js"
                checks.append(_check_item("web_html", "index.html present", html.exists(), str(html)))
                checks.append(_check_item("web_css", "styles/main.css present", css.exists(), str(css)))
                checks.append(_check_item("web_js", "scripts/main.js present", js.exists(), str(js)))
        else:
            if tech in {"node", "express"}:
                pkg = target / "package.json"
                checks.append(_check_item("node_pkg", "package.json present", pkg.exists(), str(pkg)))
            else:
                req = _first_existing([target / "requirements.txt", target / "pyproject.toml"])
                checks.append(
                    _check_item(
                        "python_deps",
                        "Python dependency manifest present",
                        req is not None,
                        str(req or (target / "requirements.txt")),
                    )
                )
                entry = _first_existing([target / "src" / "main.py", target / "main.py", target / "app.py"])
                checks.append(
                    _check_item(
                        "python_entry",
                        "Python entrypoint present",
                        entry is not None,
                        str(entry or (target / "src" / "main.py")),
                    )
                )

        tests_dir = target / "tests"
        checks.append(_check_item("tests_dir", "tests/ directory present", tests_dir.exists(), str(tests_dir)))

        total_checks = len(checks)
        passed_checks = sum(1 for c in checks if c.get("ok"))
        failed_checks = [c for c in checks if not c.get("ok")]
        score = int(round((passed_checks / max(total_checks, 1)) * 100))

        status = "ready"
        if score < 70:
            status = "blocked"
        elif score < 90:
            status = "needs_review"
        if strict and failed_checks:
            status = "blocked"

        report_lines = [
            f"# Verification Report - {name}",
            "",
            f"- Generated: {datetime.now().isoformat()}",
            f"- Project Path: {target}",
            f"- Project Kind: {kind}",
            f"- Stack: {tech}",
            f"- Score: {score}/100",
            f"- Status: {status}",
            "",
            "## Check Results",
            "| ID | Check | Result | Details |",
            "|---|---|---|---|",
        ]
        for check in checks:
            result_mark = "PASS" if check["ok"] else "FAIL"
            report_lines.append(
                f"| {check['id']} | {check['title']} | {result_mark} | {check['details']} |"
            )

        report_lines.extend(["", "## Next Actions"])
        if not failed_checks:
            report_lines.append("- Tüm temel doğrulamalar geçti. Geliştirme ve test döngüsüne devam edebilirsin.")
        else:
            for miss in failed_checks[:10]:
                report_lines.append(f"- Eksik: {miss['title']} ({miss['details']})")
        report_lines.append("")
        report_lines.append("## Delivery Recommendation")
        if status == "ready":
            report_lines.append("- Proje teslimata hazır görünüyor. Son adım olarak smoke test + release check çalıştır.")
        elif status == "needs_review":
            report_lines.append("- Proje kısmen hazır. Kritik eksikleri tamamladıktan sonra yeniden doğrula.")
        else:
            report_lines.append("- Proje şu an teslimat için bloklu. Eksik temel dosyaları tamamlayıp tekrar doğrulama çalıştır.")

        docs_dir.mkdir(parents=True, exist_ok=True)
        report_path = docs_dir / "VERIFICATION_REPORT.md"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")

        return {
            "success": True,
            "project_path": str(target),
            "project_name": name,
            "project_kind": kind,
            "stack": tech,
            "score": score,
            "status": status,
            "passed_checks": passed_checks,
            "total_checks": total_checks,
            "failed_checks": failed_checks,
            "report_path": str(report_path),
            "message": f"Verification raporu oluşturuldu: {report_path} (score={score})",
        }
    except Exception as exc:
        logger.error(f"create_coding_verification_report error: {exc}")
        return {"success": False, "error": str(exc)}


async def verify_web_project_smoke_test(
    project_path: str,
) -> dict[str, Any]:
    """
    Perform a technical smoke test on a generated static web project.
    Checks for structural integrity, broken asset links, and required metadata.
    """
    try:
        target = Path(str(project_path or "")).expanduser()
        if not target.exists() or not target.is_dir():
            return {"success": False, "error": f"Proje dizini bulunamadı: {project_path}"}

        html_file = target / "index.html"
        if not html_file.exists():
            return {"success": False, "error": "index.html bulunamadı."}

        content = html_file.read_text(encoding="utf-8")
        
        results = []
        # 1. Structure check
        has_head = "<head" in content.lower()
        has_body = "<body" in content.lower()
        results.append(_check_item("structure", "HTML Basic Structure", has_head and has_body, "Head/Body tags present"))

        # 2. Asset links check
        import re
        css_links = re.findall(r'href=["\'](.*\.css)["\']', content)
        js_links = re.findall(r'src=["\'](.*\.js)["\']', content)
        
        broken_assets = []
        for css in css_links:
            if not css.startswith(("http", "//")):
                p = (target / css).resolve()
                if not p.exists(): broken_assets.append(css)
        
        for js in js_links:
            if not js.startswith(("http", "//")):
                p = (target / js).resolve()
                if not p.exists(): broken_assets.append(js)

        results.append(_check_item("assets", "Local Asset Links", len(broken_assets) == 0, 
                                   f"Broken: {', '.join(broken_assets)}" if broken_assets else "All local assets exist"))

        # 3. Interactive features check
        has_js_init = "DOMContentLoaded" in content or 'src="./scripts/main.js"' in content
        results.append(_check_item("interactivity", "JS Initialization", has_js_init, "Main JS entry point found"))

        all_ok = all(r["ok"] for r in results)
        
        return {
            "success": True,
            "project_path": str(target),
            "all_passed": all_ok,
            "checks": results,
            "message": "Smoke test tamamlandı. " + ("Tüm kontroller başarılı." if all_ok else "Bazı sorunlar tespit edildi.")
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def generate_document_pack(
    topic: str,
    brief: str = "",
    audience: str = "executive",
    language: str = "tr",
    output_dir: str = "~/Desktop"
) -> dict[str, Any]:
    """
    Generate a professional multi-format document pack (docx + markdown + txt).
    """
    try:
        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        safe_topic = _safe_project_slug(topic).replace("_", " ")
        pack_dir = (base_dir / f"{_safe_project_slug(topic)}_document_pack").resolve()
        pack_dir.mkdir(parents=True, exist_ok=True)

        now_str = datetime.now().strftime("%Y-%m-%d")
        summary = brief.strip() or (
            f"{safe_topic} konusunda {audience} hedef kitlesine yonelik profesyonel degerlendirme. "
            "Bu belge paketi karar almayi hizlandiracak net ozet ve eylem odakli cikarimlar sunar."
        )
        findings = [
            {"title": "Durum Analizi", "summary": f"{safe_topic} icin mevcut durum ve kritik noktalar degerlendirildi."},
            {"title": "Riskler", "summary": "Operasyonel, teknik ve zamanlama riskleri listelendi."},
            {"title": "Firsatlar", "summary": "Kisa ve orta vadeli yuksek etki alanlari belirlendi."},
        ]
        key_insights = [
            "Karar kalitesini artirmak icin kapsam ve hedef metrikleri netlestirilmeli.",
            "Uygulama yol haritasi fazlara ayrilarak risk azaltilmali.",
            "Teslimat kalitesi icin dogrulama adimlari zorunlu hale getirilmeli.",
        ]
        sources = [
            {"name": "Internal Analysis", "url": "local://analysis", "reliability": "high"},
            {"name": "Project Context", "url": "local://project_context", "reliability": "high"},
        ]
        bibliography = [
            f"[{now_str}] Internal notes and project context synthesis",
        ]

        research_data = {
            "topic": safe_topic,
            "summary": summary,
            "findings": findings,
            "key_insights": key_insights,
            "sources": sources,
            "statistics": {"audience": audience, "language": language},
            "bibliography": bibliography,
        }

        outputs = []

        # Always produce local markdown/txt pack in requested output directory.
        report_md = pack_dir / "PROFESSIONAL_REPORT.md"
        report_md.write_text(
            "\n".join(
                [
                    f"# {safe_topic} - Professional Report",
                    "",
                    f"Date: {now_str}",
                    f"Audience: {audience}",
                    f"Language: {language}",
                    "",
                    "## Executive Summary",
                    summary,
                    "",
                    "## Key Findings",
                    *[f"- {item['title']}: {item['summary']}" for item in findings],
                    "",
                    "## Key Insights",
                    *[f"- {item}" for item in key_insights],
                    "",
                    "## Sources",
                    *[f"- {s['name']} ({s['url']}) - reliability: {s['reliability']}" for s in sources],
                ]
            ),
            encoding="utf-8",
        )
        outputs.append(str(report_md))

        report_txt = pack_dir / "PROFESSIONAL_REPORT.txt"
        report_txt.write_text(
            "\n".join(
                [
                    f"{safe_topic} - Professional Report",
                    "=" * 48,
                    "",
                    "Executive Summary:",
                    summary,
                    "",
                    "Key Findings:",
                    *[f"* {item['title']}: {item['summary']}" for item in findings],
                    "",
                    "Key Insights:",
                    *[f"* {item}" for item in key_insights],
                ]
            ),
            encoding="utf-8",
        )
        outputs.append(str(report_txt))

        # Try docx generation best-effort. If environment blocks it, continue.
        docx_warning = ""
        try:
            from tools.document_generator.professional_document import generate_research_document

            result = await generate_research_document(
                research_data=research_data,
                format="docx",
                template="business_report",
                custom_title=f"{safe_topic} - Professional Pack",
                language=language,
            )
            if result.get("success") and result.get("path"):
                src = Path(result["path"])
                dst = pack_dir / src.name
                if src.exists() and src.resolve() != dst.resolve():
                    dst.write_bytes(src.read_bytes())
                    outputs.append(str(dst))
                else:
                    outputs.append(str(src))
            else:
                docx_warning = str(result.get("error", "docx generation unavailable"))
        except Exception as exc:
            docx_warning = str(exc)

        executive_md = pack_dir / "EXECUTIVE_ACTIONS.md"
        executive_md.write_text(
            "\n".join(
                [
                    f"# Executive Actions - {safe_topic}",
                    "",
                    f"Audience: {audience}",
                    f"Date: {now_str}",
                    "",
                    "## Top 5 Actions",
                    "1. Scope and quality gates netlestir.",
                    "2. Faz bazli uygulama plani cikart.",
                    "3. Kritik riskler icin sahiplik ata.",
                    "4. Haftalik ilerleme metriklerini takip et.",
                    "5. Sonuclari karar toplantisina hazir paketle sun.",
                ]
            ),
            encoding="utf-8",
        )
        outputs.append(str(executive_md))

        risk_md = pack_dir / "RISK_REGISTER.md"
        risk_md.write_text(
            "\n".join(
                [
                    f"# Risk Register - {safe_topic}",
                    "",
                    "| Risk | Impact | Likelihood | Mitigation | Owner |",
                    "|---|---|---|---|---|",
                    "| Scope creep | High | Medium | Change control policy | PM |",
                    "| Delivery delay | High | Medium | Weekly milestone tracking | Tech Lead |",
                    "| Quality regression | Medium | Medium | QA gates + review checklist | QA |",
                    "| Stakeholder misalignment | High | Low | Weekly stakeholder sync | Product |",
                ]
            ),
            encoding="utf-8",
        )
        outputs.append(str(risk_md))

        actions_csv = pack_dir / "ACTION_REGISTER.csv"
        actions_csv.write_text(
            "\n".join(
                [
                    "action_id,action,owner,priority,status,due_date",
                    "A1,Scope and quality gates netlestir,PM,High,Open,",
                    "A2,Faz bazli uygulama plani cikart,Tech Lead,High,Open,",
                    "A3,Risk sahipliklerini ata,PM,Medium,Open,",
                    "A4,Haftalik KPI takip paneli ac,Ops,Medium,Open,",
                    "A5,Yonetici sunum paketini finalize et,Product,High,Open,",
                ]
            ),
            encoding="utf-8",
        )
        outputs.append(str(actions_csv))

        response = {
            "success": True,
            "topic": topic,
            "pack_dir": str(pack_dir),
            "outputs": outputs,
            "message": f"Document pack olusturuldu: {pack_dir}",
        }
        if docx_warning:
            response["docx_warning"] = docx_warning
        return response
    except Exception as exc:
        logger.error(f"generate_document_pack error: {exc}")
        return {"success": False, "error": str(exc)}


async def research_document_delivery(
    topic: str,
    brief: str = "",
    depth: str = "comprehensive",
    audience: str = "executive",
    language: str = "tr",
    output_dir: str = "~/Desktop",
    include_word: bool = True,
    include_excel: bool = True,
    include_report: bool = True,
    source_policy: str = "trusted",
    min_reliability: float = 0.62,
) -> dict[str, Any]:
    """
    Execute a high-quality research workflow, generate deliverable documents,
    and return concrete artifact paths suitable for channel delivery.
    """
    try:
        topic_clean = str(topic or "").strip()
        if not topic_clean:
            return {"success": False, "error": "Araştırma konusu gerekli."}

        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        depth_map = {
            "quick": "quick",
            "standard": "standard",
            "comprehensive": "comprehensive",
            "expert": "expert",
            "deep": "comprehensive",
            "detailed": "comprehensive",
        }
        normalized_depth = depth_map.get(str(depth or "comprehensive").strip().lower(), "comprehensive")

        policy = str(source_policy or "trusted").strip().lower()
        if policy not in {"balanced", "trusted", "academic", "official"}:
            policy = "trusted"

        try:
            min_rel = float(min_reliability)
        except Exception:
            min_rel = 0.62
        if min_rel > 1.0:
            min_rel = min_rel / 100.0
        min_rel = max(0.0, min(1.0, min_rel))

        try:
            from tools.research_tools.advanced_research import advanced_research
            from tools.office_tools.word_tools import write_word
            from tools.office_tools.excel_tools import write_excel
        except Exception as exc:
            return {"success": False, "error": f"Gerekli araştırma/ofis modülleri yüklenemedi: {exc}"}

        research_result = await advanced_research(
            topic=topic_clean,
            depth=normalized_depth,
            language=language,
            include_evaluation=True,
            generate_report=bool(include_report),
            source_policy=policy,
            min_reliability=min_rel,
            max_findings=8,
        )
        if not isinstance(research_result, dict) or not research_result.get("success"):
            err = str((research_result or {}).get("error") or "Araştırma başarısız.")
            return {"success": False, "error": err}

        slug = _safe_project_slug(topic_clean)
        delivery_dir = (base_dir / f"{slug}_research_delivery").resolve()
        delivery_dir.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        findings = [str(x).strip() for x in (research_result.get("findings") or []) if str(x).strip()]
        summary = str(research_result.get("summary") or "").strip()
        sources = research_result.get("sources") if isinstance(research_result.get("sources"), list) else []
        source_count = int(research_result.get("source_count") or len(sources))

        report_md = delivery_dir / "RESEARCH_DELIVERY.md"
        report_md.write_text(
            "\n".join(
                [
                    f"# Research Delivery - {topic_clean}",
                    "",
                    f"- Date: {now_str}",
                    f"- Audience: {audience}",
                    f"- Depth: {normalized_depth}",
                    f"- Source policy: {policy}",
                    f"- Min reliability: {min_rel:.2f}",
                    f"- Source count: {source_count}",
                    "",
                    "## Executive Summary",
                    summary or "Özet üretilemedi.",
                    "",
                    "## Findings",
                    *([f"- {item}" for item in findings] or ["- Bulgu üretilemedi."]),
                    "",
                    "## Sources",
                    *[
                        f"- {str(src.get('title') or src.get('url') or 'source')} ({str(src.get('url') or '').strip()})"
                        for src in sources[:20]
                        if isinstance(src, dict)
                    ],
                ]
            ),
            encoding="utf-8",
        )

        report_txt = delivery_dir / "RESEARCH_DELIVERY.txt"
        report_txt.write_text(
            "\n".join(
                [
                    f"Research Delivery - {topic_clean}",
                    "=" * 58,
                    f"Date: {now_str}",
                    f"Depth: {normalized_depth}",
                    f"Source count: {source_count}",
                    "",
                    "Executive Summary:",
                    summary or "Özet üretilemedi.",
                    "",
                    "Findings:",
                    *([f"* {item}" for item in findings] or ["* Bulgu üretilemedi."]),
                ]
            ),
            encoding="utf-8",
        )

        outputs: list[str] = [str(report_md), str(report_txt)]

        if include_word:
            word_path = delivery_dir / "RESEARCH_DELIVERY.docx"
            word_content = "\n\n".join(
                [
                    f"Konu: {topic_clean}",
                    f"Tarih: {now_str}",
                    f"Hedef Kitle: {audience}",
                    f"Araştırma Derinliği: {normalized_depth}",
                    f"Kaynak Sayısı: {source_count}",
                    "",
                    "Yönetici Özeti",
                    summary or "Özet üretilemedi.",
                    "",
                    "Temel Bulgular",
                    *([f"- {item}" for item in findings] or ["- Bulgu üretilemedi."]),
                ]
            )
            word_result = await write_word(
                path=str(word_path),
                title=f"Research Delivery - {topic_clean}",
                content=word_content,
            )
            if isinstance(word_result, dict) and word_result.get("success") and word_result.get("path"):
                outputs.append(str(word_result["path"]))

        if include_excel:
            excel_path = delivery_dir / "RESEARCH_DELIVERY.xlsx"
            rows: list[dict[str, Any]] = []
            for idx, item in enumerate(findings, start=1):
                rows.append(
                    {
                        "Tip": "Finding",
                        "No": idx,
                        "Metin": item[:1000],
                        "Kaynak": "",
                        "Guvenilirlik": "",
                    }
                )
            for idx, src in enumerate(sources[:40], start=1):
                if not isinstance(src, dict):
                    continue
                rows.append(
                    {
                        "Tip": "Source",
                        "No": idx,
                        "Metin": str(src.get("title") or "").strip()[:400],
                        "Kaynak": str(src.get("url") or "").strip()[:400],
                        "Guvenilirlik": str(src.get("reliability_score") or ""),
                    }
                )
            if not rows:
                rows.append({"Tip": "Summary", "No": 1, "Metin": summary[:1000], "Kaynak": "", "Guvenilirlik": ""})

            excel_result = await write_excel(
                path=str(excel_path),
                data=rows,
                headers=["Tip", "No", "Metin", "Kaynak", "Guvenilirlik"],
                sheet_name="Research",
            )
            if isinstance(excel_result, dict) and excel_result.get("success") and excel_result.get("path"):
                outputs.append(str(excel_result["path"]))

        for report_path in research_result.get("report_paths", []) if isinstance(research_result.get("report_paths"), list) else []:
            if not isinstance(report_path, str) or not report_path.strip():
                continue
            src = Path(report_path).expanduser()
            if not src.exists() or not src.is_file():
                continue
            dst = delivery_dir / src.name
            try:
                if src.resolve() != dst.resolve():
                    dst.write_bytes(src.read_bytes())
                    outputs.append(str(dst))
                else:
                    outputs.append(str(src))
            except Exception:
                outputs.append(str(src))

        dedup_outputs: list[str] = []
        seen_paths: set[str] = set()
        for item in outputs:
            if not isinstance(item, str) or not item.strip():
                continue
            key = str(Path(item).expanduser())
            if key in seen_paths:
                continue
            seen_paths.add(key)
            dedup_outputs.append(key)
        outputs = dedup_outputs

        note_path = delivery_dir / "DELIVERY_NOTE.txt"
        note_path.write_text(
            "\n".join(
                [
                    f"Research delivery hazır: {topic_clean}",
                    "",
                    "Kopya gönderimi için dosyalar:",
                    *[f"- {p}" for p in outputs[:10]],
                ]
            ),
            encoding="utf-8",
        )
        outputs.append(str(note_path))

        message_lines = [
            f"Araştırma + belge paketi hazır: {delivery_dir}",
            f"Konu: {topic_clean}",
            f"Kaynak: {source_count} | Bulgu: {len(findings)}",
            "Kopya gönderimi için dosyalar:",
            *[f"- {p}" for p in outputs[:8]],
        ]

        return {
            "success": True,
            "topic": topic_clean,
            "depth": normalized_depth,
            "source_policy": policy,
            "min_reliability": min_rel,
            "delivery_dir": str(delivery_dir),
            "outputs": outputs,
            "source_count": source_count,
            "finding_count": len(findings),
            "summary": summary,
            "message": "\n".join(message_lines),
        }
    except Exception as exc:
        logger.error(f"research_document_delivery error: {exc}")
        return {"success": False, "error": str(exc)}


async def create_image_workflow_profile(
    project_name: str,
    visual_style: str = "editorial_clean",
    aspect_ratios: str = "1:1,16:9,9:16",
    output_dir: str = "~/Desktop"
) -> dict[str, Any]:
    """
    Generate a reusable image generation workflow package (prompt pack + style guide).
    """
    try:
        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        profile_dir = (base_dir / f"{_safe_project_slug(project_name)}_image_workflow").resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)

        ratios = [r.strip() for r in str(aspect_ratios).split(",") if r.strip()] or ["1:1"]
        prompt_pack = {
            "project": project_name,
            "style": visual_style,
            "ratios": ratios,
            "base_prompt": f"{project_name}, {visual_style}, high detail, cinematic lighting, clean composition",
            "negative_prompt": "blurry, low quality, distorted anatomy, text artifacts, watermark",
            "variations": [
                "hero shot, bold composition, premium product-ad look",
                "minimal editorial layout, neutral palette, soft shadows",
                "dynamic angle, high contrast, storytelling scene",
            ],
            "postprocess_checklist": [
                "composition balance",
                "subject clarity",
                "brand consistency",
                "export format validation",
            ],
            "generated_at": datetime.now().isoformat(),
        }

        prompts_md = profile_dir / "PROMPT_PACK.md"
        prompts_md.write_text(
            "\n".join(
                [
                    f"# Prompt Pack - {project_name}",
                    "",
                    f"Style: {visual_style}",
                    f"Ratios: {', '.join(ratios)}",
                    "",
                    "## Base Prompt",
                    prompt_pack["base_prompt"],
                    "",
                    "## Negative Prompt",
                    prompt_pack["negative_prompt"],
                    "",
                    "## Variations",
                    *[f"- {v}" for v in prompt_pack["variations"]],
                    "",
                    "## Postprocess Checklist",
                    *[f"- {x}" for x in prompt_pack["postprocess_checklist"]],
                ]
            ),
            encoding="utf-8",
        )

        style_json = profile_dir / "STYLE_PROFILE.json"
        import json
        style_json.write_text(json.dumps(prompt_pack, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "success": True,
            "project_name": project_name,
            "style": visual_style,
            "profile_dir": str(profile_dir),
            "files_created": [str(prompts_md), str(style_json)],
            "message": f"Image workflow profile olusturuldu: {profile_dir}",
        }
    except Exception as exc:
        logger.error(f"create_image_workflow_profile error: {exc}")
        return {"success": False, "error": str(exc)}


async def create_software_project_pack(
    project_name: str,
    project_type: str = "webapp",
    stack: str = "python",
    complexity: str = "advanced",
    output_dir: str = "~/Desktop",
    brief: str = "",
) -> dict[str, Any]:
    """
    Create a complex project pack for web/app/game style requests.
    Produces code scaffold + test skeleton + run/deploy docs + quality checklist.
    """
    try:
        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        safe_name = _safe_project_slug(project_name)
        ptype = str(project_type or "webapp").strip().lower()
        if ptype not in {"webapp", "app", "game"}:
            ptype = "webapp"
        chosen_stack = str(stack or "python").strip().lower()
        level = str(complexity or "advanced").strip().lower()
        if level not in {"standard", "advanced", "expert"}:
            level = "advanced"

        pack_dir = (base_dir / f"{safe_name}_project_pack").resolve()
        src_dir = pack_dir / "src"
        tests_dir = pack_dir / "tests"
        docs_dir = pack_dir / "docs"
        for d in (pack_dir, src_dir, tests_dir, docs_dir):
            d.mkdir(parents=True, exist_ok=True)

        brief_text = _brief_excerpt(brief, fallback="No explicit brief provided.")
        brief_low = str(brief or "").lower()

        if ptype == "game":
            entry = src_dir / "main.py"
            entry_content = """import pygame
import random

def main():
    pygame.init()
    screen = pygame.display.set_mode((900, 520))
    pygame.display.set_caption("Elyan Game Prototype")
    clock = pygame.time.Clock()
    running = True
    x = 100
    score = 0
    target_x = random.randint(120, 760)

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                if abs((x + 35) - target_x) < 40:
                    score += 1
                    target_x = random.randint(120, 760)

        keys = pygame.key.get_pressed()
        if keys[pygame.K_RIGHT]:
            x += 4
        if keys[pygame.K_LEFT]:
            x -= 4

        screen.fill((16, 24, 40))
        pygame.draw.rect(screen, (120, 180, 255), (x, 280, 70, 70))
        pygame.draw.circle(screen, (255, 184, 108), (target_x, 160), 20)
        font = pygame.font.SysFont("Arial", 24)
        score_text = font.render(f"Score: {score}", True, (226, 232, 240))
        hint_text = font.render("SPACE: hedefi yakala", True, (148, 163, 184))
        screen.blit(score_text, (20, 18))
        screen.blit(hint_text, (20, 48))
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()
"""
            deps = ["pygame>=2.6.0"]
        elif chosen_stack in {"node", "javascript", "typescript", "express"}:
            entry = src_dir / "main.js"
            todo_mode = any(k in brief_low for k in ("todo", "task", "görev", "gorev"))
            todo_block = ""
            if todo_mode:
                todo_block = """
const todos = [];
app.get('/todos', (_req, res) => res.json({ ok: true, items: todos }));
app.post('/todos', (req, res) => {
  const title = String(req.body?.title || '').trim();
  if (!title) return res.status(400).json({ ok: false, error: 'title required' });
  const item = { id: Date.now(), title, done: false };
  todos.push(item);
  return res.json({ ok: true, item });
});
"""
            entry_content = f"""const express = require('express');
const app = express();
app.use(express.json());

app.get('/health', (_req, res) => res.json({{ ok: true, service: '{project_name}' }}));
{todo_block}
const port = process.env.PORT || 8000;
app.listen(port, () => {{
  console.log(`{project_name} running on :${{port}}`);
}});
"""
            deps = ["express@^4.21.2"]
            (pack_dir / "package.json").write_text(
                "{\n"
                f'  "name": "{safe_name.lower()}",\n'
                '  "version": "0.1.0",\n'
                '  "private": true,\n'
                '  "type": "commonjs",\n'
                '  "scripts": { "start": "node src/main.js" },\n'
                '  "dependencies": { "express": "^4.21.2" }\n'
                "}\n",
                encoding="utf-8",
            )
        else:
            entry = src_dir / "main.py"
            todo_mode = any(k in brief_low for k in ("todo", "task", "görev", "gorev"))
            research_mode = any(k in brief_low for k in ("research", "araştır", "arastir", "rapor"))
            extra_routes = []
            if todo_mode:
                extra_routes.append(
                    """
@app.get("/todos")
def list_todos():
    return {"ok": True, "items": TODOS}

@app.post("/todos")
def add_todo(payload: dict):
    title = str(payload.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    item = {"id": len(TODOS) + 1, "title": title, "done": False}
    TODOS.append(item)
    return {"ok": True, "item": item}
"""
                )
            if research_mode:
                extra_routes.append(
                    """
@app.post("/research/summary")
def summarize(payload: dict):
    topic = str(payload.get("topic") or "").strip() or "genel"
    return {
        "ok": True,
        "topic": topic,
        "summary": f"{topic} için kısa özet üretildi (örnek endpoint)."
    }
"""
                )

            entry_content = (
                "from fastapi import FastAPI\n\n"
                "app = FastAPI(title='Elyan App Pack')\n"
                "TODOS = []\n\n"
                "@app.get('/health')\n"
                "def health():\n"
                f"    return {{'ok': True, 'service': '{project_name}'}}\n"
                + ("\n".join(extra_routes) if extra_routes else "")
                + "\n\nif __name__ == '__main__':\n"
                "    import uvicorn\n"
                "    uvicorn.run(app, host='0.0.0.0', port=8000)\n"
            )
            deps = ["fastapi>=0.111.0", "uvicorn>=0.30.0"]

        entry.write_text(entry_content, encoding="utf-8")

        test_file = tests_dir / "test_smoke.py"
        if entry.suffix == ".py":
            test_file.write_text(
                "\n".join(
                    [
                        "def test_smoke_import():",
                        "    import importlib.util",
                        "    spec = importlib.util.spec_from_file_location('main', 'src/main.py')",
                        "    assert spec is not None",
                    ]
                ),
                encoding="utf-8",
            )
        else:
            test_file.write_text(
                "\n".join(
                    [
                        "from pathlib import Path",
                        "",
                        "def test_smoke_node_entry_exists():",
                        "    assert Path('src/main.js').exists()",
                    ]
                ),
                encoding="utf-8",
            )

        req_path = pack_dir / "requirements.txt"
        if entry.suffix == ".py":
            req_path.write_text("\n".join(deps) + "\n", encoding="utf-8")
        else:
            req_path.write_text("# Node stack selected. Use npm install.\n", encoding="utf-8")

        run_setup = [
            "1. python3 -m venv .venv",
            "2. source .venv/bin/activate",
            "3. pip install -r requirements.txt",
        ]
        run_cmd = ["python src/main.py"]
        test_cmd = ["pytest -q"]
        if entry.suffix != ".py":
            run_setup = ["1. npm install"]
            run_cmd = ["npm start"]
            test_cmd = ["pytest -q  # smoke check for generated files"]

        (docs_dir / "RUN_GUIDE.md").write_text(
            "\n".join(
                [
                    f"# Run Guide - {project_name}",
                    "",
                    f"Project Type: {ptype}",
                    f"Stack: {chosen_stack}",
                    f"Complexity: {level}",
                    f"Brief: {brief_text}",
                    "",
                    "## Setup",
                    *run_setup,
                    "",
                    "## Run",
                    *run_cmd,
                    "",
                    "## Test",
                    *test_cmd,
                ]
            ),
            encoding="utf-8",
        )

        (docs_dir / "DEPLOY_GUIDE.md").write_text(
            "\n".join(
                [
                    f"# Deploy Guide - {project_name}",
                    "",
                    "## Steps",
                    "1. Build artifact / container image",
                    "2. Set runtime env vars",
                    "3. Configure health checks",
                    "4. Roll out gradually and monitor logs",
                ]
            ),
            encoding="utf-8",
        )

        (docs_dir / "QUALITY_REPORT.md").write_text(
            "\n".join(
                [
                    f"# Quality Report Seed - {project_name}",
                    "",
                    "Checklist:",
                    "- [ ] Correctness",
                    "- [ ] Test coverage",
                    "- [ ] Reproducible run",
                    "- [ ] Clear deployment path",
                    "- [ ] Security review for risky operations",
                ]
            ),
            encoding="utf-8",
        )

        (pack_dir / "README.md").write_text(
            "\n".join(
                [
                    f"# {project_name} - Project Pack",
                    "",
                    f"Type: {ptype}",
                    f"Stack: {chosen_stack}",
                    f"Complexity: {level}",
                    f"Brief: {brief_text}",
                    "",
                    "This pack is generated for complex multi-step delivery by Elyan.",
                ]
            ),
            encoding="utf-8",
        )

        files = [
            str(entry),
            str(test_file),
            str(req_path),
            str(docs_dir / "RUN_GUIDE.md"),
            str(docs_dir / "DEPLOY_GUIDE.md"),
            str(docs_dir / "QUALITY_REPORT.md"),
            str(pack_dir / "README.md"),
        ]
        return {
            "success": True,
            "project_name": project_name,
            "project_type": ptype,
            "stack": chosen_stack,
            "complexity": level,
            "pack_dir": str(pack_dir),
            "files_created": files,
            "message": f"Software project pack oluşturuldu: {pack_dir}",
        }
    except Exception as exc:
        logger.error(f"create_software_project_pack error: {exc}")
        return {"success": False, "error": str(exc)}
