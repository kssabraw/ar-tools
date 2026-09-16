"""Unit tests for the site claim index (Topic-Vector P1 grounding corpus).

Pure extraction / merge / freshness helpers only — no network, no Supabase. The
discovery + scrape + cache round-trips are best-effort I/O covered by
integration testing.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import site_claim_index as s  # noqa: E402


_SPEC_TEXT = (
    "Buy GLP-3RT for $90.00 today. Purity is >=99% by HPLC on every batch. "
    "CAS 2381089-83-2 is documented. Molecular weight 4731.3 Da. "
    "Formula C221H342N46O68. Store at -20 C for stability. "
    "Available in 10mg, 30mg and 50mg vials. "
    "Every batch ships with a Certificate of Analysis."
)


def test_extract_facts_pulls_typed_number_entities():
    facts = s.extract_facts(_SPEC_TEXT.replace(">=", "≥"), "u1")
    by_type = {f["type"]: f for f in facts}
    assert by_type["price"]["value"] == "90.00"
    assert by_type["purity"]["value"] == "99"
    assert by_type["cas"]["value"] == "2381089-83-2"
    assert by_type["molecular_weight"]["value"] == "4731.3"
    assert by_type["molecular_formula"]["value"] == "C221H342N46O68"
    assert by_type["storage_temp"]["value"] == "-20"
    assert by_type["coa"]["value"] == "present"
    sizes = sorted(f["value"] for f in facts if f["type"] == "size")
    assert sizes == ["10", "30", "50"]
    assert all(f["url"] == "u1" for f in facts)


def test_extract_facts_purity_needs_context():
    # A bare percentage with no purity/HPLC context is NOT a purity fact.
    facts = s.extract_facts("Save 50% off your first order.", "u")
    assert not any(f["type"] == "purity" for f in facts)


def test_extract_claims_keeps_fact_bearing_only():
    text = ("GLP-3RT ships in 10mg vials at $90 with a verified COA. "
            "We genuinely care about your research and success. "
            "Purity is confirmed at 99% by mass spec on every batch.")
    claims = [c["text"] for c in s.extract_claims(text, "u")]
    assert any("10mg" in c for c in claims)
    assert any("99%" in c for c in claims)
    assert not any("genuinely care" in c for c in claims)  # no fact signal → dropped


def test_merge_index_dedupes_and_caps():
    p1 = {"facts": [{"type": "price", "value": "90", "unit": "USD"}],
          "claims": [{"text": "a claim with 10mg", "url": "u1"}]}
    p2 = {"facts": [{"type": "price", "value": "90", "unit": "USD"},   # dup
                    {"type": "purity", "value": "99", "unit": "%"}],
          "claims": [{"text": "A claim with 10mg", "url": "u2"},        # dup (norm)
                     {"text": "another 5mg claim", "url": "u2"}]}
    merged = s.merge_index([p1, p2], max_facts=10, max_claims=10)
    assert len(merged["facts"]) == 2            # price deduped
    assert len(merged["claims"]) == 2           # first-seen kept, dup dropped
    capped = s.merge_index([p1, p2], max_facts=1, max_claims=1)
    assert len(capped["facts"]) == 1 and len(capped["claims"]) == 1


def test_html_to_text_strips_chrome():
    html = ("<nav>Home Shop Cart</nav><header>logo</header>"
            "<main><p>GLP-3RT is 99% pure by HPLC.</p></main>"
            "<script>var x=1;</script><footer>© 2026</footer>")
    text = s.html_to_text(html).lower()
    assert "glp-3rt is 99% pure" in text
    assert "cart" not in text and "var x" not in text and "2026" not in text


def test_is_fresh():
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    fresh = (now - timedelta(days=5)).isoformat()
    stale = (now - timedelta(days=40)).isoformat()
    assert s.is_fresh(fresh, 30, now=now)
    assert not s.is_fresh(stale, 30, now=now)
    assert not s.is_fresh(None, 30, now=now)          # missing → stale
    assert not s.is_fresh(fresh, 0, now=now)          # ttl 0 → always stale
    assert not s.is_fresh("not-a-date", 30, now=now)  # unparseable → stale


def test_cache_row_shape():
    row = s.cache_row("cid", "https://x.com/", {"facts": [1], "claims": [2]},
                      "sitemap", 4, note="")
    assert row["client_id"] == "cid" and row["source"] == "sitemap"
    assert row["url_count"] == 4 and row["facts"] == [1] and row["claims"] == [2]
    assert row["note"] is None                        # empty note → NULL
    assert row["fetched_at"] == "now()"


def test_index_is_thin():
    assert s.index_is_thin(None, 3)
    assert s.index_is_thin({"claims": ["one"], "facts": []}, 3)   # <3 claims, no facts
    assert not s.index_is_thin({"claims": ["a", "b", "c"], "facts": []}, 3)
    assert not s.index_is_thin({"claims": [], "facts": [{"type": "cas"}]}, 3)  # a fact grounds
