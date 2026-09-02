"""Report a merged change on ``main`` to DORA so it can keep the in-app Guides current.

The CI half of DORA's guide sync (``services/guide_sync.py``). Run by
``.github/workflows/guide-sync.yml`` on every push to ``main``:

  1. lists the files changed between ``--before`` and ``--after``;
  2. groups them by module through ``services/guide_registry.py`` (pure — no app
     deps), dropping everything that can't be user-facing (tests, docs, CI,
     migrations, lockfiles, the seeded guides, …);
  3. for each affected module, collects the commit messages + a bounded unified
     diff of ITS user-facing files;
  4. POSTs one JSON payload to ``POST /director/module-changes`` with the shared
     bearer secret. The platform records one review per (commit, module) and
     DORA reviews each module's guide from there.

Exit codes: 0 on success AND when the sync isn't configured (no URL / secret —
printed as a notice so a fork or a fresh clone never gets a red check for it);
1 on a git failure; 2 when the platform rejected the payload. Pass
``--require`` to make a missing URL/secret an error too.

    python writer/platform-api/scripts/report_module_changes.py \\
        --before <sha> --after <sha> [--url https://…] [--secret …] [--dry-run]

Standalone on purpose — stdlib + git only, importing just the registry module
by path (mirrors scripts/verify_everhour_api_key.py's no-app-imports rule).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REGISTRY = _HERE.parent / "services" / "guide_registry.py"
_NULL_SHA = "0" * 40


def _load_registry():
    spec = importlib.util.spec_from_file_location("guide_registry", _REGISTRY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _git(*args: str, cwd: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, errors="replace")


def resolve_range(before: str, after: str, cwd: str) -> tuple[str, str]:
    """A force-push / first push reports the null SHA as ``before``; fall back to
    the parent of ``after`` so the run still covers the merged commit."""
    before = (before or "").strip()
    after = _git("rev-parse", (after or "").strip() or "HEAD", cwd=cwd).strip()
    if not before or before == _NULL_SHA:
        before = _git("rev-parse", f"{after}~1", cwd=cwd).strip()
    else:
        before = _git("rev-parse", before, cwd=cwd).strip()
    return before, after


def changed_files(before: str, after: str, cwd: str) -> list[str]:
    out = _git("diff", "--name-only", before, after, cwd=cwd)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def commits_between(before: str, after: str, cwd: str, limit: int = 25) -> list[dict]:
    raw = _git("log", "--format=%H%x1f%s%x1f%b%x1e", f"{before}..{after}", cwd=cwd)
    commits = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        parts = rec.split("\x1f")
        sha = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else ""
        body = parts[2].strip() if len(parts) > 2 else ""
        commits.append({"sha": sha, "title": title, "body": body[:4000]})
        if len(commits) >= limit:
            break
    return commits


def module_diff(before: str, after: str, files: list[str], cwd: str, max_chars: int) -> str:
    if not files:
        return ""
    out = _git("diff", "--no-color", "--unified=3", before, after, "--", *files, cwd=cwd)
    if len(out) > max_chars:
        return out[:max_chars] + f"\n\n[… diff truncated at {max_chars} characters …]"
    return out


def build_payload(before: str, after: str, cwd: str, max_chars: int, repository: str | None) -> dict:
    registry = _load_registry()
    files = changed_files(before, after, cwd)
    grouped = registry.modules_for_paths(files)
    commits = commits_between(before, after, cwd)
    changes = []
    for key in sorted(grouped):
        paths = grouped[key]
        # The platform clips a module's file list at 500; do it here too so the
        # payload stays bounded on a giant squash merge (the diff is what matters).
        entry = {"module": key, "files": paths[:500], "commits": commits}
        # The unmapped bucket is reported for visibility (the platform logs it)
        # but carries no diff — there is no guide to review against.
        entry["diff"] = "" if key == registry.UNMAPPED else module_diff(before, after, paths, cwd, max_chars)
        changes.append(entry)
    return {
        "commit_sha": after,
        "commit_range": f"{before[:12]}..{after[:12]}",
        "repository": repository,
        "changes": changes,
        "_stats": {"changed_files": len(files), "user_facing_modules": [k for k in grouped if k != registry.UNMAPPED]},
    }


def post(url: str, secret: str, payload: dict, timeout: float = 60.0) -> tuple[int, str]:
    body = json.dumps({k: v for k, v in payload.items() if not k.startswith("_")}).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/director/module-changes",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}",
                 "User-Agent": "ar-tools-guide-sync/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — https to our own API
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", default=os.environ.get("GUIDE_SYNC_BEFORE", ""))
    ap.add_argument("--after", default=os.environ.get("GUIDE_SYNC_AFTER", "HEAD"))
    ap.add_argument("--url", default=os.environ.get("PLATFORM_API_URL", ""))
    ap.add_argument("--secret", default=os.environ.get("GUIDE_SYNC_SECRET", ""))
    ap.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--max-diff-chars", type=int, default=60_000)
    ap.add_argument("--repo-root", default=str(_HERE.parent.parent.parent))
    ap.add_argument("--dry-run", action="store_true", help="print the payload summary, send nothing")
    ap.add_argument("--require", action="store_true", help="fail when the URL/secret are missing")
    args = ap.parse_args(argv)

    try:
        before, after = resolve_range(args.before, args.after, args.repo_root)
        payload = build_payload(before, after, args.repo_root, args.max_diff_chars, args.repository)
    except subprocess.CalledProcessError as exc:
        print(f"::error::git failed: {exc}", file=sys.stderr)
        return 1

    stats = payload["_stats"]
    print(f"guide-sync: {before[:12]}..{after[:12]} — {stats['changed_files']} changed file(s), "
          f"user-facing modules: {', '.join(stats['user_facing_modules']) or 'none'}")
    for ch in payload["changes"]:
        print(f"  - {ch['module']}: {len(ch['files'])} file(s), diff {len(ch['diff'])} chars")

    if not stats["user_facing_modules"]:
        print("guide-sync: nothing user-facing changed — not reporting.")
        return 0
    if args.dry_run:
        print(json.dumps({k: v for k, v in payload.items() if k != "changes"}, indent=2))
        return 0
    if not (args.url and args.secret):
        msg = "guide-sync: PLATFORM_API_URL / GUIDE_SYNC_SECRET not set — skipping the report."
        if args.require:
            print(f"::error::{msg}", file=sys.stderr)
            return 2
        print(f"::notice::{msg}")
        return 0

    status, text = post(args.url, args.secret, payload)
    if status >= 300:
        print(f"::error::platform rejected the report ({status}): {text[:500]}", file=sys.stderr)
        return 2
    print(f"guide-sync: reported ({status}): {text[:500]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
