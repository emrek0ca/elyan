from __future__ import annotations

import json
import re
import shlex
import subprocess
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

PROJECT_MANIFEST = ".opengauss/project.yaml"
PROJECT_MARKERS = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yaml",
    "compose.yml",
    "schema/init.sql",
    "sql/init.sql",
    PROJECT_MANIFEST,
)
TEXT_SUFFIXES = {
    ".sql",
    ".sh",
    ".txt",
    ".md",
    ".markdown",
    ".yaml",
    ".yml",
    ".json",
}
_DESTRUCTIVE_SQL_PATTERN = re.compile(
    r"(?is)\b("
    r"insert\s+into|update\b|delete\s+from|drop\s+(?:table|view|index|schema|database|user|role)|"
    r"truncate\s+table|alter\s+(?:table|database|schema|user|role)|create\s+(?:table|schema|database|user|role|index)|"
    r"replace\s+into|grant\b|revoke\b|vacuum\s+full|reindex\b|cluster\b"
    r")\b"
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _normalize_root(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


def _slugify(name: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(name or "").strip())
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-") or "opengauss-project"


def _safe_name(value: str) -> str:
    text = str(value or "").strip()
    return text or "OpenGauss Project"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_manifest(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            payload[str(key).strip()] = str(value).strip().strip('"').strip("'")
    except Exception:
        return {}
    return payload


def _env_default(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.startswith("${") and ":-" in text and text.endswith("}"):
        inner = text[2:-1]
        _, default = inner.split(":-", 1)
        return str(default).strip() or fallback
    return text


def _looks_like_opengauss_project(root: Path) -> bool:
    manifest = _read_manifest(root / PROJECT_MANIFEST)
    compose_text = _read_text(root / "docker-compose.yml") + "\n" + _read_text(root / "docker-compose.yaml")
    readme_text = _read_text(root / "README.md").lower()
    if any((root / marker).exists() for marker in PROJECT_MARKERS):
        return True
    if "opengauss" in compose_text.lower() or "gsql" in compose_text.lower():
        return True
    if "opengauss" in readme_text or "gauss" in readme_text:
        return True
    if manifest.get("kind") == "opengauss":
        return True
    return False


def detect_project_root(start: str | Path | None = None) -> Path | None:
    candidate = _normalize_root(start) or Path.cwd().resolve()
    for root in [candidate, *candidate.parents]:
        if _looks_like_opengauss_project(root):
            return root
    return None


def resolve_project_root(path: str | Path | None = None) -> Path | None:
    root = _normalize_root(path)
    if root and root.exists():
        return detect_project_root(root)
    return detect_project_root(path)


def discover_database_sources(root: str | Path) -> list[str]:
    root_path = _normalize_root(root)
    if root_path is None:
        return []

    candidates: list[Path] = []
    for name in (
        "README.md",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yaml",
        "compose.yml",
        "schema/init.sql",
        "sql/init.sql",
        ".env.example",
        PROJECT_MANIFEST,
    ):
        candidate = root_path / name
        if candidate.exists():
            candidates.append(candidate)

    for folder_name in ("schema", "sql", "scripts", "migrations", "queries"):
        folder = root_path / folder_name
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                candidates.append(path)

    ordered: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        clean = str(path.expanduser().resolve())
        if clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
    return ordered


def summarize_project(root: str | Path) -> dict[str, Any]:
    root_path = _normalize_root(root)
    if root_path is None:
        return {}

    manifest_path = root_path / PROJECT_MANIFEST
    compose_path = root_path / "docker-compose.yml"
    compose_alt_path = root_path / "docker-compose.yaml"
    env_path = root_path / ".env.example"
    schema_path = root_path / "schema" / "init.sql"
    sql_path = root_path / "sql" / "init.sql"
    query_script = root_path / "scripts" / "query.sh"
    backup_script = root_path / "scripts" / "backup.sh"
    restore_script = root_path / "scripts" / "restore.sh"
    readme_path = root_path / "README.md"

    manifest = _read_manifest(manifest_path) if manifest_path.exists() else {}
    compose_text = _read_text(compose_path) or _read_text(compose_alt_path)
    readme_text = _read_text(readme_path)
    schema_text = _read_text(schema_path) or _read_text(sql_path)

    features: list[str] = []
    if compose_path.exists() or compose_alt_path.exists():
        features.append("docker_compose")
    if env_path.exists():
        features.append("env_example")
    if schema_path.exists() or sql_path.exists():
        features.append("schema_sql")
    if query_script.exists():
        features.append("query_script")
    if backup_script.exists():
        features.append("backup_script")
    if restore_script.exists():
        features.append("restore_script")
    if "opengauss" in compose_text.lower():
        features.append("opengauss_image")
    if "gsql" in readme_text.lower() or "gsql" in compose_text.lower():
        features.append("query_notes")
    if "gs_dump" in readme_text.lower() or "gs_restore" in readme_text.lower():
        features.append("backup_notes")
    if "schema" in schema_text.lower():
        features.append("schema_seed")
    if "local-first" in readme_text.lower() or "local first" in readme_text.lower():
        features.append("local_first")

    ready = {"docker_compose", "schema_sql", "env_example", "query_script"}.issubset(set(features))

    image_match = re.search(r"image:\s*([^\n]+)", compose_text, re.IGNORECASE)
    port_match = re.search(r'["\']?(\d{2,5})\s*:\s*5432', compose_text)
    user_match = re.search(r"GS_USERNAME:\s*([^\s\n]+)", compose_text)
    db_match = re.search(r"OPENGAUSS_DATABASE:\s*([^\s\n]+)", compose_text)
    manifest_image = _env_default(manifest.get("image"), "opengauss/opengauss-server:latest")
    manifest_port = int(str(manifest.get("port") or "").strip() or 5432)
    manifest_user = _env_default(manifest.get("username"), "root")
    manifest_db = _env_default(manifest.get("database"), "appdb")

    return {
        "root": str(root_path),
        "name": str(manifest.get("name") or root_path.name or "opengauss"),
        "slug": _slugify(str(manifest.get("name") or root_path.name or "opengauss")),
        "status": "ready" if ready else "scaffolded",
        "ready": ready,
        "features": sorted(set(features)),
        "manifest_path": str(manifest_path),
        "compose_path": str(compose_path if compose_path.exists() else compose_alt_path),
        "env_path": str(env_path),
        "schema_path": str(schema_path if schema_path.exists() else sql_path),
        "query_script": str(query_script),
        "backup_script": str(backup_script),
        "restore_script": str(restore_script),
        "readme_path": str(readme_path),
        "has_manifest": manifest_path.exists(),
        "has_compose": compose_path.exists() or compose_alt_path.exists(),
        "has_env": env_path.exists(),
        "has_schema": schema_path.exists() or sql_path.exists(),
        "has_query_script": query_script.exists(),
        "has_backup_script": backup_script.exists(),
        "has_restore_script": restore_script.exists(),
        "image": manifest_image if manifest_image else (str(image_match.group(1).strip().strip('"').strip("'")) if image_match else "opengauss/opengauss-server:latest"),
        "port": manifest_port if manifest_port else (int(port_match.group(1)) if port_match else 5432),
        "username": manifest_user if manifest_user else (str(user_match.group(1).strip().strip('"').strip("'")) if user_match else "root"),
        "database": manifest_db if manifest_db else (str(db_match.group(1).strip().strip('"').strip("'")) if db_match else "appdb"),
        "source_files": discover_database_sources(root_path),
        "updated_at": _now_iso(),
    }


def build_opengauss_prompt(
    action: str,
    *,
    project: dict[str, Any],
    goal: str = "",
    target: str = "",
    backend: str = "auto",
) -> str:
    root = str(project.get("root") or "").strip()
    name = str(project.get("name") or project.get("slug") or "OpenGauss project").strip()
    action_text = str(action or "starter").strip().lower() or "starter"
    lines = [
        "You are Elyan's OpenGauss operator.",
        f"Project: {name}",
        f"Project root: {root}",
        f"Task: {action_text}",
        f"Backend: {backend}",
        "Use OpenGauss patterns: containerized startup, schema bootstrap, read-only SQL checks, backup and restore scripts.",
        "Prefer local-first docker compose workflows and explicit schema files.",
        "Keep queries reproducible, traceable, and safe by default.",
    ]
    if goal:
        lines.append(f"Goal: {goal}")
    if target:
        lines.append(f"Target: {target}")
    lines.extend(
        [
            "Return a compact plan, generated files, and the next database action.",
            "If execution is requested, prefer the generated script or a minimal compose command.",
        ]
    )
    return "\n".join(lines)


def build_opengauss_bundle(
    action: str,
    *,
    project: dict[str, Any],
    goal: str = "",
    target: str = "",
    backend: str = "auto",
) -> dict[str, Any]:
    root = str(project.get("root") or "").strip()
    bundle_id = f"opengauss_{str(action or 'starter').strip().lower() or 'starter'}"
    prompt = build_opengauss_prompt(action, project=project, goal=goal, target=target, backend=backend)
    return {
        "id": bundle_id,
        "name": "OpenGauss Database Starter",
        "category": "database",
        "required_skills": ["opengauss", "files", "research"],
        "required_tools": ["opengauss_status", "opengauss_project", "opengauss_scaffold", "opengauss_query", "opengauss_workflow"],
        "steps": [
            {
                "id": "inspect_database",
                "action": "opengauss_project",
                "params": {"action": "status", "path": root},
            },
            {
                "id": "scaffold_database",
                "action": "opengauss_scaffold",
                "params": {"path": root, "name": project.get("name") or ""},
            },
            {
                "id": "review_workflow",
                "action": "opengauss_workflow",
                "params": {"action": str(action or "starter"), "path": root, "goal": goal, "target": target, "backend": backend},
            },
            {
                "id": "prepare_sql",
                "action": "opengauss_query",
                "params": {"path": root, "sql": goal or "SELECT 1;"},
            },
        ],
        "trigger_markers": [
            "opengauss",
            "openGauss",
            "gaussdb",
            "database",
            "sql",
            "schema",
            "migration",
            "docker compose",
            "gsql",
            "backup",
            "restore",
        ],
        "objective": "provision_containerized_database_workspace",
        "prompt": prompt,
        "command": "docker compose up -d",
        "project_root": root,
        "project_name": str(project.get("name") or ""),
        "output_artifacts": ["docker_compose", "schema_sql", "env_example", "query_script", "backup_script", "restore_script"],
        "quality_checklist": [
            "schema_integrity",
            "connection_safety",
            "migration_safety",
            "rollback_plan",
            "traceability",
        ],
        "auto_intent": True,
    }


def _render_env_example(name: str, image: str, port: int, database: str, user: str, password: str) -> str:
    return textwrap.dedent(
        f"""
        OPENGAUSS_IMAGE={image}
        OPENGAUSS_PORT={port}
        OPENGAUSS_DATABASE={database}
        OPENGAUSS_USERNAME={user}
        OPENGAUSS_PASSWORD={password}
        OPENGAUSS_CONTAINER_NAME={_slugify(name)}
        """
    ).strip() + "\n"


def _render_docker_compose(name: str, image: str, port: int, database: str, user: str, password: str) -> str:
    return textwrap.dedent(
        f"""
        services:
          opengauss:
            image: ${{OPENGAUSS_IMAGE:-{image}}}
            container_name: ${{OPENGAUSS_CONTAINER_NAME:-{_slugify(name)}}}
            restart: unless-stopped
            ports:
              - "${{OPENGAUSS_PORT:-{port}}}:5432"
            environment:
              GS_USERNAME: ${{OPENGAUSS_USERNAME:-{user}}}
              GS_PASSWORD: ${{OPENGAUSS_PASSWORD:-{password}}}
              OPENGAUSS_DATABASE: ${{OPENGAUSS_DATABASE:-{database}}}
            volumes:
              - ./data:/var/lib/opengauss
              - ./schema:/workspace/schema
              - ./backups:/workspace/backups
        """
    ).strip() + "\n"


def _render_init_sql(name: str, database: str) -> str:
    schema_name = _slugify(name).replace("-", "_")
    return textwrap.dedent(
        f"""
        -- OpenGauss starter schema generated by Elyan
        CREATE SCHEMA IF NOT EXISTS {schema_name};

        CREATE TABLE IF NOT EXISTS {schema_name}.demo_events (
          id SERIAL PRIMARY KEY,
          title TEXT NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO {schema_name}.demo_events (title)
        VALUES ('Elyan OpenGauss bootstrap')
        ON CONFLICT DO NOTHING;
        """
    ).strip() + "\n"


def _render_query_script(database: str, user: str) -> str:
    return textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
        cd "$ROOT"

        SQL="${{*:-SELECT 1;}}"
        if [[ -f .env ]]; then
          set -a
          # shellcheck disable=SC1091
          source .env
          set +a
        fi

        export PGPASSWORD="${{OPENGAUSS_PASSWORD:-${{GS_PASSWORD:-OpenGauss@123}}}}"
        docker compose exec -T opengauss sh -lc "gsql -d \"${{OPENGAUSS_DATABASE:-{database}}}\" -U \"${{OPENGAUSS_USERNAME:-{user}}}\" -p \"${{OPENGAUSS_PORT:-5432}}\" -c \"$SQL\""
        """
    ).strip() + "\n"


def _render_backup_script(database: str, user: str) -> str:
    return textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
        cd "$ROOT"

        NAME="${{1:-backup-$(date +%Y%m%d-%H%M%S)}}"
        mkdir -p backups
        export PGPASSWORD="${{OPENGAUSS_PASSWORD:-${{GS_PASSWORD:-OpenGauss@123}}}}"
        docker compose exec -T opengauss sh -lc "gs_dump -d \"${{OPENGAUSS_DATABASE:-{database}}}\" -U \"${{OPENGAUSS_USERNAME:-{user}}}\" -p \"${{OPENGAUSS_PORT:-5432}}\" -f \"/workspace/backups/${{NAME}}.sql\""
        """
    ).strip() + "\n"


def _render_restore_script(database: str, user: str) -> str:
    return textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
        cd "$ROOT"

        FILE="${{1:-}}"
        if [[ -z "$FILE" ]]; then
          echo "Usage: $0 <backup-file.sql>" >&2
          exit 1
        fi
        export PGPASSWORD="${{OPENGAUSS_PASSWORD:-${{GS_PASSWORD:-OpenGauss@123}}}}"
        docker compose exec -T opengauss sh -lc "gs_restore -d \"${{OPENGAUSS_DATABASE:-{database}}}\" -U \"${{OPENGAUSS_USERNAME:-{user}}}\" -p \"${{OPENGAUSS_PORT:-5432}}\" \"/workspace/backups/$FILE\""
        """
    ).strip() + "\n"


def _render_readme(name: str, image: str, port: int, database: str, user: str) -> str:
    return textwrap.dedent(
        f"""
        # {_safe_name(name)}

        Local-first OpenGauss workspace scaffolded by Elyan.

        ## Included

        - `docker-compose.yml`
        - `.env.example`
        - `schema/init.sql`
        - `scripts/query.sh`
        - `scripts/backup.sh`
        - `scripts/restore.sh`

        ## Quick start

        ```sh
        cp .env.example .env
        docker compose up -d
        ./scripts/query.sh "SELECT 1;"
        ```

        ## Defaults

        - Image: `{image}`
        - Port: `{port}`
        - Database: `{database}`
        - User: `{user}`

        ## Notes

        - Queries run through `gsql` inside the container.
        - Use `./scripts/backup.sh` before migrations.
        - Use `./scripts/restore.sh <file.sql>` to restore a backup.
        """
    ).strip() + "\n"


def _render_manifest(name: str, image: str, port: int, database: str, user: str) -> str:
    return textwrap.dedent(
        f"""
        name: {_safe_name(name)}
        kind: opengauss
        image: {image}
        port: {port}
        database: {database}
        username: {user}
        created_at: {_now_iso()}
        updated_at: {_now_iso()}
        """
    ).strip() + "\n"


def scaffold_project(
    root: str | Path,
    *,
    name: str = "",
    image: str = "opengauss/opengauss-server:latest",
    port: int = 5432,
    database: str = "appdb",
    user: str = "root",
    password: str = "OpenGauss@123",
    include_samples: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root_path = _normalize_root(root)
    if root_path is None:
        raise ValueError("project root is required")

    root_path.mkdir(parents=True, exist_ok=True)
    (root_path / "schema").mkdir(parents=True, exist_ok=True)
    (root_path / "scripts").mkdir(parents=True, exist_ok=True)
    (root_path / "backups").mkdir(parents=True, exist_ok=True)
    (root_path / ".opengauss").mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "docker-compose.yml": _render_docker_compose(name or root_path.name, image, port, database, user, password),
        ".env.example": _render_env_example(name or root_path.name, image, port, database, user, password),
        "schema/init.sql": _render_init_sql(name or root_path.name, database) if include_samples else "-- add schema here\n",
        "scripts/query.sh": _render_query_script(database, user),
        "scripts/backup.sh": _render_backup_script(database, user),
        "scripts/restore.sh": _render_restore_script(database, user),
        "README.md": _render_readme(name or root_path.name, image, port, database, user),
        PROJECT_MANIFEST: _render_manifest(name or root_path.name, image, port, database, user),
    }

    writes: list[dict[str, Any]] = []
    for rel_path, content in files.items():
        target = root_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        if dry_run:
            writes.append({"path": str(target), "status": "planned", "existed": existed})
            continue
        if existed and not force:
            writes.append({"path": str(target), "status": "skipped", "existed": True})
            continue
        target.write_text(content, encoding="utf-8")
        if target.suffix == ".sh":
            try:
                target.chmod(0o755)
            except Exception:
                pass
        writes.append({"path": str(target), "status": "updated" if existed else "created", "existed": existed})

    project = summarize_project(root_path)
    return {
        "success": True,
        "status": "partial" if dry_run else "success",
        "project": project,
        "files": writes,
        "command": "cp .env.example .env && docker compose up -d",
        "next_steps": [
            "Copy .env.example to .env and review the database password.",
            "Start the container with docker compose up -d.",
            "Apply the sample schema with ./scripts/query.sh \"SELECT 1;\" or your own SQL.",
        ],
        "generated_at": _now_iso(),
    }


def build_query_command(
    *,
    project: dict[str, Any],
    sql: str,
    database: str = "",
    user: str = "",
    port: int | None = None,
) -> str:
    root = str(project.get("root") or "").strip()
    if not root or not sql.strip():
        return ""
    db_name = database or str(project.get("database") or "appdb")
    db_user = user or str(project.get("username") or "root")
    db_port = port or int(project.get("port") or 5432)
    quoted_sql = shlex.quote(sql.strip())
    return f"cd {shlex.quote(root)} && ./scripts/query.sh {quoted_sql} # db={db_name} user={db_user} port={db_port}"


def _is_destructive_sql(sql: str) -> bool:
    text = str(sql or "").strip()
    if not text:
        return False
    text = re.sub(r"--.*?$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"'(?:''|[^'])*'", "''", text)
    text = re.sub(r'"(?:\"\"|[^"])*"', '""', text)
    return bool(_DESTRUCTIVE_SQL_PATTERN.search(text))


def _run_query_script(root: Path, query: str, timeout: int) -> dict[str, Any]:
    script = root / "scripts" / "query.sh"
    if not script.exists():
        return {
            "success": False,
            "returncode": 127,
            "stdout": "",
            "stderr": "Query script not found.",
            "script": str(script),
        }

    try:
        completed = subprocess.run(
            ["bash", str(script), query],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout or 30)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "returncode": 124,
            "stdout": str(getattr(exc, "stdout", "") or ""),
            "stderr": "Query execution timed out.",
            "script": str(script),
        }
    except Exception as exc:
        return {
            "success": False,
            "returncode": 1,
            "stdout": "",
            "stderr": str(exc),
            "script": str(script),
        }

    return {
        "success": completed.returncode == 0,
        "returncode": int(completed.returncode),
        "stdout": str(completed.stdout or ""),
        "stderr": str(completed.stderr or ""),
        "script": str(script),
    }


def query_project(
    *,
    sql: str,
    path: str = "",
    database: str = "",
    user: str = "",
    port: int | None = None,
    backend: str = "docker",
    dry_run: bool = False,
    execute: bool = False,
    allow_mutation: bool = False,
    timeout: int = 30,
) -> dict[str, Any]:
    root = resolve_project_root(path) if path else None
    project = summarize_project(root or path) if (path or root) else {}
    if not project:
        return {
            "success": False,
            "status": "missing",
            "error": "No OpenGauss project found. Use opengauss_scaffold first.",
            "project": {},
        }

    query = str(sql or "").strip()
    if not query:
        return {
            "success": False,
            "status": "missing",
            "error": "SQL query is required.",
            "project": project,
        }

    command = build_query_command(project=project, sql=query, database=database, user=user, port=port)
    destructive = _is_destructive_sql(query)
    if execute and not dry_run and destructive and not allow_mutation:
        return {
            "success": False,
            "status": "blocked",
            "error": "Destructive SQL is blocked by default. Re-run with allow_mutation=True.",
            "project": project,
            "sql": query,
            "command": command,
            "destructive": True,
            "policy": {
                "allow_mutation": False,
                "execute": True,
                "timeout": int(timeout or 30),
            },
            "generated_at": _now_iso(),
        }

    if execute and not dry_run:
        root_value = Path(str(project.get("root") or path or ".")).expanduser()
        execution = _run_query_script(root_value, query, timeout)
        success = bool(execution.get("success", False))
        return {
            "success": success,
            "status": "success" if success else "failed",
            "backend": backend,
            "project": project,
            "sql": query,
            "command": command,
            "execution": execution,
            "destructive": destructive,
            "policy": {
                "allow_mutation": bool(allow_mutation),
                "execute": True,
                "timeout": int(timeout or 30),
            },
            "message": "OpenGauss query executed." if success else "OpenGauss query failed.",
            "next_steps": [
                "Review stdout and stderr before promoting the query.",
                "Use backups before any mutation.",
                "Prefer dry-run planning for destructive statements.",
            ],
            "generated_at": _now_iso(),
        }

    return {
        "success": True,
        "status": "partial",
        "backend": backend,
        "project": project,
        "sql": query,
        "command": command,
        "destructive": destructive,
        "policy": {
            "allow_mutation": bool(allow_mutation),
            "execute": False,
            "timeout": int(timeout or 30),
        },
        "message": f"OpenGauss query plan ready{' (dry-run)' if dry_run else ''}.",
        "next_steps": [
            "Start the database with docker compose up -d.",
            "Run the generated query script or a manually reviewed SQL statement.",
            "Apply schema changes through versioned SQL files and backups.",
        ],
        "data": {
            "database": database or project.get("database") or "appdb",
            "user": user or project.get("username") or "root",
            "port": int(port or project.get("port") or 5432),
        },
        "generated_at": _now_iso(),
    }
