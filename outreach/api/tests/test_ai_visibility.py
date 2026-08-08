"""The AI-visibility capture's pure layer.

The engine CALLS are I/O (OpenAI, DataForSEO) and measured on first run; what is tested here is the
AIO envelope parser — tolerant of the ai_overview shape, present=False when there is no AI answer,
and RAISING on a task-level error rather than reporting an empty answer (an outage must not read as
"the AI doesn't know you"). ChatGPT parsing reuses `ai_granularity.parse_business_names`, tested
there.
"""
import pytest

from api.services.ai_granularity import AiGranularityError
from api.services.ai_visibility import (
    ENGINE_AIO,
    build_aio_task,
    parse_aio,
)


def test_build_aio_task_puts_the_place_in_the_query():
    task = build_aio_task("plumber", "Van Nuys", language_code="en", device="desktop")
    assert task["keyword"] == "best plumber in Van Nuys"
    assert task["location_code"] == 2840  # United States
    assert task["language_code"] == "en"


def _aio_body(items):
    return {"tasks": [{"status_code": 20000, "result": [{"items": items}]}]}


def test_parse_aio_reads_references_and_text():
    body = _aio_body([
        {"type": "organic", "domain": "x.com"},  # ignored — not the AIO element
        {"type": "ai_overview",
         "text": "For plumbing in Van Nuys, top options include Ace and Bolt.",
         "references": [
             {"title": "Ace Plumbing", "domain": "ace.com", "url": "https://ace.com"},
             {"title": "Bolt Rooter", "domain": "www.bolt.com"},
         ]},
    ])
    answer = parse_aio(body)
    assert answer.engine == ENGINE_AIO
    assert answer.present is True
    assert answer.named_businesses == ["Ace Plumbing", "Bolt Rooter"]
    assert answer.reference_domains == ["ace.com", "bolt.com"]  # deduped, www-stripped, sorted
    assert "Ace and Bolt" in answer.raw_excerpt


def test_parse_aio_no_overview_is_present_false_not_an_error():
    # No ai_overview element -> the model showed no AI answer. A finding, not a failure.
    answer = parse_aio(_aio_body([{"type": "organic", "domain": "x.com"}]))
    assert answer.present is False
    assert answer.named_businesses == [] and answer.reference_domains == []


def test_parse_aio_raises_on_task_error():
    with pytest.raises(AiGranularityError):
        parse_aio({"tasks": [{"status_code": 40501, "status_message": "bad"}]})
    with pytest.raises(AiGranularityError):
        parse_aio({"tasks": []})


def test_parse_aio_tolerates_missing_items():
    answer = parse_aio({"tasks": [{"status_code": 20000, "result": [{}]}]})
    assert answer.present is False
