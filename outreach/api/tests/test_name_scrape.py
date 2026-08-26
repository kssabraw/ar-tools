"""The name-scrape producer: page selection, the bounded crawl, and measured-vs-found.

The pure name extraction is tested in `test_name_extract`; here the subject is the fetch
orchestration — which internal pages get followed, that a failed homepage is `unreachable` (not
"no owner"), and that names merge across pages. `fetch` is stubbed throughout (no egress)."""

import asyncio

from api.services import name_scrape
from api.services.scan_tech import (
    STATUS_BLOCKED,
    STATUS_OK,
    STATUS_UNREACHABLE,
    FetchResult,
)


class _Settings:
    name_scrape_max_pages = 4
    name_scrape_max_names = 8
    name_scrape_fetch_timeout_seconds = 12.0
    name_scrape_max_page_bytes = 1_000_000
    name_scrape_concurrency = 4
    name_scrape_chunk_size = 4


def _fetch_map(pages: dict[str, FetchResult]):
    # Key by canonical form so a trailing slash / root path never causes a spurious miss.
    canon = {name_scrape._canonical(k): v for k, v in pages.items()}

    async def fetch(url: str) -> FetchResult:
        return canon.get(name_scrape._canonical(url), FetchResult(STATUS_UNREACHABLE, url, ""))

    return fetch


# --- candidate_links -------------------------------------------------------------------------


def test_candidate_links_matches_hints_same_host_priority_ordered():
    html = """
      <a href="/about-us">About Us</a>
      <a href="/services">Our Services</a>
      <a href="https://acme.com/our-team/">The Team</a>
      <a href="https://other.com/about">Off-site About</a>
      <a href="mailto:info@acme.com">Email</a>
      <a href="/contact">Contact</a>
    """
    links = name_scrape.candidate_links(html, "https://acme.com/", max_links=10)
    # same-host hint pages only, off-site + non-hint + mailto dropped
    assert "https://acme.com/about-us" in links
    assert "https://acme.com/our-team" in links  # trailing slash normalised away
    assert "https://acme.com/contact" in links
    assert all("other.com" not in u for u in links)
    assert all("/services" not in u for u in links)
    # "about" outranks "contact" (earlier hint) so it comes first
    assert links.index("https://acme.com/about-us") < links.index("https://acme.com/contact")


def test_candidate_links_excludes_the_homepage_and_caps():
    html = '<a href="/">Home</a><a href="/about">About</a><a href="/team">Team</a>'
    links = name_scrape.candidate_links(html, "https://acme.com/", max_links=1)
    assert links == ["https://acme.com/about"]  # homepage dropped, capped to 1, about first


def test_candidate_links_dedups():
    html = '<a href="/about">About</a><a href="/about/">About again</a>'
    links = name_scrape.candidate_links(html, "https://acme.com/", max_links=10)
    assert links == ["https://acme.com/about"]


# --- scrape_one ------------------------------------------------------------------------------


def test_no_website_returns_none():
    got = asyncio.run(
        name_scrape.scrape_one({"id": "p1", "website": None}, _Settings(), fetch=_fetch_map({}))
    )
    assert got is None


def test_unreachable_homepage_is_unreachable_not_no_names():
    fetch = _fetch_map({"https://acme.com": FetchResult(STATUS_BLOCKED, "https://acme.com", "")})
    got = asyncio.run(
        name_scrape.scrape_one(
            {"id": "p1", "name": "Acme", "website": "acme.com"}, _Settings(), fetch=fetch
        )
    )
    assert got.status == "unreachable" and got.fetch_status == STATUS_BLOCKED
    assert got.names == () and got.pages_fetched == 0


def test_homepage_name_is_found():
    fetch = _fetch_map(
        {"https://acme.com": FetchResult(STATUS_OK, "https://acme.com", "<p>Jane Doe, Owner</p>")}
    )
    got = asyncio.run(
        name_scrape.scrape_one(
            {"id": "p1", "name": "Acme", "website": "acme.com"}, _Settings(), fetch=fetch
        )
    )
    assert got.status == "found"
    assert [n.full_name for n in got.names] == ["Jane Doe"]


def test_the_owner_is_found_on_a_followed_about_page():
    """Homepage names nobody; the About page carries the owner — the whole reason for the crawl."""
    pages = {
        "https://acme.com": FetchResult(
            STATUS_OK, "https://acme.com",
            '<h1>Acme Plumbing</h1><a href="/about">About Us</a>',
        ),
        "https://acme.com/about": FetchResult(
            STATUS_OK, "https://acme.com/about", "<p>Meet our founder, Bill Murphy.</p>"
        ),
    }
    got = asyncio.run(
        name_scrape.scrape_one(
            {"id": "p1", "name": "Acme Plumbing", "website": "acme.com"},
            _Settings(), fetch=_fetch_map(pages),
        )
    )
    assert got.status == "found"
    assert [n.full_name for n in got.names] == ["Bill Murphy"]
    assert got.pages_fetched == 2


def test_the_crawl_is_bounded_by_max_pages():
    settings = _Settings()
    settings.name_scrape_max_pages = 2  # homepage + 1 follow
    fetched: list[str] = []

    async def fetch(url):
        fetched.append(name_scrape._canonical(url))
        if url.rstrip("/") == "https://acme.com":
            return FetchResult(
                STATUS_OK, "https://acme.com",
                '<a href="/about">About</a><a href="/team">Team</a><a href="/contact">Contact</a>',
            )
        return FetchResult(STATUS_OK, url, "<p>nobody here</p>")

    asyncio.run(
        name_scrape.scrape_one(
            {"id": "p1", "name": "Acme", "website": "acme.com"}, settings, fetch=fetch
        )
    )
    assert len(fetched) == 2  # homepage + exactly one followed page


# --- scrape_names batch ----------------------------------------------------------------------


def test_scrape_names_isolates_a_per_prospect_failure():
    async def fetch(url):
        if "boom" in url:
            raise RuntimeError("kaboom")
        return FetchResult(STATUS_OK, url, "<p>Amy Cole, Owner</p>")

    prospects = [
        {"id": "p1", "name": "A", "website": "acme.com"},
        {"id": "p2", "name": "B", "website": "boom.com"},
        {"id": "p3", "name": "C", "website": None},  # skipped, neither result nor error
    ]
    results, errors = asyncio.run(name_scrape.scrape_names(_Settings(), prospects, fetch=fetch))
    assert {r.prospect_id for r in results} == {"p1"}
    assert len(errors) == 1 and errors[0].startswith("p2:")
