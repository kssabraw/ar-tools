"""Website Builder — provisioning: turn a `websites` row into a live site.

The sequence is a **resumable step machine**. Each step records completion on
`websites.provision_state`, and re-running the job skips whatever already
succeeded. That matters because provisioning spans two external APIs: a failure
at step 4 must not orphan the repo created at step 1, and the fix must be
"run it again", never "clean up by hand".

Steps:
  1. generate  — create the site repo from the house template
  2. secrets   — write CLOUDFLARE_* into the repo so Actions can deploy
  3. configure — commit site.config.json + wrangler name (one commit)
  4. deploy    — the commit's push triggers Actions; record a website_deploys row

GitHub calls reuse `services.github_publish` (headers, the Git Data API
multi-file commit) rather than introducing a second client. What is genuinely
new here — generating from a template, encrypting repo secrets, reading Actions
runs — lives below.

Everything above the I/O boundary is a pure function so it can be tested
without touching GitHub or Cloudflare.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services.github_publish import _GITHUB_API, _gh_headers, commit_files_to_github

logger = logging.getLogger(__name__)

# Ordered; `next_step` walks this list.
STEPS = ("generate", "secrets", "configure", "deploy")

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_DEDUPE_RE = re.compile(r"-{2,}")


class ProvisionError(Exception):
    """Provisioning failed. The message is a stable error code, not prose."""


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def slugify(value: str) -> str:
    """A repo/worker-safe slug.

    Cloudflare Worker names and GitHub repo names share the same practical
    shape (lowercase alphanumerics and single hyphens, no leading/trailing
    hyphen), so one slug serves both and the two stay in step.
    """
    slug = _DEDUPE_RE.sub("-", _SLUG_STRIP_RE.sub("-", (value or "").lower())).strip("-")
    return slug[:54] or "site"


def repo_name(slug: str) -> str:
    """Site repos are namespaced so they are obvious among personal repos.

    The token that creates these has account-wide reach (a personal account
    cannot scope repo-creation), so a predictable prefix is the only thing
    making "which repos does the module own?" answerable at a glance.
    """
    return f"site-{slugify(slug)}"


def worker_name(slug: str) -> str:
    return f"site-{slugify(slug)}"


def staging_url(worker: str, subdomain: str) -> str:
    return f"https://{worker}.{subdomain}.workers.dev"


def next_step(state: dict[str, Any]) -> Optional[str]:
    """The first step not yet marked done, or None when provisioning is complete."""
    done = state.get("done") or []
    for step in STEPS:
        if step not in done:
            return step
    return None


def mark_done(state: dict[str, Any], step: str) -> dict[str, Any]:
    """Idempotent: re-marking a completed step is a no-op, and order is preserved."""
    done = list(state.get("done") or [])
    if step not in done:
        done.append(step)
    return {**state, "done": done}


def build_site_config(website: dict, client: dict) -> dict:
    """The site.config.json the template reads.

    Business facts follow the §4.5 precedence — anything already stored on the
    website's own config was entered by a human and wins; GBP only fills gaps.
    That is why this merges rather than overwrites, and why each filled group
    is stamped in `provenance`.
    """
    stored = dict(website.get("config") or {})
    business = dict(stored.get("business") or {})
    gbp = (client.get("gbp") or {}) if isinstance(client.get("gbp"), dict) else {}
    provenance = dict(business.get("provenance") or {})

    def fill(key: str, value: Any) -> None:
        if business.get(key):
            provenance.setdefault(key, "user")
            return
        if value:
            business[key] = value
            provenance[key] = "gbp"

    fill("name", gbp.get("name") or client.get("name"))
    fill("phoneReal", gbp.get("phone"))
    fill("street", gbp.get("street"))
    fill("city", gbp.get("city") or client.get("business_location"))
    fill("region", gbp.get("region"))
    fill("postalCode", gbp.get("postal_code"))
    fill("country", gbp.get("country"))
    fill("mapPlaceId", gbp.get("place_id"))
    if not business.get("areaServed") and gbp.get("service_area_places"):
        business["areaServed"] = list(gbp["service_area_places"])[:12]
        provenance["areaServed"] = "gbp"
    business["provenance"] = provenance

    site_type = website.get("site_type") or "informational"
    return {
        **stored,
        "siteName": website.get("name") or client.get("name") or "Site",
        "siteType": site_type,
        "url": website.get("custom_domain") and f"https://{website['custom_domain']}"
        or website.get("staging_url")
        or "https://example.workers.dev",
        "tagline": stored.get("tagline", ""),
        "description": stored.get("description", ""),
        "locale": stored.get("locale", "en"),
        "nav": stored.get("nav") or default_nav(site_type),
        "footerNav": stored.get("footerNav")
        or [
            {"label": "About", "href": "/about"},
            {"label": "Privacy", "href": "/privacy"},
            {"label": "Contact", "href": "/contact"},
        ],
        "business": business,
        "forms": stored.get("forms") or {"web3formsKey": ""},
        "analytics": stored.get("analytics") or {"ga4": "", "callrailSnippet": ""},
        "agency": stored.get("agency") or {"name": "Amazing Rankings"},
    }


def default_nav(site_type: str) -> list[dict[str, str]]:
    if site_type == "local_business":
        return [
            {"label": "Services", "href": "/services"},
            {"label": "Areas", "href": "/locations"},
            {"label": "About", "href": "/about"},
        ]
    return [
        {"label": "Topics", "href": "/topics"},
        {"label": "About", "href": "/about"},
    ]


def build_wrangler(worker: str) -> str:
    """wrangler.jsonc, rewritten per site.

    Emitted as plain JSON: the template ships `.jsonc` with comments, which
    wrangler accepts, but round-tripping comments through a writer is a way to
    corrupt them. JSON is a strict subset, so overwriting with JSON is safe.
    """
    return json.dumps(
        {
            "$schema": "node_modules/wrangler/config-schema.json",
            "name": worker,
            "compatibility_date": "2026-07-01",
            "assets": {"directory": "./dist"},
        },
        indent=2,
    ) + "\n"


def encrypt_secret(public_key_b64: str, value: str) -> str:
    """Seal `value` for GitHub's secrets API (libsodium sealed box, base64).

    Imported lazily so that a deployment without PyNaCl still starts and every
    other code path keeps working — only secret-writing fails, and it fails
    with a clear code rather than an ImportError at module load.
    """
    try:
        from nacl import encoding, public  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on deploy env
        raise ProvisionError("pynacl_not_installed") from exc

    key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(key).encrypt(value.encode("utf-8"))
    return base64.b64encode(sealed).decode("utf-8")


def deploy_status_from_run(run: dict) -> str:
    """Map an Actions run onto a `website_deploys.status`.

    A run that is queued or in progress is 'building'; only a *completed* run
    with conclusion 'success' counts as deployed. Anything else completed —
    failure, cancelled, timed out — is a failure, because from the site's point
    of view nothing shipped.
    """
    if (run.get("status") or "") != "completed":
        return "building"
    return "success" if (run.get("conclusion") or "") == "success" else "failed"


# --------------------------------------------------------------------------
# GitHub calls not covered by services.github_publish
# --------------------------------------------------------------------------


def _token() -> str:
    token = settings.github_sites_token
    if not token:
        raise ProvisionError("github_sites_token_not_configured")
    return token


def _owner() -> str:
    owner = settings.github_sites_owner
    if not owner:
        raise ProvisionError("github_sites_owner_not_configured")
    return owner


async def generate_repo_from_template(name: str, *, private: bool = True) -> dict:
    """POST /repos/{template}/generate — mint a site repo from the house template.

    A 422 whose body mentions the template usually means the source repo does
    not have GitHub's "Template repository" flag set, which is invisible in the
    repo UI unless you look for it; it is surfaced as its own error code so the
    fix is obvious.
    """
    owner, template = _owner(), settings.website_template_repo
    url = f"{_GITHUB_API}/repos/{owner}/{template}/generate"
    async with httpx.AsyncClient(timeout=60) as http:
        resp = await http.post(
            url,
            headers=_gh_headers(_token()),
            json={"owner": owner, "name": name, "private": private,
                  "description": "Generated by AR Tools Website Builder"},
        )
    if resp.status_code == 422 and "template" in resp.text.lower():
        raise ProvisionError("template_repo_flag_not_set")
    if resp.status_code == 422 and "exists" in resp.text.lower():
        raise ProvisionError("repo_already_exists")
    if resp.status_code not in (200, 201):
        logger.error(
            "website_provision.generate_failed",
            extra={"status": resp.status_code, "body": resp.text[:400]},
        )
        raise ProvisionError(f"generate_failed_{resp.status_code}")
    return resp.json()


async def set_repo_secret(repo: str, key: str, value: str) -> None:
    """Write one Actions secret. Values must be sealed with the repo's own key."""
    headers = _gh_headers(_token())
    async with httpx.AsyncClient(timeout=30) as http:
        pk = await http.get(f"{_GITHUB_API}/repos/{repo}/actions/secrets/public-key", headers=headers)
        if pk.status_code != 200:
            raise ProvisionError(f"secret_public_key_failed_{pk.status_code}")
        data = pk.json()
        resp = await http.put(
            f"{_GITHUB_API}/repos/{repo}/actions/secrets/{key}",
            headers=headers,
            json={
                "encrypted_value": encrypt_secret(data["key"], value),
                "key_id": data["key_id"],
            },
        )
    if resp.status_code not in (201, 204):
        raise ProvisionError(f"secret_write_failed_{resp.status_code}")


async def latest_workflow_run(repo: str, *, branch: str) -> Optional[dict]:
    """The most recent Actions run on `branch`, or None if none has started."""
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{_GITHUB_API}/repos/{repo}/actions/runs",
            headers=_gh_headers(_token()),
            params={"branch": branch, "per_page": 1},
        )
    if resp.status_code != 200:
        return None
    runs = (resp.json() or {}).get("workflow_runs") or []
    return runs[0] if runs else None


# --------------------------------------------------------------------------
# Cloudflare
# --------------------------------------------------------------------------

_CF_API = "https://api.cloudflare.com/client/v4"


async def cf_workers_subdomain() -> str:
    """The account's *.workers.dev subdomain, which forms every staging URL."""
    token, account = settings.cloudflare_api_token, settings.cloudflare_account_id
    if not token or not account:
        raise ProvisionError("cloudflare_not_configured")
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"{_CF_API}/accounts/{account}/workers/subdomain",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise ProvisionError(f"cloudflare_subdomain_failed_{resp.status_code}")
    return ((resp.json() or {}).get("result") or {}).get("subdomain") or ""


# --------------------------------------------------------------------------
# The step machine
# --------------------------------------------------------------------------


def _load(website_id: str) -> tuple[dict, dict]:
    supabase = get_supabase()
    site = (
        supabase.table("websites").select("*").eq("id", website_id).limit(1).execute()
    ).data
    if not site:
        raise ProvisionError("website_not_found")
    website = site[0]
    client = (
        supabase.table("clients")
        .select("*")
        .eq("id", website["client_id"])
        .limit(1)
        .execute()
    ).data
    return website, (client[0] if client else {})


def _save(website_id: str, patch: dict) -> None:
    get_supabase().table("websites").update(patch).eq("id", website_id).execute()


async def run_provision_job(payload: dict) -> dict:
    """Async job entrypoint. Idempotent: completed steps are skipped on re-run."""
    website_id = payload.get("website_id")
    if not website_id:
        raise ProvisionError("website_id_required")

    website, client = _load(website_id)
    state = dict(website.get("provision_state") or {})
    slug = website.get("slug") or slugify(website.get("name") or "site")
    repo = website.get("github_repo") or f"{_owner()}/{repo_name(slug)}"
    worker = website.get("cf_project") or worker_name(slug)

    _save(website_id, {"status": "provisioning", "error": None})

    try:
        while (step := next_step(state)) is not None:
            logger.info(
                "website_provision.step", extra={"website_id": website_id, "step": step}
            )

            if step == "generate":
                await generate_repo_from_template(repo.split("/", 1)[1])
                _save(website_id, {"github_repo": repo, "cf_project": worker})

            elif step == "secrets":
                await set_repo_secret(repo, "CLOUDFLARE_API_TOKEN", settings.cloudflare_api_token)
                await set_repo_secret(repo, "CLOUDFLARE_ACCOUNT_ID", settings.cloudflare_account_id)

            elif step == "configure":
                subdomain = await cf_workers_subdomain()
                url = staging_url(worker, subdomain)
                website["staging_url"] = url
                config = build_site_config(website, client)
                # One commit: the push is what triggers the deploy, so config and
                # wrangler name must land together or the first build deploys
                # under the wrong worker name.
                await commit_files_to_github(
                    repo=repo,
                    branch=settings.website_default_branch,
                    token=_token(),
                    files={
                        "site.config.json": (json.dumps(config, indent=2) + "\n").encode(),
                        "wrangler.jsonc": build_wrangler(worker).encode(),
                    },
                    message="Configure site",
                )
                _save(website_id, {"staging_url": url, "config": config})

            elif step == "deploy":
                run = await latest_workflow_run(repo, branch=settings.website_default_branch)
                get_supabase().table("website_deploys").insert(
                    {
                        "website_id": website_id,
                        "trigger": "provision",
                        "status": deploy_status_from_run(run) if run else "queued",
                        "actions_run_id": str(run["id"]) if run else None,
                        "commit_sha": (run or {}).get("head_sha"),
                    }
                ).execute()

            state = mark_done(state, step)
            _save(website_id, {"provision_state": state})

    except ProvisionError as exc:
        _save(website_id, {"status": "error", "error": str(exc), "provision_state": state})
        logger.error(
            "website_provision.failed",
            extra={"website_id": website_id, "error": str(exc)},
        )
        raise

    _save(website_id, {"status": "live", "provision_state": state, "error": None})
    return {"website_id": website_id, "repo": repo, "worker": worker,
            "staging_url": website.get("staging_url")}
