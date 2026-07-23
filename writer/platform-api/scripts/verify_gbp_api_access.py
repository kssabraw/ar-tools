"""Verify the agency service account can reach the Google Business Profile APIs.

The preflight check for the GBP Posts module (docs/modules/gbp-posts-module-prd-v1_0.md
§3) and for flipping on the dormant GBP metrics layer. It proves, layer by layer:

  1. GOOGLE_SERVICE_ACCOUNT_KEY parses and a token mints for the
     ``business.manage`` scope.
  2. The v1 Account Management API answers (API enabled + project quota granted).
  3. Locations are visible per account (Business Information API + the service
     account actually added as a Manager somewhere).
  4. The **v4 Google My Business API** answers ``localPosts.list`` — the surface
     posts actually publish through (a separate enableable API from the v1 pair).
  5. Optionally (``--post-test accounts/X/locations/Y``) creates a minimal
     STANDARD post and immediately deletes it — proving write access. Only point
     this at a listing you own (the agency's own, not a client's).

Run it wherever the key lives:

    # Railway shell on PLATFORM (key already in the env), or locally:
    export GOOGLE_SERVICE_ACCOUNT_KEY="$(cat key.json)"
    python scripts/verify_gbp_api_access.py [--post-test accounts/X/locations/Y]

Every failure prints the classified cause + the fix (API not enabled vs quota
not granted vs SA not a Manager). Exit code 0 = read path fully green.

No app imports — standalone on purpose, so it runs from a bare shell with only
the platform-api requirements (google-auth, httpx) installed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

SCOPE = "https://www.googleapis.com/auth/business.manage"
V1_ACCOUNTS = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
V1_INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
V4 = "https://mybusiness.googleapis.com/v4"
TIMEOUT = 30


def _print(step: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {step}" + (f" — {detail}" if detail else ""))


def diagnose(resp: httpx.Response, api_label: str) -> str:
    """Map an error response to the actionable cause (PRD §3 table)."""
    try:
        err = resp.json().get("error", {})
    except Exception:
        err = {}
    status = err.get("status", "")
    message = err.get("message", "")
    if resp.status_code == 403 and (
        "has not been used" in message or "is disabled" in message or status == "PERMISSION_DENIED" and "Enable it" in message
    ):
        return f"{api_label} is NOT ENABLED on this GCP project. Enable it: GCP Console -> APIs & Services. ({message[:200]})"
    if resp.status_code == 429 or status == "RESOURCE_EXHAUSTED":
        return (
            f"{api_label} quota is 0 — the GCP project is NOT APPROVED for Business Profile API "
            f"access (or this specific API's quota wasn't raised). Check GCP quotas; chase the access request. ({message[:200]})"
        )
    if resp.status_code in (401, 403):
        return (
            f"Authenticated but not permitted — the service account is likely not added as a "
            f"Manager on any Business Profile, or lacks access to this resource. ({message[:200]})"
        )
    if resp.status_code == 404:
        return f"Resource not found — check the account/location id. ({message[:200]})"
    return f"HTTP {resp.status_code}: {message[:300] or resp.text[:300]}"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--post-test",
        metavar="accounts/X/locations/Y",
        help="ALSO create+delete a minimal test post on this location (use a listing you own)",
    )
    args = parser.parse_args()

    key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "")
    if not key.strip():
        _print("1. service-account key", False, "GOOGLE_SERVICE_ACCOUNT_KEY is not set in this environment")
        return 1
    try:
        token, email, project = get_token(key)
    except Exception as exc:  # noqa: BLE001 — report anything, this is a diagnostic
        _print("1. service-account key / token mint", False, f"{type(exc).__name__}: {exc}")
        return 1
    _print("1. service-account key / token mint", True, f"{email} (GCP project: {project})")
    print(f"    -> approval + API enablement are checked against project '{project}'.")

    client = httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)

    # ------------------------------------------------------------------ step 2
    resp = client.get(V1_ACCOUNTS)
    if resp.status_code != 200:
        _print("2. Account Management API (accounts.list)", False, diagnose(resp, "My Business Account Management API"))
        return 2
    accounts = resp.json().get("accounts", [])
    _print("2. Account Management API (accounts.list)", True, f"{len(accounts)} account(s) visible")
    if not accounts:
        print(
            "    !! Zero accounts: the API works but the service account has no Business Profile\n"
            "       access yet. Add its email (above) as a Manager on a profile / location group\n"
            "       (business.google.com -> Settings -> Managers), wait a few minutes, re-run."
        )

    # ------------------------------------------------------------------ step 3
    first_pair: tuple[str, str] | None = None  # (accounts/X, locations/Y)
    total_locs = 0
    for acct in accounts:
        name = acct.get("name")  # 'accounts/{id}'
        r = client.get(f"{V1_INFO}/{name}/locations", params={"readMask": "name,title"})
        if r.status_code != 200:
            _print(f"3. Business Information API ({name}/locations)", False, diagnose(r, "My Business Business Information API"))
            continue
        locs = r.json().get("locations", [])
        total_locs += len(locs)
        for loc in locs:
            print(f"    location: {name}/{loc.get('name')}  ({loc.get('title', '?')})")
            if first_pair is None:
                first_pair = (name, loc.get("name", ""))
    if accounts:
        _print("3. Business Information API (locations.list)", total_locs > 0 or not accounts, f"{total_locs} location(s) visible")

    # ------------------------------------------------------------------ step 4
    if first_pair is None:
        _print("4. v4 Google My Business API (localPosts.list)", False, "skipped — no visible location to test against (fix step 2/3 first)")
        return 3
    acct_name, loc_name = first_pair
    v4_parent = f"{V4}/{acct_name}/{loc_name}"
    resp = client.get(f"{v4_parent}/localPosts")
    if resp.status_code != 200:
        _print("4. v4 Google My Business API (localPosts.list)", False, diagnose(resp, "Google My Business API (v4)"))
        print(
            "    !! This is the API posts actually publish through. It is enabled separately\n"
            "       from the v1 APIs — look for 'Google My Business API' in the GCP API library."
        )
        return 4
    n_posts = len(resp.json().get("localPosts", []))
    _print("4. v4 Google My Business API (localPosts.list)", True, f"{n_posts} existing post(s) on {loc_name}")

    # ------------------------------------------------------------------ step 5
    if args.post_test:
        parent = f"{V4}/{args.post_test.strip('/')}"
        body = {
            "languageCode": "en-US",
            "topicType": "STANDARD",
            "summary": "API access verification post — will be deleted immediately.",
        }
        resp = client.post(f"{parent}/localPosts", json=body)
        if resp.status_code != 200:
            _print("5. write test (localPosts.create)", False, diagnose(resp, "Google My Business API (v4)"))
            return 5
        created = resp.json()
        post_name = created.get("name", "")
        _print("5. write test (localPosts.create)", True, f"state={created.get('state')} name={post_name}")
        d = client.delete(f"{V4}/{post_name}")
        _print("5. write test cleanup (localPosts.delete)", d.status_code == 200, f"HTTP {d.status_code}")

    print("\nRead path fully green — the service account can reach the Posts API surface.")
    if not args.post_test:
        print("Re-run with --post-test accounts/X/locations/Y (a listing you own) to prove write access.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
