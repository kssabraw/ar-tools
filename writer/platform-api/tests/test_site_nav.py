"""Unit tests for services.site_nav — pure nav-menu service-label extraction."""

from __future__ import annotations

from services import site_nav

_MENU = """
<header>
  <a href="/">Acme Roofing</a>
  <nav class="main-menu">
    <ul>
      <li><a href="/">Home</a></li>
      <li><a href="/about-us/">About Us</a></li>
      <li class="has-children"><a href="/services/">Services</a>
        <ul class="sub-menu">
          <li><a href="/roof-restoration/">Roof Restoration</a></li>
          <li><a href="/gutter-cleaning/">Gutter Cleaning</a></li>
          <li><a href="https://acmeroofing.com/roof-repointing/">Roof Repointing</a></li>
        </ul>
      </li>
      <li><a href="/service-areas/">Service Areas</a>
        <ul><li><a href="/melbourne/">Melbourne</a></li></ul></li>
      <li><a href="/blog/">Blog</a></li>
      <li><a href="/contact/">Contact</a></li>
      <li><a href="tel:1300123456">1300 123 456</a></li>
      <li><a href="mailto:hi@acme.com">Email</a></li>
      <li><a href="https://facebook.com/acme">Facebook</a></li>
      <li><a href="/get-a-quote/">Get a Quote</a></li>
    </ul>
  </nav>
</header>
"""


def test_base_domain():
    assert site_nav._base_domain("https://www.acmeroofing.com.au/x") == "acmeroofing.com.au"
    assert site_nav._base_domain("http://acme.com") == "acme.com"
    assert site_nav._base_domain("acme.com/path") == "acme.com"
    assert site_nav._base_domain("/relative") == ""


def test_is_internal():
    assert site_nav._is_internal("/roofing/", "acme.com") is True
    assert site_nav._is_internal("https://acme.com/roofing/", "acme.com") is True
    assert site_nav._is_internal("https://www.acme.com/roofing/", "acme.com") is True
    assert site_nav._is_internal("https://blog.acme.com/x/", "acme.com") is True  # subdomain
    assert site_nav._is_internal("https://facebook.com/acme", "acme.com") is False
    assert site_nav._is_internal("#top", "acme.com") is False
    assert site_nav._is_internal("mailto:x@acme.com", "acme.com") is False
    assert site_nav._is_internal("tel:123", "acme.com") is False
    assert site_nav._is_internal("/", "acme.com") is False  # bare home
    # No base domain known → keep relative only, drop absolute (can't verify).
    assert site_nav._is_internal("/roofing/", "") is True
    assert site_nav._is_internal("https://acme.com/roofing/", "") is False


def test_nav_service_labels_keeps_services_drops_chrome_place_and_external():
    labels = site_nav.nav_service_labels(
        _MENU, "acmeroofing.com", place_tokens=frozenset({"melbourne"})
    )
    assert labels == ["Roof Restoration", "Gutter Cleaning", "Roof Repointing"]
    # everything else was filtered
    for junk in ("Home", "About Us", "Services", "Service Areas", "Melbourne",
                 "Blog", "Contact", "Get a Quote", "Facebook"):
        assert junk not in labels


def test_nav_service_labels_dedupes_case_insensitively_preserving_first_casing():
    html = """
    <nav>
      <a href="/roof-restoration/">Roof Restoration</a>
      <a href="/roof-restoration-2/">ROOF restoration</a>
      <a href="/painting/">Painting</a>
    </nav>"""
    assert site_nav.nav_service_labels(html, "acme.com") == ["Roof Restoration", "Painting"]


def test_nav_service_labels_caps():
    links = "".join(f'<a href="/s{i}/">Service Alpha {i}</a>' for i in range(40))
    html = f"<nav>{links}</nav>"
    out = site_nav.nav_service_labels(html, "acme.com", cap=5)
    assert len(out) == 5


def test_nav_service_labels_empty_and_malformed():
    assert site_nav.nav_service_labels("", "acme.com") == []
    assert site_nav.nav_service_labels("<nav></nav>", "acme.com") == []
    # a JS-only nav (no anchors rendered) yields nothing, not an error
    assert site_nav.nav_service_labels("<div id='root'></div>", "acme.com") == []


def test_nav_falls_back_to_header_only_when_no_menu_container():
    # No <nav>/role/menu-class container → header anchors are read.
    html = """
    <header>
      <a href="/">Home</a>
      <a href="/plumbing/">Plumbing</a>
      <a href="/drain-cleaning/">Drain Cleaning</a>
    </header>"""
    assert site_nav.nav_service_labels(html, "acme.com") == ["Plumbing", "Drain Cleaning"]


def test_nav_prefers_menu_container_over_header_noise():
    # A real menu exists → the header's phone/CTA strip is NOT scraped as services.
    html = """
    <header>
      <a href="/">Logo</a>
      <a href="/get-a-quote/">Get a Quote</a>
      <nav class="primary-nav">
        <a href="/roofing/">Roofing</a>
        <a href="/siding/">Siding</a>
      </nav>
    </header>"""
    assert site_nav.nav_service_labels(html, "acme.com") == ["Roofing", "Siding"]


def test_nav_drops_phone_and_email_shaped_labels():
    html = """
    <nav>
      <a href="/call/">Call 555 123 4567</a>
      <a href="/hvac/">HVAC Repair</a>
    </nav>"""
    assert site_nav.nav_service_labels(html, "acme.com") == ["HVAC Repair"]


def test_nav_drops_pure_place_labels_via_place_tokens():
    html = """
    <nav>
      <a href="/inner-west/">Inner West</a>
      <a href="/electrical/">Electrical</a>
      <a href="/electrical-inner-west/">Electrical Inner West</a>
    </nav>"""
    labels = site_nav.nav_service_labels(
        html, "acme.com", place_tokens=frozenset({"inner", "west"})
    )
    # "Inner West" is pure place → dropped; a service that merely mentions the
    # place still carries a service token → kept.
    assert labels == ["Electrical", "Electrical Inner West"]


def test_extract_nav_links_returns_label_href_pairs():
    html = '<nav><a href="/roofing/">Roofing</a><a href="#">Skip</a></nav>'
    assert site_nav.extract_nav_links(html, "acme.com") == [("Roofing", "/roofing/")]
