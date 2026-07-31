"""Load the suppression index.

`suppression` is owned by docs/crm-layer-spec.md and belongs to Phase 1b, which runs in parallel
with Phase 1. The Phase 1 migration creates it empty with IF NOT EXISTS so this check is a real
query rather than a to_regclass() guard retrofitted later.

Two failure modes are handled deliberately, and both degrade to "nothing is suppressed":

  * The table does not exist (the Phase 1 migration has not run).
  * The table exists with a DIFFERENT shape, because the Phase 1b migration created it first and
    IF NOT EXISTS silently no-opped ours. IF NOT EXISTS is not a merge — it keeps whichever ran
    first — so this cannot be assumed away.

Failing open is correct in Phase 1 and only in Phase 1: the table is empty by definition and
nothing is contacted. From Phase 5, where suppression gates real spend and real sends, a load
failure must become a hard error rather than an empty index. Do not carry this behaviour forward.
"""

from __future__ import annotations

import logging
from typing import Any

from .filters import SuppressionIndex

logger = logging.getLogger(__name__)

# Columns that might hold the suppressed identifier, depending on whose migration won.
_VALUE_COLUMNS = ("value", "identifier", "target", "key")


def load_suppression_index(client: Any) -> SuppressionIndex:
    try:
        from .paging import fetch_all

        # Suppression is a hard exclusion gate. A truncated read would silently CONTACT people
        # who asked not to be, which is the worst failure available in this pipeline.
        rows = fetch_all(lambda: client.table("suppression").select("*"))
    except Exception as exc:  # noqa: BLE001 — any failure degrades to an empty index in Phase 1
        logger.warning(
            "suppression table unreadable, treating as empty (Phase 1 only)",
            extra={"error": repr(exc)},
        )
        return SuppressionIndex()

    values: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for column in _VALUE_COLUMNS:
            value = row.get(column)
            if isinstance(value, str) and value.strip():
                values.append(value)
                break

    if rows and not values:
        logger.warning(
            "suppression rows present but no recognised value column — "
            "the CRM migration's shape differs from this one; reconcile explicitly",
            extra={"row_count": len(rows), "columns": sorted(rows[0].keys())},
        )

    return SuppressionIndex(values)
