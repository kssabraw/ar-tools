"""Tests for the blog scoring / reoptimization service — the report-only
Topic-Vector / Information-Gain COACHING wiring into the blog reopt path.

The blog rewrite runs in pipeline-api (there is no nlp blog-rewrite endpoint), so
the gain guidance can't be injected the Local SEO way (inside an nlp rewrite
prompt). It travels instead: nlp renders the coaching string at SCORE time onto
the report-only `topic_vector.gain_guidance` field, and a blog reopt threads that
string into the pipeline-api writer payload as ADVISORY writer-notes text (never
a `deficiencies` entry, composite weight 0). These tests pin that threading.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from services import blog_page_score as bps

_PFX = "services.blog_page_score"

_GAIN = (
    "TOPIC & INFORMATION-GAIN GUIDANCE (report-only signal — improve where it "
    "does not conflict...):\n  - subtopic: dosing protocols"
)


# ---- module-aware fake supabase (query-builder shim) -------------------------
# Unlike test_service_page_score's fake (one shared module_outputs list), this
# resolves module_outputs by the `.eq("module", …)` filter, so blog_score (which
# carries topic_vector.gain_guidance) is distinct from brief/sie/writer/etc.

class _FakeChain:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self._eq: dict = {}
        self._insert = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        return self

    def insert(self, row):
        self._insert = row
        self.store.setdefault("inserts", []).append((self.table, row))
        return self

    def execute(self):
        if self._insert is not None:
            return MagicMock(data=[{"id": "new-id"}])
        if self.table == "module_outputs":
            module = self._eq.get("module")
            row = self.store["module_outputs"].get(module)
            return MagicMock(data=([row] if row else []))
        return MagicMock(data=self.store.get(self.table))


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeChain(name, self.store)


def _store(*, gain: str | None = _GAIN):
    blog_score_payload = {
        "composite_score": 74.0,
        "deficiencies": [{"engine": "AEO", "issues": ["x"], "recommendations": ["y"]}],
    }
    if gain is not None:
        blog_score_payload["topic_vector"] = {"available": True, "gain_guidance": gain}
    return {
        "runs": {"id": "r1", "content_type": "blog_post", "client_id": "c1",
                 "keyword": "collagen peptides", "writer_notes": None,
                 "content_writer_provider": None},
        "clients": {"name": "Nova", "gbp": {"gbp_category": "Peptides"}},
        "client_context_snapshots": [{"brand_guide_text": "b", "icp_text": "i",
                                      "website_analysis": None,
                                      "website_analysis_unavailable": True,
                                      "page_structures": {}}],
        "module_outputs": {
            "brief": {"attempt_number": 1, "output_payload": {"title": "T", "h1": "H"}},
            "sie": {"attempt_number": 1, "output_payload": {}},
            "research": {"attempt_number": 1, "output_payload": {}},
            "writer": {"attempt_number": 2, "output_payload": {"article": [{"heading": "A", "body": "b"}]}},
            "blog_score": {"attempt_number": 1, "output_payload": blog_score_payload},
            "sources_cited": {"attempt_number": 3, "output_payload": {
                "enriched_article": {"article": [{"order": 0, "heading": "A", "body": "body"}]}}},
        },
    }


_SCORE = {"composite_score": 80.0, "composite_status": "good", "engine_scores": {},
          "deficiencies": [], "token_usage": {"cost_usd": 0.01},
          "topic_vector": {"available": True, "gain_guidance": ""}}


# ---- _reopt_gain_guidance (pure-ish read helper) -----------------------------

def test_reopt_gain_guidance_reads_latest_blog_score():
    with patch(f"{_PFX}._sb", return_value=_FakeSB(_store())):
        assert bps._reopt_gain_guidance("r1") == _GAIN


def test_reopt_gain_guidance_empty_when_no_topic_vector():
    with patch(f"{_PFX}._sb", return_value=_FakeSB(_store(gain=None))):
        assert bps._reopt_gain_guidance("r1") == ""


def test_reopt_gain_guidance_empty_when_no_blog_score():
    store = _store()
    del store["module_outputs"]["blog_score"]
    with patch(f"{_PFX}._sb", return_value=_FakeSB(store)):
        assert bps._reopt_gain_guidance("r1") == ""


# ---- reoptimize_run threads the coaching into the writer payload -------------

def _patches(store):
    return (
        patch(f"{_PFX}._sb", return_value=_FakeSB(store)),
        patch(f"{_PFX}._post_pipeline",
              AsyncMock(return_value={"article": [], "metadata": {"cost_usd": 0.05}})),
        patch(f"{_PFX}._post_nlp", AsyncMock(return_value=_SCORE)),
        patch("services.voice_card_service.get_voice_card", AsyncMock(return_value=None)),
        patch("services.site_claim_index.resolve_index_for_request", AsyncMock(return_value=None)),
    )


async def test_reoptimize_run_threads_gain_guidance_into_writer_payload():
    store = _store()
    p_sb, p_pipe, p_nlp, p_vc, p_idx = _patches(store)
    with p_sb, p_pipe as post_pipeline, p_nlp, p_vc, p_idx:
        await bps.reoptimize_run("r1", [{"engine_key": "aeo_llm_retrieval"}], user_id="u1")

    # The FIRST _post_pipeline call is the writer (/write); assert the advisory
    # coaching rode in as reopt_gain_guidance — and NEVER as a deficiency.
    writer_payload = post_pipeline.call_args_list[0].args[1]
    assert writer_payload["reopt_gain_guidance"] == _GAIN
    assert writer_payload["mode"] == "reoptimize"
    assert writer_payload["deficiencies"] == [{"engine_key": "aeo_llm_retrieval"}]
    assert "reopt_gain_guidance" not in writer_payload["deficiencies"]
    assert _GAIN not in str(writer_payload["deficiencies"])


async def test_reoptimize_run_omits_key_when_no_guidance():
    # No topic_vector on the score → byte-identical writer payload (no key).
    store = _store(gain=None)
    p_sb, p_pipe, p_nlp, p_vc, p_idx = _patches(store)
    with p_sb, p_pipe as post_pipeline, p_nlp, p_vc, p_idx:
        await bps.reoptimize_run("r1", [], user_id="u1")

    writer_payload = post_pipeline.call_args_list[0].args[1]
    assert "reopt_gain_guidance" not in writer_payload
