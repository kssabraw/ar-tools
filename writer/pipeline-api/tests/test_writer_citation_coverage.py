"""Step 4F.1 — Citable-Claim Detection + Coverage (Writer PRD §4F.1, R7 + Phase 4)."""

from __future__ import annotations

import pytest

from modules.writer.citation_coverage import (
    apply_soften,
    coverage_for_body,
    coverage_retry_directive,
    detect_citable_claims,
)


# ---------------------------------------------------------------------------
# C1 — percentage / percent / pct
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body,expected_count", [
    ("HVAC efficiency improved 27% year over year.", 1),
    ("Adoption rose 12 percent annually.", 1),
    ("Pct gain was 8 pct in Q3.", 1),
    ("This added 15 percentage points to retention.", 1),
    ("Two stats: 27% growth then 12% drop.", 1),  # one sentence with multiple
    ("No numbers here.", 0),
])
def test_c1_percent_detection(body, expected_count):
    matches = detect_citable_claims(body)
    assert len(matches) == expected_count


# ---------------------------------------------------------------------------
# C2 — currency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    "TikTok Shop surpassed $100 million in sales.",
    "Reported $1.2 billion USD in revenue.",
    "Investment totaled €50 million.",
    "Series B was $25M.",
    "Funding hit £20bn last quarter.",
])
def test_c2_currency_detection(body):
    matches = detect_citable_claims(body)
    assert len(matches) >= 1


# ---------------------------------------------------------------------------
# C3 — year as date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body,expected_count", [
    ("Launched in 2023 to broad acclaim.", 1),
    ("Since 2024 the product has shipped widely.", 1),
    ("By 2025 most sellers will adopt it.", 1),
    ("As of 2026 the program is mature.", 1),
    # Negative cases — bare numbers without date context
    ("Model 2024X has updated specs.", 0),
    ("Order number 2024 is in queue.", 0),
])
def test_c3_year_detection(body, expected_count):
    matches = detect_citable_claims(body)
    assert len(matches) == expected_count


# ---------------------------------------------------------------------------
# C4 / C5 — source-attribution / "studies show"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    "According to Forbes the market is shifting.",
    "McKinsey reports that adoption is accelerating.",
    "Pew survey found that most users agree.",
])
def test_c4_attribution_detection(body):
    matches = detect_citable_claims(body)
    assert len(matches) == 1


@pytest.mark.parametrize("body", [
    "Studies show that adoption peaks early.",
    "Research indicates broad consensus.",
    "Data shows strong momentum.",
    "Analysts predict steady growth.",
])
def test_c5_studies_show_detection(body):
    matches = detect_citable_claims(body)
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# C6 — entity + quantitative qualifier
# ---------------------------------------------------------------------------


def test_c6_entity_with_year():
    """Entity (from SIE list) + year qualifier → C6 fires."""
    matches = detect_citable_claims(
        "TikTok Shop launched in 2023.",
        entities=["TikTok Shop"],
    )
    assert len(matches) == 1
    assert "C6" in matches[0].pattern_ids
    assert "C3" in matches[0].pattern_ids


def test_c6_entity_without_qualifier_no_match():
    """Entity alone without quantitative qualifier → C6 does NOT fire."""
    matches = detect_citable_claims(
        "TikTok Shop is popular among Gen Z creators.",
        entities=["TikTok Shop"],
    )
    # No C1/C2/C3 trigger → C6 doesn't fire either
    assert len(matches) == 0


def test_c6_no_entity_list_skips():
    """Empty entity list → C6 never fires (even with qualifier)."""
    matches = detect_citable_claims(
        "TikTok Shop launched in 2023.",
        entities=[],
    )
    # C3 alone still fires
    assert len(matches) == 1
    assert "C6" not in matches[0].pattern_ids


# ---------------------------------------------------------------------------
# C7 — Duration-as-recommendation (NEW in Phase 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    "Schedule a 4-to-6 week refresh cadence for new listings.",
    "Set a 60-day affiliate audit window before renewal.",
    "Use a 90-minute review cycle for content QA.",
    "Plan for a 2-week sprint cooldown between releases.",
    "Maintain a 30-day grace period for refunds.",
])
def test_c7_duration_detection(body):
    matches = detect_citable_claims(body)
    assert len(matches) == 1
    assert "C7" in matches[0].pattern_ids
    assert matches[0].is_operational is True


def test_c7_simple_duration_no_recommendation_does_not_match():
    """A bare duration without a recommendation noun shouldn't match C7."""
    matches = detect_citable_claims("The shipment took 4 weeks.")
    # No `cadence`/`window`/etc. → C7 doesn't fire
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# C8 — Frequency-as-recommendation (NEW in Phase 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    "Run an inventory check every 7 days.",
    "Schedule a monthly audit of supplier performance.",
    "Conduct a weekly review with the fulfillment team.",
    "Adopt a quarterly refresh of category artwork.",
    "Run a daily check on order status.",
])
def test_c8_frequency_detection(body):
    matches = detect_citable_claims(body)
    assert len(matches) == 1
    assert "C8" in matches[0].pattern_ids
    assert matches[0].is_operational is True


def test_c8_bare_frequency_word_no_match():
    """`weekly` without a recommendation noun shouldn't match C8."""
    matches = detect_citable_claims("This happens weekly across the platform.")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# C9 — Operational-percentage (NEW in Phase 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body,expected_pids", [
    ("Aim for 30% conversion improvements per cohort.", {"C9"}),
    ("Apply the 5% rule to discount budgeting.", {"C1", "C9"}),
    ("Set a 20% threshold for cart abandonment alerts.", {"C1", "C9"}),
    ("Keep within a 15% cap on returns.", {"C1", "C9"}),
])
def test_c9_operational_percentage_detection(body, expected_pids):
    matches = detect_citable_claims(body)
    assert len(matches) == 1
    assert expected_pids.issubset(set(matches[0].pattern_ids))
    assert matches[0].is_operational is True


# ---------------------------------------------------------------------------
# Coverage + threshold
# ---------------------------------------------------------------------------


def test_coverage_counts_cited_when_marker_present():
    body = (
        "TikTok Shop seller revenue rose 27% YoY.{{cit_001}} "
        "Adoption keeps accelerating each month."
    )
    cov = coverage_for_body(body)
    assert cov.citable_claims == 1
    assert cov.cited_claims == 1
    assert cov.ratio == 1.0


def test_coverage_under_threshold_when_no_markers():
    body = (
        "TikTok Shop seller revenue rose 27% YoY. "
        "Reported $100M total sales last quarter."
    )
    cov = coverage_for_body(body)
    assert cov.citable_claims == 2
    assert cov.cited_claims == 0
    assert cov.ratio == 0.0


def test_coverage_partial():
    body = (
        "TikTok Shop seller revenue rose 27% YoY.{{cit_001}} "
        "Reported $100M total sales last quarter."
    )
    cov = coverage_for_body(body)
    assert cov.citable_claims == 2
    assert cov.cited_claims == 1
    assert cov.ratio == 0.5


def test_coverage_empty_body():
    cov = coverage_for_body("")
    assert cov.citable_claims == 0
    # Empty bodies have 100% coverage by convention (no citable claims to fail).
    assert cov.ratio == 1.0


# ---------------------------------------------------------------------------
# Auto-soften — C7/C8/C9 only
# ---------------------------------------------------------------------------


def test_soften_duration_window():
    body = "Schedule a 4-to-6 week refresh cadence for new listings."
    softened, replacements = apply_soften(body)
    assert softened != body
    assert "every few weeks" in softened
    assert "4-to-6 week refresh cadence" not in softened
    assert len(replacements) == 1
    assert replacements[0].rule == "duration-as-recommendation"


def test_soften_frequency():
    body = "Conduct a weekly review with the fulfillment team."
    softened, replacements = apply_soften(body)
    assert softened != body
    assert "regular review" in softened
    assert len(replacements) == 1
    assert replacements[0].rule == "frequency-as-recommendation"


def test_soften_operational_percentage():
    body = "Apply the 5% rule to discount budgeting."
    softened, replacements = apply_soften(body)
    assert softened != body
    assert "5%" not in softened
    assert "small percentage rule" in softened
    assert len(replacements) == 1
    assert replacements[0].rule == "operational-percentage"


def test_soften_does_not_touch_c1_c6_claims():
    """C1 (percent stat), C2 (currency), C3 (year), C4 (source attribution),
    C5 (studies show) MUST NOT be softened — they're statistics/years/
    source-attributed facts where softening would mangle the claim more
    than help it."""
    cases = [
        "TikTok Shop revenue rose 27% YoY.",  # C1 alone
        "Investment totaled $100M.",  # C2
        "Launched in 2023.",  # C3
        "According to Forbes the market shifted.",  # C4
        "Studies show adoption rose.",  # C5
    ]
    for body in cases:
        softened, replacements = apply_soften(body)
        assert softened == body, f"Expected no soften for {body!r}"
        assert replacements == []


def test_soften_handles_multiple_rules_in_one_body():
    body = (
        "Use a 4-week refresh cadence "
        "and run a weekly audit. "
        "Aim for 30% improvements."
    )
    softened, replacements = apply_soften(body)
    assert "4-week refresh cadence" not in softened
    assert "weekly audit" not in softened
    # 30% should be softened by C9
    assert "30%" not in softened
    assert len(replacements) >= 3


def test_soften_empty_body():
    softened, replacements = apply_soften("")
    assert softened == ""
    assert replacements == []


# ---------------------------------------------------------------------------
# coverage_retry_directive — prompt construction
# ---------------------------------------------------------------------------


def test_coverage_retry_directive_lists_uncited():
    body = (
        "TikTok Shop seller revenue rose 27% YoY. "
        "Reported $100M total sales last quarter."
    )
    cov = coverage_for_body(body)
    directive = coverage_retry_directive(cov, ["cit_001", "cit_002"])
    assert "27%" in directive or "$100M" in directive
    assert "cit_001" in directive
    assert "cit_002" in directive
    assert "below 50%" in directive


def test_coverage_retry_directive_handles_no_pool():
    """When no citation pool is available, the directive instructs
    rewriting to remove the claim instead of inventing IDs."""
    body = "Aim for 30% improvements quarterly."
    cov = coverage_for_body(body)
    directive = coverage_retry_directive(cov, [])
    assert "rewrite to remove" in directive.lower()


def test_coverage_retry_directive_empty_when_all_cited():
    body = "Revenue rose 27%.{{cit_001}}"
    cov = coverage_for_body(body)
    directive = coverage_retry_directive(cov, ["cit_001"])
    assert directive == ""


# ---------------------------------------------------------------------------
# Audit failure-case regression
# ---------------------------------------------------------------------------


def test_audit_unsourced_operational_claims_detected():
    """The audit's "4-to-6 week refresh cadence" + "60-day affiliate
    audit window" — both stated as fact without citations — must be
    detected as citable C7 claims."""
    body = (
        "Sellers should adopt a 4-to-6 week refresh cadence for top "
        "products. Maintain a 60-day affiliate audit window before "
        "the next campaign."
    )
    cov = coverage_for_body(body)
    assert cov.citable_claims == 2
    assert cov.cited_claims == 0
    operational_count = sum(1 for m in cov.matches if m.is_operational)
    assert operational_count == 2


def test_audit_unsourced_operational_claims_softened():
    """When the LLM retry can't add citations to those claims, the
    auto-soften pass rewrites them to hedge phrasing."""
    body = (
        "Sellers should adopt a 4-to-6 week refresh cadence. "
        "Maintain a 60-day affiliate audit window."
    )
    softened, replacements = apply_soften(body)
    assert "4-to-6 week refresh cadence" not in softened
    assert "60-day affiliate audit window" not in softened
    assert "every few weeks" in softened
    # 60-day window scales as "couple of months" per the soften table
    assert "couple of months" in softened or "brief window" in softened
    assert len(replacements) == 2
