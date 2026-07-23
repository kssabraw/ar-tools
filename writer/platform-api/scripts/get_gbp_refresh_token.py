"""One-time: obtain a GBP OAuth refresh token for the agency Google account.

Run this ONCE, locally, on a machine with a browser, signed in (or signing in)
as the **agency Google account that manages the client Business Profiles**. It
opens Google's consent screen for the ``business.manage`` scope, then prints a
long-lived **refresh token** you set as ``GBP_OAUTH_REFRESH_TOKEN`` on the
platform service (alongside ``GOOGLE_OAUTH_CLIENT_ID`` / ``_SECRET``). After
that the app mints API tokens from it (services/gbp_auth) — no per-client OAuth,
no service-account Manager step.

Prereqs (GCP console, same project):
  1. Create an OAuth 2.0 Client ID of type **Desktop app** → client id + secret.
  2. OAuth consent screen: add scope
     ``https://www.googleapis.com/auth/business.manage``. With a Google Workspace
     account, set the app to **Internal** (no verification; refresh token doesn't
     expire). A personal @gmail account in "Testing" gets a token that expires in
     ~7 days — publish/verify for a permanent one.

Usage:
    pip install google-auth-oauthlib
    export GOOGLE_OAUTH_CLIENT_ID=...    # or pass --client-id
    export GOOGLE_OAUTH_CLIENT_SECRET=...# or pass --client-secret
    python scripts/get_gbp_refresh_token.py

It uses a localhost loopback redirect (handled automatically for a Desktop-app
client), so no redirect URI configuration is needed.
"""

from __future__ import annotations

import argparse
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/business.manage"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--client-id", default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
    parser.add_argument("--port", type=int, default=0, help="loopback port (0 = auto)")
    args = parser.parse_args()

    if not args.client_id or not args.client_secret:
        print("ERROR: set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET "
              "(env or --client-id/--client-secret).")
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: pip install google-auth-oauthlib")
        return 1

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    # access_type=offline + prompt=consent guarantee a refresh token is returned.
    creds = flow.run_local_server(port=args.port, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        print("ERROR: no refresh token returned. Revoke the app's access at "
              "https://myaccount.google.com/permissions and re-run (Google only "
              "returns a refresh token on first consent unless prompt=consent).")
        return 2

    print("\n================ GBP OAuth refresh token ================\n")
    print(creds.refresh_token)
    print("\n=========================================================\n")
    print("Set on the platform service:")
    print(f"  GOOGLE_OAUTH_CLIENT_ID={args.client_id}")
    print("  GOOGLE_OAUTH_CLIENT_SECRET=<the secret you used>")
    print("  GBP_OAUTH_REFRESH_TOKEN=<the token above>")
    print("Then run scripts/verify_gbp_api_access.py to confirm access.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
