"""Unit tests for the Keyword Research audience-fit filter's pure logic."""

from services import keyword_research_audience as aud


def test_is_job_seeker_matches_employment_terms():
    assert aud.is_job_seeker("insurance adjuster salary")
    assert aud.is_job_seeker("claims adjuster jobs")
    assert aud.is_job_seeker("how to become an insurance adjuster")
    assert aud.is_job_seeker("independent adjuster careers")
    assert aud.is_job_seeker("entry level claims adjuster jobs")


def test_is_job_seeker_leaves_buyer_terms():
    assert not aud.is_job_seeker("third party claims administration")
    assert not aud.is_job_seeker("independent adjusting firm")
    assert not aud.is_job_seeker("catastrophe claims management")


def test_is_job_seeker_catches_live_bsa_near_misses():
    # Career/student phrasings that leaked through as "buyer" on a live BSA run.
    assert aud.is_job_seeker("how much does an independent claims adjuster make")
    assert aud.is_job_seeker("how to be an independent claims adjuster")
    assert aud.is_job_seeker("ia firms that hire new adjusters")
    assert aud.is_job_seeker("claims adjuster exam practice questions")
    assert aud.is_job_seeker("how to get licensed as an adjuster")


def test_salary_pattern_does_not_catch_buyer_cost_question():
    # "how much does X cost" is a BUYER question — must stay buyer.
    assert not aud.is_job_seeker("how much does a tpa cost")
    assert not aud.is_job_seeker("how much does claims outsourcing cost")


def test_guard_keeps_seed_noun_with_discriminator():
    # When the seed noun IS the wrong-audience anchor, an off-term that adds a
    # discriminator ("adjuster license") is kept; the bare noun is still dropped.
    seeds = ["third party claims administration", "independent claims adjuster"]
    g = aud.guard_off_terms(
        ["adjuster license", "adjuster school", "adjuster", "claims adjuster", "license"], seeds)
    assert "adjuster license" in g and "adjuster school" in g and "license" in g
    assert "adjuster" not in g and "claims adjuster" not in g


def test_is_job_seeker_word_boundary_no_false_hit():
    # "jobsite" should not match "jobs" (word boundary).
    assert not aud.is_job_seeker("construction jobsite claims")


def test_classify_audience_precedence():
    off = aud._phrase_regex(["public adjuster"])
    assert aud.classify_audience("adjuster salary", off) == "job_seeker"   # js wins
    assert aud.classify_audience("public adjuster cost", off) == "off_audience"
    assert aud.classify_audience("third party administrator", off) == "buyer"


def test_apply_audience_drops_and_tags():
    rows = [
        {"keyword": "insurance adjuster salary"},
        {"keyword": "third party claims administration"},
        {"keyword": "public adjuster cost"},
        {"keyword": "catastrophe claims outsourcing"},
    ]
    kept, report = aud.apply_audience(rows, off_audience_terms=["public adjuster"])
    kw = {r["keyword"] for r in kept}
    assert kw == {"third party claims administration", "catastrophe claims outsourcing"}
    assert all(r["audience_fit"] == "buyer" for r in kept)
    assert report["dropped_job_seeker"] == 1
    assert report["dropped_off_audience"] == 1
    assert report["gate"] == "audience"


def test_apply_audience_drop_false_keeps_all_but_tags():
    rows = [{"keyword": "adjuster salary"}, {"keyword": "tpa services"}]
    kept, report = aud.apply_audience(rows, drop=False)
    assert len(kept) == 2
    tags = {r["keyword"]: r["audience_fit"] for r in kept}
    assert tags["adjuster salary"] == "job_seeker"
    assert tags["tpa services"] == "buyer"


def test_guard_off_terms_strips_seed_colliding_terms():
    # A mis-returned "claims" would nuke the whole run — the guard drops it.
    safe = aud.guard_off_terms(
        ["public adjuster", "claims", "license"],
        ["third party claims administration"])
    assert "claims" not in safe
    assert "public adjuster" in safe and "license" in safe


def test_guard_off_terms_no_seeds_keeps_all():
    assert aud.guard_off_terms(["a", "b"], []) == ["a", "b"]
