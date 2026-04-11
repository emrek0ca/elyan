from __future__ import annotations

from typing import Any

from core.persistence.runtime_db import RuntimeDatabase, get_runtime_database


class RuntimeSessionAPI:
    def __init__(self, runtime_db: RuntimeDatabase | None = None) -> None:
        self._runtime_db = runtime_db

    @property
    def db(self) -> RuntimeDatabase:
        return self._runtime_db or get_runtime_database()

    @staticmethod
    def _runtime_scope(user_id: str, runtime_metadata: dict[str, Any] | None = None) -> dict[str, str]:
        runtime_metadata = dict(runtime_metadata or {})
        sync = runtime_metadata.get("sync") if isinstance(runtime_metadata.get("sync"), dict) else {}
        session_id = str(sync.get("session_id") or runtime_metadata.get("session_id") or "").strip()
        channel_session_id = str(runtime_metadata.get("channel_session_id") or session_id).strip()
        return {
            "workspace_id": str(runtime_metadata.get("workspace_id") or "local-workspace").strip() or "local-workspace",
            "actor_id": str(runtime_metadata.get("user_id") or user_id or "local-user").strip() or "local-user",
            "device_id": str(sync.get("device_id") or runtime_metadata.get("device_id") or runtime_metadata.get("client_id") or "local-device").strip() or "local-device",
            "channel": str(runtime_metadata.get("channel") or runtime_metadata.get("channel_type") or "cli").strip() or "cli",
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


_runtime_session_api: RuntimeSessionAPI | None = None


def get_runtime_session_api() -> RuntimeSessionAPI:
    global _runtime_session_api
    if _runtime_session_api is None:
        _runtime_session_api = RuntimeSessionAPI()
    return _runtime_session_api


__all__ = ["RuntimeSessionAPI", "get_runtime_session_api"]
