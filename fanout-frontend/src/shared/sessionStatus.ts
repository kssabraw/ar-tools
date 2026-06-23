// Human labels + pill colors for fanout.session_status, shared by the browser
// and the workspace header. Keep in sync with the enum in the M1/M5 migrations.
const LABELS: Record<string, string> = {
  pending_approval: "Pending approval",
  rejected: "Rejected",
  running_pre_review: "Running",
  awaiting_silo_review: "Awaiting silo review",
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
  if (status === "running" || status === "running_pre_review") return "status-busy";
  return "status-neutral";
}

// A session has results to show in the three views once it has reached the
// article-planning stage (or beyond). Earlier statuses still belong to the
// silo-discovery / expansion flow, which the workspace can't resume yet (M7a).
export function hasResults(status: string): boolean {
  return status === "awaiting_article_planning" || status === "complete";
}
