import logging

from fastapi import HTTPException, Request

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Suite role model, ordered by privilege. Higher rank = more access.
#   client      — external, READ-ONLY viewer (blocked from any mutation below)
#   team_member — VA, internal operational user
#   staff       — senior internal operator (= admin minus user/team management)
#   admin       — full access, incl. user/team management
ROLE_RANK: dict[str, int] = {
    "client": 0,
    "team_member": 1,
    "staff": 2,
    "admin": 3,
}

# Roles that may only read. Any non-safe HTTP method is rejected for them.
READ_ONLY_ROLES = {"client"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def role_rank(role: str | None) -> int:
    """Privilege rank for a role. Unknown/None sorts lowest so a malformed role
    never accidentally clears a gate."""
    return ROLE_RANK.get(role or "", -1)


def is_staff_or_above(role: str | None) -> bool:
    """True for the senior-operator tiers (staff, admin)."""
    return role_rank(role) >= ROLE_RANK["staff"]


async def require_auth(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthenticated")

    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="unauthenticated")

    try:
        supabase = get_supabase()
        user_response = supabase.auth.get_user(token)
        user = user_response.user
        if not user:
            raise HTTPException(status_code=401, detail="unauthenticated")

        profile = (
            supabase.table("profiles")
            .select("role")
            .eq("id", str(user.id))
            .single()
            .execute()
        )

        request.state.user_id = str(user.id)
        request.state.role = profile.data["role"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("auth_failed", extra={"error": str(e)})
        raise HTTPException(status_code=401, detail="unauthenticated")

    # Read-only roles (e.g. 'client') may never mutate. Enforced centrally here
    # so every endpoint depending on require_auth (directly or via the role
    # gates below) is covered without per-route changes.
    if request.state.role in READ_ONLY_ROLES and request.method not in _SAFE_METHODS:
        raise HTTPException(status_code=403, detail="read_only_role")

    return {"user_id": request.state.user_id, "role": request.state.role}


def require_min_role(minimum: str):
    """Build a dependency that requires at least `minimum` privilege rank."""
    threshold = ROLE_RANK[minimum]

    async def _dependency(request: Request) -> dict:
        auth = await require_auth(request)
        if role_rank(auth["role"]) < threshold:
            raise HTTPException(status_code=403, detail="forbidden")
        return auth

    return _dependency


# Senior internal operator (staff or admin): everything except user/team
# management, which stays admin-only.
require_staff = require_min_role("staff")

# Full access, incl. user/team management. Only 'admin' clears this.
require_admin = require_min_role("admin")
