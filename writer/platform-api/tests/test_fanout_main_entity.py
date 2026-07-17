"""Pure tests for the fanout writer's main-entity read used to enforce the SRT
"main entity repeated in subheadings" factor (fanout.writer.pipeline._main_entity_label).

The brief's MCS-form H2s already carry the main entity, but the H3 subheadings the writer
generates do not. `_write_group` reads the canonical main entity from the brief metadata to
instruct the section model to weave it into the `### ` subheadings; this pins that read
(and its graceful empty fallback, which drops the instruction rather than emitting a broken
prompt fragment).
"""

from __future__ import annotations

from fanout.writer.models import Brief
from fanout.writer.pipeline import _main_entity_label


def _brief(metadata: dict | None = None) -> Brief:
    return Brief(keyword="retatrutide", title="What is retatrutide?", metadata=metadata or {})


def test_reads_canonical_main_entity():
    assert _main_entity_label(_brief({"main_entity": {"canonical": "retatrutide"}})) == "retatrutide"


def test_strips_whitespace():
    assert _main_entity_label(_brief({"main_entity": {"canonical": "  retatrutide  "}})) == "retatrutide"


def test_empty_when_no_metadata():
    assert _main_entity_label(_brief()) == ""


def test_empty_when_no_main_entity_block():
    assert _main_entity_label(_brief({"mcs": {"aio_present": True}})) == ""


def test_empty_when_canonical_missing_or_blank():
    assert _main_entity_label(_brief({"main_entity": {"variants": ["reta"]}})) == ""
    assert _main_entity_label(_brief({"main_entity": {"canonical": "   "}})) == ""
