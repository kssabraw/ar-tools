"""Pydantic models for User resources."""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    role: str
    created_at: str


class UserInviteRequest(BaseModel):
    email: EmailStr
    role: Literal["admin", "team_member"] = "team_member"
    # Where Supabase sends the invitee after they click the email link. The
    # frontend passes its own origin + "/set-password" so the invitee lands on
    # the set-password screen. Must be in Supabase's redirect allowlist.
    redirect_to: Optional[str] = None


class UserRoleUpdateRequest(BaseModel):
    role: Literal["admin", "team_member"]


class PasswordResetEmailRequest(BaseModel):
    # Optional redirect target for the recovery email (see UserInviteRequest).
    redirect_to: Optional[str] = None


class PasswordSetRequest(BaseModel):
    # bcrypt truncates beyond 72 bytes; 8 is the app-level floor (Supabase's
    # own default minimum is 6). The plaintext password is never logged.
    password: str = Field(min_length=8, max_length=72)
