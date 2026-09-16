"""Unit tests for the Brand Guide Generator Phase-1 capture pipeline + job.

The capture layer over the pure census (`brand_guide_extract`, tested separately).
Network (ScrapeOwl / DataForSEO) and Supabase are faked; the DOM digest, logo
merge, the homepage-only palette rule, the degrade-on-401 path (finding 3), the
version increment, and the flag gate are exercised against a small in-memory DB.
Runs with no deps beyond the platform-api requirements (config loads with
defaults), mirroring the rest of the suite's service tests.
"""

from __future__ import annotations

import pytest

from services import brand_guide as G
from services import brand_guide_extract as bg


# ---------------------------------------------------------------------------
# A tiny fake Supabase: select / eq / order(desc) / limit / insert / update.
# ---------------------------------------------------------------------------
class _Query:
    def __init__(self, table, rows):
        self.table = table
        self.rows = rows
        self._filters = []
        self._order = None
        self._limit = None
        self._insert = None
        self._update = None

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self._filters.append(lambda r: r.get(k) == v)
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
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
        if self._order:
            col, desc = self._order
            out = sorted(out, key=lambda r: (r.get(col) is not None, r.get(col)), reverse=desc)
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


class FakeSupabase:
    def __init__(self, **seed):
        self.tables = {"clients": [], "brand_guides": [], "async_jobs": []}
        self.tables.update(seed)

    def table(self, name):
        return _Query(name, self.tables.setdefault(name, []))


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(G, "get_supabase", lambda: db)
    return db


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
class TestDomDigest:
    def test_extracts_title_desc_h1(self):
        html = (
            '<title>Acme Roofing — Best in Town</title>'
            '<meta name="description" content="We fix roofs fast.">'
            "<h1>Trusted <span>roof repair</span></h1>"
        )
        d = G._dom_digest(html)
        assert d["title"] == "Acme Roofing — Best in Town"
        assert d["meta_description"] == "We fix roofs fast."
        assert d["h1"] == "Trusted  roof repair"

    def test_reversed_meta_attr_order(self):
        html = '<meta content="Reversed order works." name="description">'
        assert G._dom_digest(html)["meta_description"] == "Reversed order works."

    def test_empty_degrades(self):
        assert G._dom_digest("") == {"title": "", "meta_description": "", "h1": ""}


class TestMergeLogoCandidates:
    def test_extra_page_logo_folded_in_deduped_and_capped(self):
        base = bg.logo_candidates_from_html(
            '<meta property="og:image" content="https://x.com/og.png">', base_url="https://x.com"
        )
        extra = [{
            "url": "https://x.com/about",
            "_html": '<header><img src="https://x.com/logo.svg" class="logo"></header>',
        }]
        merged = G._merge_logo_candidates(base, extra)
        urls = [c.url for c in merged]
        assert "https://x.com/og.png" in urls          # homepage candidate kept
        assert "https://x.com/logo.svg" in urls          # extra-page candidate merged
        assert merged == sorted(merged, key=lambda c: c.score, reverse=True)
        assert len(merged) <= G._MAX_LOGOS

    def test_dedup_keeps_best_score(self):
        base = [bg.LogoCandidate(url="https://x.com/l.png", source="favicon", score=20)]
        extra = [{"url": "https://x.com/p", "_html": '<img src="https://x.com/l.png" alt="logo" class="logo">'}]
        merged = G._merge_logo_candidates(base, extra)
        same = [c for c in merged if c.url == "https://x.com/l.png"]
        assert len(same) == 1 and same[0].score > 20  # the logo-hinted (higher) score wins


# ---------------------------------------------------------------------------
# _capture_page — the degrade paths (findings 3)
# ---------------------------------------------------------------------------
class TestCapturePageDegrade:
    async def test_scrapeowl_401_degrades_to_screenshot(self, monkeypatch):
        async def _boom(*_a, **_k):
            raise RuntimeError("401 Unauthorized")

        async def _shot(_url):
            return b"PNGBYTES"

        monkeypatch.setattr("services.website_scraper.scrapeowl_fetch", _boom)
        monkeypatch.setattr("services.qa_visual.capture_screenshot", _shot)
        monkeypatch.setattr(G, "pixel_counts_from_png", lambda png: [((10, 20, 30), 500)])

        rec = await G._capture_page("https://blocked.example", "homepage")
        assert rec["html_len"] == 0
        assert rec["has_screenshot"] is True
        assert rec["_pixels"] == [((10, 20, 30), 500)]
        assert any("scrapeowl_failed" in n for n in rec["notes"])
        assert any("html_unavailable" in n for n in rec["notes"])  # essential-fallback note

    async def test_screenshot_none_recorded(self, monkeypatch):
        async def _html(*_a, **_k):
            return "<html><style>body{color:#123456}</style></html>"

        async def _noshot(_url):
            return None

        monkeypatch.setattr("services.website_scraper.scrapeowl_fetch", _html)
        monkeypatch.setattr("services.qa_visual.capture_screenshot", _noshot)
        rec = await G._capture_page("https://x.example", "homepage")
        assert rec["has_screenshot"] is False
        assert rec["_pixels"] == []
        assert any("screenshot_unavailable" in n for n in rec["notes"])


# ---------------------------------------------------------------------------
# generate_brand_guide — the pipeline
# ---------------------------------------------------------------------------
HOME_HTML = (
    "<html><head>"
    '<link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet">'
    '<meta property="og:image" content="https://acme.example/og.png">'
    "<style>body{font-family:'Inter',sans-serif;font-size:16px;color:#1a2b6d;background:#ffffff}"
    "h1{font-size:48px}</style></head>"
    '<body><nav><a href="/services">Services</a><a href="/about">About</a></nav></body></html>'
)


@pytest.fixture
def guide_row(fake_db):
    fake_db.tables["brand_guides"].append(
        {"id": "g-1", "client_id": "c-1", "version": 1, "status": "queued", "source_url": "https://acme.example"}
    )
    return fake_db


class TestGenerate:
    async def test_homepage_only_palette_and_captured_record(self, guide_row, monkeypatch):
        async def _cap(url, role):
            if role == "homepage":
                return {"url": url, "role": role, "notes": [], "html_len": len(HOME_HTML),
                        "has_screenshot": True, "_html": HOME_HTML,
                        "_pixels": [((26, 43, 109), 800), ((255, 255, 255), 200)], "_png": b"PNG"}
            # a degraded extra page: no html, no screenshot — must not break capture
            return {"url": url, "role": role, "notes": ["html_unavailable: …"],
                    "html_len": 0, "has_screenshot": False, "_html": "", "_pixels": [], "_png": None}

        monkeypatch.setattr(G, "_capture_page", _cap)
        monkeypatch.setattr(G, "_store_screenshot", lambda c, g, r, png: (f"path/{r}.png" if png else None))

        result = await G.generate_brand_guide("g-1", "c-1", "https://acme.example")

        row = guide_row.tables["brand_guides"][0]
        assert row["status"] == "done" and row["generated_at"] == "now()"
        census = row["visual_census"]
        # palette measured from the homepage pixels only (§4.1) — navy dominates.
        assert census["palette_source"] == "pixel"
        assert result["palette_source"] == "pixel"
        assert census["colors"][0]["rgb"] == [26, 43, 109]
        # navy snapped to the declared CSS hex
        assert census["colors"][0]["css_hex"] == "#1a2b6d"
        assert any(f["name"] == "Inter" for f in census["fonts"])
        # captured record: homepage + the 2 discovered pages, notes preserved.
        cap = row["captured"]
        assert cap["page_count"] == 3
        assert [p["role"] for p in cap["pages"]] == ["homepage", "page-1", "page-2"]
        assert cap["pages"][0]["screenshot_path"] == "path/homepage.png"
        assert cap["pages"][0]["dom_digest"]["title"] == ""  # HOME_HTML has no <title>
        assert cap["pages"][1]["screenshot_path"] is None    # degraded page kept a null path
        assert any("html_unavailable" in n for n in cap["pages"][1]["notes"])

    async def test_no_source_url_degrades_to_empty_census(self, guide_row, monkeypatch):
        # Should never call the network.
        monkeypatch.setattr(G, "_capture_page", None)
        result = await G.generate_brand_guide("g-1", "c-1", "")
        row = guide_row.tables["brand_guides"][0]
        assert row["status"] == "done"
        assert result["no_source_url"] is True
        assert row["captured"]["no_source_url"] is True
        assert row["visual_census"]["palette_source"] == "none"
        assert row["visual_census"]["notes"]  # explains the visual layer is absent


# ---------------------------------------------------------------------------
# enqueue + version + the job's flag gate
# ---------------------------------------------------------------------------
class TestEnqueueAndJob:
    def test_next_version_increments(self, fake_db):
        assert G._next_version(fake_db, "c-1") == 1
        fake_db.tables["brand_guides"] += [
            {"client_id": "c-1", "version": 1}, {"client_id": "c-1", "version": 2},
            {"client_id": "OTHER", "version": 9},
        ]
        assert G._next_version(fake_db, "c-1") == 3  # highest for THIS client + 1

    def test_enqueue_creates_row_and_job(self, fake_db):
        fake_db.tables["clients"].append({"id": "c-1", "website_url": "https://acme.example"})
        gid = G.enqueue_brand_guide_generate("c-1", user_id="u-9")
        row = next(r for r in fake_db.tables["brand_guides"] if r["id"] == gid)
        assert row["status"] == "queued" and row["version"] == 1
        assert row["source_url"] == "https://acme.example"  # resolved from the client
        job = fake_db.tables["async_jobs"][0]
        assert job["job_type"] == "brand_guide_generate"
        assert job["payload"]["guide_id"] == gid and job["payload"]["user_id"] == "u-9"

    async def test_job_disabled_settles_without_spending(self, fake_db, monkeypatch):
        monkeypatch.setattr(G.settings, "brand_guide_enabled", False)
        fake_db.tables["brand_guides"].append({"id": "g-1", "client_id": "c-1", "status": "queued"})
        fake_db.tables["async_jobs"].append({"id": "job-1"})
        await G.run_brand_guide_generate_job(
            {"id": "job-1", "payload": {"guide_id": "g-1", "client_id": "c-1"}}
        )
        job = fake_db.tables["async_jobs"][0]
        assert job["status"] == "complete" and job["result"]["skipped"] == "brand_guide_disabled"
        assert fake_db.tables["brand_guides"][0]["status"] == "error"  # not left queued

    async def test_job_enabled_defensive_row_create(self, fake_db, monkeypatch):
        # A bare {client_id} job (worker-verification path) creates its own row.
        monkeypatch.setattr(G.settings, "brand_guide_enabled", True)
        fake_db.tables["clients"].append({"id": "c-1", "website_url": ""})
        fake_db.tables["async_jobs"].append({"id": "job-1"})
        captured = {}

        async def _gen(guide_id, client_id, source_url, **kw):
            captured["guide_id"] = guide_id
            return {"guide_id": guide_id, "pages": 0}

        monkeypatch.setattr(G, "generate_brand_guide", _gen)
        await G.run_brand_guide_generate_job({"id": "job-1", "payload": {"client_id": "c-1"}})
        assert captured["guide_id"], "job created a brand_guides row for a bare client_id insert"
        assert fake_db.tables["async_jobs"][0]["status"] == "complete"


# ---------------------------------------------------------------------------
# Phase 1.5 vibe read — wiring into the row write (the read itself is tested in
# test_brand_guide_vibe.py; here we lock that generate_brand_guide folds a
# returned vibe_read into the final update + records the note either way).
# ---------------------------------------------------------------------------
class TestVibeWiring:
    async def _run(self, guide_row, monkeypatch, vibe_result):
        async def _cap(url, role):
            return {"url": url, "role": role, "notes": [], "html_len": 10,
                    "has_screenshot": True, "_html": "<html></html>",
                    "_pixels": [((26, 43, 109), 800)], "_png": b"PNG"}

        monkeypatch.setattr(G, "_capture_page", _cap)
        monkeypatch.setattr(G, "_store_screenshot", lambda c, g, r, png: f"path/{r}.png")
        monkeypatch.setattr(bg, "discover_key_pages", lambda *a, **k: [])

        async def _vibe(captured, *, homepage_png=None):
            # the generate flow reuses the in-memory homepage bytes (no bucket round-trip)
            assert homepage_png == b"PNG"
            return vibe_result

        monkeypatch.setattr("services.brand_guide_vibe.run_vibe_read_for_capture", _vibe)
        return await G.generate_brand_guide("g-1", "c-1", "https://acme.example")

    async def test_vibe_read_folded_into_row(self, guide_row, monkeypatch):
        vibe = {"aesthetic_descriptors": [{"descriptor": "clinical", "evidence": "black canvas"}]}
        result = await self._run(guide_row, monkeypatch, (vibe, "vibe read captured"))
        row = guide_row.tables["brand_guides"][0]
        assert row["status"] == "done"
        assert row["vibe_read"] == vibe
        assert row["captured"]["vibe_note"] == "vibe read captured"
        assert result["vibe"] is True

    async def test_skipped_vibe_omits_field_but_notes(self, guide_row, monkeypatch):
        result = await self._run(guide_row, monkeypatch, (None, "vibe read skipped — disabled"))
        row = guide_row.tables["brand_guides"][0]
        assert row["status"] == "done"
        assert "vibe_read" not in row                     # never written as null
        assert row["captured"]["vibe_note"] == "vibe read skipped — disabled"
        assert result["vibe"] is False


# ---------------------------------------------------------------------------
# Phase 2 synthesis wiring — generate_brand_guide → _finalize_guide → synthesis.
# The synthesis logic is tested in test_brand_guide_synthesis.py; here we lock the
# wiring: the returned (synthesized, status) is folded into the row write, and a
# regulated client's `awaiting_signoff` status reaches the row.
# ---------------------------------------------------------------------------
class TestSynthesisWiring:
    async def _run(self, guide_row, monkeypatch, synth_result, *, source_url="https://acme.example"):
        monkeypatch.setattr(G.settings, "brand_guide_enabled", True)

        async def _cap(url, role):
            return {"url": url, "role": role, "notes": [], "html_len": 10,
                    "has_screenshot": True, "_html": "<html></html>",
                    "_pixels": [((26, 43, 109), 800)], "_png": b"PNG"}

        monkeypatch.setattr(G, "_capture_page", _cap)
        monkeypatch.setattr(G, "_store_screenshot", lambda c, g, r, png: f"path/{r}.png")
        monkeypatch.setattr(bg, "discover_key_pages", lambda *a, **k: [])

        async def _vibe(captured, *, homepage_png=None):
            return None, "vibe read skipped — disabled"

        async def _synth(client, *, census, vibe_read=None, captured=None):
            return synth_result

        # Phase 3 render fires inline for a non-regulated `done` guide (brand_guide_enabled
        # is True here). Stub it — the render layer is exercised in test_brand_guide_render.py;
        # this class only locks the synthesis→row wiring.
        async def _render(guide_id, deliver=True):
            return {"guide_id": guide_id, "status": "done", "pdf_url": "https://signed/client"}

        monkeypatch.setattr("services.brand_guide_vibe.run_vibe_read_for_capture", _vibe)
        monkeypatch.setattr("services.brand_guide_synthesis.run_synthesis_for_guide", _synth)
        monkeypatch.setattr("services.brand_guide_render.render_and_store_guide", _render)
        return await G.generate_brand_guide("g-1", "c-1", source_url)

    async def test_synthesized_and_done_folded_into_row(self, guide_row, monkeypatch):
        synth = {"positioning_statement": "For pros.", "coherence": {"flags": []}}
        result = await self._run(guide_row, monkeypatch, (synth, "synthesis complete", "done"))
        row = guide_row.tables["brand_guides"][0]
        assert row["status"] == "done"
        assert row["synthesized"] == synth
        assert row["captured"]["synthesis_note"] == "synthesis complete"
        assert result["synthesized"] is True

    async def test_render_fires_inline_for_done_guide(self, guide_row, monkeypatch):
        # Phase 3: a non-regulated `done` guide renders inline; the render status +
        # pdf_url are folded into the generate result.
        synth = {"positioning_statement": "For pros.", "coherence": {"flags": []}}
        seen = {}

        async def _render(guide_id, deliver=True):
            seen["guide_id"], seen["deliver"] = guide_id, deliver
            return {"guide_id": guide_id, "status": "done", "pdf_url": "https://signed/client"}

        monkeypatch.setattr(G.settings, "brand_guide_enabled", True)

        async def _cap(url, role):
            return {"url": url, "role": role, "notes": [], "html_len": 10,
                    "has_screenshot": True, "_html": "<html></html>",
                    "_pixels": [((26, 43, 109), 800)], "_png": b"PNG"}

        async def _vibe(captured, *, homepage_png=None):
            return None, "vibe read skipped — disabled"

        async def _synth(client, *, census, vibe_read=None, captured=None):
            return synth, "synthesis complete", "done"

        monkeypatch.setattr(G, "_capture_page", _cap)
        monkeypatch.setattr(G, "_store_screenshot", lambda c, g, r, png: f"path/{r}.png")
        monkeypatch.setattr(bg, "discover_key_pages", lambda *a, **k: [])
        monkeypatch.setattr("services.brand_guide_vibe.run_vibe_read_for_capture", _vibe)
        monkeypatch.setattr("services.brand_guide_synthesis.run_synthesis_for_guide", _synth)
        monkeypatch.setattr("services.brand_guide_render.render_and_store_guide", _render)

        result = await G.generate_brand_guide("g-1", "c-1", "https://acme.example")
        assert seen == {"guide_id": "g-1", "deliver": True}
        assert result["render_status"] == "done"
        assert result["pdf_url"] == "https://signed/client"

    async def test_regulated_awaiting_signoff_reaches_row(self, guide_row, monkeypatch):
        synth = {"positioning_statement": "For patients.", "provenance": {"regulated": True}}
        result = await self._run(
            guide_row, monkeypatch, (synth, "synthesis complete — awaiting sign-off (regulated client)", "awaiting_signoff")
        )
        row = guide_row.tables["brand_guides"][0]
        assert row["status"] == "awaiting_signoff"
        assert row["synthesized"] == synth
        # Render does NOT fire for a regulated (awaiting_signoff) guide — had it, `_run`'s
        # render stub would have overridden result["status"] to "done".
        assert result["status"] == "awaiting_signoff"
        assert "render_status" not in result

    async def test_synthesis_none_omits_field(self, guide_row, monkeypatch):
        result = await self._run(guide_row, monkeypatch, (None, "synthesis produced no usable output", "done"))
        row = guide_row.tables["brand_guides"][0]
        assert row["status"] == "done"
        assert "synthesized" not in row               # never written as null
        assert result["synthesized"] is False

    async def test_no_source_url_still_runs_synthesis(self, guide_row, monkeypatch):
        # §5.4: a client with no site still gets the synthesized layer from assets.
        synth = {"positioning_statement": "From ICP alone.", "coherence": {"flags": []}}
        result = await self._run(guide_row, monkeypatch, (synth, "synthesis complete", "done"), source_url="")
        row = guide_row.tables["brand_guides"][0]
        assert row["status"] == "done"
        assert row["synthesized"] == synth
        assert row["captured"]["no_source_url"] is True
        assert result["no_source_url"] is True

    async def test_synthesis_exception_still_finalizes_done(self, guide_row, monkeypatch):
        # §5.4: an unexpected synthesis error must NOT error the guide — the census
        # + vibe still persist and the guide finalizes `done`.
        monkeypatch.setattr(G.settings, "brand_guide_enabled", True)

        async def _cap(url, role):
            return {"url": url, "role": role, "notes": [], "html_len": 10,
                    "has_screenshot": True, "_html": "<html></html>",
                    "_pixels": [((26, 43, 109), 800)], "_png": b"PNG"}

        async def _vibe(captured, *, homepage_png=None):
            return None, "vibe read skipped — disabled"

        async def _boom(*a, **k):
            raise RuntimeError("kaboom")

        async def _render(guide_id, deliver=True):
            return {"guide_id": guide_id, "status": "done"}

        monkeypatch.setattr(G, "_capture_page", _cap)
        monkeypatch.setattr(G, "_store_screenshot", lambda c, g, r, png: f"path/{r}.png")
        monkeypatch.setattr(bg, "discover_key_pages", lambda *a, **k: [])
        monkeypatch.setattr("services.brand_guide_vibe.run_vibe_read_for_capture", _vibe)
        monkeypatch.setattr("services.brand_guide_synthesis.run_synthesis_for_guide", _boom)
        monkeypatch.setattr("services.brand_guide_render.render_and_store_guide", _render)

        result = await G.generate_brand_guide("g-1", "c-1", "https://acme.example")
        row = guide_row.tables["brand_guides"][0]
        assert row["status"] == "done"                    # not "error"
        assert "synthesized" not in row
        assert row["visual_census"]["colors"]             # census still persisted
        assert row["captured"]["synthesis_note"].startswith("synthesis error")
        assert result["synthesized"] is False


class TestPixelCounts:
    def test_quantizes_a_two_colour_png(self):
        Image = pytest.importorskip("PIL.Image")
        import io

        im = Image.new("RGB", (10, 10), (200, 0, 0))
        for y in range(10):
            for x in range(5):
                im.putpixel((x, y), (0, 0, 200))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        counts = G.pixel_counts_from_png(buf.getvalue())
        rgbs = {rgb for rgb, _ in counts}
        assert any(r > 150 and g < 60 and b < 60 for r, g, b in rgbs)   # red present
        assert any(b > 150 and r < 60 and g < 60 for r, g, b in rgbs)   # blue present
