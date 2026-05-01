import logging

from fastapi import HTTPException, Request

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


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
        return {"user_id": request.state.user_id, "role": request.state.role}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("auth_failed", extra={"error": str(e)})
        raise HTTPException(status_code=401, detail="unauthenticated")


async def require_admin(request: Request) -> dict:
    auth = await require_auth(request)
    if auth["role"] != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return auth
