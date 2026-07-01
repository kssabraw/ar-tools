"""Tests for fanout.suite_mirror — mirroring a Fan-out blog article into the
suite as a first-class completed blog run.

No network: a recording fake of the suite service client captures the inserts.
Guarantees under test:

  * a client-linked session produces one `runs` row (blog_post / complete) plus
    the three module_outputs rows (brief + writer carry the title; sources_cited
    carries the article sections under enriched_article.article) — the exact
    shape both the publish flow and Saved Articles read.
  * a session with no client_id is a no-op (returns None, writes nothing).
"""

from __future__ import annotations

from unittest.mock import patch

from fanout import suite_mirror


class _Table:
    def __init__(self, name: str, log: list[dict]):
        self.name = name
        self._log = log
        self._payload = None

    def insert(self, payload):
        self._payload = payload
        self._log.append({"table": self.name, "op": "insert", "payload": payload})
        return self

    def update(self, payload):
        self._payload = payload
        self._log.append({"table": self.name, "op": "update", "payload": payload})
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        if self.name == "runs" and isinstance(self._payload, dict):
            return type("R", (), {"data": [{"id": "run-123", **self._payload}]})()
        return type("R", (), {"data": []})()


class _Client:
    def __init__(self, log: list[dict]):
        self._log = log

    def table(self, name: str) -> _Table:
        return _Table(name, self._log)


ARTICLE_JSON = {
    "title": "Best Roof Restoration in Melbourne",
    "article": [
        {"order": 0, "level": "H1", "type": "title", "heading": "Roof Restoration", "body": ""},
        {"order": 1, "level": "H2", "type": "content", "heading": "Why it matters", "body": "Because."},
    ],
}


def test_mirror_creates_run_and_three_module_rows():
    log: list[dict] = []
    with patch.object(suite_mirror, "_get_supabase", return_value=_Client(log)):
        run_id = suite_mirror.mirror_blog_article_to_suite(
            session={"client_id": "client-1"},
            keyword="roof restoration melbourne",
            article_json=ARTICLE_JSON,
            cost_usd=1.23,
        )

    assert run_id == "run-123"

    runs_inserts = [e for e in log if e["table"] == "runs" and e["op"] == "insert"]
    assert len(runs_inserts) == 1
    run_payload = runs_inserts[0]["payload"]
    assert run_payload["client_id"] == "client-1"
    assert run_payload["content_type"] == "blog_post"
    assert run_payload["status"] == "complete"
    assert run_payload["total_cost_usd"] == 1.23

    mo_inserts = [e for e in log if e["table"] == "module_outputs" and e["op"] == "insert"]
    assert len(mo_inserts) == 1
    rows = mo_inserts[0]["payload"]
    by_module = {r["module"]: r for r in rows}
    assert set(by_module) == {"brief", "writer", "sources_cited"}
    assert all(r["status"] == "complete" for r in rows)
    assert by_module["brief"]["output_payload"]["title"] == "Best Roof Restoration in Melbourne"
    assert by_module["writer"]["output_payload"]["title"] == "Best Roof Restoration in Melbourne"
    sections = by_module["sources_cited"]["output_payload"]["enriched_article"]["article"]
    assert sections == ARTICLE_JSON["article"]


def test_mirror_title_falls_back_to_keyword():
    log: list[dict] = []
    with patch.object(suite_mirror, "_get_supabase", return_value=_Client(log)):
        suite_mirror.mirror_blog_article_to_suite(
            session={"client_id": "c"}, keyword="fallback kw",
            article_json={"title": "  ", "article": []},
        )
    by_module = {
        r["module"]: r
        for e in log if e["table"] == "module_outputs"
        for r in e["payload"]
    }
    assert by_module["brief"]["output_payload"]["title"] == "fallback kw"


def test_mirror_noop_without_client_id():
    log: list[dict] = []
    with patch.object(suite_mirror, "_get_supabase", return_value=_Client(log)):
        run_id = suite_mirror.mirror_blog_article_to_suite(
            session={"client_id": None}, keyword="kw", article_json=ARTICLE_JSON,
        )
    assert run_id is None
    assert log == []
