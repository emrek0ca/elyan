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
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", " ") else " " for ch in str(name or "wiqo-project"))
    cleaned = "_".join(cleaned.strip().split())
    return cleaned[:80] or "wiqo-project"


async def create_web_project_scaffold(
    project_name: str,
    stack: str = "vanilla",
    theme: str = "professional",
    output_dir: str = "~/Desktop"
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
            "project_dir": str(project_dir),
            "files_created": files_written,
            "message": f"Web scaffold olusturuldu: {project_dir}",
        }
    except Exception as exc:
        logger.error(f"create_web_project_scaffold error: {exc}")
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

        if ptype == "game":
            entry = src_dir / "main.py"
            entry_content = """import pygame

def main():
    pygame.init()
    screen = pygame.display.set_mode((900, 520))
    pygame.display.set_caption("Elyan Game Prototype")
    clock = pygame.time.Clock()
    running = True
    x = 100

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()
        if keys[pygame.K_RIGHT]:
            x += 4
        if keys[pygame.K_LEFT]:
            x -= 4

        screen.fill((16, 24, 40))
        pygame.draw.rect(screen, (120, 180, 255), (x, 280, 70, 70))
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()
"""
            deps = ["pygame>=2.6.0"]
        elif ptype == "app":
            entry = src_dir / "main.py"
            entry_content = """def run():
    print("Elyan App Pack: application core started.")

if __name__ == "__main__":
    run()
"""
            deps = ["fastapi>=0.111.0", "uvicorn>=0.30.0"]
        else:
            entry = src_dir / "main.py"
            entry_content = """def run():
    print("Elyan WebApp Pack: project scaffold ready.")

if __name__ == "__main__":
    run()
"""
            deps = ["fastapi>=0.111.0", "uvicorn>=0.30.0"]

        entry.write_text(entry_content, encoding="utf-8")

        test_file = tests_dir / "test_smoke.py"
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

        (pack_dir / "requirements.txt").write_text("\n".join(deps) + "\n", encoding="utf-8")

        (docs_dir / "RUN_GUIDE.md").write_text(
            "\n".join(
                [
                    f"# Run Guide - {project_name}",
                    "",
                    f"Project Type: {ptype}",
                    f"Stack: {chosen_stack}",
                    f"Complexity: {level}",
                    "",
                    "## Setup",
                    "1. python3 -m venv .venv",
                    "2. source .venv/bin/activate",
                    "3. pip install -r requirements.txt",
                    "",
                    "## Run",
                    "python src/main.py",
                    "",
                    "## Test",
                    "pytest -q",
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
                    "",
                    "This pack is generated for complex multi-step delivery by Elyan.",
                ]
            ),
            encoding="utf-8",
        )

        files = [
            str(entry),
            str(test_file),
            str(pack_dir / "requirements.txt"),
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
