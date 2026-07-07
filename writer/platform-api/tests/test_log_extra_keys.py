"""Guard against reserved LogRecord attribute names in logging extra={} dicts.

Python's logging raises KeyError("Attempt to overwrite %r in LogRecord") when an
extra dict uses a key that collides with a built-in LogRecord attribute (e.g.
"filename", "message", "created", "module"). Because the crash happens inside
the logging call itself, it takes down the request that triggered it — this is
exactly how the SOP upload endpoint 500'd ("Failed to fetch" in the browser).

This test AST-scans every backend source file for literal extra={...} keys and
fails on any reserved name, so the bug class can't recur silently.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

# platform-api root (this file lives in platform-api/tests/); scan the sibling
# APIs too since they share the same logging conventions.
_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
_SCAN_ROOTS = [
    _PLATFORM_ROOT,
    _PLATFORM_ROOT.parent / "pipeline-api",
    _PLATFORM_ROOT.parent / "nlp-api",
]

# Every attribute a fresh LogRecord carries, plus the two names Formatter adds.
_RESERVED = set(
    vars(logging.LogRecord("name", logging.INFO, "path", 1, "msg", (), None))
) | {"message", "asctime"}


def _reserved_extra_keys(tree: ast.AST) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "extra" or not isinstance(kw.value, ast.Dict):
                continue
            for key in kw.value.keys:
                if isinstance(key, ast.Constant) and key.value in _RESERVED:
                    hits.append((key.lineno, key.value))
    return hits


def test_no_reserved_logrecord_keys_in_extra() -> None:
    offenders: list[str] = []
    for root in _SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for lineno, key in _reserved_extra_keys(tree):
                offenders.append(f"{path.relative_to(_PLATFORM_ROOT.parent)}:{lineno}: {key!r}")
    assert not offenders, (
        "Reserved LogRecord attribute(s) used as logging extra keys "
        f"(rename them, e.g. filename -> upload_filename): {offenders}"
    )
