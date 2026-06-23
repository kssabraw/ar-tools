"""Scaffold (#3): resolve a run's publish destinations from its AR Tools client.

The publish targets live on the client dashboard (`public.clients`): the Google
Drive folder already exists as `google_drive_folder_id`, and the GitHub repo /
branch / content-path were added alongside the `sessions.client_id` link. This
module reads them so the publish path can later default to the client's
configured destinations instead of per-run `sessions.publish_config`.

NOTE: this is wired but not yet consumed by the publish endpoints — the full
"publish from the client dashboard" behaviour is a later task. Kept here so the
data path (session -> client -> targets) is in place and testable now.
"""

import logging

logger = logging.getLogger(__name__)


def resolve_client_publish_targets(client_id: str | None) -> dict:
    """Return the client's configured publish destinations, or {} when there's no
    client (a global/owner run) or the lookup fails. Reads `public.clients` via the
    host suite's public-schema client — the Fanout service client is scoped to the
    `fanout` schema and can't see it. Best-effort: never raises into the caller."""
    if not client_id:
        return {}
    try:
        from db.supabase_client import get_supabase

        resp = (
            get_supabase()
            .table("clients")
            .select(
                "google_drive_folder_id, github_repo, github_branch, github_content_path"
            )
            .eq("id", client_id)
            .limit(1)
            .execute()
        )
        if not resp.data:
            return {}
        c = resp.data[0]
        return {
            "drive": {"folder_id": c.get("google_drive_folder_id")},
            "github": {
                "repo": c.get("github_repo"),
                "branch": c.get("github_branch"),
                "content_path": c.get("github_content_path"),
            },
        }
    except Exception as exc:  # noqa: BLE001 - advisory scaffold, never fatal
        logger.warning(
            "client_publish_targets_failed",
            extra={"event": "client_publish_targets_failed",
                   "client_id": client_id, "reason": repr(exc)},
        )
        return {}
