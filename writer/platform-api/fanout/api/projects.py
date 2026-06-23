"""M1 endpoints: who am I, and my (scoped) project list.

On first authenticated call we provision the caller's profile and Scratch
project (PRD §15.1). Reads go through the user-scoped client so RLS decides what
is visible: the Owner sees all projects, a VA sees only their own.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from fanout.auth import AuthedUser, require_user
from fanout.storage import ensure_scratch_project, ensure_user_profile, get_user_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["projects"])


class Me(BaseModel):
    user_id: str
    email: str | None
    display_name: str | None
    role: str


class Project(BaseModel):
    id: str
    name: str
    is_scratch: bool
    created_at: str


@router.get("/me", response_model=Me)
def get_me(user: AuthedUser = Depends(require_user)) -> Me:
    profile = ensure_user_profile(user.id, user.email)
    ensure_scratch_project(user.id)
    logger.info("me_resolved", extra={"event": "me_resolved", "role": profile["role"]})
    return Me(
        user_id=user.id,
        email=user.email,
        display_name=profile.get("display_name"),
        role=profile["role"],
    )


@router.get("/projects", response_model=list[Project])
def list_projects(user: AuthedUser = Depends(require_user)) -> list[Project]:
    # Ensure the caller is provisioned before listing (idempotent).
    ensure_user_profile(user.id, user.email)
    ensure_scratch_project(user.id)

    # Scoped read: RLS on fanout.projects decides visibility from the user's JWT.
    client = get_user_client(user.access_token)
    rows = (
        client.table("projects")
        .select("id, name, is_scratch, created_at")
        .order("created_at")
        .execute()
    )
    logger.info(
        "projects_listed",
        extra={"event": "projects_listed", "count": len(rows.data)},
    )
    return [Project(**row) for row in rows.data]
