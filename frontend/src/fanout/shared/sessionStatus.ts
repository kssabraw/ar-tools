// Human labels + pill colors for fanout.session_status, shared by the browser
// and the workspace header. Keep in sync with the enum in the M1/M5 migrations.
const LABELS: Record<string, string> = {
  pending_approval: "Pending approval",
  rejected: "Rejected",
  running_pre_review: "Running",
  awaiting_silo_review: "Awaiting silo review",
  queued: "Queued",
  running: "Running",
  awaiting_article_planning: "Ready to plan",
  complete: "Complete",
  cancelled: "Cancelled",
  error: "Error",
};

export function statusLabel(status: string): string {
  return LABELS[status] ?? status;
}

export function statusClass(status: string): string {
  if (status === "complete") return "status-ok";
  if (status === "error" || status === "rejected") return "status-bad";
  if (status === "running" || status === "running_pre_review" || status === "queued")
    return "status-busy";
  return "status-neutral";
}

// Statuses a background job will transition on its own (a run is queued for a
// worker slot, or expansion / clustering / article planning is executing). A
// list or overview showing one of these is stale the moment the job moves, so
// it must keep polling until the status settles — otherwise the user has to
// manually refresh to see a run flip to "Ready to plan". `pending_approval`
// waits on a human decision, not a job, so it's intentionally excluded
// (nothing to poll for).
export function isLiveStatus(status: string): boolean {
  return status === "running" || status === "running_pre_review" || status === "queued";
}

// A session has results to show in the three views once it has reached the
// article-planning stage (or beyond). Earlier statuses still belong to the
// silo-discovery / expansion flow, which the workspace can't resume yet (M7a).
export function hasResults(status: string): boolean {
  return status === "awaiting_article_planning" || status === "complete";
}
