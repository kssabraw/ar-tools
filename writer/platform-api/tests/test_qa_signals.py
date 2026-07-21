"""Unit tests for the QA Agent's pure signal layer (services/qa_signals.py).

Every rule from docs/sops/QA_Checklists.md that the deterministic layer
encodes: rubric routing (incl. the owner's skip/handoff rulings), NAP
normalization + matching, the GBP-post / press-release / map-embed / blog /
website-page check builders, sheet CSV URL extraction, the deterministic
sample spread, and the verdict fold (fail > needs_human > pass; fail-open on
unverifiable blocking checks).
"""

from services import qa_signals as sig


# ---------------------------------------------------------------------------
# Rubric routing
# ---------------------------------------------------------------------------
def _task(name, source=None, library=None, description=None):
    return {"name": name, "source": source, "library_task_name": library,
            "description": description}


def test_rubric_routing_owner_rulings():
    assert sig.rubric_for(_task("GBP Blast")) == sig.RUBRIC_SKIP
    assert sig.rubric_for(_task("HyperLocal GBP Blast")) == sig.RUBRIC_SKIP
    assert sig.rubric_for(_task("Blog Post Scheduling")) == sig.RUBRIC_SKIP
    assert sig.rubric_for(_task("Service Silo")) == sig.RUBRIC_HANDOFF
    assert sig.rubric_for(_task("SEO NEO Task")) == sig.RUBRIC_GENERIC


def test_rubric_routing_checkable_types():
    assert sig.rubric_for(_task("GBP Posts")) == sig.RUBRIC_GBP_POSTS
    assert sig.rubric_for(_task("(4) Citations")) == sig.RUBRIC_CITATIONS
    assert sig.rubric_for(_task("Guest Posts")) == sig.RUBRIC_GUEST_POST
    assert sig.rubric_for(_task("Niche Edits")) == sig.RUBRIC_NICHE_EDIT
    assert sig.rubric_for(_task("Press Release")) == sig.RUBRIC_PRESS_RELEASE
    assert sig.rubric_for(_task("Map Embeds")) == sig.RUBRIC_MAP_EMBEDS
    assert sig.rubric_for(_task("Website Pages Posted")) == sig.RUBRIC_PAGE


def test_rubric_explicit_override_wins():
    # An explicit qa_rubric (the dropdown) beats name-matching AND the
    # content_run producer, so the title can be anything.
    t = _task("Coral Springs practice-management page")
    t["qa_rubric"] = sig.RUBRIC_PAGE
    assert sig.rubric_for(t) == sig.RUBRIC_PAGE
    t2 = _task("Review & publish: roof repair", source="content_run")
    t2["qa_rubric"] = sig.RUBRIC_SKIP
    assert sig.rubric_for(t2) == sig.RUBRIC_SKIP
    # An empty / unknown explicit value falls back to the name rules.
    t3 = _task("Website Pages Posted")
    t3["qa_rubric"] = ""
    assert sig.rubric_for(t3) == sig.RUBRIC_PAGE
    t4 = _task("Website Pages Posted")
    t4["qa_rubric"] = "not_a_real_rubric"
    assert sig.rubric_for(t4) == sig.RUBRIC_PAGE
    # RUBRIC_KEYS covers every rubric constant.
    assert sig.RUBRIC_PAGE in sig.RUBRIC_KEYS and sig.RUBRIC_SKIP in sig.RUBRIC_KEYS


def test_rubric_routing_producer_and_library_precedence():
    # A content_run producer task is a blog article no matter its name.
    assert sig.rubric_for(_task("Review & publish: roof repair", source="content_run")) == sig.RUBRIC_BLOG
    # library_task_name wins over a renamed task.
    assert sig.rubric_for(_task("July batch", library="GBP Posts")) == sig.RUBRIC_GBP_POSTS
    # Unknown type → generic (needs_human downstream, never guessed).
    assert sig.rubric_for(_task("Mystery deliverable")) == sig.RUBRIC_GENERIC
    # "Blog Post Scheduling" must not be swallowed by the "blog post" rule.
    assert sig.rubric_for(_task("Blog Post Scheduling")) == sig.RUBRIC_SKIP


# ---------------------------------------------------------------------------
# NAP normalization + matching (cross-cutting #4)
# ---------------------------------------------------------------------------
def test_normalize_phone_formats():
    assert sig.normalize_phone("+1 (555) 010-2000") == "5550102000"
    assert sig.normalize_phone("555.010.2000") == "5550102000"
    assert sig.normalize_phone("1-555-010-2000") == "5550102000"
    assert sig.normalize_phone(None) == ""


def test_nap_match_abbreviations_and_formats():
    page = ("Contact Acme Roofing at 123 Main St, Springfield. "
            "Call (555) 010-2000 today!")
    nap = sig.nap_match(page, "Acme Roofing", "123 Main Street, Springfield", "+1 555 010 2000")
    assert nap["name"] is True
    assert nap["phone"] is True
    assert nap["address"] is True
    assert nap["matched"] is True


def test_nap_match_wrong_phone_but_address_ok_still_matches():
    page = "Acme Roofing — 123 Main St, Springfield."
    nap = sig.nap_match(page, "Acme Roofing", "123 Main Street Springfield", "555 999 8888")
    assert nap["phone"] is False and nap["address"] is True
    assert nap["matched"] is True  # name + one located field


def test_nap_match_name_missing_fails():
    page = "Call 555 010 2000 at 123 Main St."
    nap = sig.nap_match(page, "Acme Roofing", "123 Main Street", "555 010 2000")
    assert nap["name"] is False and nap["matched"] is False


def test_nap_match_nothing_on_card_is_unverifiable():
    nap = sig.nap_match("any page text", None, None, None)
    assert nap["matched"] is None


# ---------------------------------------------------------------------------
# GBP posts (keyword + CTA + emoji, all blocking)
# ---------------------------------------------------------------------------
def test_gbp_post_all_present_passes():
    text = "Need roof repair in Springfield? 🏠 Call us today for a free estimate!"
    checks = sig.check_gbp_post(text, "roof repair")
    assert sig.build_verdict(checks)["verdict"] == sig.PASS


def test_gbp_post_missing_emoji_fails():
    text = "Need roof repair? Call us today for a free estimate!"
    v = sig.build_verdict(sig.check_gbp_post(text, "roof repair"))
    assert v["verdict"] == sig.FAIL
    assert any("emoji" in f.lower() for f in v["failed"])


def test_gbp_post_unknown_keyword_needs_human():
    text = "Great post 🏠 — call now!"
    v = sig.build_verdict(sig.check_gbp_post(text, None))
    assert v["verdict"] == sig.NEEDS_HUMAN


# ---------------------------------------------------------------------------
# Link-back (guest posts / niche edits)
# ---------------------------------------------------------------------------
def test_link_back_present_and_absent():
    html = '<p>Read more at <a href="https://www.acme.com/roof">Acme</a>.</p>'
    assert sig.build_verdict(sig.check_link_back(html, "acme.com"))["verdict"] == sig.PASS
    html2 = '<p>No links to the client here. <a href="https://other.com">x</a></p>'
    assert sig.build_verdict(sig.check_link_back(html2, "acme.com"))["verdict"] == sig.FAIL


def test_link_back_no_domain_on_file_is_unverifiable():
    assert sig.check_link_back("<p>hi</p>", "")[0]["ok"] is None


# ---------------------------------------------------------------------------
# Press release (corrected logic: bounce if ANY of the four fail)
# ---------------------------------------------------------------------------
_PR_HTML = """
<html><head><title>Acme Roofing brings emergency roof repair to Springfield</title></head>
<body><p>Acme Roofing announced expanded emergency roof repair services.</p>
<p>Located at 123 Main St, Springfield — call (555) 010-2000.</p>
<p><a href="https://acme.com/emergency">the company's emergency services page</a></p>
</body></html>
"""


def test_press_release_all_four_pass():
    checks = sig.check_press_release(
        _PR_HTML, "emergency roof repair", "Acme Roofing",
        "123 Main Street Springfield", "555 010 2000", client_domain="acme.com",
    )
    assert sig.build_verdict(checks)["verdict"] == sig.PASS


def test_press_release_exact_match_anchor_only_fails():
    html = _PR_HTML.replace(
        "the company's emergency services page", "emergency roof repair"
    )
    checks = sig.check_press_release(
        html, "emergency roof repair", "Acme Roofing",
        "123 Main Street Springfield", "555 010 2000", client_domain="acme.com",
    )
    v = sig.build_verdict(checks)
    assert v["verdict"] == sig.FAIL
    assert any("anchor" in f.lower() for f in v["failed"])


def test_press_release_nap_missing_fails():
    html = """<html><head><title>emergency roof repair news</title></head>
    <body><p>emergency roof repair by someone.</p>
    <a href="https://acme.com/x">read about their services</a></body></html>"""
    checks = sig.check_press_release(
        html, "emergency roof repair", "Acme Roofing",
        "123 Main Street", "555 010 2000", client_domain="acme.com",
    )
    v = sig.build_verdict(checks)
    assert v["verdict"] == sig.FAIL
    assert any("nap" in f.lower() for f in v["failed"])


# ---------------------------------------------------------------------------
# Map embeds
# ---------------------------------------------------------------------------
def test_map_embed_detection():
    assert sig.has_map_embed('<iframe src="https://www.google.com/maps/embed?pb=..."></iframe>')
    assert not sig.has_map_embed("<p>no embed</p>")


def test_map_embed_page_checks_fold_assertion():
    html = ('<p>Acme Roofing provides roof repair in Springfield. '
            '123 Main St — (555) 010-2000</p>'
            '<iframe src="https://www.google.com/maps/embed?pb=1"></iframe>')
    checks = sig.check_map_embed_page(
        html, "Acme Roofing", "123 Main Street", "555 010 2000",
        assertion_ok=True, assertion_note="found",
    )
    assert sig.build_verdict(checks)["verdict"] == sig.PASS
    # Judge unavailable → fail-open needs_human, never a bounce.
    checks2 = sig.check_map_embed_page(
        html, "Acme Roofing", "123 Main Street", "555 010 2000",
        assertion_ok=None, assertion_note="judge unavailable",
    )
    assert sig.build_verdict(checks2)["verdict"] == sig.NEEDS_HUMAN


# ---------------------------------------------------------------------------
# Blog article markdown checks
# ---------------------------------------------------------------------------
_GOOD_BLOG = """
Intro paragraph answering the question directly.

## Key Takeaways

- point one

## How it works

Some body copy with an [external source](https://example.org/study).

## Get started

Contact us today for a free consultation.
"""


def test_blog_markdown_good_passes():
    v = sig.build_verdict(sig.check_blog_markdown(_GOOD_BLOG, "roof repair"))
    assert v["verdict"] == sig.PASS


def test_blog_markdown_missing_takeaways_and_dup_headings_fail():
    bad = _GOOD_BLOG.replace("## Key Takeaways", "## How it works")
    v = sig.build_verdict(sig.check_blog_markdown(bad))
    assert v["verdict"] == sig.FAIL
    labels = " ".join(v["failed"]).lower()
    assert "key takeaways" in labels and "duplicate" in labels


def test_blog_markdown_long_paragraph_is_advisory_not_blocking():
    long_para = "word " * 200
    md = _GOOD_BLOG + "\n\n" + long_para
    v = sig.build_verdict(sig.check_blog_markdown(md))
    assert v["verdict"] == sig.PASS
    assert any("length" in a.lower() for a in v["advisories"])


# ---------------------------------------------------------------------------
# Website page checks
# ---------------------------------------------------------------------------
def test_website_page_checks():
    html = """<html><head><title>Roof Repair Springfield | Acme</title>
    <meta name="description" content="Expert roof repair."></head>
    <body><h1>Roof Repair Springfield</h1>
    <img src="x.jpg" alt="roof"><a href="https://acme.com/contact">contact</a>
    <p>Acme Roofing serves Springfield.</p></body></html>"""
    v = sig.build_verdict(sig.check_website_page(
        html, "acme.com", "Acme Roofing",
        keyword="roof repair springfield",
        url="https://acme.com/roof-repair-springfield/",
    ))
    assert v["verdict"] == sig.PASS


def test_website_page_missing_meta_title_fails_but_description_is_advisory():
    # No title, no meta description, no H1. Meta title is still blocking (fails);
    # meta description is now advisory (owner ruling) — it must NOT appear as a
    # blocking failure.
    html = "<html><body><a href='https://acme.com/x'>x</a><img src='a.jpg' alt='a'></body></html>"
    checks = sig.check_website_page(html, "acme.com", "Acme",
                                    keyword="roofing", url="https://acme.com/x")
    v = sig.build_verdict(checks)
    assert v["verdict"] == sig.FAIL
    labels = " ".join(v["failed"]).lower()
    assert "meta title" in labels
    assert "meta description" not in labels
    md = next(c for c in checks if c["key"] == "meta_description")
    assert md["blocking"] is False and md["ok"] is False


def test_website_page_meta_description_optional():
    # Everything present except the meta description → still passes (advisory).
    html = """<html><head><title>Practice Management Coral Springs</title></head>
    <body><h1>Practice Management Coral Springs</h1>
    <img src="x.jpg" alt="x"><a href="https://myihbs.com/contact">contact</a></body></html>"""
    checks = sig.check_website_page(
        html, "myihbs.com", None,
        keyword="practice management coral springs",
        url="https://www.myihbs.com/coral-springs/practice-management-coral-springs/",
    )
    assert sig.build_verdict(checks)["verdict"] == sig.PASS


def test_website_page_keyword_placement_blocking():
    # Keyword in title + H1 but NOT in the URL slug → blocking fail on the URL.
    html = """<html><head><title>Emergency Plumber Miami</title></head>
    <body><h1>Emergency Plumber Miami</h1><a href="https://acme.com/x">x</a>
    <img src="a.jpg" alt="a"></body></html>"""
    checks = sig.check_website_page(
        html, "acme.com", None,
        keyword="emergency plumber miami", url="https://acme.com/services/plumbing/",
    )
    by = {c["key"]: c for c in checks}
    assert by["keyword_in_title"]["ok"] is True
    assert by["keyword_in_h1"]["ok"] is True
    assert by["keyword_in_url"]["ok"] is False
    assert sig.build_verdict(checks)["verdict"] == sig.FAIL


def test_website_page_keyword_unknown_needs_human():
    # No keyword on the task → the three placement checks read 'could not verify'
    # → needs_human (never a guess), everything else being fine.
    html = """<html><head><title>Some Page</title></head>
    <body><h1>Some Page</h1><a href="https://acme.com/x">x</a>
    <img src="a.jpg" alt="a"></body></html>"""
    checks = sig.check_website_page(html, "acme.com", None, keyword=None, url="https://acme.com/x")
    by = {c["key"]: c for c in checks}
    assert by["keyword_in_title"]["ok"] is None
    assert by["keyword_in_url"]["ok"] is None
    assert by["keyword_in_h1"]["ok"] is None
    assert sig.build_verdict(checks)["verdict"] == sig.NEEDS_HUMAN


def test_keyword_in_url():
    assert sig.keyword_in_url(
        "https://x.com/practice-management-services-in-coral-springs/",
        "practice management services") is True
    assert sig.keyword_in_url("https://x.com/about/", "roof repair") is False
    assert sig.keyword_in_url("https://x.com/x", None) is None
    assert sig.keyword_in_url(None, "roofing") is None


# ---------------------------------------------------------------------------
# Sheets, URLs, sampling, task conventions
# ---------------------------------------------------------------------------
def test_sheet_id_and_export_url():
    sid = sig.sheet_id_of("https://docs.google.com/spreadsheets/d/abc123XYZ_-/edit#gid=0")
    assert sid == "abc123XYZ_-"
    assert sig.sheet_csv_export_url(sid).endswith("/export?format=csv")
    assert sig.sheet_id_of("https://example.com/notasheet") is None


def test_urls_from_sheet_csv_header_column():
    csv_text = (
        "Directory,Live URL,Notes\n"
        "Yelp,https://yelp.com/biz/acme,ok\n"
        "YP,https://yellowpages.com/acme,ok\n"
    )
    assert sig.urls_from_sheet_csv(csv_text) == [
        "https://yelp.com/biz/acme", "https://yellowpages.com/acme",
    ]


def test_urls_from_sheet_csv_fallback_best_column():
    csv_text = (
        "a,b\n"
        "one,https://x.com/1\n"
        "two,https://x.com/2\n"
    )
    assert sig.urls_from_sheet_csv(csv_text) == ["https://x.com/1", "https://x.com/2"]


def test_sample_spread_deterministic():
    items = list(range(10))
    assert sig.sample_spread(items, 3) == [0, 4, 9] or sig.sample_spread(items, 3) == [0, 5, 9]
    assert sig.sample_spread(items, 3) == sig.sample_spread(items, 3)  # stable
    assert sig.sample_spread([1, 2], 3) == [1, 2]
    assert sig.sample_spread([], 3) == []


def test_extract_urls_dedup_and_trailing_punct():
    text = "See https://a.com/x, then https://a.com/x and https://b.com."
    assert sig.extract_urls(text) == ["https://a.com/x", "https://b.com"]


def test_keyword_from_task_name_convention():
    # Owner convention: the keyword is entered into the task NAME.
    assert sig.keyword_from_task(
        {"name": "GBP Posts — emergency roof repair", "library_task_name": "GBP Posts"}
    ) == "emergency roof repair"
    assert sig.keyword_from_task(
        {"name": "Press Release: new location launch", "library_task_name": "Press Release"}
    ) == "new location launch"
    # Fully renamed task — the library link says the type, the name IS the keyword.
    assert sig.keyword_from_task(
        {"name": "emergency roof repair", "library_task_name": "GBP Posts"}
    ) == "emergency roof repair"
    # Bare template name → no keyword (checks read "could not verify").
    assert sig.keyword_from_task(
        {"name": "GBP Posts", "library_task_name": "GBP Posts"}
    ) is None
    # No library link: separator split still works (e.g. producer task names).
    assert sig.keyword_from_task({"name": "Review & publish: roof repair"}) == "roof repair"
    assert sig.keyword_from_task({"name": "GBP Posts"}) is None
    assert sig.keyword_from_task({}) is None


def test_keyword_from_task_description_override_still_wins():
    assert sig.keyword_from_task(
        {"name": "GBP Posts — wrong thing", "library_task_name": "GBP Posts",
         "description": "Keyword: roof repair\nNotes: x"}
    ) == "roof repair"
    assert sig.keyword_from_task({"description": "keywords - emergency plumber"}) == "emergency plumber"


def test_keyword_from_task_kw_marker_in_description_or_title():
    # Short 'KW:' form is accepted (description).
    assert sig.keyword_from_task({"description": "KW: practice management coral springs"}) \
        == "practice management coral springs"
    assert sig.keyword_from_task({"description": "kw - blocked drain sydney"}) == "blocked drain sydney"
    # The marker is also honoured anywhere in the TASK NAME/title.
    assert sig.keyword_from_task({"name": "Coral Springs page  KW: practice management services"}) \
        == "practice management services"
    assert sig.keyword_from_task({"name": "Keyword: emergency plumber brisbane"}) \
        == "emergency plumber brisbane"
    # Description marker still wins over a name marker.
    assert sig.keyword_from_task(
        {"description": "KW: roof restoration", "name": "KW: wrong keyword"}
    ) == "roof restoration"
    # A name with a plain separator (no marker) still uses the template split —
    # 'kw'/'keyword' must be present to trigger the marker path, so this is
    # unaffected.
    assert sig.keyword_from_task({"name": "Review & publish: roof repair"}) == "roof repair"
    assert sig.keyword_from_task(
        {"name": "GBP Posts — emergency roof repair", "library_task_name": "GBP Posts"}
    ) == "emergency roof repair"


def test_deliverable_subtask_name_matches_and_is_not_work_item():
    from services.task_service import is_work_item

    assert sig.is_deliverable_subtask("Deliverable links")
    assert sig.is_deliverable_subtask("  deliverable  LINKS ")
    assert not sig.is_deliverable_subtask("Write the page")
    # Must never count as a work item (would break auto-advance Rule B).
    assert not is_work_item("Deliverable links")


# ---------------------------------------------------------------------------
# Verdict fold
# ---------------------------------------------------------------------------
def test_build_verdict_precedence_fail_over_unknown():
    checks = [
        sig._check("a", "A", False),
        sig._check("b", "B", None),
        sig._check("c", "C", True),
    ]
    assert sig.build_verdict(checks)["verdict"] == sig.FAIL


def test_build_verdict_unknown_blocking_is_needs_human():
    checks = [sig._check("a", "A", None), sig._check("b", "B", True)]
    assert sig.build_verdict(checks)["verdict"] == sig.NEEDS_HUMAN


def test_build_verdict_advisory_failures_still_pass():
    checks = [sig._check("a", "A", True), sig._check("b", "B", False, blocking=False)]
    v = sig.build_verdict(checks)
    assert v["verdict"] == sig.PASS and v["advisories"]


# ---------------------------------------------------------------------------
# Rework-subtask dedupe (hardening #1) + "Rework:" prefix (review fix B)
# ---------------------------------------------------------------------------
def test_new_rework_names_dedupes_open_fixes():
    failed = ["NAP included", "A CTA is present"]
    existing_open = ["Rework: NAP included", "Write the page"]
    assert sig.new_rework_names(failed, existing_open) == ["Rework: A CTA is present"]


def test_new_rework_names_case_and_whitespace_insensitive():
    assert sig.new_rework_names(["NAP included"], ["rEWORK:   nap  included"]) == []


def test_new_rework_names_completed_fix_recreated():
    # A ticked fix is NOT in the open list, so a regression re-creates it.
    assert sig.new_rework_names(["NAP included"], []) == ["Rework: NAP included"]


# ---------------------------------------------------------------------------
# Adversarial-review fixes (2026-07-12)
# ---------------------------------------------------------------------------
def test_rework_subtasks_are_work_items():
    """Fix B: the QA-fail rework prefix must be 'Rework:' (a work item), NOT
    'QA fix:' — 'qa' trips the marker classifier and breaks the re-QA loop."""
    from services.task_service import is_work_item

    for label in ("NAP included", "Link back to the client's site", "Meta title present"):
        assert is_work_item(f"Rework: {label}") is True
        # The old buggy prefix would have been a marker (not a work item):
        assert is_work_item(f"QA fix: {label}") is False


def test_links_to_domain_www_prefix_only():
    """Fix C: strip a 'www.' prefix, not a {w,.} character set — a domain
    starting with 'w' must survive."""
    anchors = [{"href": "https://westroofing.com/roof", "text": "x"},
               {"href": "https://other.com", "text": "y"}]
    assert sig.links_to_domain(anchors, "westroofing.com") == [anchors[0]]
    assert sig.links_to_domain(anchors, "www.westroofing.com") == [anchors[0]]
    # No spurious match against an unrelated domain.
    assert sig.links_to_domain([{"href": "https://estroofing.com", "text": "z"}], "westroofing.com") == []


def test_has_map_embed_precedence():
    """Fix D: a bare 'maps.google' mention without an iframe is NOT an embed."""
    assert sig.has_map_embed('<iframe src="https://www.google.com/maps/embed?pb=1"></iframe>')
    # "maps.google" + an iframe anywhere → embed (the second, and-guarded clause).
    assert sig.has_map_embed('see maps.google.com <iframe src="x"></iframe>') is True
    # A plain text mention of maps.google with NO iframe → not an embed (this is
    # what the operator-precedence fix guarantees).
    assert sig.has_map_embed("visit us on maps.google.com/place/x") is False


def test_urls_from_sheet_csv_headerless_keeps_row0():
    """Fix E: a headerless sheet whose first row already holds a URL must not
    lose that first URL."""
    csv_text = "https://a.com/1\nhttps://a.com/2\nhttps://a.com/3"
    urls = sig.urls_from_sheet_csv(csv_text)
    assert urls == ["https://a.com/1", "https://a.com/2", "https://a.com/3"]
    # A real header row (labels, no URLs) is still skipped.
    csv2 = "Live URL,Notes\nhttps://a.com/1,ok\nhttps://a.com/2,ok"
    assert sig.urls_from_sheet_csv(csv2) == ["https://a.com/1", "https://a.com/2"]


# ---------------------------------------------------------------------------
# Gathering-only detection (skips the narrative LLM call)
# ---------------------------------------------------------------------------
def test_gathering_only_true_for_missing_deliverable():
    checks = [sig._check("deliverable", "Deliverable link(s) located", None,
                         note="no deliverable URLs on the task")]
    assert sig.gathering_only(checks) is True


def test_gathering_only_false_for_real_quality_findings():
    # A genuine failed check → the narrative SHOULD run.
    assert sig.gathering_only([sig._check("nap", "NAP included", False)]) is False
    # A quality check that couldn't be verified (not a locator) → still narrate.
    assert sig.gathering_only([sig._check("nap", "NAP included", None)]) is False
    # Mixed: locator unverified + a real failure → narrate.
    checks = [
        sig._check("page", "Page reachable", None),
        sig._check("cta", "A CTA is present", False),
    ]
    assert sig.gathering_only(checks) is False
    assert sig.gathering_only([]) is False


# ---------------------------------------------------------------------------
# Google Doc (draft container) detection
# ---------------------------------------------------------------------------
def test_is_google_doc_url():
    assert sig.is_google_doc_url("https://docs.google.com/document/d/abc123/edit")
    assert sig.is_google_doc_url("https://docs.google.com/presentation/d/x/edit")
    # Sheets are the deliverable-LIST container — handled separately, not a doc.
    assert not sig.is_google_doc_url("https://docs.google.com/spreadsheets/d/abc/edit")
    assert not sig.is_google_doc_url("https://example.com/press-release")
    assert not sig.is_google_doc_url(None)
