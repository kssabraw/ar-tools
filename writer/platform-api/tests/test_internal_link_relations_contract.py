"""Cross-service contract guard: every internal-link RELATION string the matrix
planner (platform-api `local_seo_matrix`) emits onto a page's `internal_links`
must be a key in nlp-api's `_INTERNAL_LINK_RELATIONS` label map.

The two services can't share a module, so the relation strings are duplicated.
Without this guard, renaming a relation constant here would NOT fail any test —
nlp would just silently fall back to the generic "a related page" label. This
reads nlp-api's source (the same read-across-services pattern as the vendored
voice_card guard) and fails loudly on that drift.
"""

from __future__ import annotations

import ast
from pathlib import Path

from services import local_seo_matrix as core

_NLP_MAIN = Path(__file__).resolve().parents[2] / "nlp-api" / "main.py"


def _nlp_relation_keys() -> set[str]:
    tree = ast.parse(_NLP_MAIN.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_INTERNAL_LINK_RELATIONS" for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            return {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    raise AssertionError("_INTERNAL_LINK_RELATIONS dict literal not found in nlp-api/main.py")


def test_every_matrix_relation_has_an_nlp_label():
    emitted = {core.SAME_LOCATION, core.SAME_SERVICE, core.SERVICE_HUB, core.HOME}
    labels = _nlp_relation_keys()
    missing = emitted - labels
    assert not missing, (
        "nlp-api _INTERNAL_LINK_RELATIONS is missing a friendly label for the "
        f"relation string(s) {sorted(missing)} that the matrix planner emits — the "
        "nlp prompt would silently degrade them to 'a related page'. Add the "
        "label in writer/nlp-api/main.py (or keep the relation constants in sync)."
    )
