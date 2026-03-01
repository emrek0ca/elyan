"""
Elyan Project Architect — LLM-driven architecture design

Generates project structure, dependency lists, and API contracts
from a user's high-level description.
"""

from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("architect")


# Pre-defined architecture blueprints
BLUEPRINTS = {
    "fastapi": {
        "structure": ["main.py", "requirements.txt", "Dockerfile", "app/__init__.py", "app/routes.py", "app/models.py", "app/schemas.py", "app/database.py", "tests/test_routes.py"],
        "deps": ["fastapi", "uvicorn[standard]", "sqlalchemy", "pydantic"],
    },
    "nextjs": {
        "structure": ["package.json", "next.config.js", "tsconfig.json", "pages/index.tsx", "pages/api/hello.ts", "styles/globals.css", "components/Layout.tsx", "public/favicon.ico"],
        "deps": ["next", "react", "react-dom", "typescript", "@types/react"],
    },
    "django": {
        "structure": ["manage.py", "requirements.txt", "Dockerfile", "project/settings.py", "project/urls.py", "project/wsgi.py", "app/models.py", "app/views.py", "app/urls.py", "app/admin.py", "templates/base.html"],
        "deps": ["django", "django-cors-headers", "gunicorn", "psycopg2-binary"],
    },
    "express": {
        "structure": ["package.json", "server.js", "routes/index.js", "middleware/auth.js", "models/User.js", "config/db.js", "Dockerfile", "tests/api.test.js"],
        "deps": ["express", "cors", "helmet", "dotenv", "mongoose"],
    },
    "flutter": {
        "structure": ["pubspec.yaml", "lib/main.dart", "lib/screens/home_screen.dart", "lib/widgets/custom_button.dart", "lib/services/api_service.dart", "lib/models/user_model.dart", "test/widget_test.dart"],
        "deps": ["flutter", "http", "provider"],
    },
    "electron": {
        "structure": ["package.json", "main.js", "preload.js", "renderer/index.html", "renderer/renderer.js", "renderer/styles.css"],
        "deps": ["electron"],
    },
}


class ProjectArchitect:
    """Designs project architecture from user intent."""

    def __init__(self):
        self._llm = None

    async def design(
        self,
        description: str,
        project_type: str = None,
        llm_client=None,
    ) -> Dict[str, Any]:
        """Design full project architecture."""
        # Detect type if not provided
        if not project_type:
            project_type = self._detect_type(description)

        blueprint = BLUEPRINTS.get(project_type)
        if not blueprint:
            blueprint = BLUEPRINTS.get("fastapi")  # default fallback
            project_type = "fastapi"

        # Build architecture spec
        architecture = {
            "project_type": project_type,
            "files": blueprint["structure"],
            "dependencies": blueprint["deps"],
            "description": description,
        }

        # If LLM available, enrich with custom files
        if llm_client:
            try:
                prompt = (
                    f"Given this project description: '{description}'\n"
                    f"Base type: {project_type}\n"
                    f"Base files: {blueprint['structure']}\n\n"
                    "Suggest up to 5 additional files that would be needed. "
                    "Return ONLY a JSON list of file paths, nothing else."
                )
                resp = await llm_client.generate(prompt, role="planning")
                import json
                extra_files = json.loads(resp.strip().strip("```json").strip("```"))
                if isinstance(extra_files, list):
                    architecture["files"].extend(extra_files[:5])
                    architecture["llm_enriched"] = True
            except Exception as e:
                logger.debug(f"LLM enrichment failed: {e}")

        logger.info(f"Designed {project_type} architecture with {len(architecture['files'])} files")
        return architecture

    @staticmethod
    def _detect_type(description: str) -> str:
        lower = description.lower()
        mapping = [
            (["react", "next", "nextjs", "next.js", "frontend"], "nextjs"),
            (["django", "admin panel"], "django"),
            (["express", "node", "nodejs", "backend js"], "express"),
            (["flutter", "mobile", "dart", "ios app", "android"], "flutter"),
            (["electron", "desktop app", "masaüstü"], "electron"),
            (["fastapi", "api", "microservice", "rest", "backend", "python"], "fastapi"),
        ]
        for keywords, ptype in mapping:
            if any(kw in lower for kw in keywords):
                return ptype
        return "fastapi"


# Global instance
architect = ProjectArchitect()
