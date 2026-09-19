"""Unit tests for the Social P5 (slice a) Video Storyboard engine — pure prompt/
sanitize helpers + the DB/LLM-mocked generate + CRUD paths (no network)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from config import settings
from services.social import storyboard


# ── a tiny fake Supabase (echoes inserts; returns seeded rows) ────────────────

class _Q:
    def __init__(self, store, tbl):
        self.store = store
        self.tbl = tbl
        self._op = None
        self._fields = None

    def insert(self, fields):
        self.store.setdefault("inserts", []).append((self.tbl, fields))
        self._op, self._fields = "insert", fields
        return self

    def update(self, fields):
        self.store.setdefault("updates", []).append((self.tbl, fields))
        self._op, self._fields = "update", fields
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        rows = self.store.get("rows", {}).get(self.tbl, [])
        if self._op in ("insert", "update") and not rows:
            rows = [dict(self._fields or {})]
        return SimpleNamespace(data=rows)


def _fake_sb(store):
    return SimpleNamespace(table=lambda t: _Q(store, t))


# ── pure: platform_video_guidance ────────────────────────────────────────────

def test_platform_video_guidance_is_distinct_per_platform():
    yt = storyboard.platform_video_guidance("youtube", "short")
    ig = storyboard.platform_video_guidance("instagram", "reel")
    fb = storyboard.platform_video_guidance("facebook", "reel")
    other = storyboard.platform_video_guidance("tiktok", "reel")
    assert "YouTube Short" in yt
    assert "Instagram Reel" in ig
    assert "Facebook Reel" in fb
    # all are vertical 9:16, hook-first
    for g in (yt, ig, fb, other):
        assert "9:16" in g and "hook" in g.lower()


# ── pure: build_storyboard_prompt ─────────────────────────────────────────────

def test_build_storyboard_prompt_with_source_and_voice_last():
    p = storyboard.build_storyboard_prompt(
        platform="instagram", fmt="reel", source_title="Roof 101",
        source_text="We fix roofs.", angle="myth-bust", tone="warm",
        client_context="Business: Acme", voice_block="VOICE: say we",
        competitor_signals_block="COMPETITORS: reels win",
    )
    assert "Business: Acme" in p
    assert "--- SOURCE ---" in p and "We fix roofs." in p
    assert "Angle / hook to take: myth-bust" in p
    assert "Tone: warm" in p
    assert "COMPETITORS: reels win" in p
    # voice block is appended LAST so it wins on expression
    assert p.rstrip().endswith("VOICE: say we")


def test_build_storyboard_prompt_topic_only_and_empty_competitor_block_is_noop():
    with_block = storyboard.build_storyboard_prompt(
        platform="youtube", fmt="short", source_title="Spring promo", source_text="",
        angle=None, tone=None, client_context="Business: Acme", voice_block="V",
        competitor_signals_block="SIGNALS",
    )
    without_block = storyboard.build_storyboard_prompt(
        platform="youtube", fmt="short", source_title="Spring promo", source_text="",
        angle=None, tone=None, client_context="Business: Acme", voice_block="V",
        competitor_signals_block="",
    )
    assert "--- SOURCE ---" not in without_block
    assert "Topic: Spring promo" in without_block
    # the only difference is the competitor block — everything else byte-identical
    assert without_block == with_block.replace("\n\nSIGNALS", "")


# ── pure: sanitize_storyboard ─────────────────────────────────────────────────

def test_sanitize_storyboard_coerces_caps_and_numbers_shots():
    raw = {
        "title": "Roof restoration in 30s",
        "hook": "Your roof is older than you think",
        "duration_seconds": "45",                       # string → int
        "shots": [
            {"visual": "Drone shot of the roof", "on_screen_text": "Before", "duration_seconds": "3", "b_roll": True},
            {"visual": "", "on_screen_text": "dropped — no visual"},   # dropped
            {"voiceover": "no visual here"},                            # dropped
            {"visual": "Owner talking to camera", "voiceover": "We restore, not replace."},
        ],
        "music": "upbeat acoustic",
        "caption": "See how we restored this roof.",
        "hashtags": ["#roofing", "RoofRestoration", "  "],
        "cta": "Book a free inspection",
    }
    out = storyboard.sanitize_storyboard(raw, max_shots=12)
    assert out["hook"] == "Your roof is older than you think"
    assert out["duration_seconds"] == 45
    assert [s["n"] for s in out["shots"]] == [1, 2]        # renumbered, empties dropped
    assert out["shots"][0]["duration_seconds"] == 3        # coerced from "3"
    assert out["shots"][0]["b_roll"] is True
    assert out["hashtags"] == ["roofing", "RoofRestoration"]   # '#' stripped, blank dropped
    assert out["cta"] == "Book a free inspection"


def test_sanitize_storyboard_caps_shots_and_backfills_hook():
    raw = {
        "hook": "",  # missing → backfilled from the first shot's visual
        "shots": [{"visual": f"Shot {i}"} for i in range(20)],
    }
    out = storyboard.sanitize_storyboard(raw, max_shots=5)
    assert len(out["shots"]) == 5
    assert out["hook"] == "Shot 0"[:200]


def test_sanitize_storyboard_empty_raises():
    with pytest.raises(HTTPException) as ei:
        storyboard.sanitize_storyboard({"hook": "", "shots": []}, max_shots=12)
    assert ei.value.status_code == 502
    assert ei.value.detail == "social_storyboard_empty"
    # non-dict input is also empty
    with pytest.raises(HTTPException):
        storyboard.sanitize_storyboard("not a dict", max_shots=12)


# ── impure: generate_storyboard (LLM + DB mocked) ─────────────────────────────

@pytest.mark.asyncio
async def test_generate_storyboard_happy_path(monkeypatch):
    from services import gbp_posts_service, report_llm
    from services.social import competitor_research, creator

    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(settings, "social_storyboard_max_shots", 12)

    async def fake_load_source(cid, st, **k):
        return ("Roof 101", "We fix roofs.", {"type": "topic"})

    async def fake_voice(client, user_id=None):
        return ({}, "VOICE", "CTX")

    monkeypatch.setattr(creator, "load_source", fake_load_source)
    monkeypatch.setattr(creator, "resolve_voice_context", fake_voice)
    monkeypatch.setattr(creator, "_client_row", lambda cid: {"id": cid, "name": "Acme"})
    monkeypatch.setattr(creator, "source_version_of", lambda t: "ver123")
    monkeypatch.setattr(competitor_research, "latest_signals_for_client", lambda cid: [])
    monkeypatch.setattr(competitor_research, "render_competitor_signals_block", lambda s: "")
    monkeypatch.setattr(gbp_posts_service, "voice_forbidden_hits", lambda text, card: [])

    async def fake_forced_tool(**k):
        return {
            "title": "Roof restoration in 30s",
            "hook": "Your roof is older than you think",
            "shots": [{"visual": "Drone shot"}, {"visual": "Owner to camera"}],
            "caption": "See how we restored this roof.",
            "hashtags": ["roofing"],
            "cta": "Book now",
        }

    monkeypatch.setattr(report_llm, "run_forced_tool", fake_forced_tool)
    store: dict = {}
    monkeypatch.setattr(storyboard, "_sb", lambda: _fake_sb(store))

    req = SimpleNamespace(
        platform="instagram", source_type="topic", source_id=None, url=None,
        text="roof restoration", angle="myth-bust", tone=None, format="reel",
    )
    row = await storyboard.generate_storyboard("c1", req, user_id="u1")

    assert row["platform"] == "instagram"
    assert row["format"] == "reel"
    assert row["status"] == "generated"
    assert row["title"] == "Roof restoration in 30s"
    assert row["source_version"] == "ver123"
    assert row["storyboard"]["hook"] == "Your roof is older than you think"
    assert len(row["storyboard"]["shots"]) == 2
    assert row["voice_warnings"] is None
    # exactly one insert into the storyboards table
    assert [t for t, _ in store.get("inserts", [])] == ["social_storyboards"]


@pytest.mark.asyncio
async def test_generate_storyboard_rejects_bad_platform(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", True)
    req = SimpleNamespace(
        platform="linkedin", source_type="topic", source_id=None, url=None,
        text="x", angle=None, tone=None, format="reel",
    )
    with pytest.raises(HTTPException) as ei:
        await storyboard.generate_storyboard("c1", req)
    assert ei.value.status_code == 422
    assert ei.value.detail == "social_storyboard_bad_platform"


@pytest.mark.asyncio
async def test_generate_storyboard_disabled_503(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", False)
    req = SimpleNamespace(
        platform="instagram", source_type="topic", source_id=None, url=None,
        text="x", angle=None, tone=None, format="reel",
    )
    with pytest.raises(HTTPException) as ei:
        await storyboard.generate_storyboard("c1", req)
    assert ei.value.status_code == 503


# ── impure: CRUD ──────────────────────────────────────────────────────────────

def test_get_storyboard_404(monkeypatch):
    monkeypatch.setattr(storyboard, "_sb", lambda: _fake_sb({"rows": {"social_storyboards": []}}))
    with pytest.raises(HTTPException) as ei:
        storyboard.get_storyboard("nope")
    assert ei.value.status_code == 404


def test_update_storyboard_only_changes_present_fields(monkeypatch):
    store = {"rows": {"social_storyboards": [{"id": "s1", "title": "old"}]}}
    monkeypatch.setattr(storyboard, "_sb", lambda: _fake_sb(store))
    storyboard.update_storyboard("s1", title="new", thumbnail_url="https://cdn/x.png")
    updates = [f for t, f in store["updates"] if t == "social_storyboards"]
    assert updates and updates[0]["title"] == "new"
    assert updates[0]["thumbnail_url"] == "https://cdn/x.png"
    assert "storyboard" not in updates[0]   # not provided → untouched


def test_delete_storyboard_archives(monkeypatch):
    store = {"rows": {"social_storyboards": [{"id": "s1"}]}}
    monkeypatch.setattr(storyboard, "_sb", lambda: _fake_sb(store))
    assert storyboard.delete_storyboard("s1") == {"ok": True}
    updates = [f for t, f in store["updates"] if t == "social_storyboards"]
    assert updates and updates[0]["status"] == "archived"


# ── pure: render_storyboard_markdown (slice a.1 — Doc export) ──────────────────

def test_render_storyboard_markdown_full():
    row = {
        "platform": "instagram", "format": "reel", "title": "Roof in 30s", "angle": "myth-bust",
        "source_title": "Roof 101",
        "voice_warnings": ["forbidden_term:cheapest"],
        "storyboard": {
            "hook": "Your roof is older than you think", "duration_seconds": 30,
            "shots": [
                {"visual": "Drone shot", "on_screen_text": "Before", "duration_seconds": 3, "b_roll": True},
                {"visual": "Owner to camera", "voiceover": "We restore, not replace."},
                {"visual": ""},   # empty → skipped
            ],
            "music": "upbeat acoustic", "caption": "See the restore.",
            "hashtags": ["roofing", "#RoofRestoration"], "cta": "Book a free inspection",
        },
    }
    title, md = storyboard.render_storyboard_markdown(row)
    assert title == "Roof in 30s"
    assert md.startswith("# Roof in 30s")
    assert "**Instagram · Reel · ~30s**" in md
    assert "_Angle: myth-bust_" in md
    assert "## Hook" in md and "older than you think" in md
    assert "1. **Drone shot** (b-roll, ~3s)" in md
    assert "   - On-screen text: Before" in md
    assert "2. **Owner to camera**" in md
    assert "   - Voiceover: We restore, not replace." in md
    assert "Owner to camera**\n" in md  # the empty-visual shot was dropped (only 2 shots)
    assert "## Music / audio" in md and "upbeat acoustic" in md
    assert "## Caption" in md and "See the restore." in md
    assert "#roofing #RoofRestoration" in md          # leading # normalized, both present
    assert "**Call to action:** Book a free inspection" in md
    assert "_Source: Roof 101_" in md
    assert "Brand-voice advisory:" in md and "forbidden_term:cheapest" in md


def test_render_storyboard_markdown_minimal_omits_empty_sections():
    title, md = storyboard.render_storyboard_markdown(
        {"platform": "youtube", "format": "short",
         "storyboard": {"hook": "Hook only", "shots": [{"visual": "Just one shot"}]}}
    )
    assert title == "Video storyboard"          # no title/source_title → default
    assert "## Hook" in md and "## Shot list" in md
    assert "## Music" not in md and "## Caption" not in md
    assert "Call to action:" not in md and "Brand-voice advisory:" not in md


# ── impure: export_storyboard_doc ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_storyboard_doc_happy_path(monkeypatch):
    import services.google_docs as gd

    store = {"rows": {
        "social_storyboards": [{"id": "s1", "client_id": "c1", "platform": "instagram",
                                "format": "reel", "title": "T",
                                "storyboard": {"hook": "H", "shots": [{"visual": "V"}]}}],
        "clients": [{"id": "c1", "name": "Acme", "google_drive_folder_id": "folder-1",
                     "drive_folders": None}],
    }}
    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(storyboard, "_sb", lambda: _fake_sb(store))

    calls = {}

    async def _fake_create(folder_id, doc_title, content, **kw):
        calls.update(folder_id=folder_id, title=doc_title, content=content, kw=kw)
        return {"doc_id": "d1", "doc_url": "https://docs/x", "reused": False}

    monkeypatch.setattr(gd, "create_google_doc", _fake_create)

    out = await storyboard.export_storyboard_doc("c1", "s1")
    assert out == {"doc_id": "d1", "doc_url": "https://docs/x", "reused": False}
    assert calls["folder_id"] == "folder-1"
    assert calls["kw"]["content_format"] == "markdown" and calls["kw"]["dedupe_by_name"] is True
    assert "# T" in calls["content"]
    updates = [f for t, f in store["updates"] if t == "social_storyboards"]
    assert updates and updates[0]["doc_url"] == "https://docs/x"


@pytest.mark.asyncio
async def test_export_storyboard_doc_missing_folder_422(monkeypatch):
    store = {"rows": {
        "social_storyboards": [{"id": "s1", "client_id": "c1", "storyboard": {"hook": "H", "shots": []}}],
        "clients": [{"id": "c1", "name": "Acme", "google_drive_folder_id": None, "drive_folders": None}],
    }}
    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(storyboard, "_sb", lambda: _fake_sb(store))
    with pytest.raises(HTTPException) as ei:
        await storyboard.export_storyboard_doc("c1", "s1")
    assert ei.value.status_code == 422 and ei.value.detail == "missing_google_drive_folder_id"


@pytest.mark.asyncio
async def test_export_storyboard_doc_client_mismatch_404(monkeypatch):
    store = {"rows": {"social_storyboards": [{"id": "s1", "client_id": "OTHER",
                                              "storyboard": {"hook": "H", "shots": []}}]}}
    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(storyboard, "_sb", lambda: _fake_sb(store))
    with pytest.raises(HTTPException) as ei:
        await storyboard.export_storyboard_doc("c1", "s1")
    assert ei.value.status_code == 404
