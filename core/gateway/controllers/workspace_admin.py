from __future__ import annotations

from typing import Any

from aiohttp import web


def _json_ok(payload: dict[str, Any] | None = None, *, status: int = 200) -> web.Response:
    body = {"ok": True, "success": True}
    if payload:
        body.update(payload)
    return web.json_response(body, status=status)


def _json_error(error: str, *, status: int = 400, payload: dict[str, Any] | None = None) -> web.Response:
    body = {"ok": False, "success": False, "error": str(error or "unknown_error")}
    if payload:
        body.update(payload)
    return web.json_response(body, status=status)


class WorkspaceAdminController:
    _MEMBER_READ_ROLES = {"owner", "billing_admin", "security_admin", "operator", "viewer", "member"}
    _FINANCE_READ_ROLES = {"owner", "billing_admin"}
    _MANAGE_MEMBERS_ROLES = {"owner", "security_admin"}
    _MANAGE_ROLES_ROLES = {"owner"}
    _MANAGE_SEATS_ROLES = {"owner", "billing_admin"}

    def __init__(self, gateway_server: Any) -> None:
        self.server = gateway_server

    def _auth_context(self, request) -> dict[str, Any]:
        return self.server._auth_context(request)

    def _actor_id(self, request, payload: dict[str, Any] | None = None) -> str:
        return self.server._actor_id(request, payload)

    def _workspace_id(self, request, payload: dict[str, Any] | None = None) -> str:
        return self.server._workspace_id(request, payload)

    def _is_breakglass_admin(self, request) -> bool:
        auth = self._auth_context(request)
        return str(auth.get("role") or "") == "admin" and str(auth.get("user_id") or "") == "local-admin"

    def _workspace_role(self, request, workspace_id: str) -> str:
        if self._is_breakglass_admin(request):
            return "admin"
        auth = self._auth_context(request)
        role = str(auth.get("role") or "").strip().lower()
        if role and str(auth.get("workspace_id") or "").strip() == str(workspace_id or "").strip():
            return role
        return self.server._runtime_db().access.get_actor_role(
            workspace_id=workspace_id,
            actor_id=self._actor_id(request),
        )

    def _require_workspace_role(self, request, workspace_id: str, *, allowed: set[str]) -> tuple[bool, str]:
        role = self._workspace_role(request, workspace_id)
        if role == "admin":
            return True, role
        if role not in allowed:
            return False, role
        return True, role

    def _permission_flags(self, role: str) -> dict[str, bool]:
        if role == "admin":
            return {
                "view_workspace": True,
                "view_financials": True,
                "manage_members": True,
                "manage_roles": True,
                "manage_seats": True,
            }
        return {
            "view_workspace": role in self._MEMBER_READ_ROLES,
            "view_financials": role in self._FINANCE_READ_ROLES,
            "manage_members": role in self._MANAGE_MEMBERS_ROLES,
            "manage_roles": role in self._MANAGE_ROLES_ROLES,
            "manage_seats": role in self._MANAGE_SEATS_ROLES,
        }

    def _workspace_summary(self, workspace_id: str, *, include_financials: bool) -> dict[str, Any]:
        access = self.server._runtime_db().access
        workspace = access.get_workspace(workspace_id)
        if workspace is None:
            raise KeyError("workspace_not_found")
        payload = {
            "workspace": workspace,
            "seats": access.seat_summary(workspace_id),
        }
        if include_financials:
            payload["billing"] = self.server._workspace_billing().get_workspace_summary(workspace_id)
        return payload

    async def handle_create_workspace(self, request):
        """POST /api/v1/admin/workspaces — Create a new workspace."""
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid request body", status=400)

        display_name = str(data.get("display_name") or "").strip()
        if not display_name:
            return _json_error("display_name required", status=400)

        actor_id = self._actor_id(request)
        if not actor_id or actor_id == "local-workspace":
            return _json_error("authenticated user required", status=401)

        import secrets
        workspace_id = f"ws_{secrets.token_hex(8)}"

        access = self.server._runtime_db().access
        try:
            access.ensure_workspace(workspace_id, display_name=display_name)
            access.ensure_membership(workspace_id=workspace_id, actor_id=actor_id, role="owner")
            access.assign_seat(workspace_id=workspace_id, actor_id=actor_id, assigned_by=actor_id)
        except Exception as exc:
            return _json_error(f"workspace creation failed: {exc}", status=500)

        return _json_ok({
            "workspace_id": workspace_id,
            "display_name": display_name,
            "role": "owner",
        })

    async def handle_list_workspaces(self, request):
        access = self.server._runtime_db().access
        if self._is_breakglass_admin(request):
            workspaces = access.list_workspaces(include_inactive=True)
        else:
            workspaces = access.list_workspaces(actor_id=self._actor_id(request))
        items: list[dict[str, Any]] = []
        for item in workspaces:
            membership = dict(item.get("membership") or {})
            role = str(membership.get("role") or self._workspace_role(request, item["workspace_id"]) or "member")
            seat_summary = access.seat_summary(item["workspace_id"])
            entry = {
                "workspace_id": item["workspace_id"],
                "display_name": item.get("display_name") or item["workspace_id"],
                "status": item.get("status") or "active",
                "role": role,
                "seats": {
                    "seat_limit": seat_summary["seat_limit"],
                    "seats_used": seat_summary["seats_used"],
                    "seats_available": seat_summary["seats_available"],
                },
                "permissions": self._permission_flags(role),
            }
            if role in self._FINANCE_READ_ROLES or self._is_breakglass_admin(request):
                billing = self.server._workspace_billing().get_workspace_summary(item["workspace_id"])
                entry["billing"] = {
                    "plan_id": billing["plan"]["effective_id"],
                    "status": billing["subscription_state"]["status"],
                    "credits_total": int((billing.get("credit_balance") or {}).get("total") or 0),
                }
            items.append(entry)
        return _json_ok({"workspaces": items})

    async def handle_get_workspace(self, request):
        workspace_id = str(request.match_info.get("workspace_id") or "").strip()
        if not workspace_id:
            return _json_error("workspace_id required", status=400)
        allowed, role = self._require_workspace_role(request, workspace_id, allowed=self._MEMBER_READ_ROLES)
        if not allowed:
            return _json_error("workspace access denied", status=403, payload={"role": role})
        try:
            payload = self._workspace_summary(
                workspace_id,
                include_financials=bool(role == "admin" or role in self._FINANCE_READ_ROLES),
            )
        except KeyError:
            return _json_error("workspace not found", status=404)
        payload["permissions"] = self._permission_flags(role)
        payload["current_role"] = role
        return _json_ok(payload)

    async def handle_list_members(self, request):
        workspace_id = str(request.match_info.get("workspace_id") or "").strip()
        if not workspace_id:
            return _json_error("workspace_id required", status=400)
        allowed, role = self._require_workspace_role(request, workspace_id, allowed=self._MEMBER_READ_ROLES)
        if not allowed:
            return _json_error("workspace access denied", status=403, payload={"role": role})
        members = self.server._runtime_db().access.list_memberships(workspace_id, include_users=True)
        return _json_ok(
            {
                "workspace_id": workspace_id,
                "members": members,
                "permissions": self._permission_flags(role),
                "seats": self.server._runtime_db().access.seat_summary(workspace_id),
            }
        )

    async def handle_create_invite(self, request):
        workspace_id = str(request.match_info.get("workspace_id") or "").strip()
        if not workspace_id:
            return _json_error("workspace_id required", status=400)
        allowed, role = self._require_workspace_role(request, workspace_id, allowed=self._MANAGE_MEMBERS_ROLES | {"admin"})
        if not allowed:
            return _json_error("invite access denied", status=403, payload={"role": role})
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        try:
            invite = self.server._runtime_db().access.create_invite(
                workspace_id=workspace_id,
                email=str(data.get("email") or "").strip().lower(),
                role=str(data.get("role") or "member").strip().lower(),
                invited_by=self._actor_id(request, data),
                ttl_seconds=int(data.get("ttl_seconds") or 60 * 60 * 24 * 7),
                metadata=dict(data.get("metadata") or {}),
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        return _json_ok({"invite": invite}, status=201)

    async def handle_list_invites(self, request):
        workspace_id = str(request.match_info.get("workspace_id") or "").strip()
        if not workspace_id:
            return _json_error("workspace_id required", status=400)
        allowed, role = self._require_workspace_role(request, workspace_id, allowed=self._MANAGE_MEMBERS_ROLES | {"admin"})
        if not allowed:
            return _json_error("invite access denied", status=403, payload={"role": role})
        status = str(request.rel_url.query.get("status") or "").strip().lower()
        invites = self.server._runtime_db().access.list_invites(workspace_id, status=status)
        return _json_ok({"workspace_id": workspace_id, "invites": invites})

    async def handle_accept_invite(self, request):
        workspace_id = str(request.match_info.get("workspace_id") or "").strip()
        invite_id = str(request.match_info.get("invite_id") or "").strip()
        if not workspace_id:
            return _json_error("workspace_id required", status=400)
        if not invite_id:
            return _json_error("invite_id required", status=400)
        invite = self.server._runtime_db().access.get_invite(invite_id)
        if invite is None or str(invite.get("workspace_id") or "") != workspace_id:
            return _json_error("invite not found", status=404)
        auth = self._auth_context(request)
        role = self._workspace_role(request, workspace_id)
        email = str(auth.get("email") or "").strip().lower()
        is_manager = bool(role == "admin" or role in self._MANAGE_MEMBERS_ROLES)
        if not is_manager and email != str(invite.get("email") or "").strip().lower():
            return _json_error("invite access denied", status=403)
        try:
            payload = self.server._runtime_db().access.accept_invite(
                invite_id=invite_id,
                actor_id=self._actor_id(request),
                email="" if is_manager else email,
            )
        except PermissionError as exc:
            return _json_error(str(exc), status=403)
        if payload is None:
            return _json_error("invite unavailable", status=404)
        return _json_ok(payload)

    async def handle_update_role(self, request):
        workspace_id = str(request.match_info.get("workspace_id") or "").strip()
        actor_id = str(request.match_info.get("actor_id") or "").strip()
        if not workspace_id:
            return _json_error("workspace_id required", status=400)
        if not actor_id:
            return _json_error("actor_id required", status=400)
        allowed, role = self._require_workspace_role(request, workspace_id, allowed=self._MANAGE_ROLES_ROLES | {"admin"})
        if not allowed:
            return _json_error("role update denied", status=403, payload={"role": role})
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        try:
            membership = self.server._runtime_db().access.update_membership_role(
                workspace_id=workspace_id,
                actor_id=actor_id,
                role=str(data.get("role") or "").strip().lower(),
                updated_by=self._actor_id(request, data),
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        except KeyError:
            return _json_error("membership not found", status=404)
        except RuntimeError as exc:
            return _json_error(str(exc), status=409)
        return _json_ok({"membership": membership})

    async def handle_assign_seat(self, request):
        workspace_id = str(request.match_info.get("workspace_id") or "").strip()
        if not workspace_id:
            return _json_error("workspace_id required", status=400)
        allowed, role = self._require_workspace_role(request, workspace_id, allowed=self._MANAGE_SEATS_ROLES | {"admin"})
        if not allowed:
            return _json_error("seat assignment denied", status=403, payload={"role": role})
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        target_actor = str(data.get("actor_id") or data.get("user_id") or "").strip()
        if not target_actor:
            return _json_error("actor_id required", status=400)
        action = str(data.get("action") or "assign").strip().lower()
        if action == "release":
            released = self.server._runtime_db().access.release_seat(
                workspace_id=workspace_id,
                actor_id=target_actor,
                released_by=self._actor_id(request, data),
            )
            if not released:
                return _json_error("seat assignment not found", status=404)
            return _json_ok({"released": True, "seats": self.server._runtime_db().access.seat_summary(workspace_id)})
        try:
            assignment = self.server._runtime_db().access.assign_seat(
                workspace_id=workspace_id,
                actor_id=target_actor,
                assigned_by=self._actor_id(request, data),
            )
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        except KeyError:
            return _json_error("membership not found", status=404)
        except RuntimeError as exc:
            return _json_error(str(exc), status=409)
        return _json_ok({"assignment": assignment, "seats": self.server._runtime_db().access.seat_summary(workspace_id)})
