#!/usr/bin/env python3
"""CLI: score how faithfully a generated page mirrors a client's reference structure.

This is the tuning harness for reference page-structure mirroring. Generate a
page against the live stack, then compare it to the reference the suite stored
for the client (clients.page_structures) to get a structural-fidelity score.

Usage
-----
  # Compare a generated page (HTML or Markdown) to a reference analysis JSON.
  python -m scripts.eval_page_structure \
      --reference ref.json \
      --generated out.html

  # Reference can be a full page_structures entry, a bare analysis dict, OR a
  # whole page_structures object — in which case pass --page-type to pick one.
  python -m scripts.eval_page_structure \
      --reference client_page_structures.json --page-type service \
      --generated out.md

  # Pull the reference straight from a client row dump (the GET /clients/{id}
  # response saved to a file): --reference client.json --page-type blog_post

The generated file type is inferred from its extension (.md/.markdown → Markdown,
else HTML); override with --generated-format {html,markdown}.

Exit code is 0 unless --min-score is given and the composite falls below it.
Run from writer/platform-api/ so `services` is importable, or rely on the sys.path
shim below.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running as `python scripts/eval_page_structure.py` from platform-api/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.page_structure_eval import (  # noqa: E402
    extract_outline_from_html,
    extract_outline_from_markdown,
    score_structural_fidelity,
)
from services.page_structure_render import PAGE_TYPE_LABELS  # noqa: E402


def _load_reference(path: str, page_type: str | None) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise SystemExit("reference JSON must be an object")
    # A client row dump → its page_structures.
    if "page_structures" in data and isinstance(data["page_structures"], dict):
        data = data["page_structures"]
    # A whole page_structures map keyed by page type → pick one.
    if any(k in data for k in PAGE_TYPE_LABELS):
        if not page_type:
            raise SystemExit(
                "reference looks like a page_structures map; pass --page-type "
                f"({', '.join(PAGE_TYPE_LABELS)})"
            )
        entry = data.get(page_type)
        if not isinstance(entry, dict):
            raise SystemExit(f"no '{page_type}' entry in the reference")
        return entry
    return data


def _load_generated(path: str, fmt: str | None) -> dict:
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    if fmt is None:
        fmt = "markdown" if path.lower().endswith((".md", ".markdown")) else "html"
    if fmt == "markdown":
        return extract_outline_from_markdown(content)
    return extract_outline_from_html(content)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", required=True, help="Path to the reference analysis / page_structures / client JSON")
    ap.add_argument("--generated", required=True, help="Path to the generated page (HTML or Markdown)")
    ap.add_argument("--page-type", choices=list(PAGE_TYPE_LABELS), help="Which reference page type to score against")
    ap.add_argument("--generated-format", choices=["html", "markdown"], help="Override generated-file format inference")
    ap.add_argument("--min-score", type=float, help="Exit non-zero if composite falls below this")
    ap.add_argument("--json", action="store_true", help="Emit the result as JSON")
    args = ap.parse_args()

    reference = _load_reference(args.reference, args.page_type)
    generated = _load_generated(args.generated, args.generated_format)
    result = score_structural_fidelity(reference, generated)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Composite structural fidelity: {result['composite']}/100")
        print("Dimensions:")
        for k, v in result["dimensions"].items():
            print(f"  {k:<14} {v}")
        if result["notes"]:
            print("Notes:")
            for n in result["notes"]:
                print(f"  - {n}")

    if args.min_score is not None and result["composite"] < args.min_score:
        print(f"FAIL: {result['composite']} < {args.min_score}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
