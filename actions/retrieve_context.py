from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from actions._read_only_common import content_type_for, preview_text, workspace_root
from actions.document_read import _extract_document_text
from runtime import native_file_indexer
from runtime import state_store
from runtime.capability_registry import SafeCapabilityError


_WORKSPACE_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".csv", ".pdf", ".docx"}
_SKIP_DIR_NAMES = {
    ".git",
    ".dart_tool",
    ".idea",
    ".vscode",
    "build",
    "dist",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
}
_MAX_WORKSPACE_FILES = 40
_MAX_CONVERSATIONS = 10
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 120
_MAX_WORKSPACE_CHUNKS = 240
_MAX_CONVERSATION_CHUNKS = 80
_MAX_MATCH_SNIPPET_CHARS = 400
_EMBEDDING_MODEL_DEFAULT = "all-MiniLM-L6-v2"
_RETRIEVAL_CACHE_VERSION = 3


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _workspace_root() -> Path:
    return workspace_root()


def _retrieval_dir() -> Path:
    return state_store.CONFIG_DIR / "retrieval"


def _index_cache_path() -> Path:
    return _retrieval_dir() / "index.json"


def _embeddings_cache_path() -> Path:
    return _retrieval_dir() / "embeddings.json"


def _embedding_model_name() -> str:
    return str(os.environ.get("ELYAN_SENTENCE_TRANSFORMERS_MODEL", _EMBEDDING_MODEL_DEFAULT) or _EMBEDDING_MODEL_DEFAULT)


def _empty_index() -> dict[str, Any]:
    return {
        "version": _RETRIEVAL_CACHE_VERSION,
        "indexedAt": "",
        "lastStrategy": "lexical",
        "workspace": {},
        "conversations": {},
        "localFiles": {},
    }


def _empty_embeddings_cache(model_name: str) -> dict[str, Any]:
    return {
        "version": _RETRIEVAL_CACHE_VERSION,
        "model": model_name,
        "updatedAt": "",
        "vectors": {},
    }


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return copy.deepcopy(default)
    if not isinstance(payload, dict):
        return copy.deepcopy(default)
    return payload


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_index_cache() -> dict[str, Any]:
    payload = _load_json(_index_cache_path(), _empty_index())
    if int(payload.get("version", 0) or 0) != _RETRIEVAL_CACHE_VERSION:
        return _empty_index()
    return payload


def _save_index_cache(payload: dict[str, Any]) -> None:
    normalized = {
        "version": _RETRIEVAL_CACHE_VERSION,
        "indexedAt": str(payload.get("indexedAt", "") or ""),
        "lastStrategy": str(payload.get("lastStrategy", "lexical") or "lexical"),
        "workspace": payload.get("workspace", {}) if isinstance(payload.get("workspace"), dict) else {},
        "conversations": payload.get("conversations", {}) if isinstance(payload.get("conversations"), dict) else {},
        "localFiles": payload.get("localFiles", {}) if isinstance(payload.get("localFiles"), dict) else {},
    }
    _save_json(_index_cache_path(), normalized)


def _load_embeddings_cache(model_name: str) -> dict[str, Any]:
    payload = _load_json(_embeddings_cache_path(), _empty_embeddings_cache(model_name))
    if int(payload.get("version", 0) or 0) != _RETRIEVAL_CACHE_VERSION:
        return _empty_embeddings_cache(model_name)
    if str(payload.get("model", "") or "") != model_name:
        return _empty_embeddings_cache(model_name)
    return payload


def _save_embeddings_cache(payload: dict[str, Any]) -> None:
    normalized = {
        "version": _RETRIEVAL_CACHE_VERSION,
        "model": str(payload.get("model", "") or _embedding_model_name()),
        "updatedAt": str(payload.get("updatedAt", "") or ""),
        "vectors": payload.get("vectors", {}) if isinstance(payload.get("vectors"), dict) else {},
    }
    _save_json(_embeddings_cache_path(), normalized)


def _iter_workspace_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIR_NAMES and not name.startswith(".")]
        base = Path(current_root)
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            path = base / filename
            if path.suffix.lower() not in _WORKSPACE_SUFFIXES:
                continue
            candidates.append(path)
            if len(candidates) >= _MAX_WORKSPACE_FILES:
                return candidates
    return candidates


def _chunk_text(text: str, *, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start += step
    return chunks


def _stable_chunk_id(source: str, identity: str, chunk_index: int) -> str:
    raw = f"{source}:{identity}:{chunk_index}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:16]


def _fingerprint(*parts: Any) -> str:
    raw = ":".join(str(part or "").strip() for part in parts).encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:20]


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return path.name


def _approved_root_for_path(path: Path) -> dict[str, str]:
    for item in native_file_indexer.approved_roots():
        root_path = Path(str(item.get("path", "") or "")).expanduser()
        try:
            resolved_root = root_path.resolve()
            resolved_path = path.resolve()
        except Exception:
            continue
        if resolved_root == resolved_path or resolved_root in resolved_path.parents:
            return {
                "path": str(resolved_root),
                "label": str(item.get("label", "") or resolved_root.name or "Approved root"),
                "relativePath": _relative_path(resolved_path, resolved_root),
            }
    return {
        "path": "",
        "label": "",
        "relativePath": path.name,
    }


def _normalize_tokens(value: str) -> list[str]:
    normalized = (
        str(value or "")
        .lower()
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    return re.findall(r"[a-z0-9]+", normalized)


def _lexical_score(query: str, candidate: str) -> float:
    query_tokens = set(_normalize_tokens(query))
    candidate_tokens = set(_normalize_tokens(candidate))
    overlap = 0.0
    if query_tokens and candidate_tokens:
        overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens), 1)
    ratio = difflib.SequenceMatcher(None, " ".join(query_tokens), " ".join(candidate_tokens)).ratio()
    return max(overlap, ratio)


@lru_cache(maxsize=1)
def _sentence_transformer_model() -> Any | None:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[reportMissingImports]
    except Exception:
        return None
    model_name = _embedding_model_name()
    try:
        return SentenceTransformer(model_name)
    except Exception:
        return None


def _vector_list(value: Any) -> list[float]:
    raw = value.tolist() if hasattr(value, "tolist") else list(value)
    return [round(float(item), 6) for item in raw]


def _workspace_entries(existing_workspace: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = _workspace_root().resolve()
    next_workspace: dict[str, Any] = {}
    chunks: list[dict[str, Any]] = []

    for path in _iter_workspace_files(root):
        try:
            resolved = path.resolve()
            stat = resolved.stat()
        except OSError:
            continue
        cache_key = str(resolved)
        relative_path = _relative_path(resolved, root)
        indexed_at = _utc_now_iso()
        cached = existing_workspace.get(cache_key, {})
        entry: dict[str, Any] | None = None
        if (
            isinstance(cached, dict)
            and cached.get("mtime") == stat.st_mtime_ns
            and cached.get("size") == stat.st_size
            and isinstance(cached.get("chunks"), list)
            and cached.get("chunks")
        ):
            entry = copy.deepcopy(cached)
            entry["indexedAt"] = indexed_at
        else:
            try:
                text, pages = _extract_document_text(resolved)
            except Exception:
                continue
            text_chunks = _chunk_text(text)
            if not text_chunks:
                continue
            identity = f"{cache_key}:{stat.st_mtime_ns}:{stat.st_size}"
            fingerprint = _fingerprint(cache_key, stat.st_mtime_ns, stat.st_size)
            chunk_items: list[dict[str, Any]] = []
            for index, chunk_text in enumerate(text_chunks):
                chunk_items.append(
                    {
                        "source": "workspace",
                        "chunkId": _stable_chunk_id("workspace", identity, index),
                        "title": resolved.name,
                        "snippet": preview_text(chunk_text, limit=_MAX_MATCH_SNIPPET_CHARS),
                        "text": chunk_text,
                        "path": cache_key,
                        "relativePath": relative_path,
                        "contentType": content_type_for(resolved),
                        "pages": pages,
                        "mtime": stat.st_mtime_ns,
                        "size": stat.st_size,
                        "indexedAt": indexed_at,
                        "fingerprint": fingerprint,
                    }
                )
            entry = {
                "path": cache_key,
                "relativePath": relative_path,
                "title": resolved.name,
                "mtime": stat.st_mtime_ns,
                "size": stat.st_size,
                "fingerprint": fingerprint,
                "contentType": content_type_for(resolved),
                "pages": pages,
                "chunkCount": len(chunk_items),
                "indexedAt": indexed_at,
                "chunks": chunk_items,
            }
        if entry is None:
            continue
        remaining = _MAX_WORKSPACE_CHUNKS - len(chunks)
        if remaining <= 0:
            break
        chunk_list = entry.get("chunks", [])
        if not isinstance(chunk_list, list):
            continue
        bounded_chunks = [copy.deepcopy(item) for item in chunk_list[:remaining] if isinstance(item, dict)]
        if not bounded_chunks:
            continue
        entry["chunks"] = bounded_chunks
        next_workspace[cache_key] = entry
        chunks.extend(copy.deepcopy(item) for item in bounded_chunks)
        if len(chunks) >= _MAX_WORKSPACE_CHUNKS:
            break

    return next_workspace, chunks


def _conversation_entries(existing_conversations: dict[str, Any], conversation_id: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = state_store.snapshot()
    conversation_state = state.get("conversation", {})
    items = conversation_state.get("items", []) if isinstance(conversation_state, dict) else []
    if not isinstance(items, list):
        return {}, []

    ordered = sorted(
        [item for item in items if isinstance(item, dict)],
        key=lambda entry: str(entry.get("updatedAt", "") or ""),
        reverse=True,
    )
    if conversation_id:
        ordered.sort(key=lambda entry: str(entry.get("id", "") or "") != conversation_id)

    next_conversations: dict[str, Any] = {}
    chunks: list[dict[str, Any]] = []

    for item in ordered[:_MAX_CONVERSATIONS]:
        conv_id = str(item.get("id", "") or "").strip()
        if not conv_id:
            continue
        updated_at = str(item.get("updatedAt", "") or "")
        cache_key = conv_id
        indexed_at = _utc_now_iso()
        cached = existing_conversations.get(cache_key, {})
        entry: dict[str, Any] | None = None
        if (
            isinstance(cached, dict)
            and str(cached.get("updatedAt", "") or "") == updated_at
            and isinstance(cached.get("chunks"), list)
            and cached.get("chunks")
        ):
            entry = copy.deepcopy(cached)
            entry["indexedAt"] = indexed_at
        else:
            messages = item.get("messages", [])
            if not isinstance(messages, list):
                continue
            lines: list[str] = []
            message_count = 0
            for message in messages[-12:]:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role", "") or "user").strip() or "user"
                text = " ".join(str(message.get("text", "") or "").split()).strip()
                if not text:
                    continue
                message_count += 1
                lines.append(f"{role}: {text}")
            text_chunks = _chunk_text("\n".join(lines))
            if not text_chunks:
                continue
            identity = f"{conv_id}:{updated_at}"
            fingerprint = _fingerprint(conv_id, updated_at, message_count)
            chunk_items: list[dict[str, Any]] = []
            for index, chunk_text in enumerate(text_chunks):
                chunk_items.append(
                    {
                        "source": "conversations",
                        "chunkId": _stable_chunk_id("conversations", identity, index),
                        "title": str(item.get("title", "") or conv_id or "conversation"),
                        "snippet": preview_text(chunk_text, limit=_MAX_MATCH_SNIPPET_CHARS),
                        "text": chunk_text,
                        "conversationId": conv_id,
                        "updatedAt": updated_at,
                        "messageWindow": message_count,
                        "indexedAt": indexed_at,
                        "fingerprint": fingerprint,
                    }
                )
            entry = {
                "conversationId": conv_id,
                "title": str(item.get("title", "") or conv_id or "conversation"),
                "updatedAt": updated_at,
                "messageWindow": message_count,
                "chunkCount": len(chunk_items),
                "fingerprint": fingerprint,
                "indexedAt": indexed_at,
                "chunks": chunk_items,
            }
        if entry is None:
            continue
        remaining = _MAX_CONVERSATION_CHUNKS - len(chunks)
        if remaining <= 0:
            break
        chunk_list = entry.get("chunks", [])
        if not isinstance(chunk_list, list):
            continue
        bounded_chunks = [copy.deepcopy(chunk) for chunk in chunk_list[:remaining] if isinstance(chunk, dict)]
        if not bounded_chunks:
            continue
        entry["chunks"] = bounded_chunks
        next_conversations[cache_key] = entry
        chunks.extend(copy.deepcopy(item) for item in bounded_chunks)
        if len(chunks) >= _MAX_CONVERSATION_CHUNKS:
            break

    return next_conversations, chunks


def _local_file_preview_text(item: dict[str, Any], resolved: Path) -> str:
    metadata_text = " ".join(
        part
        for part in [
            str(item.get("name", "") or "").strip(),
            str(item.get("path", "") or "").strip(),
            str(item.get("rootLabel", "") or "").strip(),
        ]
        if part
    ).strip()
    try:
        extracted_text, _pages = _extract_document_text(resolved)
    except Exception:
        return metadata_text
    trimmed = preview_text(extracted_text, limit=4000)
    if not trimmed:
        return metadata_text
    return f"{metadata_text}\n{trimmed}".strip() if metadata_text else trimmed


def _local_file_entries(existing_local_files: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    metadata_items, index_status = native_file_indexer.ensure_index(force=False)
    if not index_status.get("ready", False) or not metadata_items:
        return {}, [], index_status

    next_local_files: dict[str, Any] = {}
    chunks: list[dict[str, Any]] = []

    for item in metadata_items:
        path_text = str(item.get("path", "") or "").strip()
        if not path_text:
            continue
        try:
            resolved = Path(path_text).expanduser().resolve()
        except Exception:
            continue
        approved_root = _approved_root_for_path(resolved)
        fingerprint = f"{path_text}:{int(item.get('modifiedMs', 0) or 0)}:{int(item.get('size', 0) or 0)}"
        cache_key = path_text
        indexed_at = _utc_now_iso()
        cached = existing_local_files.get(cache_key, {})
        entry: dict[str, Any] | None = None
        if (
            isinstance(cached, dict)
            and str(cached.get("fingerprint", "") or "") == fingerprint
            and isinstance(cached.get("chunks"), list)
            and cached.get("chunks")
        ):
            entry = copy.deepcopy(cached)
            entry["indexedAt"] = indexed_at
        else:
            preview = _local_file_preview_text(item, resolved)
            chunk_texts = _chunk_text(preview)
            if not chunk_texts:
                continue
            chunk_items: list[dict[str, Any]] = []
            for index, chunk_text in enumerate(chunk_texts):
                chunk_items.append(
                    {
                        "source": "local_files",
                        "chunkId": str(item.get("id", "") or _stable_chunk_id("local_files", fingerprint, index)),
                        "title": str(item.get("name", "") or resolved.name or "file"),
                        "snippet": preview_text(chunk_text, limit=_MAX_MATCH_SNIPPET_CHARS),
                        "text": chunk_text,
                        "path": path_text,
                        "relativePath": approved_root.get("relativePath", resolved.name),
                        "approvedRoot": approved_root.get("path", ""),
                        "approvedRootLabel": approved_root.get("label", ""),
                        "contentType": str(item.get("contentType", "") or content_type_for(resolved)),
                        "rootLabel": str(item.get("rootLabel", "") or "").strip(),
                        "modifiedMs": int(item.get("modifiedMs", 0) or 0),
                        "size": int(item.get("size", 0) or 0),
                        "indexedAt": indexed_at,
                    }
                )
            entry = {
                "path": path_text,
                "title": str(item.get("name", "") or resolved.name or "file"),
                "fingerprint": fingerprint,
                "relativePath": approved_root.get("relativePath", resolved.name),
                "approvedRoot": approved_root.get("path", ""),
                "approvedRootLabel": approved_root.get("label", ""),
                "rootLabel": str(item.get("rootLabel", "") or "").strip(),
                "contentType": str(item.get("contentType", "") or content_type_for(resolved)),
                "size": int(item.get("size", 0) or 0),
                "modifiedMs": int(item.get("modifiedMs", 0) or 0),
                "chunkCount": len(chunk_items),
                "indexedAt": indexed_at,
                "chunks": chunk_items,
            }
        if entry is None:
            continue
        remaining = _MAX_WORKSPACE_CHUNKS - len(chunks)
        if remaining <= 0:
            break
        chunk_list = entry.get("chunks", [])
        if not isinstance(chunk_list, list):
            continue
        bounded_chunks = [copy.deepcopy(chunk) for chunk in chunk_list[:remaining] if isinstance(chunk, dict)]
        if not bounded_chunks:
            continue
        entry["chunks"] = bounded_chunks
        next_local_files[cache_key] = entry
        chunks.extend(copy.deepcopy(chunk) for chunk in bounded_chunks)
        if len(chunks) >= _MAX_WORKSPACE_CHUNKS:
            break

    return next_local_files, chunks, index_status


def _build_index(
    sources: list[str],
    *,
    conversation_id: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    index = _load_index_cache()
    workspace_entries = index.get("workspace", {}) if isinstance(index.get("workspace"), dict) else {}
    conversation_entries = index.get("conversations", {}) if isinstance(index.get("conversations"), dict) else {}
    local_file_entries = index.get("localFiles", {}) if isinstance(index.get("localFiles"), dict) else {}

    next_workspace = workspace_entries
    next_conversations = conversation_entries
    next_local_files = local_file_entries
    documents: list[dict[str, Any]] = []
    local_index_status = native_file_indexer.current_capability_state()

    if "workspace" in sources:
        next_workspace, workspace_chunks = _workspace_entries(workspace_entries)
        documents.extend(workspace_chunks)
    if "conversations" in sources:
        next_conversations, conversation_chunks = _conversation_entries(conversation_entries, conversation_id)
        documents.extend(conversation_chunks)
    if "local_files" in sources:
        next_local_files, local_chunks, local_index_status = _local_file_entries(local_file_entries)
        documents.extend(local_chunks)

    index["workspace"] = next_workspace
    index["conversations"] = next_conversations
    index["localFiles"] = next_local_files
    index["indexedAt"] = _utc_now_iso()
    _save_index_cache(index)
    return index, documents, local_index_status


def _embedding_rank(query: str, documents: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    model = _sentence_transformer_model()
    if model is None or not documents:
        return None
    model_name = _embedding_model_name()
    embedding_cache = _load_embeddings_cache(model_name)
    vectors = embedding_cache.get("vectors", {})
    vectors = dict(vectors) if isinstance(vectors, dict) else {}

    missing_documents = [
        item
        for item in documents
        if str(item.get("chunkId", "") or "").strip() and str(item.get("chunkId", "") or "").strip() not in vectors
    ]
    if missing_documents:
        try:
            encoded_docs = model.encode(
                [str(item.get("text", "") or "") for item in missing_documents],
                normalize_embeddings=True,
            )
        except Exception:
            return None
        for item, vector in zip(missing_documents, encoded_docs):
            chunk_id = str(item.get("chunkId", "") or "").strip()
            if chunk_id:
                vectors[chunk_id] = _vector_list(vector)

    try:
        query_vector = _vector_list(model.encode([query], normalize_embeddings=True)[0])
    except Exception:
        return None

    ranked: list[dict[str, Any]] = []
    for item in documents:
        chunk_id = str(item.get("chunkId", "") or "").strip()
        candidate_vector = vectors.get(chunk_id)
        if not chunk_id or not isinstance(candidate_vector, list) or not candidate_vector:
            continue
        semantic_score = sum(float(left) * float(right) for left, right in zip(query_vector, candidate_vector))
        lexical_score = _lexical_score(query, str(item.get("text", "") or ""))
        score = (float(semantic_score) * 0.7) + (float(lexical_score) * 0.3)
        ranked.append(
            {
                "item": item,
                "score": float(score),
                "lexicalScore": float(lexical_score),
                "semanticScore": float(semantic_score),
            }
        )

    ranked.sort(key=lambda row: (row["score"], row["semanticScore"], row["lexicalScore"]), reverse=True)

    bounded_chunk_ids = [str(item.get("chunkId", "") or "") for item in documents if str(item.get("chunkId", "") or "").strip()]
    embedding_cache["vectors"] = {
        chunk_id: vectors[chunk_id]
        for chunk_id in bounded_chunk_ids
        if chunk_id in vectors
    }
    embedding_cache["updatedAt"] = _utc_now_iso()
    _save_embeddings_cache(embedding_cache)
    return ranked


def _lexical_rank(query: str, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = [
        {
            "item": item,
            "score": _lexical_score(query, str(item.get("text", "") or "")),
            "lexicalScore": _lexical_score(query, str(item.get("text", "") or "")),
            "semanticScore": 0.0,
        }
        for item in documents
    ]
    ranked.sort(key=lambda row: row["score"], reverse=True)
    return ranked


def retrieval_status() -> dict[str, Any]:
    index = _load_index_cache()
    workspace = index.get("workspace", {})
    conversations = index.get("conversations", {})
    local_files = index.get("localFiles", {})
    workspace_chunks = sum(
        len(entry.get("chunks", []))
        for entry in workspace.values()
        if isinstance(entry, dict) and isinstance(entry.get("chunks"), list)
    ) if isinstance(workspace, dict) else 0
    conversation_chunks = sum(
        len(entry.get("chunks", []))
        for entry in conversations.values()
        if isinstance(entry, dict) and isinstance(entry.get("chunks"), list)
    ) if isinstance(conversations, dict) else 0
    local_file_chunks = sum(
        len(entry.get("chunks", []))
        for entry in local_files.values()
        if isinstance(entry, dict) and isinstance(entry.get("chunks"), list)
    ) if isinstance(local_files, dict) else 0
    local_index_status = native_file_indexer.current_capability_state()
    return {
        "available": True,
        "strategy": str(index.get("lastStrategy", "lexical") or "lexical"),
        "model": _embedding_model_name(),
        "cacheReady": _index_cache_path().exists() and int(index.get("version", 0) or 0) == _RETRIEVAL_CACHE_VERSION,
        "indexedWorkspaceChunks": workspace_chunks,
        "indexedConversationChunks": conversation_chunks,
        "indexedLocalFileChunks": local_file_chunks,
        "lastIndexedAt": str(index.get("indexedAt", "") or ""),
        "localFileIndex": local_index_status,
    }


def retrieve_context(
    query: str,
    sources: list[str] | str | None = None,
    limit: int = 6,
    conversation_id: str = "",
) -> dict[str, Any]:
    question = str(query or "").strip()
    if not question:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Bağlam araması için query gerekli.")

    requested_sources = sources
    if isinstance(requested_sources, str):
        requested_sources = [item.strip() for item in requested_sources.split(",") if item.strip()]
    normalized_sources = [
        item
        for item in [str(source).strip().lower() for source in (requested_sources or ["workspace", "conversations"])]
        if item in {"workspace", "conversations", "local_files"}
    ]
    if not normalized_sources:
        normalized_sources = ["workspace", "conversations"]

    index, documents, local_index_status = _build_index(normalized_sources, conversation_id=conversation_id)
    cache_ready = _index_cache_path().exists() and int(index.get("version", 0) or 0) == _RETRIEVAL_CACHE_VERSION

    strategy = "lexical"
    ranked = _embedding_rank(question, documents)
    if ranked is None:
        ranked = _lexical_rank(question, documents)
    else:
        strategy = "hybrid_semantic"

    index["lastStrategy"] = strategy
    _save_index_cache(index)

    matches: list[dict[str, Any]] = []
    for row in ranked[: max(1, int(limit or 6))]:
        item = row["item"]
        match = copy.deepcopy(item)
        match["score"] = round(float(row["score"]), 4)
        match["lexicalScore"] = round(float(row.get("lexicalScore", 0.0) or 0.0), 4)
        match["semanticScore"] = round(float(row.get("semanticScore", 0.0) or 0.0), 4)
        match["snippet"] = preview_text(str(item.get("text", "") or ""), limit=_MAX_MATCH_SNIPPET_CHARS)
        match.pop("text", None)
        matches.append(match)

    lines = [
        f"{match.get('source', 'source')}: {match.get('title', '')} ({match.get('score', 0):.2f})"
        for match in matches
    ]
    indexed_at = str(index.get("indexedAt", "") or "")
    return {
        "text": "Bağlam eşleşmeleri:\n" + "\n".join(lines) if lines else "İlgili yerel bağlam bulunamadı.",
        "result": {
            "kind": "retrieve_context",
            "sources": normalized_sources,
            "matches": matches,
            "strategy": strategy,
            "model": _embedding_model_name(),
            "indexedAt": indexed_at,
            "cacheReady": cache_ready,
            "localIndexStatus": local_index_status,
            "localFileIndex": local_index_status,
            "sourceStatus": {
                "workspace": {"available": True, "ready": True},
                "conversations": {"available": True, "ready": True},
                "local_files": local_index_status,
            },
        },
        "artifacts": [],
    }
