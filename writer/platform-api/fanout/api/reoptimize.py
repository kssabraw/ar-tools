"""Fan-out blog reoptimization endpoints.

Score + rewrite-to-threshold a Fan-out blog article by driving the suite's blog
score/reopt spine on the article's mirrored suite run, then reflecting the
improved article back into the Fan-out Articles library. Owner-only (like article
generation). Only **client-linked** articles are reoptimizable — an unlinked one
is refused with ``not_client_linked`` (409). See ``fanout/reoptimize.py``.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from fanout import reoptimize as reopt
from fanout.auth import AuthedUser, require_owner
from fanout.storage import silo as store

router = APIRouter(tags=["reoptimize"])


def _require_session(user: AuthedUser, session_id: str) -> dict:
    session = store.session_visible_to_user(user.access_token, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def _require_cluster_in_session(session_id: str, cluster_id: str) -> None:
    sid = store.cluster_session_id(cluster_id)
    if not sid or sid != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")


@router.post("/sessions/{session_id}/clusters/{cluster_id}/reopt-score", status_code=status.HTTP_202_ACCEPTED)
def score_article(
    session_id: str, cluster_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Score the cluster's latest article (via its mirrored suite run). Enqueues a
    background ``fanout_blog_score`` job; poll via /reopt-jobs/status."""
    _require_session(user, session_id)
    _require_cluster_in_session(session_id, cluster_id)
    job_id = reopt.enqueue_score(cluster_id, user.id)
    return {"job_id": job_id, "cluster_id": cluster_id}


@router.post("/sessions/{session_id}/clusters/{cluster_id}/reopt", status_code=status.HTTP_202_ACCEPTED)
def reoptimize_article(
    session_id: str, cluster_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Reoptimize the cluster's latest article: score → rewrite-to-threshold on the
    mirrored suite run → reflect the improved article back into the library.
    Enqueues a background ``fanout_blog_reoptimize`` job; poll via /reopt-jobs/status."""
    _require_session(user, session_id)
    _require_cluster_in_session(session_id, cluster_id)
    job_id = reopt.enqueue_reoptimize(cluster_id, user.id)
    return {"job_id": job_id, "cluster_id": cluster_id}


class ReoptBulkBody(BaseModel):
    cluster_ids: list[str]


@router.post("/sessions/{session_id}/reopt-bulk", status_code=status.HTTP_202_ACCEPTED)
def reoptimize_bulk(
    session_id: str, body: ReoptBulkBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Reoptimize each ticked article. Each becomes its own background job;
    articles that can't be reoptimized (not client-linked / no article) are
    returned in ``skipped`` with a reason rather than failing the batch."""
    _require_session(user, session_id)
    jobs: list[dict] = []
    skipped: list[dict] = []
    for cid in (body.cluster_ids or [])[:200]:
        try:
            _require_cluster_in_session(session_id, cid)
            jobs.append({"cluster_id": cid, "job_id": reopt.enqueue_reoptimize(cid, user.id)})
        except HTTPException as exc:
            skipped.append({"cluster_id": cid, "reason": str(exc.detail)})
    return {"jobs": jobs, "skipped": skipped, "count": len(jobs)}


class ReoptStatusBody(BaseModel):
    job_ids: list[str]


@router.post("/sessions/{session_id}/reopt-jobs/status")
def reopt_jobs_status(
    session_id: str, body: ReoptStatusBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Batch-poll reopt jobs for a session (scoped so a caller only sees jobs for a
    session they can access)."""
    _require_session(user, session_id)
    return {"jobs": reopt.read_jobs(session_id, body.job_ids or [])}


@router.get("/clients/{client_id}/reoptimizable-articles")
def list_reoptimizable(
    client_id: str, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Client-scoped list of reoptimizable Fan-out articles (the shared suite
    ReoptimizePanel's 'pick existing' source): the latest client-linked article
    per cluster across the client's Fan-out sessions."""
    items = reopt.list_client_reoptimizable(client_id)
    return {"articles": items, "count": len(items)}


@router.post("/clients/{client_id}/reopt-bulk", status_code=status.HTTP_202_ACCEPTED)
def client_reoptimize_bulk(
    client_id: str, body: ReoptBulkBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Client-scoped bulk reoptimize (the shared ReoptimizePanel). One background
    job per cluster; each is asserted to belong to this client, and any that
    can't be reoptimized are returned in ``skipped``."""
    jobs: list[dict] = []
    skipped: list[dict] = []
    for cid in (body.cluster_ids or [])[:200]:
        try:
            jobs.append({
                "cluster_id": cid,
                "job_id": reopt.enqueue_reoptimize_for_client(cid, client_id, user.id),
            })
        except HTTPException as exc:
            skipped.append({"cluster_id": cid, "reason": str(exc.detail)})
    return {"jobs": jobs, "skipped": skipped, "count": len(jobs)}


@router.post("/clients/{client_id}/reopt-jobs/status")
def client_reopt_jobs_status(
    client_id: str, body: ReoptStatusBody, user: AuthedUser = Depends(require_owner)
) -> dict:
    """Batch-poll client-scoped reopt jobs (the shared ReoptimizePanel)."""
    return {"jobs": reopt.read_jobs_for_client(client_id, body.job_ids or [])}
