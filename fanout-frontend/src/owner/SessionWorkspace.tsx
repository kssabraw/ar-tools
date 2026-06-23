import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getMe, getSession, getSummary, planArticles, type Silo } from "../shared/api";
import { AppShell } from "../shared/AppShell";
import { CancelRunButton } from "../shared/CancelRunButton";
import { CostBanner } from "../shared/CostBanner";
import { SessionIdChip } from "../shared/SessionIdChip";
import { hasResults, statusClass, statusLabel } from "../shared/sessionStatus";

export interface SessionCtx {
  sessionId: string;
  topics: Silo[];
  topicName: (id: string) => string;
  // Drives the restricted VA editing surface in the shared views (PRD §10).
  role: "owner" | "va";
}

export function useSession() {
  return useOutletContext<SessionCtx>();
}

// VAs get a simplified results surface + a read-only Architecture view
// (PRD §10.2 / §10.3): no split view, no orchestrator re-run controls.
const OWNER_TABS = [
  { to: "table", label: "Table" },
  { to: "cluster", label: "Cluster" },
  { to: "architecture", label: "Architecture" },
  { to: "schedule", label: "Schedule" },
  { to: "articles", label: "Articles" },
  { to: "split", label: "Split" },
  { to: "exports", label: "Exports" },
];
const VA_TABS = [
  { to: "table", label: "Table" },
  { to: "cluster", label: "Cluster" },
  { to: "architecture", label: "Architecture" },
  { to: "schedule", label: "Schedule" },
  { to: "exports", label: "Exports" },
];

// Per-session shell (PRD §9): segmented control over the three views, fed by the
// read-only M1–M6 API. Views render against the shared topic map below.
export function SessionWorkspace() {
  const { id } = useParams<{ id: string }>();
  const sessionId = id!;

  const session = useQuery({ queryKey: ["session", sessionId], queryFn: () => getSession(sessionId) });
  const summary = useQuery({
    queryKey: ["summary", sessionId],
    queryFn: () => getSummary(sessionId),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 4000 : false),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: getMe });
  const role: "owner" | "va" = me.data?.role === "owner" ? "owner" : "va";

  const qc = useQueryClient();
  // Plan articles from the workspace (PRD §7.10). The in-memory creation flow has
  // its own "Plan articles" button, but a session resumed from the browser (or a
  // page refresh) lands here, so the workspace needs to be able to kick off
  // planning too. plan-articles is allowed for both roles (not capability-gated).
  const planMut = useMutation({
    mutationFn: () => planArticles(sessionId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["summary", sessionId] }),
  });

  const status = summary.data?.status ?? session.data?.status;
  const topics = session.data?.silos ?? [];
  const topicName = (tid: string) => topics.find((t) => t.id === tid)?.name ?? "Unknown topic";
  const tabs = role === "owner" ? OWNER_TABS : VA_TABS;

  return (
    <AppShell>
      <div className="workspace-head">
        <div className="workspace-head-row">
          <h1 className="page-title" style={{ margin: 0 }}>
            {session.data?.seed_keyword ?? "Session"}
          </h1>
          {status && (
            <span className={"status-pill " + statusClass(status)}>{statusLabel(status)}</span>
          )}
          {role === "owner" && (
            <Link to={`/session/${sessionId}/debug`} className="debug-link">
              Debug
            </Link>
          )}
        </div>
        <SessionIdChip sessionId={sessionId} />
        <CostBanner cost={summary.data?.cost} running={status === "running"} />
        <nav className="segmented">
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) => "segmented-item" + (isActive ? " segmented-item-active" : "")}
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </div>

      <main className="content content-wide">
        {(session.isLoading || summary.isLoading) && <p className="muted">Loading session…</p>}
        {session.isError && <p className="form-error">Couldn’t load this session.</p>}

        {status === "running" && (
          <div className="card" style={{ textAlign: "center" }}>
            <div className="spinner" />
            <p className="muted">This session is still running. Results will appear when it finishes.</p>
            <div style={{ marginTop: 12 }}>
              <CancelRunButton sessionId={sessionId} />
            </div>
          </div>
        )}

        {status === "cancelled" && (
          <div className="card">
            <p style={{ margin: 0, fontWeight: 600 }}>This run was cancelled.</p>
            <p className="muted" style={{ marginBottom: 0 }}>
              Any partial work and the cost spent before cancellation are preserved.
              Start a new session to try again.
            </p>
          </div>
        )}

        {status && status !== "running" && status !== "cancelled" && !hasResults(status) && (
          <div className="card">
            <p style={{ margin: 0, fontWeight: 600 }}>This session hasn’t produced results yet.</p>
            <p className="muted" style={{ marginBottom: 0 }}>
              It’s at the “{statusLabel(status)}” stage. Resuming an in-progress run from the UI
              arrives later; for now, open it from the creation flow or run the remaining pipeline
              steps via the API.
            </p>
          </div>
        )}

        {status === "awaiting_article_planning" && (
          <div className="plan-bar">
            <div>
              <p style={{ margin: 0, fontWeight: 600 }}>Keyword pipeline complete — ready to plan.</p>
              <p className="muted" style={{ margin: "2px 0 0" }}>
                Turn the statistical groupings into a content map (article planning, §7.10).
              </p>
            </div>
            <button
              className="btn btn-primary"
              style={{ width: "auto" }}
              disabled={planMut.isPending}
              onClick={() => planMut.mutate()}
            >
              {planMut.isPending ? "Starting…" : "Plan articles"}
            </button>
          </div>
        )}
        {planMut.isError && (
          <p className="form-error">Couldn’t start planning. Try again.</p>
        )}

        {status && hasResults(status) && session.data && (
          <Outlet context={{ sessionId, topics, topicName, role } satisfies SessionCtx} />
        )}
      </main>
    </AppShell>
  );
}
