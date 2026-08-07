"""Website Builder — editing a site's business facts.

The template renders a site's name, phone, address, hours area, form and
analytics straight from `site.config.json`. Those facts auto-fill from the
client's GBP at provision time (`website_provision.build_site_config`), which is
right for the common case — the site represents the client whose GBP is
connected. This module is the escape hatch for when they differ: a second
location's phone, a service-area business with no street address, a tagline the
owner wants in their own words.

The one rule that makes this safe to layer over the auto-fill is **provenance**.
A field the user edits is stamped `provenance: "user"`, and `build_site_config`'s
fill step leaves any user-stamped field alone — so a later GBP re-scan can refill
the gaps a person never touched without ever clobbering what they did. Clearing a
field removes both the value and its stamp, which hands it back to GBP.

Editing is deliberately split from the auto-fill: this writes only the **raw
stored** `websites.config` (the human layer); GBP fill still happens at build
time. The two never race because build always re-derives GBP over whatever the
human layer holds.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SettingsError(Exception):
    """Stable error code, not prose."""


# The business-identity fields a person may set. `mapPlaceId` is deliberately
# absent — it is a Google place id, not a fact anyone types, and it only ever
# comes from GBP. Keyed exactly as build_site_config stores them so a saved value
# is the one its fill step then protects.
EDITABLE_FACTS = ("name", "phoneReal", "street", "city", "region", "postalCode", "country")

# Nested config groups the settings tab owns, and the sub-keys it may write. A
# sub-key not listed here is left untouched, so this can't trample a field some
# other part of the suite manages.
_FORMS_KEYS = ("web3formsKey",)
_ANALYTICS_KEYS = ("ga4", "callrailSnippet")


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def apply_facts_edit(
    config: dict,
    *,
    business: Optional[dict] = None,
    tagline: Optional[str] = None,
    description: Optional[str] = None,
    forms: Optional[dict] = None,
    analytics: Optional[dict] = None,
) -> dict:
    """A new raw config with the user's edits merged over it (never mutates input).

    Field semantics, so the UI behaves predictably:
    - a business field **present and non-empty** → set it, stamp `user`;
    - **present and empty** → the user cleared it: drop the value and its stamp,
      handing the field back to GBP on the next build;
    - **absent** → untouched.

    `tagline`/`description` are plain overrides (empty is a legitimate value —
    an owner may want no tagline). Only the whitelisted `forms`/`analytics`
    sub-keys are written.
    """
    out = copy.deepcopy(config or {})
    biz = dict(out.get("business") or {})
    provenance = dict(biz.get("provenance") or {})

    if business is not None:
        for field in EDITABLE_FACTS:
            if field not in business:
                continue
            value = _clean(business.get(field))
            if value:
                biz[field] = value
                provenance[field] = "user"
            else:
                biz.pop(field, None)
                provenance.pop(field, None)

        if "areaServed" in business:
            raw = business.get("areaServed")
            places = [p.strip() for p in raw if isinstance(p, str) and p.strip()] if isinstance(raw, list) else []
            if places:
                biz["areaServed"] = places[:12]
                provenance["areaServed"] = "user"
            else:
                biz.pop("areaServed", None)
                provenance.pop("areaServed", None)

    biz["provenance"] = provenance
    out["business"] = biz

    if tagline is not None:
        out["tagline"] = tagline.strip()
    if description is not None:
        out["description"] = description.strip()

    if forms is not None:
        merged = dict(out.get("forms") or {})
        for key in _FORMS_KEYS:
            if key in forms:
                merged[key] = _clean(forms.get(key))
        out["forms"] = merged

    if analytics is not None:
        merged = dict(out.get("analytics") or {})
        for key in _ANALYTICS_KEYS:
            if key in analytics:
                merged[key] = _clean(analytics.get(key))
        out["analytics"] = merged

    return out


def facts_view(built_config: dict) -> dict:
    """The editable facts as the site would actually use them, for the GET.

    Reads the **built** config (GBP already filled in) rather than raw storage,
    so the tab shows real values and can label each `user` / `gbp` / unset — the
    point being to show a person what GBP supplied before they override it.
    """
    biz = (built_config or {}).get("business") or {}
    provenance = biz.get("provenance") or {}
    fields = {f: biz.get(f, "") for f in EDITABLE_FACTS}
    fields["areaServed"] = list(biz.get("areaServed") or [])
    return {
        "business": fields,
        "provenance": {f: provenance.get(f) for f in (*EDITABLE_FACTS, "areaServed")},
        "tagline": (built_config or {}).get("tagline", ""),
        "description": (built_config or {}).get("description", ""),
        "forms": {k: ((built_config or {}).get("forms") or {}).get(k, "") for k in _FORMS_KEYS},
        "analytics": {k: ((built_config or {}).get("analytics") or {}).get(k, "") for k in _ANALYTICS_KEYS},
    }


# --------------------------------------------------------------------------
# Impure
# --------------------------------------------------------------------------


def _load(website_id: str) -> tuple[dict, dict]:
    from db.supabase_client import get_supabase

    supabase = get_supabase()
    sites = (
        supabase.table("websites").select("*").eq("id", website_id).limit(1).execute()
    ).data
    if not sites:
        raise SettingsError("website_not_found")
    website = sites[0]
    client = (
        supabase.table("clients").select("*").eq("id", website["client_id"]).limit(1).execute()
    ).data
    return website, (client[0] if client else {})


def get_facts(website_id: str) -> dict:
    """Current editable facts (GBP-filled) + whether a save would redeploy."""
    from services.website_provision import build_site_config

    website, client = _load(website_id)
    view = facts_view(build_site_config(website, client))
    view["provisioned"] = bool(website.get("github_repo"))
    return view


async def save_facts(website_id: str, edits: dict) -> dict:
    """Persist edited facts and, on a provisioned site, re-commit + redeploy.

    Returns `{website, committed, deploy_id}`. The re-commit is best-effort: a
    commit failure leaves the facts saved (so the edit is never lost) and reports
    `committed=False`, rather than failing the whole save over a transient GitHub
    error.
    """
    from db.supabase_client import get_supabase

    website, client = _load(website_id)
    new_config = apply_facts_edit(website.get("config") or {}, **edits)

    supabase = get_supabase()
    updated = (
        supabase.table("websites")
        .update({"config": new_config, "updated_at": "now()"})
        .eq("id", website_id)
        .execute()
    ).data
    website = updated[0] if updated else {**website, "config": new_config}

    result = {"website": website, "committed": False, "deploy_id": None}
    if not website.get("github_repo"):
        # Not provisioned yet — the facts are stored and provisioning will carry
        # them in with its configure commit. Nothing to redeploy.
        return result

    try:
        result.update(await recommit_config(website, client))
    except Exception as exc:  # noqa: BLE001 — the facts are saved; the deploy can be retried
        logger.warning(
            "website_settings.recommit_failed",
            extra={"website_id": website_id, "error": str(exc)[:200]},
        )
    return result


async def recommit_config(website: dict, client: dict) -> dict:
    """Commit the rebuilt site.config.json and record a `config` deploy."""
    import json

    from config import settings
    from db.supabase_client import get_supabase
    from services.github_publish import commit_files_to_github
    from services.website_provision import build_site_config

    config = build_site_config(website, client)
    commit = await commit_files_to_github(
        repo=website["github_repo"],
        branch=settings.website_default_branch,
        token=settings.github_sites_token,
        files={"site.config.json": (json.dumps(config, indent=2) + "\n").encode()},
        message="Update site settings",
    )
    sha = commit.get("commit_sha")
    deploy = (
        get_supabase()
        .table("website_deploys")
        .insert({"website_id": website["id"], "trigger": "config", "status": "queued",
                 "commit_sha": sha})
        .execute()
    ).data
    return {"committed": True, "deploy_id": deploy[0]["id"] if deploy else None}
