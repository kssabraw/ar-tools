"""PostPeer connect-and-post smoke test — the P0 vendor go/no-go.

Proves the PostPeer dependency end-to-end BEFORE the calendar is built on it
(docs/modules/social-media/HANDOFF.md "P0 — smoke test FIRST"). Standalone, like
scripts/verify_gbp_api_access.py — no app imports, only httpx — so it runs from a
bare shell wherever the key + egress live (your machine, or the PLATFORM Railway
shell). The Claude Code sandbox cannot reach api.postpeer.dev (org egress policy),
so run this yourself.

It mirrors services/social/postpeer_adapter.py's calls (base, x-access-key,
/health/auth, /profiles, /connect/integrations pagination, /posts one platform
per call, tokenStatus.reconnectRequired, X 5/50 credit rule).

Usage:

    export POSTPEER_API_KEY="…"                 # your existing agency key
    python scripts/smoke_test_postpeer.py       # SAFE: auth + list only (no posting, free)

    # Publish a real low-stakes test post (spends credits, posts to a REAL account):
    python scripts/smoke_test_postpeer.py \
        --post --account-id <integration id> --platform facebook \
        --text "PostPeer smoke test — please ignore."

Exit codes: 0 all requested steps passed · 2 auth failed · 3 a post step failed
· 4 bad usage. Read-only steps never publish. Posting requires BOTH --post and
--account-id and prints the credit cost first; posting to X with a link costs 50
credits, so the script warns and (unless --yes-x-link) refuses an X link post.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import httpx

BASE = os.environ.get("POSTPEER_BASE_URL", "https://api.postpeer.dev/v1").rstrip("/")
TIMEOUT = 45
_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def _print(step: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {step}" + (f" — {detail}" if detail else ""))


def _headers(key: str) -> dict:
    return {"x-access-key": key, "Content-Type": "application/json"}


def x_credit_cost(platform: str, content: str) -> int:
    if (platform or "").lower() in ("twitter", "x"):
        return 50 if _URL_RE.search(content or "") else 5
    return 1


def _diagnose(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        msg = str(body.get("error") or body.get("message") or body)
    except Exception:
        msg = resp.text[:300]
    if resp.status_code == 401:
        return f"key rejected (401). Check POSTPEER_API_KEY. ({msg[:160]})"
    if resp.status_code in (402, 429) or "credit" in msg.lower():
        return f"credits/rate limit (HTTP {resp.status_code}). ({msg[:160]})"
    return f"HTTP {resp.status_code}: {msg[:200]}"


def main() -> int:
    ap = argparse.ArgumentParser(description="PostPeer connect-and-post smoke test")
    ap.add_argument("--profile-id", help="scope integration listing to one profile (social group)")
    ap.add_argument("--post", action="store_true", help="actually publish a test post (spends credits)")
    ap.add_argument("--account-id", help="integration id to post to (required with --post)")
    ap.add_argument("--platform", default="facebook", help="platform slug for the test post")
    ap.add_argument("--text", default="PostPeer smoke test — please ignore.", help="post body")
    ap.add_argument("--media-url", help="optional public image URL to attach")
    ap.add_argument("--yes-x-link", action="store_true", help="allow a 50-credit X link post")
    args = ap.parse_args()

    key = os.environ.get("POSTPEER_API_KEY", "").strip()
    if not key:
        _print("POSTPEER_API_KEY present", False, "set it in the environment first")
        return 4

    with httpx.Client(timeout=TIMEOUT) as client:
        # 1. auth (free)
        try:
            r = client.get(f"{BASE}/health/auth", headers=_headers(key))
        except Exception as e:  # noqa: BLE001
            _print("reach api.postpeer.dev", False, f"{type(e).__name__}: {e}")
            return 2
        if r.status_code >= 400:
            _print("auth /health/auth", False, _diagnose(r))
            return 2
        _print("auth /health/auth", True, "key accepted")

        # 2. profiles (free)
        try:
            r = client.get(f"{BASE}/profiles", headers=_headers(key), params={"limit": 100})
            profiles = (r.json() or {}).get("profiles") or (r.json() or {}).get("data") or []
            _print("list /profiles", r.status_code < 400,
                   f"{len(profiles)} social group(s): " + ", ".join(
                       f"{p.get('name')}({p.get('id')})" for p in profiles[:8]) if r.status_code < 400 else _diagnose(r))
        except Exception as e:  # noqa: BLE001
            _print("list /profiles", False, str(e))

        # 3. integrations (free, paginated)
        params = {"limit": 100, "offset": 0}
        if args.profile_id:
            params["profileId"] = args.profile_id
        r = client.get(f"{BASE}/connect/integrations", headers=_headers(key), params=params)
        if r.status_code >= 400:
            _print("list /connect/integrations", False, _diagnose(r))
            return 2
        integ = (r.json() or {}).get("integrations") or (r.json() or {}).get("data") or []
        _print("list /connect/integrations", True, f"{len(integ)} connected account(s)")
        for i in integ[:20]:
            ts = (i.get("tokenStatus") or {}).get("reconnectRequired")
            flag = "  ⚠ RECONNECT" if ts else ""
            print(f"    - {i.get('platform'):<10} id={i.get('id')}  user={i.get('platformUserId')}{flag}")

        # 4. optional real publish
        if not args.post:
            print("\nRead-only smoke test passed. To publish a real test post, re-run with "
                  "--post --account-id <id> --platform <slug>.")
            return 0

        if not args.account_id:
            _print("post", False, "--account-id is required with --post")
            return 4
        cost = x_credit_cost(args.platform, args.text)
        if args.platform.lower() in ("twitter", "x") and _URL_RE.search(args.text) and not args.yes_x_link:
            _print("post", False, f"X link post costs {cost} credits — pass --yes-x-link to allow, "
                                  "or drop the URL scheme from --text")
            return 4
        print(f"\nPublishing to {args.platform} account {args.account_id} — cost ~{cost} credit(s).")
        entry = {"platform": args.platform, "accountId": args.account_id}
        payload = {"content": args.text, "platforms": [entry], "publishNow": True}
        if args.media_url:
            payload["mediaItems"] = [{"type": "image", "url": args.media_url}]
        r = client.post(f"{BASE}/posts", headers=_headers(key), json=payload)
        if r.status_code >= 400:
            _print("post /posts", False, _diagnose(r))
            return 3
        body = r.json() or {}
        pentry = next((p for p in (body.get("platforms") or [])
                       if (p.get("platform") or "").lower() == args.platform.lower()),
                      (body.get("platforms") or [{}])[0] if body.get("platforms") else {})
        ok = bool(pentry.get("success", body.get("success")))
        _print("post /posts", ok,
               (f"live: {pentry.get('platformPostUrl')} (postId={body.get('postId')})" if ok
                else f"platform rejected: {pentry.get('error') or pentry.get('message') or body.get('status')}"))
        return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
