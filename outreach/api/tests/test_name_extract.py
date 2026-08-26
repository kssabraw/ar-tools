"""Golden cases for the owner/manager name extractor. These pin the ANTI-FABRICATION bar.

The extractor's whole value is that it does NOT invent a name — so most of these are rejections:
the business name masquerading as a person, nav chrome, a bare Title-Case phrase with no role,
a staff member who isn't ownership. The acceptances are the shapes a real local-business site uses
to name its owner. Independent of the implementation — computed from the spec, not read back from
the code (the golden-fixture discipline)."""

from api.services import name_extract as ne


def _names(html, business_name=None):
    return [n.full_name for n in ne.extract_names(html, business_name=business_name)]


# --- is_plausible_name (the guard, unit) -----------------------------------------------------


def test_a_two_token_titlecase_name_is_plausible():
    assert ne.is_plausible_name("John Smith", business_tokens=frozenset())


def test_a_single_token_is_not_a_name():
    assert not ne.is_plausible_name("John", business_tokens=frozenset())


def test_nav_chrome_is_rejected():
    assert not ne.is_plausible_name("Contact Us", business_tokens=frozenset())
    assert not ne.is_plausible_name("Our Team", business_tokens=frozenset())


def test_a_trade_phrase_is_rejected():
    assert not ne.is_plausible_name("Emergency Plumbing", business_tokens=frozenset())
    assert not ne.is_plausible_name("Family Owned", business_tokens=frozenset())


def test_the_business_name_is_rejected_one_directional():
    biz = ne._business_tokens("Acme Plumbing Services")
    # "Acme Plumbing" is entirely business tokens → not a person.
    assert not ne.is_plausible_name("Acme Plumbing", business_tokens=biz)
    # A real person sharing ONE token (a founder named after the business) still passes.
    assert ne.is_plausible_name("Acme Johnson", business_tokens=biz)


def test_a_role_word_inside_the_name_is_rejected():
    assert not ne.is_plausible_name("Owner Operated", business_tokens=frozenset())
    assert not ne.is_plausible_name("Managing Director", business_tokens=frozenset())


# --- text patterns: acceptances --------------------------------------------------------------


def test_name_comma_role():
    assert _names("<p>John Smith, Owner</p>") == ["John Smith"]


def test_name_dash_role():
    assert _names("<p>Jane A. Doe — Founder &amp; CEO</p>") == ["Jane A. Doe"]


def test_role_colon_name():
    assert _names("<div>Owner: Robert Brown</div>") == ["Robert Brown"]


def test_meet_our_role_name():
    assert _names("<h2>Meet our founder, Maria Garcia</h2>") == ["Maria Garcia"]


def test_name_is_the_role():
    assert _names("<p>Kevin O'Neil is the owner of the shop.</p>") == ["Kevin O'Neil"]


def test_strong_role_then_name():
    assert _names("<span>Owner Sarah Lee</span>") == ["Sarah Lee"]


def test_the_stored_title_is_canonical():
    got = ne.extract_names("<p>Tom Hardy, co-owner</p>")
    assert got and got[0].title == "Co-Owner"


# --- text patterns: rejections (the anti-fabrication core) -----------------------------------


def test_a_bare_titlecase_phrase_with_no_role_yields_nothing():
    assert _names("<h1>Reliable Plumbing Solutions</h1><p>Serving Los Angeles since 1998.</p>") == []


def test_a_weak_role_needs_punctuation_not_a_loose_prose_hit():
    # "manager" is not a strong role, so "...manager Bob discussed..." must NOT fire the loose form.
    assert _names("<p>Our project manager Bob discussed the timeline.</p>") == []


def test_president_and_ceo_do_not_fire_the_loose_form():
    # These name people of OTHER entities all over ordinary prose — the bare "<role> <Name>" byline
    # is withheld for them (they still fire on punctuated forms, tested below).
    assert _names("<p>As President Joe Biden noted, small businesses matter.</p>") == []
    assert _names("<p>CEO Tim Cook praised the design.</p>") == []
    assert _names("<p>Principal Jane Doe spoke at the school.</p>") == []


def test_president_still_fires_on_a_punctuated_byline():
    # The real way a business page credits them — kept.
    assert _names("<p>Jane Doe, President</p>") == ["Jane Doe"]
    assert _names("<div>President: Robert King</div>") == ["Robert King"]


def test_the_business_is_not_extracted_as_a_person():
    html = "<p>Acme Plumbing, proudly owner operated since 1995.</p>"
    assert _names(html, business_name="Acme Plumbing") == []


def test_a_testimonial_name_is_not_an_owner():
    # No role anchor → nothing, even though "Great work! — Dave Wilson" carries a real name.
    assert _names("<blockquote>Great service! — Dave Wilson, Happy Customer</blockquote>") == []


def test_tags_do_not_fuse_adjacent_words():
    # <b>John</b> Smith must read as "John Smith", not "JohnSmith".
    assert _names("<p><b>John</b> Smith, Owner</p>") == ["John Smith"]


# --- JSON-LD ---------------------------------------------------------------------------------


def test_jsonld_founder():
    html = """
    <script type="application/ld+json">
    {"@type":"LocalBusiness","name":"Acme Plumbing",
     "founder":{"@type":"Person","name":"Bill Murphy"}}
    </script>"""
    got = ne.extract_names(html, business_name="Acme Plumbing")
    assert [n.full_name for n in got] == ["Bill Murphy"]
    assert got[0].title == "Founder" and got[0].source_kind == "jsonld"


def test_jsonld_employee_needs_an_ownership_jobtitle():
    html = """
    <script type="application/ld+json">
    {"@type":"Organization","name":"Acme",
     "employee":[{"@type":"Person","name":"Ann Reid","jobTitle":"General Manager"},
                 {"@type":"Person","name":"Joe Fox","jobTitle":"Plumber"}]}
    </script>"""
    got = {n.full_name: n.title for n in ne.extract_names(html)}
    assert got == {"Ann Reid": "General Manager"}  # the plumber is not surfaced


def test_jsonld_upgrades_a_text_hit_provenance():
    html = """
    <p>Bill Murphy, Owner</p>
    <script type="application/ld+json">
    {"@type":"Person","name":"Bill Murphy","jobTitle":"Owner"}
    </script>"""
    got = ne.extract_names(html)
    assert len(got) == 1 and got[0].source_kind == "jsonld"


def test_malformed_jsonld_is_ignored_not_raised():
    html = '<script type="application/ld+json">{ not json </script><p>Lee Park, Owner</p>'
    assert _names(html) == ["Lee Park"]


# --- merge / dedup ---------------------------------------------------------------------------


def test_dedup_across_the_same_page():
    html = "<p>John Smith, Owner</p><footer>Owner: John Smith</footer>"
    assert _names(html) == ["John Smith"]


def test_merge_preserves_order_and_dedups():
    home = ne.extract_names("<p>Amy Cole, Owner</p>")
    about = ne.extract_names("<p>Amy Cole, Owner</p><p>Ben Diaz, Manager</p>")
    merged = ne.merge_names(home, about)
    assert [n.full_name for n in merged] == ["Amy Cole", "Ben Diaz"]


def test_empty_and_none_are_safe():
    assert ne.extract_names(None) == []
    assert ne.extract_names("") == []
    assert ne.extract_names("<p>no people here, just text</p>") == []


def test_first_and_last_name_split():
    got = ne.extract_names("<p>Maria Garcia Lopez, Owner</p>")[0]
    assert got.first_name == "Maria" and got.last_name == "Lopez"
