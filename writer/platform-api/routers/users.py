"""Users router — admin-only user management."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from db.supabase_client import get_supabase
from middleware.auth import require_admin
from models.users import (
    PasswordResetEmailRequest,
    PasswordSetRequest,
    UserCreateRequest,
    UserInviteRequest,
    UserResponse,
    UserRoleUpdateRequest,
)

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
    options = {"redirect_to": body.redirect_to} if body.redirect_to else {}
    try:
        resp = supabase.auth.admin.invite_user_by_email(body.email, options)
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


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    body: UserCreateRequest,
    auth: dict = Depends(require_admin),
) -> UserResponse:
    """Create a user directly with an email + password (no invite email).

    The account is created already email-confirmed so the user can sign in
    immediately with the credentials the admin sets and relays out-of-band.
    """
    supabase = get_supabase()
    try:
        resp = supabase.auth.admin.create_user(
            {
                "email": body.email,
                "password": body.password,
                "email_confirm": True,
            }
        )
        user_id = str(resp.user.id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"create_failed: {exc}") from exc

    # The on_auth_user_created trigger inserts the profile row; set the role.
    supabase.table("profiles").update({"role": body.role}).eq("id", user_id).execute()

    logger.info(
        "user_created_direct",
        extra={"target_user_id": user_id, "user_id": auth["user_id"]},
    )

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


@router.post("/users/{user_id}/password", response_model=dict)
async def set_user_password(
    user_id: UUID,
    body: PasswordSetRequest,
    auth: dict = Depends(require_admin),
) -> dict:
    """Admin directly sets a new password for a user (e.g. a VA who can't
    receive the reset email). The admin relays the password out-of-band."""
    supabase = get_supabase()
    try:
        supabase.auth.admin.update_user_by_id(str(user_id), {"password": body.password})
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"password_update_failed: {exc}") from exc

    logger.info(
        "user_password_set",
        extra={"target_user_id": str(user_id), "user_id": auth["user_id"]},
    )
    return {"id": str(user_id), "password_set": True}


@router.post("/users/{user_id}/password-reset", response_model=dict)
async def send_password_reset(
    user_id: UUID,
    body: PasswordResetEmailRequest = PasswordResetEmailRequest(),
    auth: dict = Depends(require_admin),
) -> dict:
    """Trigger a Supabase password-recovery email so the user sets their own
    password. The admin never sees the password."""
    supabase = get_supabase()
    user_resp = supabase.auth.admin.get_user_by_id(str(user_id))
    email = user_resp.user.email if user_resp and user_resp.user else None
    if not email:
        raise HTTPException(status_code=404, detail="user_not_found")

    options = {"redirect_to": body.redirect_to} if body.redirect_to else {}
    try:
        supabase.auth.reset_password_for_email(email, options)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"reset_email_failed: {exc}") from exc

    logger.info(
        "user_password_reset_sent",
        extra={"target_user_id": str(user_id), "user_id": auth["user_id"]},
    )
    return {"id": str(user_id), "email": email, "reset_sent": True}


@router.delete("/users/{user_id}", status_code=204, response_class=Response)
async def delete_user(
    user_id: UUID,
    auth: dict = Depends(require_admin),
) -> Response:
    if str(user_id) == auth["user_id"]:
        raise HTTPException(status_code=409, detail="cannot_delete_self")

    supabase = get_supabase()
    try:
        supabase.auth.admin.delete_user(str(user_id))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"delete_failed: {exc}") from exc

    return Response(status_code=204)
