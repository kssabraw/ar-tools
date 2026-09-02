"""async_jobs queue priorities.

A tiny leaf module (no service imports) so both the enqueue sites and the
worker can share the constants without an import cycle — `job_worker` imports
the content services, so they cannot import it back.

The claim orders pending rows by `priority DESC, scheduled_at ASC`: a higher
number runs first; ties fall back to the oldest scheduled time. Bulk flows
stamp their per-item jobs BACKGROUND so a just-clicked interactive job never
queues behind a batch, however old the batch's rows are. Background jobs still
run back-to-back whenever nothing else is pending (no gate, no delay).
"""

INTERACTIVE = 0   # the column default — every job not marked otherwise
BACKGROUND = -1   # bulk-create / matrix / reoptimize-bulk items
