"""The web-search name parser + producer. The subject is the ANTI-FABRICATION guard: a web-searched
name is the lowest-trust source, so it is kept ONLY with a real citation AND only if it passes the
same business-name/stopword plausibility guard as the site-scrape. Most cases here are drops."""

import asyncio

from api.services import name_search


def _names(text, citations=(), business_name="Acme Plumbing"):
    return name_search.parse_search_answer(text, list(citations), business_name=business_name)


# --- parse_search_answer: the require-citation guard ------------------------------------------


def test_a_cited_plausible_name_is_kept():
    got = _names('{"found": true, "name": "John Smith", "title": "Owner", '
                 '"source_url": "https://example.com/about"}')
    assert len(got) == 1
    assert got[0].full_name == "John Smith" and got[0].title == "Owner"
    assert got[0].citation == "https://example.com/about"
    assert got[0].first_name == "John" and got[0].last_name == "Smith"


def test_an_uncited_name_is_dropped():
    # found + a name but NO source_url and NO citation annotations → dropped (the whole guard).
    assert _names('{"found": true, "name": "John Smith", "source_url": null}') == []
    assert _names('{"found": true, "name": "John Smith"}', citations=[]) == []


def test_a_url_citation_annotation_rescues_a_missing_source_url():
    got = _names('{"found": true, "name": "John Smith", "source_url": null}',
                 citations=["https://directory.example/john-smith"])
    assert len(got) == 1 and got[0].citation == "https://directory.example/john-smith"


def test_a_non_http_source_url_is_not_a_citation():
    assert _names('{"found": true, "name": "John Smith", "source_url": "not a url"}') == []


def test_found_false_is_empty():
    assert _names('{"found": false, "name": null, "source_url": null}') == []


def test_a_null_or_missing_name_is_empty():
    assert _names('{"found": true, "name": null, "source_url": "https://x.com"}') == []
    assert _names('{"found": true, "source_url": "https://x.com"}') == []


def test_the_business_name_is_not_returned_as_a_person():
    # is_plausible_name (shared with the site-scrape) rejects the business masquerading as a person.
    assert _names('{"found": true, "name": "Acme Plumbing", "source_url": "https://x.com"}',
                  business_name="Acme Plumbing") == []


def test_json_wrapped_in_prose_or_fences_is_extracted():
    assert len(_names('Here is what I found:\n```json\n'
                      '{"found": true, "name": "Jane Doe", "source_url": "https://x.com/jane"}\n```')) == 1


def test_malformed_output_is_empty_not_raised():
    assert _names("not json at all") == []
    assert _names("") == []


# --- extract_output: OpenAI Responses shape ---------------------------------------------------


def test_extract_output_reads_text_and_url_citations():
    output = [
        {"type": "message", "content": [
            {"type": "output_text", "text": "The owner is Jane Doe.",
             "annotations": [{"type": "url_citation", "url": "https://x.com/jane"}]},
        ]},
    ]
    text, cites = name_search.extract_output(output)
    assert "Jane Doe" in text and cites == ["https://x.com/jane"]


def test_extract_output_tolerates_junk():
    assert name_search.extract_output([]) == ("", [])
    assert name_search.extract_output([{"foo": "bar"}, "nope"]) == ("", [])


# --- producer (stubbed web search) ------------------------------------------------------------


class _Settings:
    openai_api_key = "sk-test"
    name_search_model = "gpt-5.4"
    name_search_web_search_tool = "web_search"
    name_search_request_timeout_seconds = 120.0
    name_search_chunk_size = 4
    name_search_max_names = 2


def _stub_search(monkeypatch, by_id):
    async def _openai_web_search(settings, prompt, *, client=None):
        # crude: find which prospect this prompt is for by its name appearing in the prompt
        for pid, (text, cites) in by_id.items():
            if pid in prompt:
                return text, cites
        return "", []

    monkeypatch.setattr(name_search, "_openai_web_search", _openai_web_search)


def test_search_owner_name_found(monkeypatch):
    async def _openai_web_search(settings, prompt, *, client=None):
        return '{"found": true, "name": "Bob Lee", "title": "Owner", "source_url": "https://x.com/bob"}', []
    monkeypatch.setattr(name_search, "_openai_web_search", _openai_web_search)

    got = asyncio.run(name_search.search_owner_name(
        {"id": "p1", "name": "Acme Plumbing", "address": "123 Main St", "website": "acme.com"},
        _Settings()))
    assert got.status == "found" and [n.full_name for n in got.names] == ["Bob Lee"]
    assert "https://x.com/bob" in got.citations


def test_search_owner_name_no_names_when_uncited(monkeypatch):
    async def _openai_web_search(settings, prompt, *, client=None):
        return '{"found": true, "name": "Bob Lee", "source_url": null}', []
    monkeypatch.setattr(name_search, "_openai_web_search", _openai_web_search)

    got = asyncio.run(name_search.search_owner_name(
        {"id": "p1", "name": "Acme", "address": "", "website": ""}, _Settings()))
    assert got.status == "no_names" and got.names == ()


def test_search_names_isolates_a_per_prospect_failure(monkeypatch):
    async def _openai_web_search(settings, prompt, *, client=None):
        if "Boom" in prompt:
            raise name_search.NameSearchError("provider 500")
        return '{"found": true, "name": "Amy Cole", "source_url": "https://x.com/amy"}', []
    monkeypatch.setattr(name_search, "_openai_web_search", _openai_web_search)

    prospects = [
        {"id": "p1", "name": "Acme", "address": "", "website": ""},
        {"id": "p2", "name": "Boom Co", "address": "", "website": ""},
    ]
    results, errors = asyncio.run(name_search.search_names(_Settings(), prospects))
    assert {r.prospect_id for r in results} == {"p1"}
    assert len(errors) == 1 and errors[0].startswith("p2:")
