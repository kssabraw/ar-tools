"""Paged reads.

PostgREST caps an unbounded `select()` at 1000 rows and returns the truncated set WITHOUT any
error, header or warning that would make a caller notice. That is how the first LA run reported
`evaluated: 1000` against 1388 prospects and left 215 of them silently unfiltered — the
definition-of-done question "how many survived" would simply have undercounted, confidently.

Every read that can return more than a handful of rows must go through `fetch_all`. The rule is
not "paginate the big tables": `prospect` was small enough not to matter for a week, and then it
wasn't. Any table that grows with the portfolio is a candidate, and the failure is silent, so
there is no signal to wait for.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# PostgREST's own default ceiling. Requesting a range larger than this returns only this many.
DEFAULT_PAGE_SIZE = 1000


def fetch_all(
    build_query: Callable[[], Any],
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_rows: int | None = None,
) -> list[dict[str, Any]]:
    """Read every row a query matches, one page at a time.

    `build_query` returns a FRESH query builder each call — supabase-py builders are stateful and
    accumulate modifiers, so reusing one across pages compounds `.range()` calls instead of
    replacing them.

    Stops when a page comes back short, which is the only reliable end-of-data signal PostgREST
    gives. `max_rows` is a runaway guard, and reaching it is logged rather than passed over in
    silence — a truncation nobody is told about is the bug this module exists to prevent.
    """
    rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        page = build_query().range(offset, offset + page_size - 1).execute().data or []
        rows.extend(page)

        if len(page) < page_size:
            return rows

        offset += page_size

        if max_rows is not None and len(rows) >= max_rows:
            logger.warning(
                "fetch_all hit max_rows and stopped early — the result is TRUNCATED",
                extra={"rows": len(rows), "max_rows": max_rows},
            )
            return rows[:max_rows]
