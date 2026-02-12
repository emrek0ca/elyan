"""
Smart Path Resolution Module

Provides intelligent path resolution with:
- Automatic alternative path discovery
- Fuzzy path matching
- Common folder aliases
- Path suggestions when not found
"""

import os
from pathlib import Path
from typing import Optional, List, Tuple
from utils.logger import get_logger

logger = get_logger("smart_paths")

# Common folder mappings (Turkish and English)
FOLDER_ALIASES = {
    # Projects
    "projeler": ["Projects", "Developer", "Code", "repos", "dev", "workspace", "src"],
    "projects": ["Projects", "Developer", "Code", "repos", "dev", "workspace", "src"],
    
    # Documents
    "belgeler": ["Documents", "Belgeler"],
    "documents": ["Documents", "Belgeler"],
    "dökümanlar": ["Documents", "Belgeler"],
    
    # Desktop
    "masaüstü": ["Desktop", "Masaüstü"],
    "desktop": ["Desktop", "Masaüstü"],
    
    # Downloads
    "indirilenler": ["Downloads", "İndirilenler"],
    "downloads": ["Downloads", "İndirilenler"],
    
    # Pictures
    "resimler": ["Pictures", "Photos", "Resimler", "Fotoğraflar"],
    "pictures": ["Pictures", "Photos", "Resimler", "Fotoğraflar"],
    "fotoğraflar": ["Pictures", "Photos", "Resimler", "Fotoğraflar"],
    
    # Music
    "müzik": ["Music", "Müzik"],
    "music": ["Music", "Müzik"],
    
    # Videos
    "videolar": ["Movies", "Videos", "Videolar"],
    "movies": ["Movies", "Videos", "Videolar"],
    
    # Work
    "iş": ["Work", "İş", "work"],
    "work": ["Work", "İş", "work"],
    
    # School
    "okul": ["School", "Okul", "Üniversite", "University"],
    "school": ["School", "Okul", "Üniversite", "University"],
}

# Common root locations to search
SEARCH_ROOTS = [
    Path.home(),
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
]


def resolve_path(path_str: str) -> Tuple[Optional[Path], List[str]]:
    """
    Intelligently resolve a path, trying alternatives if not found.
    
    Args:
        path_str: The path string from user input
        
    Returns:
        Tuple of (resolved_path or None, list of suggestions)
    """
    # Expand ~ and environment variables
    expanded = os.path.expanduser(os.path.expandvars(path_str))
    path = Path(expanded)
    
    # If path exists, return it
    if path.exists():
        logger.info(f"Path found: {path}")
        return path, []
    
    # Try to find alternatives
    suggestions = []
    
    # Extract the folder name being looked for
    folder_name = path.name.lower()
    
    # Check if it's an alias
    if folder_name in FOLDER_ALIASES:
        alternatives = FOLDER_ALIASES[folder_name]
        for alt in alternatives:
            for root in SEARCH_ROOTS:
                alt_path = root / alt
                if alt_path.exists():
                    logger.info(f"Found alternative: {alt_path}")
                    return alt_path, []
                suggestions.append(str(alt_path))
    
    # Try searching in common locations
    for root in SEARCH_ROOTS:
        # Exact match
        exact = root / path.name
        if exact.exists():
            return exact, []
        
        # Case-insensitive search
        if root.exists():
            for item in root.iterdir():
                if item.name.lower() == folder_name:
                    return item, []
                # Fuzzy match
                if folder_name in item.name.lower():
                    suggestions.append(str(item))
    
    # Use Spotlight on macOS as last resort
    spotlight_results = _spotlight_search(folder_name)
    suggestions.extend(spotlight_results[:5])
    
    logger.warning(f"Path not found: {path}, suggestions: {suggestions}")
    return None, suggestions


def _spotlight_search(query: str) -> List[str]:
    """Use macOS Spotlight to find folders"""
    import subprocess
    try:
        result = subprocess.run(
            ["mdfind", f"kMDItemDisplayName == '*{query}*' && kMDItemContentType == public.folder"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            paths = result.stdout.strip().split('\n')
            # Filter to home directory
            home = str(Path.home())
            return [p for p in paths if p.startswith(home) and p][:10]
    except Exception as e:
        logger.debug(f"Spotlight search failed: {e}")
    return []


def suggest_path_alternatives(path_str: str) -> str:
    """
    Generate a helpful message with path alternatives.
    
    Args:
        path_str: The path that wasn't found
        
    Returns:
        Human-readable suggestion message
    """
    resolved, suggestions = resolve_path(path_str)
    
    if resolved:
        return f"'{path_str}' yerine '{resolved}' buldum."
    
    if suggestions:
        suggestion_list = "\n".join(f"  - {s}" for s in suggestions[:5])
        return f"'{path_str}' bulunamadı. Şunları denedin mi:\n{suggestion_list}"
    
    return f"'{path_str}' bulunamadı. Bu klasörü farklı bir isimle mi arıyorsun?"


def get_common_paths() -> dict:
    """Get dictionary of common paths that exist on this system"""
    home = Path.home()
    paths = {
        "home": str(home),
        "desktop": str(home / "Desktop"),
        "documents": str(home / "Documents"),
        "downloads": str(home / "Downloads"),
        "pictures": str(home / "Pictures"),
        "music": str(home / "Music"),
        "movies": str(home / "Movies"),
    }
    
    # Check for developer directories
    for dev_name in ["Developer", "Projects", "Code", "repos"]:
        dev_path = home / dev_name
        if dev_path.exists():
            paths["projects"] = str(dev_path)
            break
    
    return {k: v for k, v in paths.items() if Path(v).exists()}


def normalize_path_input(user_input: str) -> str:
    """
    Normalize user's path references to actual paths.
    
    Examples:
        "masaüstü" -> "~/Desktop"
        "projeler klasörü" -> "~/Projects" (if exists) or alternatives
    """
    lower_input = user_input.lower()
    
    # Check for folder aliases in input
    for alias, alternatives in FOLDER_ALIASES.items():
        if alias in lower_input:
            for alt in alternatives:
                path = Path.home() / alt
                if path.exists():
                    return str(path)
    
    return user_input
