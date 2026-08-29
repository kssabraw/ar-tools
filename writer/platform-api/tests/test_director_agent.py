"""DORA persona — the pure/deterministic helpers.

Covers the seam-flag rendering, the deterministic opening brief, the fallback
text, scope resolution precedence, and the seam-label ↔ read-model coverage
guard. The LLM turn (interpret_dora / _answer) is not exercised here.
"""

from services import director_agent as da


def test_seam_labels_cover_the_read_model_seams():
    # Drift guard: every seam type the read model's seam predicates can emit has a
    # human label for the deterministic brief (so a new seam can't render as a
    # bare key). Sourced by scanning the `"seam": "<type>"` literals in
    # services/director/seams.py so a new seam there fails this test until labeled.
    import re
    from pathlib import Path

    src = Path(da.__file__).with_name("director").joinpath("seams.py").read_text()
    emitted = set(re.findall(r'"seam":\s*"([a-z_]+)"', src))
    assert emitted, "expected to find seam type literals in seams.py"
    assert emitted <= set(da._SEAM_LABELS), f"unlabeled seams: {emitted - set(da._SEAM_LABELS)}"


def test_render_flags_groups_and_names_clients(monkeypatch):
    monkeypatch.setattr(da, "_client_names", lambda ids: {"c1": "Acme", "c2": "Globex"})
    flags = [
        {"seam": "qa_idle", "client_id": None, "evidence": "8 days"},
        {"seam": "strategist_approved_unplaced", "client_id": "c1", "evidence": "3 proposals"},
        {"seam": "duplicate_target", "client_id": "c2"},
    ]
    out = da._render_flags(flags)
    assert "3 open seam flags across the agents:" in out
    assert "QA idle" in out and "8 days" in out
    assert "Acme" in out and "3 proposals" in out
    assert "Globex" in out
    # An unknown seam type still renders (as its raw key), never crashes.
    assert da._render_flags([{"seam": "brand_new_seam"}]).endswith("brand_new_seam")


def test_render_flags_singular_and_truncation(monkeypatch):
    monkeypatch.setattr(da, "_client_names", lambda ids: {})
    assert "1 open seam flag across" in da._render_flags([{"seam": "qa_idle"}])
    many = [{"seam": "qa_idle"} for _ in range(15)]
    out = da._render_flags(many)
    assert "15 open seam flags" in out
    assert "…and 3 more." in out


def test_opening_brief_all_clear(monkeypatch):
    monkeypatch.setattr(da, "build_context", lambda cid, today=None: {"flow": {"flags": []}})
    assert "All clear across the agents" in da.opening_brief_text()


def test_opening_brief_lists_flags(monkeypatch):
    monkeypatch.setattr(da, "_client_names", lambda ids: {})
    monkeypatch.setattr(
        da, "build_context",
        lambda cid, today=None: {"flow": {"flags": [{"seam": "qa_idle", "evidence": "9d"}]}},
    )
    assert "QA idle" in da.opening_brief_text()


def test_opening_brief_best_effort_on_error(monkeypatch):
    def _boom(cid, today=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(da, "build_context", _boom)
    assert da.opening_brief_text() == ""


def test_fallback_text(monkeypatch):
    monkeypatch.setattr(da, "_client_names", lambda ids: {})
    assert "Nothing's snagged" in da._fallback_text({"flow": {"flags": []}})
    assert "raw read" in da._fallback_text({"flow": {"flags": [{"seam": "qa_idle"}]}})
    assert "Nothing's snagged" in da._fallback_text(None)


def test_resolve_scope_precedence(monkeypatch):
    import services.slack_assistant as sa

    clients = [{"id": "c1", "name": "Acme"}, {"id": "c2", "name": "Globex"}]
    monkeypatch.setattr(da, "_all_clients", lambda: clients)

    # A named client wins.
    monkeypatch.setattr(sa, "resolve_client", lambda q, cs: clients[0] if "acme" in q.lower() else None)
    assert da._resolve_scope("how is Acme flowing?", None) == ("client", "c1", "Acme")

    # No named client → sticky client.
    assert da._resolve_scope("where are we bottlenecked?", "c2") == ("client", "c2", "Globex")

    # No named, no sticky → portfolio.
    assert da._resolve_scope("where are we bottlenecked?", None) == ("portfolio", None, None)

    # A sticky id that isn't a real client → portfolio (not a crash).
    assert da._resolve_scope("status?", "ghost") == ("portfolio", None, None)
