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
                "conversation_profile": {
                    "tone": "natural_concise",
                    "response_length": "short",
                    "channel_tone_overrides": {},
                    "followup_preference": "balanced",
                    "decision_style": "direct",
                    "prefers_brief_answers": True,
                },
                "safe_relational_memory": {
                    "preferred_name": "",
                    "projects": [],
                    "people": [],
                },
                "sensitive_personal_memory": {},
                "updated_at": int(time.time()),
            }
        return self._profiles[uid]

    def get_conversation_profile(self, user_id: str) -> dict[str, Any]:
        profile = self.get(user_id)
        stored = profile.get("conversation_profile")
        if not isinstance(stored, dict):
            stored = {}
        channel_overrides = stored.get("channel_tone_overrides")
        return {
            "tone": str(stored.get("tone", "natural_concise") or "natural_concise"),
            "response_length": str(stored.get("response_length", profile.get("response_length_bias", "short")) or "short"),
            "channel_tone_overrides": dict(channel_overrides or {}),
            "followup_preference": str(stored.get("followup_preference", "balanced") or "balanced"),
            "decision_style": str(stored.get("decision_style", "direct") or "direct"),
            "prefers_brief_answers": bool(stored.get("prefers_brief_answers", True)),
        }

    def update_conversation_profile(
        self,
        user_id: str,
        *,
        tone: str | None = None,
        response_length: str | None = None,
        channel_type: str | None = None,
        channel_tone: str | None = None,
        followup_preference: str | None = None,
        decision_style: str | None = None,
        prefers_brief_answers: bool | None = None,
        preferred_name: str | None = None,
        project_hint: str | None = None,
    ) -> dict[str, Any]:
        profile = self.get(user_id)
        conversation = self.get_conversation_profile(user_id)
        safe_memory = profile.get("safe_relational_memory")
        if not isinstance(safe_memory, dict):
            safe_memory = {"preferred_name": "", "projects": [], "people": []}

        if tone:
            conversation["tone"] = str(tone)
        if response_length:
            conversation["response_length"] = str(response_length)
            profile["response_length_bias"] = str(response_length)
        if channel_type and channel_tone:
            overrides = dict(conversation.get("channel_tone_overrides", {}) or {})
            overrides[str(channel_type)] = str(channel_tone)
            conversation["channel_tone_overrides"] = overrides
        if followup_preference:
            conversation["followup_preference"] = str(followup_preference)
        if decision_style:
            conversation["decision_style"] = str(decision_style)
        if prefers_brief_answers is not None:
            conversation["prefers_brief_answers"] = bool(prefers_brief_answers)

        if preferred_name:
            safe_memory["preferred_name"] = str(preferred_name).strip()[:48]

        if project_hint:
            value = str(project_hint).strip()[:80]
            if value:
                projects = [str(item) for item in list(safe_memory.get("projects", []) or []) if str(item).strip()]
                if value not in projects:
                    safe_memory["projects"] = [value, *projects][:8]

        profile["conversation_profile"] = conversation
        profile["safe_relational_memory"] = safe_memory
        profile["updated_at"] = int(time.time())
        self._save()
        return conversation

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
            "conversation_profile": self.get_conversation_profile(user_id),
            "safe_relational_memory": dict(profile.get("safe_relational_memory", {}) or {}),
        }


_profile_store: UserProfileStore | None = None


def get_user_profile_store() -> UserProfileStore:
    global _profile_store
    if _profile_store is None:
        _profile_store = UserProfileStore()
    return _profile_store
