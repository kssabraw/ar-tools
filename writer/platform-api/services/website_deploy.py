"""Website Builder — resolving what happened to a deploy.

A site repo builds and deploys itself: a push to `main` runs the template's
Actions workflow, which builds the Astro site and ships it to Cloudflare. GitHub
does not call us back, so every `website_deploys` row starts as an unresolved
claim ("a commit went in") and has to be walked to an outcome by polling.

The outcome vocabulary is wider than success/failure, and both extra values earn
their place:

* **superseded** — the workflow sets `concurrency: cancel-in-progress: true`, so
  a batch publish cancels every run but the last. Those cancellations are not
  failures of anything.
* **unknown** — a run we can no longer see (poll timeout, a run list that has
  rolled past it, a GitHub read failing repeatedly). PRD §6.3 is explicit that
  this is NOT reported as failed: the site is probably serving fine and we
  simply stopped being able to tell. It carries a re-check action instead.

Polling is observation, not output, so it is deliberately *not* freeze-gated —
the same split the rest of the suite uses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import settings
from db.supabase_client import get_supabase
from services.website_provision import deploy_status_from_run, list_workflow_runs

logger = logging.getLogger(__name__)

PENDING_STATUSES = ("queued", "building")
TERMINAL_STATUSES = ("success", "failed", "superseded")


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def match_run(deploy: dict, runs: list[dict]) -> Optional[dict]:
    """The Actions run that is building this deploy's commit.

    Matched on `head_sha` rather than on recency: a batch publish pushes several
    commits in quick succession, so "the newest run" is the wrong run for every
    deploy but one. A row whose run id is already known is matched on that.
    """
    run_id = deploy.get("actions_run_id")
    if run_id:
        for run in runs:
            if str(run.get("id")) == str(run_id):
                return run
        return None
    sha = deploy.get("commit_sha")
    if not sha:
        return None
    for run in runs:
        if (run.get("head_sha") or "") == sha:
            return run
    return None


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resolve_deploy(
    deploy: dict,
    run: Optional[dict],
    *,
    now: datetime,
    timeout_minutes: int,
) -> dict:
    """The patch this deploy row needs, or `{}` when nothing has changed.

    Timing out is the interesting case. A deploy whose run we never found, past
    the timeout, becomes `unknown` — not `failed`. The distinction matters
    because the recovery differs: a failed deploy wants a retry, an unknown one
    wants somebody to look at the Actions tab, and reporting the second as the
    first sends people to re-push a site that already shipped.
    """
    if run is not None:
        status = deploy_status_from_run(run)
        patch: dict[str, Any] = {"status": status, "actions_run_id": str(run.get("id"))}
        if run.get("head_sha") and not deploy.get("commit_sha"):
            patch["commit_sha"] = run["head_sha"]
        if run.get("html_url"):
            patch["url"] = run["html_url"]
        if status == deploy.get("status") and patch.get("actions_run_id") == str(
            deploy.get("actions_run_id") or ""
        ):
            return {}
        return patch

    started = _parse_ts(deploy.get("created_at")) or now
    if now - started >= timedelta(minutes=max(1, timeout_minutes)):
        if deploy.get("status") == "unknown":
            return {}
        return {
            "status": "unknown",
            "error": "deploy_run_not_found",
        }
    return {}


def notification_for(status: str, website: dict, deploy: dict) -> Optional[dict]:
    """The notification a terminal transition earns, or None for the quiet ones.

    'superseded' is silent by design: it means a later commit took over, which
    is the normal shape of a batch publish and not news. 'unknown' is silent too
    — it is a visible chip with a re-check button, not an alarm, and alarming on
    every poll blip would be noise on the one signal that should stay credible.
    """
    name = website.get("name") or "site"
    if status == "success":
        return {
            "kind": "website_deployed",
            "title": f"Website deployed: {name}",
            "summary": deploy.get("url") or website.get("staging_url") or "",
            "severity": "info",
        }
    if status == "failed":
        return {
            "kind": "website_deploy_failed",
            "title": f"Website deploy failed: {name}",
            # The site keeps serving its last good deploy — the surface must say
            # so, or a red chip reads as "the site is down".
            "summary": (
                f"{deploy.get('url') or 'Actions run'} — the site is still serving its "
                "last successful deploy"
            ),
            "severity": "warning",
        }
    return None


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------


def record_deploy(
    *,
    website_id: str,
    commit_sha: Optional[str],
    trigger: str,
    meta: Optional[dict] = None,
) -> Optional[str]:
    """Record the deploy a commit just triggered and queue its resolution."""
    rows = (
        get_supabase()
        .table("website_deploys")
        .insert(
            {
                "website_id": website_id,
                "commit_sha": commit_sha,
                "trigger": trigger,
                "status": "queued",
                "meta": meta or {},
            }
        )
        .execute()
    ).data or []
    enqueue_deploy_poll(website_id)
    return rows[0]["id"] if rows else None


def enqueue_deploy_poll(website_id: str) -> Optional[str]:
    """One poll job per site at a time. Returns the job id, or None if queued."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "website_deploy_poll")
        .eq("entity_id", website_id)
        .in_("status", ["pending", "running"])
        .execute()
    ).data or []
    if existing:
        return None
    res = (
        supabase.table("async_jobs")
        .insert(
            {
                "job_type": "website_deploy_poll",
                "entity_id": website_id,
                "payload": {"website_id": website_id},
            }
        )
        .execute()
    )
    return res.data[0]["id"] if res.data else None


def pending_deploys(website_id: str) -> list[dict]:
    return (
        get_supabase()
        .table("website_deploys")
        .select("*")
        .eq("website_id", website_id)
        .in_("status", list(PENDING_STATUSES) + ["unknown"])
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    ).data or []


async def poll_website_deploys(website_id: str) -> dict:
    """Walk every unresolved deploy on one site toward an outcome."""
    supabase = get_supabase()
    sites = (
        supabase.table("websites").select("*").eq("id", website_id).limit(1).execute()
    ).data
    if not sites:
        return {"website_id": website_id, "resolved": 0, "reason": "website_not_found"}
    website = sites[0]

    deploys = pending_deploys(website_id)
    if not deploys:
        return {"website_id": website_id, "resolved": 0}

    runs: list[dict] = []
    if website.get("github_repo"):
        runs = await list_workflow_runs(
            website["github_repo"], branch=settings.website_default_branch
        )

    now = datetime.now(timezone.utc)
    resolved = 0
    for deploy in deploys:
        patch = resolve_deploy(
            deploy,
            match_run(deploy, runs),
            now=now,
            timeout_minutes=settings.website_deploy_timeout_minutes,
        )
        if not patch:
            supabase.table("website_deploys").update({"polled_at": "now()"}).eq(
                "id", deploy["id"]
            ).execute()
            continue

        patch["polled_at"] = "now()"
        patch["updated_at"] = "now()"
        supabase.table("website_deploys").update(patch).eq("id", deploy["id"]).execute()
        resolved += 1

        note = notification_for(patch["status"], website, {**deploy, **patch})
        if note:
            from services import notifications

            notifications.emit(
                website.get("client_id"),
                note["kind"],
                note["title"],
                summary=note["summary"],
                severity=note["severity"],
                payload={"website_id": website_id, "deploy_id": deploy["id"],
                         "commit_sha": patch.get("commit_sha") or deploy.get("commit_sha")},
            )

    # Still in flight → come back next tick. The scheduler's sweep would pick it
    # up anyway; re-queueing here keeps a single site's deploy converging at the
    # job worker's pace rather than the scheduler's.
    if any(d["status"] in PENDING_STATUSES for d in pending_deploys(website_id)):
        enqueue_deploy_poll(website_id)

    return {"website_id": website_id, "resolved": resolved}


async def run_deploy_poll_job(job: dict) -> None:
    """async_jobs handler for `website_deploy_poll`."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await poll_website_deploys(payload["website_id"])
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "website_deploy.poll_failed", extra={"job_id": job["id"], "error": str(exc)}
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


def enqueue_due_deploy_polls() -> int:
    """Scheduler hook: any site with an unresolved deploy gets a poll job.

    Inert while the module is dark, and a no-op when nothing is in flight — the
    query is one indexed read over a table that is empty until a site exists.
    """
    if not settings.website_builder_enabled:
        return 0
    rows = (
        get_supabase()
        .table("website_deploys")
        .select("website_id")
        .in_("status", list(PENDING_STATUSES))
        .limit(200)
        .execute()
    ).data or []
    queued = 0
    for website_id in {r["website_id"] for r in rows}:
        if enqueue_deploy_poll(website_id):
            queued += 1
    if queued:
        logger.info("website_deploy.polls_enqueued", extra={"sites": queued})
    return queued
