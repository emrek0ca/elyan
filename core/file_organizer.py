"""
Smart File Organization System
Automatic categorization, duplicate detection, smart cleanup
"""

import os
import hashlib
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timedelta

from utils.logger import get_logger

logger = get_logger("file_organizer")


@dataclass
class FileInfo:
    """File information"""
    path: str
    size: int
    hash: str
    extension: str
    category: str
    tags: Set[str]
    created: float
    modified: float


@dataclass
class OrganizationRule:
    """File organization rule"""
    name: str
    pattern: str  # File pattern (*.pdf, *.jpg, etc.)
    target_folder: str
    condition: Optional[str] = None  # Additional condition


class SmartFileOrganizer:
    """
    Smart File Organization System
    - Automatic categorization by type
    - Duplicate detection with MD5 hashing
    - Smart naming suggestions
    - File tagging
    - Cleanup automation
    - Organization rules
    """

    def __init__(self):
        self.file_index: Dict[str, FileInfo] = {}
        self.duplicate_groups: List[List[str]] = []
        self.organization_rules: List[OrganizationRule] = []
        self.file_tags: Dict[str, Set[str]] = defaultdict(set)

        # Category mappings
        self.category_map = {
            # Documents
            'pdf': 'documents',
            'doc': 'documents',
            'docx': 'documents',
            'txt': 'documents',
            'rtf': 'documents',
            'odt': 'documents',

            # Images
            'jpg': 'images',
            'jpeg': 'images',
            'png': 'images',
            'gif': 'images',
            'bmp': 'images',
            'svg': 'images',
            'webp': 'images',

            # Videos
            'mp4': 'videos',
            'avi': 'videos',
            'mov': 'videos',
            'mkv': 'videos',
            'webm': 'videos',

            # Audio
            'mp3': 'audio',
            'wav': 'audio',
            'ogg': 'audio',
            'm4a': 'audio',
            'flac': 'audio',

            # Archives
            'zip': 'archives',
            'rar': 'archives',
            '7z': 'archives',
            'tar': 'archives',
            'gz': 'archives',

            # Code
            'py': 'code',
            'js': 'code',
            'html': 'code',
            'css': 'code',
            'java': 'code',
            'cpp': 'code',
            'go': 'code',
            'rs': 'code',

            # Spreadsheets
            'xls': 'spreadsheets',
            'xlsx': 'spreadsheets',
            'csv': 'spreadsheets',

            # Presentations
            'ppt': 'presentations',
            'pptx': 'presentations',
            'key': 'presentations',
        }

        logger.info("Smart File Organizer initialized")

    def calculate_file_hash(self, file_path: str) -> str:
        """Calculate MD5 hash of file"""
        try:
            hasher = hashlib.md5()
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"Hash calculation error: {e}")
            return ""

    def categorize_file(self, file_path: str) -> str:
        """Categorize file by extension"""
        ext = Path(file_path).suffix.lower().lstrip('.')
        return self.category_map.get(ext, 'other')

    def index_directory(
        self,
        directory: str,
        recursive: bool = True
    ) -> Dict[str, Any]:
        """Index all files in directory"""
        indexed_count = 0
        total_size = 0

        path = Path(directory)
        if not path.exists():
            return {"success": False, "error": "Directory not found"}

        # Get all files
        if recursive:
            files = path.rglob('*')
        else:
            files = path.glob('*')

        for file in files:
            if file.is_file():
                try:
                    file_hash = self.calculate_file_hash(str(file))
                    stats = file.stat()

                    file_info = FileInfo(
                        path=str(file),
                        size=stats.st_size,
                        hash=file_hash,
                        extension=file.suffix.lower().lstrip('.'),
                        category=self.categorize_file(str(file)),
                        tags=set(),
                        created=stats.st_ctime,
                        modified=stats.st_mtime
                    )

                    self.file_index[str(file)] = file_info
                    indexed_count += 1
                    total_size += stats.st_size

                except Exception as e:
                    logger.error(f"Error indexing {file}: {e}")

        logger.info(f"Indexed {indexed_count} files ({total_size} bytes)")

        return {
            "success": True,
            "indexed_files": indexed_count,
            "total_size": total_size
        }

    def find_duplicates(self) -> List[List[str]]:
        """Find duplicate files by hash"""
        hash_groups = defaultdict(list)

        for file_path, file_info in self.file_index.items():
            if file_info.hash:
                hash_groups[file_info.hash].append(file_path)

        # Keep only groups with duplicates
        self.duplicate_groups = [
            group for group in hash_groups.values()
            if len(group) > 1
        ]

        logger.info(f"Found {len(self.duplicate_groups)} duplicate groups")
        return self.duplicate_groups

    def get_duplicates_report(self) -> Dict[str, Any]:
        """Get detailed duplicates report"""
        total_duplicates = sum(len(group) - 1 for group in self.duplicate_groups)
        wasted_space = 0

        for group in self.duplicate_groups:
            if group:
                file_size = self.file_index[group[0]].size
                wasted_space += file_size * (len(group) - 1)

        return {
            "duplicate_groups": len(self.duplicate_groups),
            "total_duplicates": total_duplicates,
            "wasted_space_bytes": wasted_space,
            "wasted_space_mb": wasted_space / (1024 * 1024),
            "groups": [
                {
                    "files": group,
                    "size": self.file_index[group[0]].size,
                    "hash": self.file_index[group[0]].hash
                }
                for group in self.duplicate_groups[:10]  # Top 10
            ]
        }

    def remove_duplicates(
        self,
        keep_strategy: str = "oldest"
    ) -> Dict[str, Any]:
        """Remove duplicate files"""
        removed_count = 0
        freed_space = 0

        for group in self.duplicate_groups:
            if len(group) < 2:
                continue

            # Determine which file to keep
            if keep_strategy == "oldest":
                files_sorted = sorted(group, key=lambda f: self.file_index[f].created)
            elif keep_strategy == "newest":
                files_sorted = sorted(group, key=lambda f: self.file_index[f].created, reverse=True)
            else:  # "first"
                files_sorted = group

            keep_file = files_sorted[0]
            remove_files = files_sorted[1:]

            # Remove duplicates
            for file_path in remove_files:
                try:
                    file_size = self.file_index[file_path].size
                    os.remove(file_path)
                    del self.file_index[file_path]
                    removed_count += 1
                    freed_space += file_size
                    logger.info(f"Removed duplicate: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to remove {file_path}: {e}")

        self.duplicate_groups.clear()

        return {
            "success": True,
            "removed_files": removed_count,
            "freed_space_bytes": freed_space,
            "freed_space_mb": freed_space / (1024 * 1024)
        }

    def organize_by_category(
        self,
        source_dir: str,
        target_base_dir: str,
        move: bool = False
    ) -> Dict[str, Any]:
        """Organize files into category folders"""
        organized_count = 0
        errors = []

        source_path = Path(source_dir)
        target_base = Path(target_base_dir)

        if not source_path.exists():
            return {"success": False, "error": "Source directory not found"}

        # Create category folders
        for category in set(self.category_map.values()):
            (target_base / category).mkdir(parents=True, exist_ok=True)

        # Organize files
        for file in source_path.iterdir():
            if file.is_file():
                try:
                    category = self.categorize_file(str(file))
                    target_dir = target_base / category
                    target_file = target_dir / file.name

                    # Handle name conflicts
                    if target_file.exists():
                        base = target_file.stem
                        ext = target_file.suffix
                        counter = 1
                        while target_file.exists():
                            target_file = target_dir / f"{base}_{counter}{ext}"
                            counter += 1

                    # Move or copy
                    if move:
                        shutil.move(str(file), str(target_file))
                    else:
                        shutil.copy2(str(file), str(target_file))

                    organized_count += 1

                except Exception as e:
                    errors.append(f"{file.name}: {str(e)}")
                    logger.error(f"Error organizing {file}: {e}")

        return {
            "success": True,
            "organized_files": organized_count,
            "errors": errors
        }

    def suggest_name(self, file_path: str) -> str:
        """Suggest better file name based on content/metadata"""
        path = Path(file_path)
        ext = path.suffix

        # Get file info
        file_info = self.file_index.get(str(path))
        if not file_info:
            return path.name

        # Generate name based on category
        category = file_info.category
        timestamp = datetime.fromtimestamp(file_info.created).strftime("%Y%m%d")

        # Suggest pattern: category_timestamp_originalname
        original_stem = path.stem.lower().replace(" ", "_")
        suggested = f"{category}_{timestamp}_{original_stem}{ext}"

        return suggested

    def cleanup_old_files(
        self,
        directory: str,
        days_old: int = 30,
        min_size_mb: float = 0,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """Cleanup old files"""
        cutoff_time = time.time() - (days_old * 86400)
        min_size_bytes = min_size_mb * 1024 * 1024

        cleanup_candidates = []
        total_size = 0

        path = Path(directory)
        for file in path.rglob('*'):
            if file.is_file():
                try:
                    stats = file.stat()

                    if (stats.st_mtime < cutoff_time and
                        stats.st_size >= min_size_bytes):

                        cleanup_candidates.append({
                            "path": str(file),
                            "size": stats.st_size,
                            "age_days": (time.time() - stats.st_mtime) / 86400
                        })
                        total_size += stats.st_size

                except Exception as e:
                    logger.error(f"Error checking {file}: {e}")

        # Actually delete if not dry run
        deleted_count = 0
        if not dry_run:
            for candidate in cleanup_candidates:
                try:
                    os.remove(candidate["path"])
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete {candidate['path']}: {e}")

        return {
            "success": True,
            "candidates": len(cleanup_candidates),
            "total_size_mb": total_size / (1024 * 1024),
            "deleted": deleted_count if not dry_run else 0,
            "dry_run": dry_run,
            "files": cleanup_candidates[:20]  # Top 20
        }

    def add_tag(self, file_path: str, tag: str):
        """Add tag to file"""
        if file_path in self.file_index:
            self.file_index[file_path].tags.add(tag)
            self.file_tags[file_path].add(tag)
            logger.info(f"Tagged {file_path} with '{tag}'")

    def find_by_tag(self, tag: str) -> List[str]:
        """Find files by tag"""
        return [
            path for path, file_info in self.file_index.items()
            if tag in file_info.tags
        ]

    def get_category_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics by category"""
        stats = defaultdict(lambda: {"count": 0, "total_size": 0})

        for file_info in self.file_index.values():
            stats[file_info.category]["count"] += 1
            stats[file_info.category]["total_size"] += file_info.size

        return {
            category: {
                "count": data["count"],
                "total_size_mb": data["total_size"] / (1024 * 1024)
            }
            for category, data in stats.items()
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get organizer summary"""
        total_size = sum(f.size for f in self.file_index.values())

        return {
            "indexed_files": len(self.file_index),
            "total_size_mb": total_size / (1024 * 1024),
            "duplicate_groups": len(self.duplicate_groups),
            "categories": len(set(f.category for f in self.file_index.values())),
            "tagged_files": len(self.file_tags),
            "organization_rules": len(self.organization_rules)
        }


# Global instance
_file_organizer: Optional[SmartFileOrganizer] = None


def get_file_organizer() -> SmartFileOrganizer:
    """Get or create global file organizer instance"""
    global _file_organizer
    if _file_organizer is None:
        _file_organizer = SmartFileOrganizer()
    return _file_organizer
