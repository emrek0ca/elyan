from __future__ import annotations

import json
import re
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

PROJECT_MARKERS = ("basic_rag_workflow.yaml",)
TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
}


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
    return text.strip("-") or "quivr-second-brain"


def _safe_name(value: str) -> str:
    text = str(value or "").strip()
    return text or "Quivr Second Brain"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _looks_like_quivr_project(root: Path) -> bool:
    requirements = _read_text(root / "requirements.txt").lower()
    pyproject = _read_text(root / "pyproject.toml").lower()
    brain_text = _read_text(root / "brain.py")
    workflow_exists = any((root / marker).exists() for marker in PROJECT_MARKERS)
    if workflow_exists and (root / "brain.py").exists():
        return True
    if workflow_exists and (root / "quivr_chat.py").exists():
        return True
    if "quivr-core" in requirements or "quivr_core" in requirements:
        return True
    if "quivr-core" in pyproject or "quivr_core" in pyproject:
        return True
    if "Brain.from_files" in brain_text or "RetrievalConfig.from_yaml" in brain_text:
        return True
    if "Brain.ask" in brain_text and (root / "quivr_chat.py").exists():
        return True
    return False


def detect_project_root(start: str | Path | None = None) -> Path | None:
    candidate = _normalize_root(start) or Path.cwd().resolve()
    for root in [candidate, *candidate.parents]:
        if _looks_like_quivr_project(root):
            return root
    return None


def resolve_project_root(path: str | Path | None = None) -> Path | None:
    root = _normalize_root(path)
    if root and root.exists():
        return detect_project_root(root)
    return detect_project_root(path)


def discover_brain_sources(root: str | Path) -> list[str]:
    root_path = _normalize_root(root)
    if root_path is None:
        return []

    candidates: list[Path] = []
    for name in ("README.md", "brain.py", "quivr_chat.py", "basic_rag_workflow.yaml"):
        candidate = root_path / name
        if candidate.exists():
            candidates.append(candidate)

    for folder_name in ("docs", "knowledge", "content"):
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

    requirements_path = root_path / "requirements.txt"
    pyproject_path = root_path / "pyproject.toml"
    workflow_path = root_path / "basic_rag_workflow.yaml"
    brain_path = root_path / "brain.py"
    chat_path = root_path / "quivr_chat.py"
    sample_doc_path = root_path / "docs" / "sample_knowledge.md"
    readme_path = root_path / "README.md"

    requirements_text = _read_text(requirements_path).lower()
    pyproject_text = _read_text(pyproject_path).lower()
    workflow_text = _read_text(workflow_path)
    brain_text = _read_text(brain_path)
    chat_text = _read_text(chat_path)
    readme_text = _read_text(readme_path)
    sample_doc_text = _read_text(sample_doc_path)

    features: list[str] = []
    if "quivr-core" in requirements_text or "quivr_core" in requirements_text or "quivr-core" in pyproject_text:
        features.append("quivr_core")
    if "Brain.from_files" in brain_text:
        features.append("brain_from_files")
    if "RetrievalConfig.from_yaml" in brain_text or "basic_rag_workflow.yaml" in workflow_text:
        features.append("retrieval_config")
    if "brain.ask" in brain_text or "ask(" in chat_text:
        features.append("query_loop")
    if workflow_path.exists():
        features.append("workflow_yaml")
    if sample_doc_path.exists():
        features.append("sample_docs")
    if "megaparse" in readme_text.lower() or "megaparse" in workflow_text.lower():
        features.append("megaparse_notes")
    if "ollama" in readme_text.lower() or "local models" in readme_text.lower():
        features.append("local_models")
    if "ask your brain" in readme_text.lower() or "second brain" in readme_text.lower():
        features.append("second_brain")
    if "pipeline" in readme_text.lower() or "workflow" in readme_text.lower():
        features.append("workflow_notes")
    if sample_doc_text:
        features.append("knowledge_seed")

    ready = {"quivr_core", "brain_from_files", "retrieval_config", "query_loop", "workflow_yaml"}.issubset(set(features))

    return {
        "root": str(root_path),
        "name": str(root_path.name or "quivr"),
        "slug": _slugify(root_path.name),
        "status": "ready" if ready else "scaffolded",
        "ready": ready,
        "features": sorted(set(features)),
        "requirements_path": str(requirements_path),
        "pyproject_path": str(pyproject_path),
        "workflow_path": str(workflow_path),
        "brain_path": str(brain_path),
        "chat_path": str(chat_path),
        "sample_doc_path": str(sample_doc_path),
        "readme_path": str(readme_path),
        "has_requirements": requirements_path.exists(),
        "has_pyproject": pyproject_path.exists(),
        "has_workflow": workflow_path.exists(),
        "has_brain": brain_path.exists(),
        "has_chat": chat_path.exists(),
        "has_sample_docs": sample_doc_path.exists(),
        "source_files": discover_brain_sources(root_path),
        "updated_at": _now_iso(),
    }


def build_quivr_prompt(
    action: str,
    *,
    project: dict[str, Any],
    goal: str = "",
    target: str = "",
    backend: str = "auto",
) -> str:
    root = str(project.get("root") or "").strip()
    name = str(project.get("name") or project.get("slug") or "Quivr").strip()
    lines = [
        "You are Elyan's Quivr operator.",
        f"Project: {name}",
        f"Project root: {root}",
        f"Task: {str(action or 'starter').strip().lower() or 'starter'}",
        f"Backend: {backend}",
        "Use Quivr patterns: Brain.from_files, Brain.ask, RetrievalConfig.from_yaml, Megaparse, and any LLM.",
        "Prefer grounded answers, file-backed retrieval, and concise second-brain workflows.",
        "Support PDF, TXT, Markdown, and custom file parsers.",
    ]
    if goal:
        lines.append(f"Goal: {goal}")
    if target:
        lines.append(f"Target: {target}")
    lines.extend(
        [
            "Keep the starter deployable, local-first, and easy to extend.",
            "Return a compact plan, generated files, and the next action.",
        ]
    )
    return "\n".join(lines)


def build_quivr_bundle(
    action: str,
    *,
    project: dict[str, Any],
    goal: str = "",
    target: str = "",
    backend: str = "auto",
) -> dict[str, Any]:
    root = str(project.get("root") or "").strip()
    bundle_id = f"quivr_{str(action or 'starter').strip().lower() or 'starter'}"
    prompt = build_quivr_prompt(action, project=project, goal=goal, target=target, backend=backend)
    return {
        "id": bundle_id,
        "name": "Quivr Second Brain Starter",
        "category": "knowledge",
        "required_skills": ["quivr", "research", "files"],
        "required_tools": ["quivr_status", "quivr_project", "quivr_scaffold", "quivr_brain_ask"],
        "steps": [
            {
                "id": "inspect_brain",
                "action": "quivr_project",
                "params": {"action": "status", "path": root},
            },
            {
                "id": "scaffold_brain",
                "action": "quivr_scaffold",
                "params": {"path": root, "name": project.get("name") or ""},
            },
            {
                "id": "ask_brain",
                "action": "quivr_brain_ask",
                "params": {"path": root, "question": goal or "What does this brain know?"},
            },
        ],
        "trigger_markers": [
            "quivr",
            "quivr-core",
            "second brain",
            "brain.from_files",
            "retrievalconfig",
            "retrieval config",
            "megaparse",
            "knowledge base",
            "ask your brain",
        ],
        "objective": "build_second_brain_rag_stack",
        "prompt": prompt,
        "command": "pip install quivr-core && python brain.py",
        "project_root": root,
        "project_name": str(project.get("name") or ""),
        "output_artifacts": ["brain_py", "quivr_chat_py", "basic_rag_workflow_yaml", "requirements_txt", "sample_docs"],
        "quality_checklist": [
            "grounded_answers",
            "retrieval_config",
            "source_coverage",
            "file_ingestion",
            "deployability",
        ],
        "auto_intent": True,
    }


def _tokenize_quivr_terms(text: str) -> set[str]:
    return {token for token in re.findall(r"\w+", str(text or "").lower()) if len(token) > 2}


def _score_quivr_line(question_terms: set[str], line: str) -> float:
    clean_line = str(line or "").strip().lower()
    if not clean_line or not question_terms:
        return 0.0
    hits = [term for term in question_terms if term in clean_line]
    if not hits:
        return 0.0
    score = len(hits) / max(len(question_terms), 1)
    if "second brain" in clean_line or "brain.from_files" in clean_line:
        score += 0.2
    if "retrieval" in clean_line or "knowledge" in clean_line:
        score += 0.1
    return min(1.0, score)


def _fast_quivr_answer(
    question: str,
    source_paths: Sequence[str],
    *,
    project: dict[str, Any],
    retrieval_config_path: str = "",
) -> dict[str, Any]:
    question_terms = _tokenize_quivr_terms(question)
    ranked_hits: list[dict[str, Any]] = []
    matched_sources: set[str] = set()

    for raw_path in source_paths:
        path = Path(raw_path)
        text = _read_text(path)
        if not text:
            continue

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            snippet = text.strip()[:240]
            if snippet:
                ranked_hits.append(
                    {
                        "citation_id": f"S{len(ranked_hits) + 1}",
                        "source_name": path.name or str(path),
                        "source_path": str(path),
                        "line_number": 1,
                        "score": 0.05,
                        "snippet": snippet,
                    }
                )
                matched_sources.add(str(path))
            continue

        local_hits: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            score = _score_quivr_line(question_terms, line)
            if score <= 0:
                continue
            local_hits.append(
                {
                    "citation_id": "",
                    "source_name": path.name or str(path),
                    "source_path": str(path),
                    "line_number": line_number,
                    "score": round(score, 4),
                    "snippet": line[:320],
                }
            )

        local_hits.sort(key=lambda item: item["score"], reverse=True)
        for hit in local_hits[:3]:
            matched_sources.add(str(path))
            ranked_hits.append(hit)

    ranked_hits.sort(key=lambda item: item["score"], reverse=True)
    selected = ranked_hits[:5]
    for idx, hit in enumerate(selected, start=1):
        hit["citation_id"] = f"S{idx}"

    selected_snippets = [str(hit["snippet"]) for hit in selected if str(hit.get("snippet") or "").strip()]
    if selected_snippets:
        intro = "Kısa cevap: Quivr, second-brain ve grounded dosya sorgulama akışı kurmana yardımcı olur."
        if any("second brain" in snippet.lower() for snippet in selected_snippets):
            intro = "Kısa cevap: Quivr, second brain (ikinci beyin) kurmanı kolaylaştırır."
        answer_lines = [intro]
        answer_lines.extend(f"- [{hit['citation_id']}] {hit['snippet']}" for hit in selected)
        answer_lines.extend(
            [
                "",
                "Daha fazla ayrıntı istersen kaynak kapsamını genişletebilirim.",
            ]
        )
        confidence = min(
            0.95,
            0.45 + (sum(float(hit["score"]) for hit in selected) / max(len(selected), 1)) * 0.35 + len(selected) * 0.03,
        )
        status = "success" if selected and float(selected[0]["score"]) >= 0.2 else "partial"
    else:
        answer_lines = [
            "Quivr fallback çalıştı, ancak bu kaynaklarda yeterli grounded kanıt bulunamadı.",
            "İstersen daha fazla dosya ekleyebilir veya kapsamı genişletebilirim.",
        ]
        confidence = 0.0
        status = "partial"

    indexed_count = len(matched_sources)
    failed_count = max(len(source_paths) - indexed_count, 0)

    return {
        "success": True,
        "status": status,
        "backend": "elyan_document_rag",
        "retrieval_mode": "lexical",
        "project": project,
        "question": str(question or "").strip(),
        "answer": "\n".join(answer_lines).strip(),
        "confidence": round(confidence, 3),
        "source_paths": [str(Path(item).expanduser().resolve()) for item in source_paths],
        "retrieval_config_path": retrieval_config_path,
        "message": answer_lines[0] if answer_lines else "Quivr fallback completed.",
        "data": {
            "backend": "elyan_document_rag",
            "retrieval_mode": "lexical",
            "question": str(question or "").strip(),
            "answer": "\n".join(answer_lines).strip(),
            "confidence": round(confidence, 3),
        },
        "qa_success": bool(selected_snippets),
        "index_success": bool(source_paths),
        "indexed_count": indexed_count,
        "failed_count": failed_count,
        "citations": [
            {
                "citation_id": hit["citation_id"],
                "source_name": hit["source_name"],
                "source_path": hit["source_path"],
                "line_number": hit["line_number"],
                "score": hit["score"],
                "snippet": hit["snippet"],
            }
            for hit in selected
        ],
        "notes": "Fast lexical fallback answer path",
    }


def _render_requirements_txt() -> str:
    return "\n".join(
        [
            "quivr-core",
            "pyyaml",
        ]
    ) + "\n"


def _render_basic_rag_workflow_yaml(name: str) -> str:
    return textwrap.dedent(
        """
        workflow_config:
          name: "standard RAG"
          nodes:
            - name: "START"
              edges: ["filter_history"]

            - name: "filter_history"
              edges: ["rewrite"]

            - name: "rewrite"
              edges: ["retrieve"]

            - name: "retrieve"
              edges: ["generate_rag"]

            - name: "generate_rag"
              edges: ["END"]
          max_history: 10

        reranker_config:
          supplier: "cohere"
          model: "rerank-multilingual-v3.0"
          top_n: 5

        llm_config:
          max_input_tokens: 4000
          temperature: 0.7
        """
    ).strip() + "\n"


def _render_brain_py(name: str) -> str:
    app_name = _safe_name(name)
    return textwrap.dedent(
        """
        from __future__ import annotations

        from pathlib import Path
        from typing import Iterable

        from quivr_core import Brain
        from quivr_core.config import RetrievalConfig

        APP_NAME = "__APP_NAME__"
        ROOT = Path(__file__).resolve().parent
        SOURCE_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".yaml", ".yml"}


        def collect_source_files() -> list[str]:
            files: list[str] = []
            for relative in ("README.md", "basic_rag_workflow.yaml"):
                candidate = ROOT / relative
                if candidate.exists():
                    files.append(str(candidate))

            for folder_name in ("docs", "knowledge", "content"):
                folder = ROOT / folder_name
                if not folder.exists():
                    continue
                for path in sorted(folder.rglob("*")):
                    if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
                        files.append(str(path))

            ordered: list[str] = []
            seen: set[str] = set()
            for item in files:
                clean = str(Path(item).expanduser().resolve())
                if clean in seen:
                    continue
                seen.add(clean)
                ordered.append(clean)
            return ordered


        def load_retrieval_config(path: str | None = None):
            workflow_path = Path(path or (ROOT / "basic_rag_workflow.yaml")).expanduser()
            if not workflow_path.exists():
                return None
            return RetrievalConfig.from_yaml(str(workflow_path))


        def build_brain(file_paths: Iterable[str] | None = None) -> Brain:
            sources = [str(Path(item).expanduser().resolve()) for item in list(file_paths or []) if str(item or "").strip()]
            if not sources:
                sources = collect_source_files()
            if not sources:
                raise SystemExit("No source files found. Add documents to docs/ or knowledge/.")
            return Brain.from_files(name=APP_NAME, file_paths=sources)


        def ask(question: str, *, file_paths: Iterable[str] | None = None, retrieval_config_path: str | None = None, brain: Brain | None = None) -> str:
            active_brain = brain or build_brain(file_paths=file_paths)
            retrieval_config = load_retrieval_config(retrieval_config_path)
            if retrieval_config is None:
                answer = active_brain.ask(question)
            else:
                answer = active_brain.ask(question, retrieval_config=retrieval_config)
            return str(getattr(answer, "answer", answer)).strip()


        def main() -> int:
            brain = build_brain()
            print(f"{APP_NAME} ready. Type 'exit' to quit.")
            while True:
                try:
                    question = input("Question: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if question.lower() in {"exit", "quit"}:
                    break
                answer = ask(question, brain=brain)
                print()
                print(answer)
                print()
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        """
    ).replace("__APP_NAME__", app_name)


def _render_chat_py(name: str) -> str:
    app_name = _safe_name(name)
    return textwrap.dedent(
        """
        from __future__ import annotations

        from brain import ask, build_brain

        APP_NAME = "__APP_NAME__ Chat"


        def main() -> int:
            brain = build_brain()
            print(f"{APP_NAME} ready. Type 'exit' to quit.")
            while True:
                try:
                    question = input("Question: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if question.lower() in {"exit", "quit"}:
                    break
                print()
                print(ask(question, brain=brain))
                print()
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        """
    ).replace("__APP_NAME__", app_name)


def _render_sample_knowledge_md(name: str) -> str:
    app_name = _safe_name(name)
    return textwrap.dedent(
        """
        # Sample Knowledge

        __APP_NAME__ is a Quivr-style second brain starter.

        Quivr uses `Brain.from_files` to ingest PDFs, TXT, Markdown, and custom files.
        Quivr asks questions with `Brain.ask` and can be tuned with `RetrievalConfig.from_yaml`.
        It supports any LLM and can use local models such as Ollama.
        Megaparse can be added for richer ingestion pipelines when you need broader file coverage.

        This starter exists so Elyan can answer grounded questions about a local knowledge base.
        """
    ).replace("__APP_NAME__", app_name)


def _render_readme(name: str, include_samples: bool) -> str:
    app_name = _safe_name(name)
    lines = [
        f"# {app_name}",
        "",
        "Quivr second brain starter generated by Elyan.",
        "",
        "## What is included",
        "",
        "- `Brain.from_files` to ingest local knowledge files.",
        "- `Brain.ask` for grounded second-brain Q&A.",
        "- `RetrievalConfig.from_yaml` for configurable RAG workflows.",
        "- Any-file ingestion with optional Megaparse integration.",
        "- Local-first support for Ollama or any supported LLM provider.",
    ]
    if include_samples:
        lines.append("- Sample knowledge docs to make the brain usable immediately.")
    lines.extend(
        [
            "",
            "## Quick start",
            "",
            "```sh",
            "pip install -r requirements.txt",
            "python brain.py",
            "python quivr_chat.py",
            "```",
            "",
            "## Notes",
            "",
            "- Place your docs in `docs/` or `knowledge/`.",
            "- Tune retrieval in `basic_rag_workflow.yaml`.",
            "- Add custom parsers or internet search when you are ready to extend the brain.",
        ]
    )
    return "\n".join(lines) + "\n"


def scaffold_project(
    root: str | Path,
    *,
    name: str = "",
    include_samples: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root_path = _normalize_root(root)
    if root_path is None:
        raise ValueError("project root is required")

    root_path.mkdir(parents=True, exist_ok=True)
    docs_dir = root_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "requirements.txt": _render_requirements_txt(),
        "basic_rag_workflow.yaml": _render_basic_rag_workflow_yaml(name or root_path.name),
        "brain.py": _render_brain_py(name or root_path.name),
        "quivr_chat.py": _render_chat_py(name or root_path.name),
        "README.md": _render_readme(name or root_path.name, include_samples),
    }
    if include_samples:
        files["docs/sample_knowledge.md"] = _render_sample_knowledge_md(name or root_path.name)

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
        writes.append({"path": str(target), "status": "updated" if existed else "created", "existed": existed})

    project = summarize_project(root_path)
    return {
        "success": True,
        "status": "partial" if dry_run else "success",
        "project": project,
        "files": writes,
        "command": "pip install -r requirements.txt && python brain.py",
        "next_steps": [
            "Install quivr-core and tune the workflow YAML.",
            "Place more source files in docs/ or knowledge/.",
            "Use the chat loop to validate retrieval and grounded answers.",
        ],
        "generated_at": _now_iso(),
    }


async def ask_quivr_brain(
    *,
    question: str,
    path: str = "",
    file_paths: Sequence[str] | None = None,
    retrieval_config_path: str = "",
    backend: str = "auto",
    use_llm: bool = False,
    storage_dir: str | Path | None = None,
) -> dict[str, Any]:
    clean_question = str(question or "").strip()
    if not clean_question:
        return {"success": False, "status": "missing", "error": "question required"}

    root = resolve_project_root(path) or _normalize_root(path)
    source_paths: list[str] = []
    if file_paths:
        source_paths.extend(str(Path(item).expanduser().resolve()) for item in file_paths if str(item or "").strip())
    if not source_paths and root is not None:
        source_paths.extend(discover_brain_sources(root))
    source_paths = [str(Path(item).expanduser().resolve()) for item in source_paths if str(item or "").strip()]

    project = summarize_project(root) if root is not None else {}
    preferred_backend = str(backend or "auto").strip().lower() or "auto"
    retrieval_path = str(retrieval_config_path or "").strip()

    if preferred_backend in {"auto", "quivr_core"} and source_paths:
        try:
            from quivr_core import Brain
            from quivr_core.config import RetrievalConfig

            brain_name = str(project.get("name") or (root.name if root else "quivr-brain") or "quivr-brain")
            brain = Brain.from_files(name=brain_name, file_paths=source_paths)
            retrieval_config = None
            if retrieval_path:
                workflow_candidate = Path(retrieval_path).expanduser()
                if workflow_candidate.exists():
                    retrieval_config = RetrievalConfig.from_yaml(str(workflow_candidate))
            elif root is not None:
                default_workflow = root / "basic_rag_workflow.yaml"
                if default_workflow.exists():
                    retrieval_config = RetrievalConfig.from_yaml(str(default_workflow))
            answer = brain.ask(clean_question, retrieval_config=retrieval_config) if retrieval_config else brain.ask(clean_question)
            return {
                "success": True,
                "status": "success",
                "backend": "quivr_core",
                "project": project,
                "question": clean_question,
                "answer": str(getattr(answer, "answer", answer)).strip(),
                "confidence": float(getattr(answer, "confidence", 0.0) or 0.0),
                "source_paths": source_paths,
                "retrieval_config_path": retrieval_path,
                "message": str(getattr(answer, "answer", answer)).strip()[:240],
                "data": {
                    "backend": "quivr_core",
                    "retrieval_mode": "quivr_core",
                    "question": clean_question,
                    "answer": str(getattr(answer, "answer", answer)).strip(),
                },
                "notes": "Quivr-core answer path",
            }
        except Exception as exc:
            if preferred_backend == "quivr_core":
                return {
                    "success": False,
                    "status": "failed",
                    "backend": "quivr_core",
                    "project": project,
                    "question": clean_question,
                    "error": str(exc),
                    "source_paths": source_paths,
                }

    if not source_paths:
        return {
            "success": False,
            "status": "missing",
            "backend": "elyan_document_rag",
            "project": project,
            "question": clean_question,
            "error": "No source files found for fallback RAG.",
        }
    return _fast_quivr_answer(
        clean_question,
        source_paths,
        project=project,
        retrieval_config_path=retrieval_path,
    )
