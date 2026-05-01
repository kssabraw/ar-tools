"""Users router — admin-only user management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from db.supabase_client import get_supabase
from middleware.auth import require_admin
from models.users import UserInviteRequest, UserResponse, UserRoleUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(auth: dict = Depends(require_admin)) -> list[UserResponse]:
    supabase = get_supabase()
    profiles = supabase.table("profiles").select("id, full_name, role, created_at").execute()

    # Get emails from auth.users via admin API
    users_resp = supabase.auth.admin.list_users()
    email_map: dict[str, str] = {}
    for u in (users_resp or []):
        email_map[str(u.id)] = u.email or ""

    out = []
    for p in profiles.data or []:
        out.append(
            UserResponse(
                id=p["id"],
                email=email_map.get(p["id"], ""),
                full_name=p.get("full_name"),
                role=p["role"],
                created_at=p["created_at"],
            )
        )
    return out


@router.post("/users/invite", response_model=UserResponse, status_code=201)
async def invite_user(
    body: UserInviteRequest,
    auth: dict = Depends(require_admin),
) -> UserResponse:
    supabase = get_supabase()
    try:
        resp = supabase.auth.admin.invite_user_by_email(body.email)
        user_id = str(resp.user.id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invite_failed: {exc}") from exc

    # Set role in profile
    supabase.table("profiles").update({"role": body.role}).eq("id", user_id).execute()

    return UserResponse(
        id=user_id,
        email=body.email,
        full_name=None,
        role=body.role,
        created_at=resp.user.created_at.isoformat() if resp.user.created_at else "",
    )


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: UUID,
    body: UserRoleUpdateRequest,
    auth: dict = Depends(require_admin),
) -> UserResponse:
    supabase = get_supabase()

    # Guard: cannot demote self if last admin
    if str(user_id) == auth["user_id"] and body.role != "admin":
        admins = (
            supabase.table("profiles").select("id", count="exact").eq("role", "admin").execute()
        )
        if (admins.count or 0) <= 1:
            raise HTTPException(status_code=409, detail="last_admin_demotion")

    result = (
        supabase.table("profiles")
        .update({"role": body.role})
        .eq("id", str(user_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="user_not_found")

    p = result.data[0]
    user_resp = supabase.auth.admin.get_user_by_id(str(user_id))
    email = user_resp.user.email if user_resp and user_resp.user else ""

    return UserResponse(
        id=p["id"],
        email=email,
        full_name=p.get("full_name"),
        role=p["role"],
        created_at=p["created_at"],
    )


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    auth: dict = Depends(require_admin),
) -> None:
    if str(user_id) == auth["user_id"]:
        raise HTTPException(status_code=409, detail="cannot_delete_self")

    supabase = get_supabase()
    try:
        supabase.auth.admin.delete_user(str(user_id))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"delete_failed: {exc}") from exc
