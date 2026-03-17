"""
Code Memory - Pattern library and code reuse detection
Stores and retrieves code patterns for reuse
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class CodePattern:
    """Represents a reusable code pattern"""

    def __init__(self, pattern_id: str, name: str, code: str, language: str,
                 category: str, tags: List[str]):
        self.pattern_id = pattern_id
        self.name = name
        self.code = code
        self.language = language
        self.category = category
        self.tags = tags
        self.usage_count = 0
        self.success_count = 0
        self.created_at = datetime.now().isoformat()
        self.last_used = None
        self.quality_score = 0.0

    def record_usage(self, success: bool):
        """Record usage of this pattern"""
        self.usage_count += 1
        if success:
            self.success_count += 1
        self.last_used = datetime.now().isoformat()
        self._update_quality()

    def _update_quality(self):
        """Update quality score based on usage"""
        if self.usage_count > 0:
            self.quality_score = self.success_count / self.usage_count

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "code": self.code,
            "language": self.language,
            "category": self.category,
            "tags": self.tags,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "quality_score": self.quality_score,
            "created_at": self.created_at,
            "last_used": self.last_used
        }


class CodeMemory:
    """Stores and retrieves code patterns"""

    def __init__(self, storage_path: str = ".elyan/code_memory"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.patterns: Dict[str, CodePattern] = {}
        self.user_style: Dict[str, any] = {}
        self.category_index: Dict[str, List[str]] = {}
        self.tag_index: Dict[str, List[str]] = {}

        self._load_patterns()

    def _load_patterns(self):
        """Load patterns from storage"""
        try:
            patterns_file = self.storage_path / "patterns.json"
            if patterns_file.exists():
                with open(patterns_file) as f:
                    data = json.load(f)
                    for pattern_data in data.get("patterns", []):
                        pattern = CodePattern(
                            pattern_id=pattern_data["pattern_id"],
                            name=pattern_data["name"],
                            code=pattern_data["code"],
                            language=pattern_data["language"],
                            category=pattern_data["category"],
                            tags=pattern_data["tags"]
                        )
                        pattern.usage_count = pattern_data.get("usage_count", 0)
                        pattern.success_count = pattern_data.get("success_count", 0)
                        pattern.quality_score = pattern_data.get("quality_score", 0.0)
                        self.patterns[pattern.pattern_id] = pattern
                        self._index_pattern(pattern)
        except Exception as e:
            logger.error(f"Failed to load patterns: {e}")

    def _index_pattern(self, pattern: CodePattern):
        """Index pattern by category and tags"""
        if pattern.category not in self.category_index:
            self.category_index[pattern.category] = []
        self.category_index[pattern.category].append(pattern.pattern_id)

        for tag in pattern.tags:
            if tag not in self.tag_index:
                self.tag_index[tag] = []
            self.tag_index[tag].append(pattern.pattern_id)

    def store_solution(self, task: str, code: str, quality_score: float,
                      language: str = "python", tags: List[str] = None):
        """Store a successful code solution"""
        try:
            tags = tags or []
            pattern_id = f"pattern_{hash(code)}"

            pattern = CodePattern(
                pattern_id=pattern_id,
                name=task,
                code=code,
                language=language,
                category=self._categorize_code(code),
                tags=tags
            )
            pattern.quality_score = quality_score
            pattern.success_count = 1
            pattern.usage_count = 1

            self.patterns[pattern_id] = pattern
            self._index_pattern(pattern)
            self._save_patterns()

            logger.info(f"Stored solution: {pattern_id}")
            return pattern_id

        except Exception as e:
            logger.error(f"Failed to store solution: {e}")
            return None

    def find_similar_patterns(self, task: str, limit: int = 5) -> List[CodePattern]:
        """Find similar code patterns"""
        try:
            keywords = task.lower().split()
            candidates = []

            for pattern in self.patterns.values():
                # Score by tag match
                tag_matches = len(set(pattern.tags) & set(keywords))
                keyword_matches = sum(1 for kw in keywords if kw in pattern.name.lower())

                score = tag_matches + keyword_matches
                if score > 0:
                    candidates.append((score, pattern))

            # Sort by score
            candidates.sort(key=lambda x: x[0], reverse=True)
            return [p for _, p in candidates[:limit]]

        except Exception as e:
            logger.error(f"Failed to find patterns: {e}")
            return []

    def get_user_style(self) -> Dict:
        """Get user's coding style preferences"""
        try:
            style = {
                "preferred_language": self._detect_preferred_language(),
                "indentation": self._detect_indentation(),
                "naming_convention": self._detect_naming(),
                "code_organization": self._detect_organization(),
                "comment_style": self._detect_comments()
            }
            self.user_style = style
            return style
        except Exception as e:
            logger.error(f"Failed to get user style: {e}")
            return {}

    def _detect_preferred_language(self) -> str:
        """Detect preferred programming language"""
        lang_count = {}
        for pattern in self.patterns.values():
            lang_count[pattern.language] = lang_count.get(pattern.language, 0) + 1
        return max(lang_count, key=lang_count.get) if lang_count else "python"

    def _detect_indentation(self) -> str:
        """Detect preferred indentation style"""
        for pattern in self.patterns.values():
            if "\t" in pattern.code:
                return "tab"
            elif "    " in pattern.code:
                return "space (4)"
            elif "  " in pattern.code:
                return "space (2)"
        return "space (4)"  # default

    def _detect_naming(self) -> str:
        """Detect naming convention"""
        uses_snake = sum(1 for p in self.patterns.values() if "_" in p.code)
        uses_camel = sum(1 for p in self.patterns.values() if any(c.isupper() for c in p.code))
        return "snake_case" if uses_snake > uses_camel else "camelCase"

    def _detect_organization(self) -> str:
        """Detect code organization preference"""
        return "modular"  # Simplified

    def _detect_comments(self) -> str:
        """Detect comment style preference"""
        comment_count = sum(1 for p in self.patterns.values() if "#" in p.code or "//" in p.code)
        return "inline" if comment_count > 0 else "docstring"

    def suggest_implementation(self, task: str) -> List[str]:
        """Suggest implementation approaches"""
        similar = self.find_similar_patterns(task, limit=3)
        suggestions = []

        for pattern in similar:
            suggestions.append(f"Pattern: {pattern.name}\nCode:\n{pattern.code[:200]}...")

        return suggestions if suggestions else ["No similar patterns found"]

    def update_pattern_usage(self, pattern_id: str, success: bool):
        """Update pattern usage statistics"""
        if pattern_id in self.patterns:
            self.patterns[pattern_id].record_usage(success)
            self._save_patterns()

    def _categorize_code(self, code: str) -> str:
        """Categorize code snippet"""
        if "class " in code:
            return "object_oriented"
        elif "def " in code:
            return "functional"
        elif "sql" in code.lower() or "query" in code.lower():
            return "database"
        elif "api" in code.lower() or "request" in code.lower():
            return "api_integration"
        else:
            return "generic"

    def _save_patterns(self):
        """Save patterns to storage"""
        try:
            patterns_file = self.storage_path / "patterns.json"
            data = {
                "patterns": [p.to_dict() for p in self.patterns.values()],
                "saved_at": datetime.now().isoformat()
            }
            with open(patterns_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save patterns: {e}")

    def get_statistics(self) -> Dict:
        """Get memory statistics"""
        total_patterns = len(self.patterns)
        total_usage = sum(p.usage_count for p in self.patterns.values())
        avg_quality = sum(p.quality_score for p in self.patterns.values()) / total_patterns if total_patterns > 0 else 0

        return {
            "total_patterns": total_patterns,
            "total_usage": total_usage,
            "average_quality": avg_quality,
            "categories": dict(self.category_index),
            "top_patterns": [
                p.to_dict() for p in sorted(
                    self.patterns.values(),
                    key=lambda x: x.quality_score,
                    reverse=True
                )[:5]
            ]
        }
