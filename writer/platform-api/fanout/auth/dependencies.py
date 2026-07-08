"""Auth dependency: verify the Supabase JWT and expose the caller.

The bearer token is validated against Supabase Auth (which checks the
signature/expiry). The raw token is retained on the returned object so scoped
queries can run as the user with RLS enforced.
"""

from dataclasses import dataclass
import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fanout.storage import ensure_user_profile, get_service_client, host_is_read_only

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=True)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class AuthedUser:
    id: str
    email: str | None
    access_token: str


def require_user(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> AuthedUser:
    token = creds.credentials
    try:
        result = get_service_client().auth.get_user(token)
    except Exception as exc:
        # Log the real reason (token rejected vs. a server/config error) but
        # don't leak it to the client.
        logger.warning(
            "auth_verification_failed",
            extra={"event": "auth_verification_failed", "reason": repr(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = getattr(result, "user", None)
    if user is None or not user.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Read-only suite roles ('client') may never mutate — mirror the suite's
    # require_auth guard, which never runs for /fanout routes. The host-role
    # lookup only runs on write requests so reads pay no extra query.
    if request.method not in _SAFE_METHODS and host_is_read_only(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="read_only_role",
        )

    return AuthedUser(id=user.id, email=user.email, access_token=token)


def get_role(user: AuthedUser) -> str:
    """Resolve the caller's workspace role ('owner' | 'va'). Reads (and on first
    login provisions) the profile via the service client. Used by endpoints that
    must enforce the §11.2 capability matrix server-side — RLS scopes *which rows*
    a user sees, but the backend's writes run as service_role (RLS-bypassing), so
    capability restrictions can't lean on RLS alone."""
    profile = ensure_user_profile(user.id, user.email)
    return profile["role"]


def require_owner(user: AuthedUser = Depends(require_user)) -> AuthedUser:
    """Gate an endpoint to owners (PRD §11.2). A VA hitting an owner-only action
    gets 403 before the handler runs — defense in depth behind the VA UI, which
    never surfaces these controls (§10.3)."""
    if get_role(user) != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is restricted to the workspace owner.",
        )
    return user
