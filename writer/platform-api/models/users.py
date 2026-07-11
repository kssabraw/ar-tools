"""Pydantic models for User resources."""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

# Suite user types, ordered by privilege in middleware.auth.ROLE_RANK.
UserRole = Literal["admin", "staff", "team_member", "client"]


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    role: str
    created_at: str
    # PACE identity bridge: the Slack user this suite login maps to, if linked.
    slack_user_id: Optional[str] = None


class UserSlackLinkRequest(BaseModel):
    # An empty/blank value clears the link. Slack user ids look like "U01ABCDEF".
    slack_user_id: Optional[str] = None


class UserInviteRequest(BaseModel):
    email: EmailStr
    role: UserRole = "team_member"
    # Where Supabase sends the invitee after they click the email link. The
    # frontend passes its own origin + "/set-password" so the invitee lands on
    # the set-password screen. Must be in Supabase's redirect allowlist.
    redirect_to: Optional[str] = None


class UserCreateRequest(BaseModel):
    # Direct create: admin sets the email + password themselves and relays the
    # credentials out-of-band. No invite email is sent and the account is
    # created already email-confirmed so the user can sign in immediately.
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: UserRole = "team_member"


class UserRoleUpdateRequest(BaseModel):
    role: UserRole


class PasswordResetEmailRequest(BaseModel):
    # Optional redirect target for the recovery email (see UserInviteRequest).
    redirect_to: Optional[str] = None


class PasswordSetRequest(BaseModel):
    # bcrypt truncates beyond 72 bytes; 8 is the app-level floor (Supabase's
    # own default minimum is 6). The plaintext password is never logged.
    password: str = Field(min_length=8, max_length=72)
