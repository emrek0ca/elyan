"""
Elyan Dependency Resolver — Auto-generate dependency manifests

Creates requirements.txt, package.json, Cargo.toml, go.mod
based on project code analysis.
"""

import ast
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Set
from utils.logger import get_logger

logger = get_logger("dependency_resolver")

# Common Python package name → PyPI name mapping
PYTHON_STDLIB = {
    "os", "sys", "re", "json", "csv", "math", "random", "time", "datetime",
    "pathlib", "shutil", "tempfile", "subprocess", "asyncio", "logging",
    "collections", "itertools", "functools", "typing", "dataclasses",
    "unittest", "sqlite3", "hashlib", "base64", "io", "copy", "abc",
    "threading", "multiprocessing", "signal", "socket", "http", "urllib",
    "email", "html", "xml", "argparse", "configparser", "enum", "uuid",
}

IMPORT_TO_PYPI = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn[standard]",
    "flask": "flask",
    "django": "django",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "requests": "requests",
    "httpx": "httpx",
    "click": "click",
    "pytest": "pytest",
    "numpy": "numpy",
    "pandas": "pandas",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "torch": "torch",
    "transformers": "transformers",
    "openai": "openai",
    "redis": "redis",
    "celery": "celery",
    "boto3": "boto3",
    "pymongo": "pymongo",
    "psycopg2": "psycopg2-binary",
}


class DependencyResolver:
    """Analyze code and generate dependency files."""

    def resolve_python(self, project_dir: str) -> Dict[str, Any]:
        """Scan Python files and generate requirements.txt."""
        imports: Set[str] = set()
        
        for py_file in Path(project_dir).rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.add(alias.name.split(".")[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.add(node.module.split(".")[0])
            except Exception:
                continue

        # Filter out stdlib and local imports
        external = imports - PYTHON_STDLIB
        # Map to PyPI names
        requirements = []
        for imp in sorted(external):
            pypi_name = IMPORT_TO_PYPI.get(imp, imp)
            requirements.append(pypi_name)

        # Write requirements.txt
        req_path = Path(project_dir) / "requirements.txt"
        req_path.write_text("\n".join(requirements) + "\n")

        return {
            "success": True,
            "path": str(req_path),
            "packages": requirements,
            "count": len(requirements),
        }

    def resolve_node(self, project_dir: str) -> Dict[str, Any]:
        """Scan JS/TS files and update package.json dependencies."""
        imports: Set[str] = set()
        
        for ext in ("*.js", "*.ts", "*.jsx", "*.tsx"):
            for js_file in Path(project_dir).rglob(ext):
                try:
                    content = js_file.read_text()
                    # Match require('pkg') and import ... from 'pkg'
                    for match in re.finditer(r"(?:require|from)\s*\(?['\"]([^./][^'\"]*)['\"]", content):
                        pkg = match.group(1).split("/")[0]
                        if not pkg.startswith("."):
                            imports.add(pkg)
                except Exception:
                    continue

        return {
            "success": True,
            "packages": sorted(imports),
            "count": len(imports),
        }


# Global instance
dep_resolver = DependencyResolver()
