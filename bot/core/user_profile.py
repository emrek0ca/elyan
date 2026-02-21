"""Persistent user profile and adaptive preference learning."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("user_profile")


class UserProfileStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or self._default_path()
        self._profiles: dict[str, dict[str, Any]] = {}
        self._load()

    def _default_path(self) -> Path:
        base = Path.home() / ".elyan"
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return base / "user_profiles.json"
        except Exception:
            local = Path(__file__).parent.parent / ".elyan"
            local.mkdir(parents=True, exist_ok=True)
            return local / "user_profiles.json"

    def _load(self):
        try:
            if self.db_path.exists():
                self._profiles = json.loads(self.db_path.read_text(encoding="utf-8"))
            else:
                self._profiles = {}
        except Exception as exc:
            logger.warning(f"Failed to load user profiles: {exc}")
            self._profiles = {}

    def _save(self):
        try:
            self.db_path.write_text(
                json.dumps(self._profiles, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"Failed to save user profiles: {exc}")
            local = Path(__file__).parent.parent / ".elyan" / "user_profiles.json"
            local.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.db_path = local
                self.db_path.write_text(
                    json.dumps(self._profiles, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as inner_exc:
                logger.warning(f"Failed to save user profiles (local fallback): {inner_exc}")

    def get(self, user_id: str) -> dict[str, Any]:
        uid = str(user_id or "local")
        if uid not in self._profiles:
            self._profiles[uid] = {
                "preferred_language": "auto",
                "top_topics": {},
                "successful_actions": {},
                "failed_actions": {},
                "response_length_bias": "short",
                "updated_at": int(time.time()),
            }
        return self._profiles[uid]

    def update_after_interaction(
        self,
        user_id: str,
        *,
        language: str,
        action: str,
        success: bool,
        topic_keywords: list[str] | None = None,
    ):
        profile = self.get(user_id)
        if language and language != "auto":
            profile["preferred_language"] = language

        bucket = "successful_actions" if success else "failed_actions"
        actions = profile.setdefault(bucket, {})
        if action:
            actions[action] = int(actions.get(action, 0)) + 1

        topics = profile.setdefault("top_topics", {})
        for keyword in (topic_keywords or [])[:8]:
            if not keyword or len(keyword) < 3:
                continue
            topics[keyword] = int(topics.get(keyword, 0)) + 1

        profile["updated_at"] = int(time.time())
        self._save()

    def profile_summary(self, user_id: str) -> dict[str, Any]:
        profile = self.get(user_id)
        top_topics = sorted(
            profile.get("top_topics", {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        top_actions = sorted(
            profile.get("successful_actions", {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        return {
            "preferred_language": profile.get("preferred_language", "auto"),
            "top_topics": [topic for topic, _ in top_topics],
            "top_actions": [action for action, _ in top_actions],
            "response_length_bias": profile.get("response_length_bias", "short"),
        }


_profile_store: UserProfileStore | None = None


def get_user_profile_store() -> UserProfileStore:
    global _profile_store
    if _profile_store is None:
        _profile_store = UserProfileStore()
    return _profile_store
