"""Unit tests for the Brand Guide Generator Phase-3 render layer.

The pure HTML/section builders (rendered from the stored `visual_census` /
`vibe_read` / `synthesized` shapes), the "not captured" degrade paths, the
internal↔client profile delta (§4.7 — the only difference is the coherence/audit
treatment), and the `render_and_store_guide` orchestration (WeasyPrint + storage +
Drive all faked). No network; WeasyPrint is never imported (the render call is
monkeypatched). Mirrors the rest of the suite's service tests.
"""

from __future__ import annotations

import pytest

from services import brand_guide_render as R


# ---------------------------------------------------------------------------
# Fixtures — representative stored shapes
# ---------------------------------------------------------------------------
def _guide(**over) -> dict:
    g = {
        "id": "guide-1",
        "client_id": "client-1",
        "version": 2,
        "generated_at": "2026-09-15T12:00:00Z",
        "visual_census": {
            "colors": [
                {"hex": "#0f172a", "rgb": [15, 23, 42], "hsl": [222, 47, 11], "cmyk": [64, 45, 0, 84], "share": 0.55, "source": "both"},
                {"hex": "#6366f1", "rgb": [99, 102, 241], "hsl": [239, 84, 67], "cmyk": [59, 58, 0, 5], "share": 0.12, "source": "pixel"},
            ],
            "fonts": [
                {"name": "Inter", "count": 12, "google": True},
                {"name": "Georgia", "count": 3, "google": False},
            ],
            "type_scale": [{"px": 40, "count": 2}, {"px": 16, "count": 30}],
            "logo_candidates": [
                {"url": "https://acme.com/logo.svg", "source": "img_logo", "score": 90, "note": ""},
            ],
            "palette_source": "pixel",
            "notes": ["Captured 3 page(s); palette from the homepage only."],
        },
        "vibe_read": {
            "aesthetic_descriptors": [
                {"descriptor": "premium", "evidence": "near-black canvas, single violet accent, generous whitespace"},
            ],
            "mood_axes": {"minimal_maximal": 20, "budget_premium": 80},
            "character": {"color_mood": "muted, near-mono", "imagery_style": "clean product photography on white"},
            "methodology_note": "This is an interpretive reading, not a measurement.",
        },
        "synthesized": {
            "tagline": "Roofs done right.",
            "tagline_options": ["Roofs done right.", "Above the rest."],
            "mission": "Protect every home we touch.",
            "positioning_statement": "The roofer homeowners trust.",
            "color": {
                "swatches": [
                    {"hex": "#0f172a", "name": "Midnight", "role": "primary", "share": 0.55},
                    {"hex": "#6366f1", "name": "Signal Violet", "role": "accent", "share": 0.12},
                ],
                "usage_ratios": {"ratio": "60/30/10", "roles": {"primary": {"hexes": ["#0f172a"], "share": "~60%"}}},
                "usage_narrative": "Lead with Midnight; use Signal Violet only for CTAs.",
                "pairings": [
                    {"background": "#0f172a", "text": "#ffffff", "ratio": 16.1, "level": "AAA", "passes_body": True},
                ],
            },
            "type_scale": [
                {"px": 40, "name": "H1", "usage": "page titles"},
                {"px": 16, "name": "Body", "usage": "paragraphs"},
            ],
            "imagery_direction": {"subjects": "finished roofs", "lighting": "bright daylight", "dos": ["real jobs"], "donts": ["stock clip-art"]},
            "iconography": "simple line icons",
            "voice_examples": {"headline": "Your roof, handled.", "cta": "Get a free quote"},
            "we_say_we_dont": [{"we_say": "we", "we_dont": "the company"}],
            "key_messages": ["Fast, honest, local."],
            "boilerplate": {"short": "Acme Roofing fixes roofs.", "long": "Acme Roofing has fixed roofs since 1998."},
            "coherence": {
                "flags": [
                    {"code": "neutral_sprawl", "section": "color", "severity": "gap",
                     "title": "5 near-duplicate neutrals", "detail": "Consolidate to three."},
                ],
                "narrative": "The palette reads premium; tightening the neutrals would make it land.",
            },
            "section_gaps": [{"section": "color", "gap": "Consolidate the grays."}],
            "provenance": {"regulated": False},
        },
        "captured": {"pages": [{"role": "homepage", "screenshot_path": "client-1/guide-1/homepage.png"}], "page_count": 3},
    }
    g.update(over)
    return g


def _ctx(**over) -> dict:
    c = {
        "name": "Acme Roofing",
        "website": "https://acme.com",
        "logo_url": "https://acme.com/logo.svg",
        "brand_voice_text": "Confident, local, no-nonsense.\n\nWe speak plainly.",
        "icp_text": "Homeowners 35–65 with an aging roof.\n\nThey fear surprise costs.",
        "brand_voice": {"personality": ["confident", "local"], "tone": "warm", "messaging_themes": ["trust", "speed"]},
        "voice_card": {"must_use_terms": ["licensed"], "never_use_terms": ["cheap"]},
        "differentiators": [{"claim": "24h response", "mechanism": "local crews"}],
    }
    c.update(over)
    return c


# ---------------------------------------------------------------------------
# gather_render_context — pure over a client dict
# ---------------------------------------------------------------------------
class TestGatherContext:
    def test_reads_owned_assets(self, monkeypatch):
        monkeypatch.setattr(R.brand_voice_service, "resolve_brand_guide_text", lambda c: "voice text")
        monkeypatch.setattr(R.icp_service, "resolve_icp_text", lambda c: "icp text")
        client = {"name": "Acme", "website_url": "https://a.com", "logo_url": "https://a.com/l.png",
                  "brand_voice": {"tone": "warm"}, "voice_card": {"card": {"must_use_terms": ["x"]}},
                  "differentiators": [{"claim": "fast"}]}
        ctx = R.gather_render_context(client)
        assert ctx["name"] == "Acme"
        assert ctx["brand_voice_text"] == "voice text"
        assert ctx["icp_text"] == "icp text"
        assert ctx["voice_card"] == {"must_use_terms": ["x"]}
        assert ctx["logo_url"] == "https://a.com/l.png"

    def test_logo_falls_back_to_gbp(self, monkeypatch):
        monkeypatch.setattr(R.brand_voice_service, "resolve_brand_guide_text", lambda c: "")
        monkeypatch.setattr(R.icp_service, "resolve_icp_text", lambda c: "")
        ctx = R.gather_render_context({"gbp": {"logo": "https://g.com/l.png"}})
        assert ctx["logo_url"] == "https://g.com/l.png"

    def test_empty_client_degrades(self, monkeypatch):
        monkeypatch.setattr(R.brand_voice_service, "resolve_brand_guide_text", lambda c: "")
        monkeypatch.setattr(R.icp_service, "resolve_icp_text", lambda c: "")
        ctx = R.gather_render_context({})
        assert ctx["logo_url"] is None
        assert ctx["voice_card"] == {}
        assert ctx["differentiators"] == []


# ---------------------------------------------------------------------------
# Full document assembly (pure)
# ---------------------------------------------------------------------------
class TestBuildHtml:
    def test_full_document_renders_all_sections(self):
        html = R.build_guide_html(_guide(), _ctx(), profile="client", agency="Amazing Rankings")
        assert html.startswith("<!doctype html>")
        # Cover + tagline
        assert "Acme Roofing" in html
        assert "Roofs done right." in html
        # Every section heading present
        for h2 in ("Brand Foundation", "Audience", "Voice &amp; Messaging", "Aesthetic &amp; Art Direction",
                   "Color", "Typography", "Logo", "Imagery &amp; Iconography", "Brand in action", "How this was made"):
            assert h2 in html
        # Measured palette hexes + WCAG pairing
        assert "#0f172a" in html and "16.1:1" in html and "AAA" in html
        # Type scale + fonts
        assert "Inter" in html and "Google Fonts" in html
        # Worked voice example
        assert "Your roof, handled." in html

    def test_footer_carries_agency(self):
        html = R.build_guide_html(_guide(), _ctx(), profile="client", agency="Acme Agency")
        assert "Prepared by Acme Agency" in html

    def test_no_llm_at_render(self):
        # Render is pure assembly over the stored record (§5.2) — no LLM call.
        # The render module must not depend on report_llm / anthropic at all.
        import inspect

        src = inspect.getsource(R)
        assert "report_llm" not in src
        assert "anthropic" not in src.lower()


# ---------------------------------------------------------------------------
# Profile delta — the ONLY difference is the coherence/audit treatment (§4.7)
# ---------------------------------------------------------------------------
class TestProfileDelta:
    def test_internal_shows_blunt_flags(self):
        html = R._section_aesthetic(_guide(), client_facing=False)
        assert "Coherence audit" in html
        assert "5 near-duplicate neutrals" in html       # the blunt flag title
        assert "Consolidate to three." in html            # the blunt flag detail

    def test_client_reframes_as_opportunities(self):
        html = R._section_aesthetic(_guide(), client_facing=True)
        assert "Opportunities to sharpen" in html
        assert "Coherence audit" not in html
        # Client shows the reframed narrative + gaps, NOT the raw flag detail line.
        assert "would make it land" in html
        assert "Consolidate to three." not in html

    def test_cover_marks_internal(self):
        internal = R.build_guide_html(_guide(), _ctx(), profile="internal")
        client = R.build_guide_html(_guide(), _ctx(), profile="client")
        assert "Internal Audit" in internal
        assert "Internal audit — not for client distribution" in internal
        assert "Internal Audit" not in client


# ---------------------------------------------------------------------------
# Degrade paths — "not captured", never a blank section (§5.4)
# ---------------------------------------------------------------------------
class TestDegrade:
    def test_empty_census_renders_not_captured(self):
        bare = {"id": "g", "client_id": "c", "version": 1, "visual_census": {}, "synthesized": {}, "vibe_read": {}, "captured": {}}
        html = R.build_guide_html(bare, {"name": "Nobody"}, profile="client")
        assert "No palette recovered" in html
        assert "No typefaces recovered" in html
        # Still a complete document with every heading.
        assert "Color" in html and "Typography" in html

    def test_no_site_client_still_renders(self, monkeypatch):
        monkeypatch.setattr(R.brand_voice_service, "resolve_brand_guide_text", lambda c: "")
        monkeypatch.setattr(R.icp_service, "resolve_icp_text", lambda c: "")
        ctx = R.gather_render_context({"name": "No Site Co"})
        bare = {"id": "g", "client_id": "c", "version": 1, "visual_census": {}, "synthesized": {}, "vibe_read": {}, "captured": {}}
        html = R.build_guide_html(bare, ctx, profile="client")
        assert "No Site Co" in html
        assert "No audience (ICP) profile on file" in html

    def test_aesthetic_no_vibe_degrades(self):
        g = _guide(vibe_read={})
        html = R._section_aesthetic(g, client_facing=True)
        assert "No aesthetic read captured" in html

    def test_synthesis_missing_shows_placeholder(self):
        g = _guide(synthesized={})
        html = R._section_color(g)
        assert "No proposed colour system synthesized" in html


# ---------------------------------------------------------------------------
# render_and_store_guide — orchestration (WeasyPrint / storage / Drive faked)
# ---------------------------------------------------------------------------
class _Query:
    def __init__(self, table, rows):
        self.table, self.rows = table, rows
        self._filters, self._limit, self._insert, self._update = [], None, None, None

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self._filters.append(lambda r: r.get(k) == v)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, row):
        self._insert = row
        return self

    def update(self, upd):
        self._update = upd
        return self

    def _matching(self):
        out = [r for r in self.rows if all(f(r) for f in self._filters)]
        return out[: self._limit] if self._limit else out

    def execute(self):
        if self._insert is not None:
            rows = self._insert if isinstance(self._insert, list) else [self._insert]
            for i, r in enumerate(rows):
                r.setdefault("id", f"{self.table}-{len(self.rows) + 1 + i}")
                self.rows.append(r)
            return type("R", (), {"data": rows})()
        if self._update is not None:
            hit = self._matching()
            for r in hit:
                r.update(self._update)
            return type("R", (), {"data": hit})()
        return type("R", (), {"data": self._matching()})()


class _FakeDB:
    def __init__(self, **seed):
        self.tables = {"clients": [], "brand_guides": [], "async_jobs": []}
        self.tables.update(seed)

    def table(self, name):
        return _Query(name, self.tables.setdefault(name, []))


@pytest.fixture
def render_stubs(monkeypatch):
    """Fake the heavy I/O so the orchestration is exercised without WeasyPrint/net."""
    monkeypatch.setattr(R, "_render_pdf", lambda html: b"%PDF-" + html[:8].encode())
    monkeypatch.setattr(R, "_store_profile_pdf",
                        lambda cid, gid, prof, pdf: (f"{cid}/brand-guide/{gid}-{prof}.pdf", f"https://signed/{prof}"))
    monkeypatch.setattr(R, "_homepage_screenshot_data_uri", lambda captured: "data:image/png;base64,AAAA")

    async def _logo(url):
        return url

    monkeypatch.setattr(R, "_inline_logo", _logo)
    monkeypatch.setattr(R, "_get_client", lambda cid: {"name": "Acme", "website_url": "https://a.com"})
    monkeypatch.setattr(R.brand_voice_service, "resolve_brand_guide_text", lambda c: "voice")
    monkeypatch.setattr(R.icp_service, "resolve_icp_text", lambda c: "icp")


class TestRenderAndStore:
    async def test_renders_both_profiles_and_mirrors_client(self, monkeypatch, render_stubs):
        db = _FakeDB(brand_guides=[_guide()])

        async def _no_deliver(*_a, **_k):
            return {"drive": "skipped"}

        monkeypatch.setattr(R, "get_supabase", lambda: db)
        monkeypatch.setattr(R, "_deliver_client_pdf", _no_deliver)

        result = await R.render_and_store_guide("guide-1", deliver=True)

        assert result["status"] == "done"
        assert set(result["profiles"]) == {"internal", "client"}
        row = db.tables["brand_guides"][0]
        assert row["status"] == "done"
        assert set(row["renders"].keys()) == {"internal", "client"}
        # Top-level columns mirror the CLIENT profile (the deliverable).
        assert row["storage_path"] == "client-1/brand-guide/guide-1-client.pdf"
        assert row["pdf_url"] == "https://signed/client"
        assert row["renders"]["client"]["delivery"] == {"drive": "skipped"}
        assert row["error"] is None

    async def test_delivers_client_profile_to_drive(self, monkeypatch, render_stubs):
        db = _FakeDB(brand_guides=[_guide()])
        seen = {}

        async def _deliver(client, ctx, pdf):
            seen["pdf"] = pdf
            return {"drive": "ok", "drive_doc_id": "file-9"}

        monkeypatch.setattr(R, "get_supabase", lambda: db)
        monkeypatch.setattr(R, "_deliver_client_pdf", _deliver)

        result = await R.render_and_store_guide("guide-1", deliver=True)
        assert result["delivery"] == {"drive": "ok", "drive_doc_id": "file-9"}
        # The CLIENT profile PDF is the one delivered.
        assert seen["pdf"].startswith(b"%PDF-")

    async def test_render_failure_marks_error_note(self, monkeypatch, render_stubs):
        db = _FakeDB(brand_guides=[_guide()])
        monkeypatch.setattr(R, "get_supabase", lambda: db)

        def _boom(html):
            raise RuntimeError("weasyprint exploded")

        monkeypatch.setattr(R, "_render_pdf", _boom)
        result = await R.render_and_store_guide("guide-1")
        assert result["status"] == "error"
        row = db.tables["brand_guides"][0]
        assert row["status"] == "error"
        assert "weasyprint exploded" in row["error"]
        # The stored census/synthesized data is untouched — only status flips.
        assert row["visual_census"]["colors"]

    async def test_missing_guide(self, monkeypatch, render_stubs):
        db = _FakeDB(brand_guides=[])
        monkeypatch.setattr(R, "get_supabase", lambda: db)
        result = await R.render_and_store_guide("nope")
        assert result["status"] == "error" and result["error"] == "guide_not_found"


# ---------------------------------------------------------------------------
# run_brand_guide_render_job — the regulated sign-off render job
# ---------------------------------------------------------------------------
class TestRenderJob:
    async def test_disabled_flag_settles_without_render(self, monkeypatch):
        db = _FakeDB(async_jobs=[{"id": "job-1", "payload": {"guide_id": "g", "client_id": "c"}}])
        monkeypatch.setattr(R, "get_supabase", lambda: db)
        monkeypatch.setattr(R.settings, "brand_guide_enabled", False)
        called = {"n": 0}

        async def _spy(*_a, **_k):
            called["n"] += 1
            return {}

        monkeypatch.setattr(R, "render_and_store_guide", _spy)
        await R.run_brand_guide_render_job({"id": "job-1", "payload": {"guide_id": "g", "client_id": "c"}})
        assert called["n"] == 0
        assert db.tables["async_jobs"][0]["status"] == "complete"

    async def test_missing_guide_id_fails(self, monkeypatch):
        db = _FakeDB(async_jobs=[{"id": "job-1", "payload": {}}])
        monkeypatch.setattr(R, "get_supabase", lambda: db)
        monkeypatch.setattr(R.settings, "brand_guide_enabled", True)
        await R.run_brand_guide_render_job({"id": "job-1", "payload": {}})
        assert db.tables["async_jobs"][0]["status"] == "failed"

    async def test_runs_render_and_completes(self, monkeypatch):
        db = _FakeDB(async_jobs=[{"id": "job-1", "payload": {"guide_id": "g", "client_id": "c"}}])
        monkeypatch.setattr(R, "get_supabase", lambda: db)
        monkeypatch.setattr(R.settings, "brand_guide_enabled", True)

        async def _ok(guide_id, deliver=True):
            return {"guide_id": guide_id, "status": "done", "profiles": ["internal", "client"]}

        monkeypatch.setattr(R, "render_and_store_guide", _ok)
        await R.run_brand_guide_render_job({"id": "job-1", "payload": {"guide_id": "g", "client_id": "c"}})
        assert db.tables["async_jobs"][0]["status"] == "complete"
        assert db.tables["async_jobs"][0]["result"]["status"] == "done"


# ---------------------------------------------------------------------------
# enqueue_brand_guide_render
# ---------------------------------------------------------------------------
def test_enqueue_creates_job(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(R, "get_supabase", lambda: db)
    job_id = R.enqueue_brand_guide_render("client-1", "guide-1", user_id="user-7")
    assert job_id
    job = db.tables["async_jobs"][0]
    assert job["job_type"] == "brand_guide_render"
    assert job["payload"] == {"guide_id": "guide-1", "client_id": "client-1", "user_id": "user-7"}
