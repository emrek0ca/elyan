"""macOS Spotlight Search using mdfind"""

import asyncio
from typing import Any
from pathlib import Path
from utils.logger import get_logger
from config.settings import HOME_DIR, ALLOWED_DIRECTORIES

logger = get_logger("macos.spotlight")

# Maximum results to return
MAX_RESULTS = 50

# File type mappings for common queries
FILE_TYPE_MAPPINGS = {
    "pdf": "kMDItemContentType == 'com.adobe.pdf'",
    "word": "kMDItemContentType == 'org.openxmlformats.wordprocessingml.document' || kMDItemContentType == 'com.microsoft.word.doc'",
    "excel": "kMDItemContentType == 'org.openxmlformats.spreadsheetml.sheet' || kMDItemContentType == 'com.microsoft.excel.xls'",
    "powerpoint": "kMDItemContentType == 'org.openxmlformats.presentationml.presentation'",
    "image": "kMDItemContentTypeTree == 'public.image'",
    "video": "kMDItemContentTypeTree == 'public.movie'",
    "audio": "kMDItemContentTypeTree == 'public.audio'",
    "document": "kMDItemContentTypeTree == 'public.content'",
    "folder": "kMDItemContentType == 'public.folder'",
    "app": "kMDItemContentType == 'com.apple.application-bundle'",
}


async def spotlight_search(
    query: str,
    file_type: str = None,
    directory: str = None,
    limit: int = MAX_RESULTS
) -> dict[str, Any]:
    """Search files using macOS Spotlight (mdfind)

    Args:
        query: Search query (file name or content)
        file_type: Optional file type filter (pdf, word, excel, image, video, etc.)
        directory: Optional directory to limit search
        limit: Maximum number of results
    """
    try:
        cmd = ["mdfind"]

        # Build the query
        search_query = query

        # Add file type filter if specified
        if file_type and file_type.lower() in FILE_TYPE_MAPPINGS:
            type_filter = FILE_TYPE_MAPPINGS[file_type.lower()]
            search_query = f"({type_filter}) && (kMDItemDisplayName == '*{query}*'wc || kMDItemTextContent == '*{query}*'wc)"
            cmd.extend(["-interpret", search_query])
        else:
            # Simple name-based search
            cmd.extend(["-name", query])

        # Limit search to specific directory if provided
        if directory:
            dir_path = Path(directory).expanduser()
            # Security check
            allowed = any(str(dir_path).startswith(str(d)) for d in ALLOWED_DIRECTORIES)
            if allowed or str(dir_path).startswith(str(HOME_DIR)):
                cmd.extend(["-onlyin", str(dir_path)])

        logger.info(f"Spotlight search: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("Spotlight search timed out")
            return {"success": False, "error": "Spotlight arama zaman aşımına uğradı (5s)"}

        if proc.returncode != 0:
            error = stderr.decode().strip()
            return {"success": False, "error": error}

        output = stdout.decode().strip()
        results = []

        if output:
            paths = output.split("\n")
            for path in paths[:limit]:
                if path.strip():
                    p = Path(path)
                    # Filter out system directories for security
                    if _is_safe_path(p):
                        results.append({
                            "path": str(p),
                            "name": p.name,
                            "type": "folder" if p.is_dir() else "file",
                            "extension": p.suffix if p.is_file() else None
                        })

        logger.info(f"Found {len(results)} results for '{query}'")

        return {
            "success": True,
            "query": query,
            "file_type": file_type,
            "results": results,
            "count": len(results),
            "limited": len(results) >= limit
        }

    except Exception as e:
        logger.error(f"Spotlight search error: {e}")
        return {"success": False, "error": str(e)}


def _is_safe_path(path: Path) -> bool:
    """Check if path is safe to show (not system/sensitive)"""
    str_path = str(path).lower()

    # Blocked patterns
    blocked = [
        "/library/",
        "/system/",
        "/.ssh/",
        "/.aws/",
        "/.config/",
        "/private/var/",
        "/.trash/",
        "/applications/utilities/",
    ]

    for pattern in blocked:
        if pattern in str_path:
            return False

    return True
