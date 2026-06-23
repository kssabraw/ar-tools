"""Context-propagating thread pool (PRD §16.3 / §16.4).

The pipeline parallelizes its external API calls across raw `ThreadPoolExecutor`
worker threads. A plain executor does NOT copy the submitting thread's
`contextvars` into its workers, so anything bound on the job thread —
`correlation_id`, `session_id` (PRD §16.3 per-session correlation), and the M11
cost meter (§16.4) — would be invisible inside those nested calls. That means the
dominant DataForSEO cost (made in nested threads) couldn't be attributed, and the
external-call logs would carry `session_id: null`.

`ContextThreadPoolExecutor` captures the caller's context at submit time and runs
each task inside it, so the bound values propagate one level down. The pipeline
files import it under the `ThreadPoolExecutor` alias, so no other call-site
changes are needed.
"""

import contextvars
from concurrent.futures import ThreadPoolExecutor


class ContextThreadPoolExecutor(ThreadPoolExecutor):
    def submit(self, fn, /, *args, **kwargs):  # type: ignore[override]
        # copy_context() runs in the *submitting* thread, capturing its
        # contextvars (correlation_id / session_id / cost meter). The worker then
        # executes the task inside that snapshot.
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)
