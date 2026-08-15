"""Verify the agency service account can reach the Google Analytics (GA4) APIs.

The preflight check for Client Reporting **Phase 2** (GA4 connector —
docs/modules/client-reporting-prd-v1_0.md §Prerequisites 1 + §Phase 2). It
proves, layer by layer, that GA4 reporting can actually be built and turned on:

  1. GOOGLE_SERVICE_ACCOUNT_KEY parses and a token mints for the
     ``analytics.readonly`` scope.
  2. The **GA4 Admin API** answers ``accountSummaries.list`` (API enabled +
     project quota granted) AND surfaces every GA4 **property** the service
     account can actually see — i.e. the properties whose owners have added the
     SA's ``client_email`` as a Viewer. This is both the "is access granted"
     check and the way to discover each client's numeric **property id**.
  3. The **GA4 Data API** answers ``properties/{id}:runReport`` — the surface the
     report gatherer reads (sessions/users/conversions). Enabled + quota'd
     SEPARATELY from the Admin API, so it can be dark even when Admin is green.

By default step 3 runs against the first property step 2 discovers; pass
``--property properties/123456789`` (or a bare ``123456789``) to test a specific
one — e.g. to confirm a particular client's listing before wiring it up.

Run it wherever the key lives:

    # Railway shell on PLATFORM (key already in the env), or locally:
    export GOOGLE_SERVICE_ACCOUNT_KEY="$(cat key.json)"
    python scripts/verify_ga4_api_access.py [--property properties/123456789]

Every failure prints the classified cause + the fix (API not enabled vs quota
not granted vs SA not added as a Viewer). Exit code 0 = the Data API read
surface is green and at least one property is reachable, so Phase 2 can proceed;
a non-zero code pinpoints which layer is dark.

No app imports — standalone on purpose, so it runs from a bare shell with only
the platform-api requirements (google-auth, httpx) installed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
ADMIN = "https://analyticsadmin.googleapis.com/v1beta"
DATA = "https://analyticsdata.googleapis.com/v1beta"
TIMEOUT = 30


def _print(step: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {step}" + (f" — {detail}" if detail else ""))


def diagnose(resp: httpx.Response, api_label: str) -> str:
    """Map an error response to the actionable cause."""
    try:
        message = resp.json().get("error", {}).get("message", "")
    except Exception:  # noqa: BLE001
        message = ""
    status = resp.status_code
    lowered = message.lower()
    if status == 403 and ("has not been used" in lowered or "disabled" in lowered):
        return (
            f"{api_label} is NOT ENABLED on this GCP project. Enable it: "
            f"GCP Console -> APIs & Services -> Enable APIs. ({message[:200]})"
        )
    if status == 403:
        return (
            f"{api_label} reachable but ACCESS DENIED — the service account is not "
            f"added as a Viewer on this property (GA4 Admin -> Property Access "
            f"Management -> add the SA client_email). ({message[:200]})"
        )
    if status == 429:
        return f"{api_label} quota exceeded (transient). ({message[:200]})"
    if status == 404:
        return f"Property not found — check the numeric property id. ({message[:200]})"
    return f"HTTP {status}: {message[:300] or resp.text[:300]}"


def get_token(key_json: str) -> tuple[str, str, str]:
    """Return (access_token, client_email, project_id). Raises with a clear message."""
    from google.oauth2 import service_account  # lazy, like the app does

    info = json.loads(key_json)
    email = info.get("client_email", "?")
    project = info.get("project_id", "?")
    creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    # google-auth needs a transport to refresh; requests may not be installed,
    # so fall back to the httplib2 adapter that google-api-python-client ships.
    try:
        from google.auth.transport.requests import Request  # type: ignore

        creds.refresh(Request())
    except ImportError:
        import google_auth_httplib2  # type: ignore
        import httplib2  # type: ignore

        creds.refresh(google_auth_httplib2.Request(httplib2.Http()))
    return creds.token, email, project


def _normalize_property(value: str) -> str:
    """Accept ``properties/123`` or a bare ``123`` and return ``properties/123``."""
    v = value.strip()
    if v.startswith("properties/"):
        return v
    return f"properties/{v}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--property",
        help="GA4 property to test the Data API against "
        "(e.g. 'properties/123456789' or '123456789'). "
        "Defaults to the first property the Admin API discovers.",
    )
    args = parser.parse_args()

    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "").strip()
    if not key_json:
        _print("0. GOOGLE_SERVICE_ACCOUNT_KEY present", False, "env var is empty")
        return 1

    # --- 1. credentials -----------------------------------------------------
    try:
        token, email, project = get_token(key_json)
    except json.JSONDecodeError as exc:
        _print("1. credentials", False, f"key is not valid JSON: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        _print("1. credentials", False, f"could not mint a token: {exc}")
        return 1
    _print("1. credentials", True, f"token minted for {email} (project {project})")

    headers = {"Authorization": f"Bearer {token}"}

    # --- 2. Admin API: accountSummaries.list --------------------------------
    # Surfaces every GA4 property the SA can see + proves the Admin API is on.
    properties: list[tuple[str, str]] = []  # (property resource, display name)
    with httpx.Client(timeout=TIMEOUT) as http:
        resp = http.get(f"{ADMIN}/accountSummaries", headers=headers)
        if resp.status_code != 200:
            _print("2. GA4 Admin API (accountSummaries)", False,
                   diagnose(resp, "GA4 Admin API (analyticsadmin.googleapis.com)"))
            return 2
        summaries = resp.json().get("accountSummaries", []) or []
        for acct in summaries:
            for prop in acct.get("propertySummaries", []) or []:
                res = prop.get("property")  # "properties/123456789"
                name = prop.get("displayName", "?")
                if res:
                    properties.append((res, name))

    if not properties:
        _print("2. GA4 Admin API (accountSummaries)", True,
               "API enabled, but the service account can see ZERO properties")
        print(
            "     -> No client GA4 property has added this service account yet.\n"
            f"     -> Add {email} as a **Viewer** in each client's GA4 property\n"
            "        (Admin -> Property Access Management), then re-run."
        )
        return 3

    _print("2. GA4 Admin API (accountSummaries)", True,
           f"{len(properties)} propert{'y' if len(properties) == 1 else 'ies'} visible")
    for res, name in properties[:25]:
        print(f"     - {res}  ({name})")
    if len(properties) > 25:
        print(f"     ... and {len(properties) - 25} more")

    # --- 3. Data API: runReport ---------------------------------------------
    target = _normalize_property(args.property) if args.property else properties[0][0]
    body = {
        "dateRanges": [{"startDate": "7daysAgo", "endDate": "today"}],
        "metrics": [{"name": "sessions"}],
        "limit": 1,
    }
    with httpx.Client(timeout=TIMEOUT) as http:
        resp = http.post(f"{DATA}/{target}:runReport", headers=headers, json=body)
        if resp.status_code != 200:
            _print("3. GA4 Data API (runReport)", False,
                   diagnose(resp, "GA4 Data API (analyticsdata.googleapis.com)"))
            print(f"     -> tested against {target}")
            return 4
        rows = resp.json().get("rows", []) or []
        sessions = rows[0]["metricValues"][0]["value"] if rows else "0"
    _print("3. GA4 Data API (runReport)", True,
           f"{target} read OK — {sessions} sessions in the last 7 days")

    print(
        "\nGA4 access is GREEN. Client Reporting Phase 2 can proceed:\n"
        "  - the Admin API discovers each client's numeric property id (step 2),\n"
        "  - the Data API reads sessions/users/conversions (step 3)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
