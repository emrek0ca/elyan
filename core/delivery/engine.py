"""
Delivery Engine v2 — LLM-Driven Project Generation

Primary path: LLM designs architecture → generates each file with context → verifies → packages
Fallback path: Template-based generation (legacy)

Flow: INTAKE → PLAN (architect) → EXECUTE (codegen per file) → VERIFY → DELIVER
"""

import os
import ast
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

logger = get_logger("delivery_engine")

# Max files per project to prevent runaway generation
MAX_PROJECT_FILES = 15
# Max LLM tokens per file
MAX_TOKENS_PER_FILE = 4000


class DeliveryEngine:
    """v2 Delivery Engine: LLM-first project generation with template fallback."""

    def __init__(self):
        self.workspace = resolve_elyan_data_dir() / "projects" / "delivery"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.templates_dir = Path(__file__).parent / "templates"
        from core.delivery.state_machine import delivery_state_manager, DeliveryState
        self.state_manager = delivery_state_manager
        self.DeliveryState = DeliveryState

    # ── Public API ──────────────────────────────────────────────

    async def create_project(
        self,
        name: str,
        description: str,
        template_type: str = "",
        data: Optional[Dict[str, Any]] = None,
        llm_client=None,
    ) -> Dict[str, Any]:
        """Create a project — LLM-driven if client available, template fallback otherwise."""
        data = data or {}
        project = self.state_manager.start_project(name)
        project_path = self.workspace / _safe_dirname(name)
        project_path.mkdir(parents=True, exist_ok=True)

        # ── Try LLM-driven path first ──
        if llm_client:
            try:
                result = await self._llm_driven_create(
                    project, project_path, name, description, llm_client
                )
                if result.get("success"):
                    return result
                logger.warning("LLM-driven path failed, falling back to template")
            except Exception as e:
                logger.warning(f"LLM-driven creation error: {e}")

        # ── Template fallback ──
        return await self._template_create(project, project_path, template_type, data)

    # ── Phase 1: LLM-Driven Architecture Design ────────────────

    async def _llm_driven_create(
        self,
        project,
        project_path: Path,
        name: str,
        description: str,
        llm_client,
    ) -> Dict[str, Any]:
        """Full LLM pipeline: architect → codegen → verify → readme → test."""

        # Phase 1: Architecture
        project.transition_to(self.DeliveryState.PLANNING, {"method": "llm"})
        architecture = await self._llm_architect(description, llm_client)
        if not architecture:
            return {"success": False, "error": "Architecture design failed"}

        files_plan = architecture.get("files", [])
        if not files_plan:
            return {"success": False, "error": "No files in architecture plan"}

        # Phase 2: Code Generation (file by file with cumulative context)
        project.transition_to(self.DeliveryState.EXECUTING, {"files": len(files_plan)})
        generated_files = await self._llm_codegen(
            project_path, description, files_plan, llm_client
        )

        # Phase 3: Verification
        project.transition_to(self.DeliveryState.VERIFYING)
        verification = self._verify_project(project_path, generated_files)

        # Phase 4: README generation
        await self._generate_readme(project_path, name, description, generated_files, llm_client)

        # Phase 5: Auto-test generation (best-effort)
        await self._generate_tests(project_path, description, generated_files, llm_client)

        # Done
        project.transition_to(self.DeliveryState.DELIVERED, {"path": str(project_path)})

        return {
            "success": True,
            "path": str(project_path),
            "method": "llm",
            "files_generated": len(generated_files),
            "architecture": architecture,
            "verification": verification,
        }

    async def _llm_architect(
        self, description: str, llm_client
    ) -> Optional[Dict[str, Any]]:
        """Ask LLM to design project architecture. Returns file list with purposes."""
        prompt = (
            "You are a senior software architect. Design a project structure for:\n"
            f'"{description}"\n\n'
            "Rules:\n"
            f"- Maximum {MAX_PROJECT_FILES} files\n"
            "- Include only essential files (entry point, core logic, config, dependencies)\n"
            "- Each file must have a clear single purpose\n"
            "- Use modern best practices for the detected tech stack\n\n"
            "Return ONLY valid JSON (no markdown fences):\n"
            '{"project_type": "detected_type", "files": [\n'
            '  {"path": "relative/path.ext", "purpose": "one-line description"},\n'
            "  ...\n"
            '], "dependencies": ["dep1", "dep2"]}'
        )
        try:
            raw = await llm_client.generate(prompt, role="planning")
            parsed = _extract_json(raw)
            if not parsed or "files" not in parsed:
                return None

            # Validate & sanitize file paths
            safe_files = []
            for f in parsed["files"][:MAX_PROJECT_FILES]:
                p = f.get("path", "")
                if not p or ".." in p or p.startswith("/"):
                    continue
                safe_files.append({"path": p, "purpose": f.get("purpose", "")})

            parsed["files"] = safe_files
            logger.info(f"Architecture: {parsed.get('project_type')} with {len(safe_files)} files")
            return parsed
        except Exception as e:
            logger.error(f"Architect LLM call failed: {e}")
            return None

    async def _llm_codegen(
        self,
        project_path: Path,
        description: str,
        files_plan: List[Dict[str, str]],
        llm_client,
    ) -> List[str]:
        """Generate each file with cumulative context (previous files inform next)."""
        generated = []
        context_files: List[Dict[str, str]] = []  # {"path": ..., "content": ...}

        for file_spec in files_plan:
            fpath = file_spec["path"]
            purpose = file_spec.get("purpose", "")
            full_path = project_path / fpath
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Build context from previously generated files
            ctx_block = ""
            if context_files:
                ctx_parts = []
                for cf in context_files[-5:]:  # Last 5 files for context window efficiency
                    snippet = cf["content"][:1500]  # Truncate for token budget
                    ctx_parts.append(f"--- {cf['path']} ---\n{snippet}")
                ctx_block = "\nAlready generated files:\n" + "\n".join(ctx_parts) + "\n"

            prompt = (
                f"Generate the COMPLETE, WORKING content for: {fpath}\n"
                f"Purpose: {purpose}\n"
                f"Project description: {description}\n"
                f"{ctx_block}\n"
                "Rules:\n"
                "- Return ONLY the file content, no markdown fences or explanations\n"
                "- Code must be complete and runnable\n"
                "- Use proper imports matching the existing files\n"
                "- Follow modern conventions for this file type"
            )

            try:
                content = await llm_client.generate(prompt, role="inference")
                content = _strip_markdown_fences(content)
            except Exception as e:
                content = f"# {fpath} — placeholder (generation error: {e})\n"
                logger.warning(f"Codegen failed for {fpath}: {e}")

            full_path.write_text(content, encoding="utf-8")
            generated.append(fpath)
            context_files.append({"path": fpath, "content": content})

        return generated

    # ── Phase 3: Verification ──────────────────────────────────

    def _verify_project(self, project_path: Path, files: List[str]) -> Dict[str, Any]:
        """Verify generated project: syntax check Python, detect entry points."""
        results = {"syntax_ok": [], "syntax_errors": [], "has_entry_point": False, "has_deps": False}

        for fpath in files:
            full = project_path / fpath
            if not full.exists():
                continue

            # Python syntax check
            if fpath.endswith(".py"):
                try:
                    code = full.read_text(encoding="utf-8")
                    ast.parse(code)
                    results["syntax_ok"].append(fpath)
                except SyntaxError as e:
                    results["syntax_errors"].append({"file": fpath, "error": str(e)})

            # Detect entry point
            if fpath in ("main.py", "app.py", "server.py", "index.js", "index.ts", "manage.py"):
                results["has_entry_point"] = True
            if fpath in ("pages/index.tsx", "src/main.jsx", "src/main.tsx", "lib/main.dart"):
                results["has_entry_point"] = True

            # Detect dependency file
            if fpath in ("requirements.txt", "package.json", "pubspec.yaml", "Cargo.toml", "go.mod"):
                results["has_deps"] = True

        total_py = len(results["syntax_ok"]) + len(results["syntax_errors"])
        results["python_pass_rate"] = (
            len(results["syntax_ok"]) / total_py if total_py > 0 else 1.0
        )

        logger.info(
            f"Verification: {len(results['syntax_ok'])} OK, "
            f"{len(results['syntax_errors'])} errors, "
            f"entry_point={results['has_entry_point']}"
        )
        return results

    # ── Phase 4 & 5: README + Tests ───────────────────────────

    async def _generate_readme(
        self,
        project_path: Path,
        name: str,
        description: str,
        files: List[str],
        llm_client,
    ):
        """Generate a README.md for the project."""
        try:
            prompt = (
                f"Write a concise README.md for a project named '{name}'.\n"
                f"Description: {description}\n"
                f"Files: {', '.join(files)}\n\n"
                "Include: project title, description, setup instructions, usage, file structure.\n"
                "Return ONLY the markdown content."
            )
            content = await llm_client.generate(prompt, role="inference")
            content = _strip_markdown_fences(content)
            (project_path / "README.md").write_text(content, encoding="utf-8")
        except Exception as e:
            logger.debug(f"README generation skipped: {e}")

    async def _generate_tests(
        self,
        project_path: Path,
        description: str,
        files: List[str],
        llm_client,
    ):
        """Generate basic test file (best-effort, non-blocking)."""
        py_files = [f for f in files if f.endswith(".py") and "test" not in f.lower()]
        if not py_files:
            return

        try:
            # Read the main entry file for context
            main_file = None
            for candidate in ("main.py", "app.py", "server.py"):
                if candidate in py_files:
                    main_file = candidate
                    break
            if not main_file:
                main_file = py_files[0]

            main_content = (project_path / main_file).read_text(encoding="utf-8")[:2000]

            prompt = (
                f"Write pytest tests for this Python project.\n"
                f"Main file ({main_file}):\n```python\n{main_content}\n```\n\n"
                f"Other files: {', '.join(py_files)}\n"
                "Rules:\n"
                "- Use pytest conventions\n"
                "- Test the main public functions/endpoints\n"
                "- Include at least 3 test cases\n"
                "- Return ONLY the test file content, no markdown fences"
            )
            content = await llm_client.generate(prompt, role="inference")
            content = _strip_markdown_fences(content)

            tests_dir = project_path / "tests"
            tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_main.py").write_text(content, encoding="utf-8")
        except Exception as e:
            logger.debug(f"Test generation skipped: {e}")

    # ── Template Fallback (Legacy) ─────────────────────────────

    async def _template_create(
        self,
        project,
        project_path: Path,
        template_type: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Legacy template-based project creation."""
        logger.info(f"Template fallback: {template_type}")
        project.transition_to(self.DeliveryState.EXECUTING, {"template": template_type})

        generators = {
            "gsap_landing": self._gen_gsap_landing,
            "threejs_showcase": self._gen_threejs_showcase,
            "react_app": self._gen_react_app,
            "python_cli": self._gen_python_cli,
        }

        gen = generators.get(template_type)
        if not gen:
            project.transition_to(self.DeliveryState.FAILED, {"error": "Unknown template"})
            return {"success": False, "error": f"Template '{template_type}' not found"}

        result = await gen(project_path, data)
        state = self.DeliveryState.DELIVERED if result.get("success") else self.DeliveryState.FAILED
        project.transition_to(state, {"path": str(project_path)})
        return result

    async def _gen_gsap_landing(self, path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
        title = data.get("title", "Elyan Project")
        hero = data.get("hero_title", "Future is here")
        desc = data.get("description", "High performance autonomous delivery.")
        html = (
            "<!DOCTYPE html>\n<html>\n<head>\n"
            f"    <title>{title}</title>\n"
            '    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js"></script>\n'
            '    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/ScrollTrigger.min.js"></script>\n'
            '    <script src="https://cdn.tailwindcss.com"></script>\n'
            "    <style>body { background: #000; color: #fff; overflow-x: hidden; }\n"
            "    .hero-text { opacity: 0; transform: translateY(50px); }</style>\n"
            "</head>\n<body>\n"
            '    <section class="h-screen flex items-center justify-center">\n'
            f'        <h1 class="hero-text text-6xl font-bold tracking-tighter">{hero}</h1>\n'
            "    </section>\n"
            '    <section class="h-screen bg-white text-black p-20">\n'
            '        <h2 class="text-4xl reveal">Elyan Delivery Engine</h2>\n'
            f'        <p class="mt-4 text-xl">{desc}</p>\n'
            "    </section>\n"
            "    <script>\n"
            "        gsap.registerPlugin(ScrollTrigger);\n"
            '        gsap.to(".hero-text", { opacity: 1, y: 0, duration: 1.5, ease: "expo.out" });\n'
            '        gsap.from(".reveal", { scrollTrigger: ".reveal", opacity: 0, x: -100, duration: 1 });\n'
            "    </script>\n</body>\n</html>"
        )
        (path / "index.html").write_text(html)
        return {"success": True, "url": f"file://{path}/index.html", "path": str(path)}

    async def _gen_threejs_showcase(self, path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
        html = (
            "<!DOCTYPE html>\n<html>\n<head><title>3D Showcase</title>"
            "<style>body { margin: 0; background: #000; }</style></head>\n<body>\n"
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/0.158.0/three.min.js"></script>\n'
            "<script>\n"
            "const scene = new THREE.Scene();\n"
            "const camera = new THREE.PerspectiveCamera(75, innerWidth/innerHeight, 0.1, 1000);\n"
            "const renderer = new THREE.WebGLRenderer({antialias:true});\n"
            "renderer.setSize(innerWidth, innerHeight);\n"
            "document.body.appendChild(renderer.domElement);\n"
            "const geo = new THREE.IcosahedronGeometry(1,1);\n"
            "const mat = new THREE.MeshNormalMaterial({wireframe:true});\n"
            "const mesh = new THREE.Mesh(geo,mat); scene.add(mesh);\n"
            "camera.position.z = 5;\n"
            "function animate(){requestAnimationFrame(animate);\n"
            "mesh.rotation.x+=0.01; mesh.rotation.y+=0.01;\n"
            "renderer.render(scene,camera);} animate();\n"
            "</script>\n</body>\n</html>"
        )
        (path / "index.html").write_text(html)
        return {"success": True, "url": f"file://{path}/index.html", "path": str(path)}

    async def _gen_react_app(self, path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
        (path / "src").mkdir(exist_ok=True)
        title = data.get("title", "React App")
        (path / "index.html").write_text(
            f"<!DOCTYPE html><html><body><div id='root'></div>"
            f"<script type='module' src='./src/main.jsx'></script></body></html>"
        )
        (path / "src" / "main.jsx").write_text(
            f"import React from 'react';\nimport ReactDOM from 'react-dom/client';\n"
            f"ReactDOM.createRoot(document.getElementById('root')).render(<h1>{title}</h1>);"
        )
        return {"success": True, "path": str(path), "type": "react"}

    async def _gen_python_cli(self, path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
        msg = data.get("welcome_msg", "Hello from Elyan CLI!")
        (path / "main.py").write_text(
            f"def main():\n    print('{msg}')\n\nif __name__ == '__main__':\n    main()"
        )
        (path / "requirements.txt").write_text("click\nrequests\n")
        return {"success": True, "path": str(path), "type": "python_cli"}


# ── Utility Functions ──────────────────────────────────────────

def _safe_dirname(name: str) -> str:
    """Sanitize project name for filesystem use."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return safe[:60] or "project"


def _strip_markdown_fences(text: str) -> str:
    """Remove ```lang ... ``` wrapper from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```lang) and last line (```)
        if len(lines) > 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1])
        elif len(lines) > 1:
            return "\n".join(lines[1:])
    return text


def _extract_json(text: str) -> Optional[Dict]:
    """Robustly extract JSON from LLM output."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try stripping markdown fences
    cleaned = _strip_markdown_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Try finding JSON block
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    return None


# Global instance
delivery_engine = DeliveryEngine()
