"""Pure tests for the fanout writer's MCS-proper topic-adherence exemption
(fanout.writer.budget.mcs_answer_validated_orders + drop_low_adherence).

When the brief carried a live AI-answer target, its Max-Cosine Synthesis already
selected the content H2s against that answer, so the writer must NOT re-drop them by
cosine-to-title. These tests pin that exemption and the fallback when no answer-engine
target was present.
"""

from __future__ import annotations

from fanout.writer.budget import drop_low_adherence, mcs_answer_validated_orders
from fanout.writer.models import BriefHeading


def _h2(order: int, *, source: str | None = "mcs", text: str = "") -> BriefHeading:
    return BriefHeading(order=order, level="H2", type="content", text=text or f"H2 {order}",
                        source=source)


def test_exempts_mcs_h2s_when_aio_present():
    headings = [_h2(2), _h2(3), _h2(4)]
    exempt = mcs_answer_validated_orders(headings, aio_present=True, chatgpt_present=False)
    assert exempt == {2, 3, 4}


def test_exempts_when_only_chatgpt_present():
    headings = [_h2(2), _h2(3)]
    exempt = mcs_answer_validated_orders(headings, aio_present=False, chatgpt_present=True)
    assert exempt == {2, 3}


def test_no_exemption_without_any_answer_target():
    headings = [_h2(2), _h2(3)]
    exempt = mcs_answer_validated_orders(headings, aio_present=False, chatgpt_present=False)
    assert exempt == set()


def test_non_mcs_rows_never_exempt():
    headings = [_h2(2, source="mcs"), _h2(3, source="organic"), _h2(4, source=None)]
    exempt = mcs_answer_validated_orders(headings, aio_present=True, chatgpt_present=True)
    assert exempt == {2}


def test_ignores_non_content_and_h3_rows():
    headings = [
        _h2(2),
        BriefHeading(order=3, level="H3", type="content", text="child", source="mcs"),
        BriefHeading(order=4, level="H2", type="conclusion", text="Conclusion", source="mcs"),
    ]
    exempt = mcs_answer_validated_orders(headings, aio_present=True, chatgpt_present=False)
    assert exempt == {2}


def test_exempt_mcs_h2_survives_low_title_cosine():
    # A genuinely on-answer H2 with a low cosine-to-title: excluded from `scores`
    # (exempt), so drop_low_adherence keeps it via the default-1.0 path.
    headings = [_h2(2), _h2(3)]
    exempt = mcs_answer_validated_orders(headings, aio_present=True, chatgpt_present=False)
    scores = {h.order: 0.10 for h in headings if h.order not in exempt}  # -> {} here
    kept, dropped = drop_low_adherence(headings, scores, threshold=0.62)
    assert set(kept) == {2, 3}
    assert dropped == []


def test_title_gate_still_drops_non_exempt_offtopic_h2():
    # No answer target -> nothing exempt -> the title gate applies as before.
    headings = [_h2(2, source="organic"), _h2(3, source="organic")]
    exempt = mcs_answer_validated_orders(headings, aio_present=False, chatgpt_present=False)
    assert exempt == set()
    scores = {2: 0.90, 3: 0.10}
    kept, dropped = drop_low_adherence(headings, scores, threshold=0.62)
    assert kept == [2]
    assert [d["order"] for d in dropped] == [3]
