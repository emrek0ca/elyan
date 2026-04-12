from __future__ import annotations

from typing import Any

from core.persistence.runtime_db import RuntimeDatabase, get_runtime_database


def _draft_name_hint_to_title(value: str) -> str:
    parts = [part for part in str(value or "").strip().replace("-", " ").replace("_", " ").split() if part]
    if not parts:
        return ""
    return " ".join(part[:1].upper() + part[1:] for part in parts[:8])


class RuntimeSessionAPI:
    def __init__(self, runtime_db: RuntimeDatabase | None = None) -> None:
        self._runtime_db = runtime_db

    @property
    def db(self) -> RuntimeDatabase:
        return self._runtime_db or get_runtime_database()

    def _runtime_scope(self, user_id: str, runtime_metadata: dict[str, Any] | None = None) -> dict[str, str]:
        runtime_metadata = dict(runtime_metadata or {})
        sync = runtime_metadata.get("sync") if isinstance(runtime_metadata.get("sync"), dict) else {}
        session_id = str(sync.get("session_id") or runtime_metadata.get("session_id") or "").strip()
        channel_session_id = str(runtime_metadata.get("channel_session_id") or session_id).strip()
        workspace_id = str(runtime_metadata.get("workspace_id") or "local-workspace").strip() or "local-workspace"
        channel = str(runtime_metadata.get("channel") or runtime_metadata.get("channel_type") or "cli").strip() or "cli"
        external_user_id = str(
            runtime_metadata.get("external_user_id")
            or runtime_metadata.get("channel_user_id")
            or runtime_metadata.get("user_id")
            or user_id
            or "local-user"
        ).strip() or "local-user"
        actor_id = str(runtime_metadata.get("actor_id") or "").strip()
        if not actor_id and channel != "cli":
            linked = self.db.identities.resolve_actor(
                workspace_id=workspace_id,
                channel=channel,
                external_user_id=external_user_id,
            )
            if linked:
                actor_id = str(linked.get("actor_id") or "").strip()
        actor_id = actor_id or external_user_id or "local-user"
        return {
            "workspace_id": workspace_id,
            "actor_id": actor_id,
            "device_id": str(sync.get("device_id") or runtime_metadata.get("device_id") or runtime_metadata.get("client_id") or "local-device").strip() or "local-device",
            "channel": channel,
            "external_user_id": external_user_id,
            "auth_session_id": session_id,
            "client_session_id": channel_session_id,
            "conversation_session_id": str(runtime_metadata.get("conversation_session_id") or "").strip(),
        }

    def ensure_session(
        self,
        *,
        user_id: str,
        runtime_metadata: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = self._runtime_scope(str(user_id or ""), runtime_metadata)
        session_metadata = {
            **dict(runtime_metadata or {}),
            **dict(metadata or {}),
        }
        if scope["channel"] != "cli" and scope["external_user_id"]:
            self.db.identities.bind_identity(
                workspace_id=scope["workspace_id"],
                channel=scope["channel"],
                external_user_id=scope["external_user_id"],
                actor_id=scope["actor_id"],
                display_name=str(session_metadata.get("user_name") or session_metadata.get("display_name") or "").strip(),
                metadata={
                    "auth_session_id": scope["auth_session_id"],
                    "client_session_id": scope["client_session_id"],
                },
            )
        return self.db.conversations.ensure_session(
            workspace_id=scope["workspace_id"],
            actor_id=scope["actor_id"],
            device_id=scope["device_id"],
            channel=scope["channel"],
            auth_session_id=scope["auth_session_id"],
            client_session_id=scope["client_session_id"],
            conversation_session_id=scope["conversation_session_id"],
            metadata=session_metadata,
        )

    def ensure_auth_session(self, auth_session: dict[str, Any]) -> dict[str, Any]:
        session = dict(auth_session or {})
        metadata = dict(session.get("metadata") or {}) if isinstance(session.get("metadata"), dict) else {}
        conversation = self.ensure_session(
            user_id=str(session.get("user_id") or ""),
            runtime_metadata={
                "workspace_id": str(session.get("workspace_id") or "local-workspace"),
                "user_id": str(session.get("user_id") or ""),
                "device_id": str(metadata.get("device_id") or metadata.get("client_id") or metadata.get("client") or "desktop"),
                "channel": str(metadata.get("client") or "desktop"),
                "session_id": str(session.get("session_id") or ""),
                "channel_session_id": str(session.get("session_id") or ""),
                "conversation_session_id": str(session.get("conversation_session_id") or metadata.get("conversation_session_id") or ""),
            },
            metadata={
                "source": "auth_session",
                "login_source": str(metadata.get("login_source") or ""),
                "client": str(metadata.get("client") or ""),
            },
        )
        conversation_id = str(conversation.get("conversation_session_id") or "").strip()
        if not conversation_id:
            return session
        if str(session.get("conversation_session_id") or "") != conversation_id:
            updated = self.db.auth_sessions.update_metadata(
                str(session.get("session_id") or ""),
                {"conversation_session_id": conversation_id},
            )
            if updated:
                session = dict(updated)
        merged_metadata = {
            **metadata,
            "conversation_session_id": conversation_id,
        }
        session["metadata"] = merged_metadata
        session["conversation_session_id"] = conversation_id
        return session

    def append_turn(
        self,
        *,
        user_id: str,
        user_input: str,
        response_text: str,
        action: str,
        success: bool,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self.ensure_session(
            user_id=user_id,
            runtime_metadata=runtime_metadata,
            metadata={"last_action": str(action or "chat")},
        )
        conversation_id = str(session.get("conversation_session_id") or "")
        if str(user_input or "").strip():
            self.db.conversations.append_message(
                conversation_session_id=conversation_id,
                role="user",
                content=str(user_input or ""),
                workspace_id=str(session.get("workspace_id") or ""),
                actor_id=str(session.get("actor_id") or ""),
                run_id=str((runtime_metadata or {}).get("run_id") or ""),
                metadata={
                    "channel": str((runtime_metadata or {}).get("channel") or ""),
                },
            )
        if str(response_text or "").strip():
            self.db.conversations.append_message(
                conversation_session_id=conversation_id,
                role="assistant",
                content=str(response_text or ""),
                workspace_id=str(session.get("workspace_id") or ""),
                actor_id=str(session.get("actor_id") or ""),
                run_id=str((runtime_metadata or {}).get("run_id") or ""),
                action=str(action or ""),
                success=bool(success),
                metadata={
                    "channel": str((runtime_metadata or {}).get("channel") or ""),
                    "action": str(action or ""),
                    "success": bool(success),
                },
            )
        refreshed = self.db.conversations.get_session(conversation_id)
        return refreshed or session

    def get_recent_conversations(
        self,
        *,
        user_id: str,
        limit: int = 8,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        session = self.ensure_session(user_id=user_id, runtime_metadata=runtime_metadata)
        session_id = str(session.get("conversation_session_id") or "")
        messages = self.db.conversations.list_recent_messages(session_id, limit=max(1, int(limit or 8)) * 2)
        if not messages:
            return []
        turns: list[dict[str, Any]] = []
        pending_user: dict[str, Any] | None = None
        for message in messages:
            role = str(message.get("role") or "").strip().lower()
            if role == "user":
                if pending_user:
                    turns.append(
                        {
                            "conversation_session_id": session_id,
                            "workspace_id": str(session.get("workspace_id") or ""),
                            "user_message": str(pending_user.get("content") or ""),
                            "bot_response": "",
                            "timestamp": float(pending_user.get("created_at") or 0.0),
                        }
                    )
                pending_user = message
                continue
            if role == "assistant":
                turns.append(
                    {
                        "conversation_session_id": session_id,
                        "workspace_id": str(session.get("workspace_id") or ""),
                        "user_message": str((pending_user or {}).get("content") or ""),
                        "bot_response": str(message.get("content") or ""),
                        "action": str(message.get("action") or ""),
                        "success": bool(message.get("success")),
                        "timestamp": float(message.get("created_at") or (pending_user or {}).get("created_at") or 0.0),
                    }
                )
                pending_user = None
        if pending_user:
            turns.append(
                {
                    "conversation_session_id": session_id,
                    "workspace_id": str(session.get("workspace_id") or ""),
                    "user_message": str(pending_user.get("content") or ""),
                    "bot_response": "",
                    "timestamp": float(pending_user.get("created_at") or 0.0),
                }
            )
        turns = turns[-max(1, int(limit or 8)) :]
        turns.reverse()
        return turns

    def list_recent_history(
        self,
        *,
        user_id: str,
        limit: int = 8,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        scope = self._runtime_scope(str(user_id or ""), runtime_metadata)
        return self.db.conversations.list_recent_turns(
            workspace_id=scope["workspace_id"],
            actor_id=scope["actor_id"],
            limit=max(1, int(limit or 8)),
        )

    def search_history(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 8,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        scope = self._runtime_scope(str(user_id or ""), runtime_metadata)
        return self.db.conversations.search_turns(
            workspace_id=scope["workspace_id"],
            actor_id=scope["actor_id"],
            query=str(query or ""),
            limit=max(1, int(limit or 8)),
        )

    def get_preference_profile(
        self,
        *,
        user_id: str,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        scope = self._runtime_scope(str(user_id or ""), runtime_metadata)
        return self.db.learning.get_user_preference_profile(
            workspace_id=scope["workspace_id"],
            user_id=scope["actor_id"],
        )

    def list_learning_drafts(
        self,
        *,
        user_id: str,
        draft_type: str = "all",
        limit: int = 20,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        scope = self._runtime_scope(str(user_id or ""), runtime_metadata)
        normalized = str(draft_type or "all").strip().lower() or "all"
        result = {"preferences": [], "skills": [], "routines": []}
        if normalized in {"all", "preferences", "preference"}:
            result["preferences"] = self.db.learning.list_preference_updates(
                workspace_id=scope["workspace_id"],
                user_id=scope["actor_id"],
                limit=max(1, int(limit or 20)),
            )
        if normalized in {"all", "skills", "skill"}:
            result["skills"] = self.db.learning.list_skill_drafts(
                workspace_id=scope["workspace_id"],
                user_id=scope["actor_id"],
                limit=max(1, int(limit or 20)),
            )
        if normalized in {"all", "routines", "routine"}:
            result["routines"] = self.db.learning.list_routine_drafts(
                workspace_id=scope["workspace_id"],
                user_id=scope["actor_id"],
                limit=max(1, int(limit or 20)),
            )
        return result

    def promote_routine_draft(
        self,
        *,
        user_id: str,
        draft_id: str,
        runtime_metadata: dict[str, Any] | None = None,
        enabled: bool = True,
        name: str = "",
        expression: str = "",
        report_channel: str = "",
        report_chat_id: str = "",
    ) -> dict[str, Any]:
        scope = self._runtime_scope(str(user_id or ""), runtime_metadata)
        draft = self.db.learning.get_routine_draft(
            workspace_id=scope["workspace_id"],
            user_id=scope["actor_id"],
            draft_id=str(draft_id or ""),
        )
        if not draft:
            raise KeyError("routine draft not found")
        status = str(draft.get("status") or "draft").strip().lower()
        if status not in {"draft", "approved"}:
            raise ValueError(f"routine draft not promotable: {status}")

        from core.scheduler.routine_engine import routine_engine

        source_text = (
            str(draft.get("trigger_text") or "").strip()
            or str(draft.get("description") or "").strip()
            or _draft_name_hint_to_title(str(draft.get("name_hint") or ""))
        )
        if not source_text:
            raise ValueError("routine draft source text missing")
        final_name = str(name or "").strip() or str(draft.get("description") or "").strip() or _draft_name_hint_to_title(str(draft.get("name_hint") or ""))
        routine = routine_engine.create_from_text(
            text=source_text,
            enabled=bool(enabled),
            created_by="learning-draft",
            report_chat_id=str(report_chat_id or "").strip(),
            report_channel=str(report_channel or draft.get("delivery_channel") or "").strip(),
            expression=str(expression or draft.get("schedule_expression") or "").strip(),
            name=final_name,
            tags=["learned", "approved-draft"],
            metadata={
                "workspace_id": scope["workspace_id"],
                "actor_id": scope["actor_id"],
                "source_draft_id": str(draft.get("draft_id") or ""),
            },
        )
        updated_draft = self.db.learning.update_routine_draft_status(
            workspace_id=scope["workspace_id"],
            user_id=scope["actor_id"],
            draft_id=str(draft["draft_id"]),
            status="promoted",
            metadata={
                "promoted_routine_id": str(routine.get("id") or ""),
                "promoted_at": str(routine.get("updated_at") or ""),
            },
        )
        return {
            "draft": updated_draft or draft,
            "routine": routine,
        }

    def promote_skill_draft(
        self,
        *,
        user_id: str,
        draft_id: str,
        runtime_metadata: dict[str, Any] | None = None,
        name: str = "",
        description: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        scope = self._runtime_scope(str(user_id or ""), runtime_metadata)
        draft = self.db.learning.get_skill_draft(
            workspace_id=scope["workspace_id"],
            user_id=scope["actor_id"],
            draft_id=str(draft_id or ""),
        )
        if not draft:
            raise KeyError("skill draft not found")
        status = str(draft.get("status") or "draft").strip().lower()
        if status not in {"draft", "approved"}:
            raise ValueError(f"skill draft not promotable: {status}")

        from core.skills.manager import skill_manager

        skill_name = str(name or draft.get("name_hint") or "").strip().lower().replace(" ", "_").replace("-", "_")
        if not skill_name:
            raise ValueError("skill draft name missing")
        skill_description = str(description or draft.get("description") or "").strip() or f"{skill_name} workflow skill"

        ok, msg, info = skill_manager.install_skill(skill_name)
        if not ok:
            raise RuntimeError(msg or "skill install failed")
        ok, msg, info = skill_manager.edit_skill(
            skill_name,
            {
                "description": skill_description,
                "category": "learned",
                "source": "learning_draft",
                "required_tools": list(draft.get("tool_names") or []),
                "commands": [],
                "enabled": bool(enabled),
                "metadata": {
                    "workspace_id": scope["workspace_id"],
                    "actor_id": scope["actor_id"],
                    "source_draft_id": str(draft.get("draft_id") or ""),
                    "trigger_text": str(draft.get("trigger_text") or ""),
                    "confidence": float(draft.get("confidence") or 0.0),
                },
            },
        )
        if not ok:
            raise RuntimeError(msg or "skill manifest update failed")
        updated_draft = self.db.learning.update_skill_draft_status(
            workspace_id=scope["workspace_id"],
            user_id=scope["actor_id"],
            draft_id=str(draft["draft_id"]),
            status="promoted",
            metadata={
                "promoted_skill_name": skill_name,
                "promoted_at": str((info or {}).get("updated_at") or ""),
            },
        )
        return {
            "draft": updated_draft or draft,
            "skill": info or {"name": skill_name},
        }


_runtime_session_api: RuntimeSessionAPI | None = None


def get_runtime_session_api() -> RuntimeSessionAPI:
    global _runtime_session_api
    if _runtime_session_api is None:
        _runtime_session_api = RuntimeSessionAPI()
    return _runtime_session_api


__all__ = ["RuntimeSessionAPI", "get_runtime_session_api"]
