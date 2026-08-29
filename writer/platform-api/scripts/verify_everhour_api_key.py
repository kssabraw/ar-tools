"""Verify an Everhour API key against the live API.

The preflight check for the Everhour time-tracking integration
(docs/modules/everhour-time-tracking-integration-plan-v1_0.md, Phase 0 — "config +
everhour_service.py wrapper + is_configured(); validate against a real key").
Endpoint shapes are already verified against Everhour's published OpenAPI spec
(https://developers.everhour.com/openapi.json); this script proves a specific
KEY actually works, layer by layer:

  1. ``GET /users/me`` answers — the key is valid at all (403 "Access denied"
     on a bad/missing key, per https://developers.everhour.com/errors).
  2. ``GET /team/users`` answers — the key's account can see the team roster
     (needed for Phase 1's Everhour-user-link picker).
  3. ``GET /projects`` answers — the key's account can see projects (needed
     for Phase 1's client<->project mapping).
  4. ``GET /team/time`` (today only) answers — proves the time-pull shape
     Phase 3 depends on, with zero risk (a date-range-less call defaults to
     just today, per the docs).

Run it wherever the key lives:

    export EVERHOUR_API_KEY="..."
    python scripts/verify_everhour_api_key.py

    # or pass it directly:
    python scripts/verify_everhour_api_key.py --key <your-key>

No app imports — standalone on purpose, so it runs from a bare shell with only
``httpx`` installed (mirrors scripts/verify_gbp_api_access.py).
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

BASE_URL = "https://api.everhour.com"
TIMEOUT = 30


def _print(step: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {step}" + (f" — {detail}" if detail else ""))


def _check(client: httpx.Client, path: str, params: dict | None = None):
    """GET ``path`` and return its parsed JSON body, or ``None`` on any
    failure. A transport-level error (timeout, DNS failure, connection
    refused), a non-2xx status, and a malformed/non-JSON response body are
    all handled here — each prints exactly one ``[FAIL]`` line and returns
    ``None`` rather than raising, so a network hiccup produces a clean
    diagnostic instead of a raw traceback (and an unreachable domain doesn't
    leave the caller's client unclosed)."""
    label = f"GET {path}"
    try:
        resp = client.get(f"{BASE_URL}{path}", params=params)
    except httpx.RequestError as exc:
        _print(label, False, f"{type(exc).__name__}: {exc}")
        return None
    if resp.status_code != 200:
        _print(label, False, f"HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    try:
        return resp.json()
    except ValueError as exc:
        _print(label, False, f"malformed response body ({type(exc).__name__}: {exc})")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", default=os.environ.get("EVERHOUR_API_KEY", ""))
    args = parser.parse_args()

    if not args.key:
        _print("EVERHOUR_API_KEY", False, "not set (env var or --key)")
        return 2

    # A context manager guarantees the client is closed on every exit path,
    # including one we didn't anticipate — no matching manual .close() call
    # to forget on a new branch later.
    with httpx.Client(
        headers={"X-Api-Key": args.key, "Accept": "application/json"}, timeout=TIMEOUT
    ) as client:
        me = _check(client, "/users/me")
        if me is None:
            # A bad key fails every subsequent call identically — stop here.
            return 1
        _print(
            "GET /users/me",
            True,
            f"authenticated as {me.get('name')!r} (id={me.get('id')}, role={me.get('role')})",
        )

        all_ok = True

        users = _check(client, "/team/users")
        if users is not None:
            _print("GET /team/users", True, f"{len(users)} team member(s)")
        else:
            all_ok = False

        projects = _check(client, "/projects")
        if projects is not None:
            _print("GET /projects", True, f"{len(projects)} project(s) visible")
            for p in projects[:5]:
                print(f"       - {p.get('id')}: {p.get('name')}")
        else:
            all_ok = False

        records = _check(client, "/team/time")  # from/to omitted -> today only, per the docs
        if records is not None:
            _print("GET /team/time (today)", True, f"{len(records)} time record(s) today")
        else:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
