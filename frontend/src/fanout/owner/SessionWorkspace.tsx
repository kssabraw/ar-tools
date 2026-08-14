import { useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getMe, getSession, getSummary, planArticles, regate, type Silo } from "../shared/api";
import { AppShell } from "../shared/AppShell";
import { CancelRunButton } from "../shared/CancelRunButton";
import { CostBanner } from "../shared/CostBanner";
import { friendlyError } from "../shared/errors";
import { ResumeReview } from "../shared/ResumeReview";
import { SessionIdChip } from "../shared/SessionIdChip";
import { hasResults, isLiveStatus, statusClass, statusLabel } from "../shared/sessionStatus";

export interface SessionCtx {
  sessionId: string;
  topics: Silo[];
  topicName: (id: string) => string;
  // Drives the restricted VA editing surface in the shared views (PRD §10).
  role: "owner" | "va";
  // Content type chosen at session creation; seeds the Schedule modal.
  contentType?: "blog_post" | "local_seo_page" | null;
  // Local SEO target area chosen at session creation; pre-fills the Schedule modal.
  location?: string | null;
  // Client + market for this run — scope the Schedule modal's location typeahead.
  clientId?: string | null;
  locationCode?: number | null;
  // Whether the linked client has WordPress configured — gates the Schedule
  // modal's direct-to-WordPress option.
  wordpressAvailable?: boolean;
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
    refetchInterval: (q) => (isLiveStatus(q.state.data?.status ?? "") ? 4000 : false),
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

  // Re-gate: re-run the relevance gate + clustering on the stored keyword pool at
  // a stricter cutoff, to drop off-topic keywords the default threshold let in.
  // The backend has always supported it (a calibration tool that skips DataForSEO,
  // so it costs no expansion spend) but nothing in the UI reached it. Owner-only,
  // matching the endpoint. It clears any existing article plan, so it has to be
  // followed by a fresh "Plan articles" — hence the confirm.
  const [threshold, setThreshold] = useState("");
  const regateMut = useMutation({
    mutationFn: () => {
      const t = parseFloat(threshold);
      return regate(sessionId, Number.isFinite(t) ? { relevance_threshold: t } : {});
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["summary", sessionId] }),
  });
  const thresholdValid = threshold.trim() === "" || (() => {
    const t = parseFloat(threshold);
    return Number.isFinite(t) && t > 0 && t < 1;
  })();

  const status = summary.data?.status ?? session.data?.status;
  const topics = session.data?.silos ?? [];
  const topicName = (tid: string) => topics.find((t) => t.id === tid)?.name ?? "Unknown topic";
  const tabs = role === "owner" ? OWNER_TABS : VA_TABS;

  // A run that errored *after* its keyword pool was persisted — e.g. a transient
  // Supabase disconnect between the keyword insert and the clustering-log write,
  // the failure that stranded a $7 pool on 2026-08-14 — leaves a complete,
  // resumable pool with only the clustering log missing. Re-gate rebuilds the
  // clustering from the stored keywords with no new expansion spend, so an errored
  // owner session that still has keywords on file offers recovery instead of only
  // "start over". Gated on a non-empty pool so a run that died mid-expansion (no
  // usable pool) still points at a fresh session.
  const poolCounts = summary.data?.expansion?.counts;
  const savedPoolSize = poolCounts
    ? poolCounts.active + poolCounts.filtered_relevance + poolCounts.filtered_junk +
      (poolCounts.filtered_language ?? 0)
    : 0;
  const canRecoverError = role === "owner" && savedPoolSize > 0;

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
            <Link to={`/fanout/session/${sessionId}/debug`} className="debug-link">
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
        {(session.isLoading || summary.isLoading || me.isLoading) && (
          <p className="muted">Loading session…</p>
        )}
        {session.isError && <p className="form-error">Couldn’t load this session.</p>}

        {status === "queued" && (
          <div className="card" style={{ textAlign: "center" }}>
            <div className="spinner" />
            <p style={{ margin: 0, fontWeight: 600 }}>Waiting for a free worker slot…</p>
            <p className="muted">
              Up to two pipeline runs execute at once; this one starts automatically
              when a slot frees up. Nothing has been spent yet.
            </p>
            <div style={{ marginTop: 12 }}>
              <CancelRunButton sessionId={sessionId} />
            </div>
          </div>
        )}

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

        {/* Editable pre-run states: resume silo review in-place (review → deep-mine
            → confirm → run), rather than stranding the session with no way to
            review its silos. `rejected` is the same flow — adjust and resubmit. */}
        {(status === "awaiting_silo_review" || status === "rejected") && !me.isLoading && (
          <>
            {status === "rejected" && summary.data?.approval.note && (
              <div className="banner">Note from the Owner: {summary.data.approval.note}</div>
            )}
            {/* Wait for `me` to settle so `role` is authoritative — the deep-mine
                cap and approval gating below depend on it (owner vs VA). */}
            <ResumeReview sessionId={sessionId} role={role} />
          </>
        )}

        {/* An errored run is terminal, not a "come back later" stage: surface the
            real reason (e.g. a transient disconnect mid-persist, or a deploy
            interrupting the run). If the keyword pool was already saved before the
            failure (canRecoverError), offer a no-new-spend re-gate to rebuild the
            clustering and continue; otherwise point at a fresh session rather than a
            dead-end API hint. */}
        {status === "error" && (
          <div className="card">
            <p style={{ margin: 0, fontWeight: 600 }}>This run hit an error.</p>
            <p className="muted" style={{ margin: "6px 0" }}>
              {friendlyError(summary.data?.last_error, "The pipeline failed before it finished.")}
            </p>
            {canRecoverError ? (
              <>
                <p className="muted" style={{ margin: "0 0 12px" }}>
                  The {savedPoolSize.toLocaleString()} keywords collected before the
                  failure were saved. You can re-cluster them into silos and continue —
                  no new expansion spend. If the pool looks incomplete, start a fresh
                  session instead.
                </p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <button
                    className="btn btn-primary"
                    style={{ width: "auto" }}
                    disabled={regateMut.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Recover this run by re-clustering the ${savedPoolSize.toLocaleString()} ` +
                            `saved keywords?\n\nThis reuses the keywords already collected — no new ` +
                            `expansion spend — and lands the session ready to plan articles.`,
                        )
                      ) {
                        regateMut.mutate();
                      }
                    }}
                  >
                    {regateMut.isPending ? "Recovering…" : "Re-gate to recover"}
                  </button>
                  <Link
                    className="btn btn-ghost"
                    style={{ width: "auto" }}
                    to="/fanout/session/new"
                  >
                    Start a new session
                  </Link>
                </div>
                {regateMut.isError && (
                  <p className="form-error">
                    {friendlyError(regateMut.error, "Couldn’t start recovery.")}
                  </p>
                )}
              </>
            ) : (
              <>
                <p className="muted" style={{ margin: "0 0 12px" }}>
                  Anything collected before the failure was saved, but the keyword pool is
                  incomplete, so this run can’t be resumed. Start a new session for this seed
                  to try again.
                </p>
                <Link
                  className="btn btn-primary"
                  style={{ width: "auto" }}
                  to={role === "owner" ? "/fanout/session/new" : "/fanout/wizard"}
                >
                  Start a new session
                </Link>
              </>
            )}
          </div>
        )}

        {status && status !== "running" && status !== "queued" && status !== "cancelled" &&
          status !== "awaiting_silo_review" && status !== "rejected" && status !== "error" &&
          !hasResults(status) && (
          <div className="card">
            <p style={{ margin: 0, fontWeight: 600 }}>This session hasn’t produced results yet.</p>
            <p className="muted" style={{ marginBottom: 0 }}>
              It’s at the “{statusLabel(status)}” stage
              {status === "pending_approval"
                ? " — waiting on Owner approval before the run can start."
                : ". Resuming this stage from the UI isn’t available yet; run the remaining pipeline steps via the API."}
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
          <p className="form-error">{friendlyError(planMut.error, "Couldn’t start planning.")}</p>
        )}

        {role === "owner" && status && hasResults(status) && (
          <div className="plan-bar">
            <div>
              <p style={{ margin: 0, fontWeight: 600 }}>Tighten the keyword pool</p>
              <p className="muted" style={{ margin: "2px 0 0" }}>
                Re-run the relevance gate at a stricter cutoff to drop off-topic keywords,
                then re-cluster. Uses the keywords already collected — no new expansion
                spend. Leave blank for the default. <strong>Clears the current article
                plan</strong>, so run “Plan articles” again afterwards.
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="number"
                min="0.05"
                max="0.99"
                step="0.01"
                placeholder="0.65"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                aria-label="Relevance threshold"
                style={{ width: 90 }}
              />
              <button
                className="btn btn-ghost"
                style={{ width: "auto" }}
                disabled={regateMut.isPending || !thresholdValid}
                onClick={() => {
                  const at = threshold.trim() === "" ? "the default threshold" : threshold.trim();
                  if (
                    window.confirm(
                      `Re-gate this session at ${at}?\n\nThis discards the current article plan ` +
                        `and re-clusters the keyword pool. You'll need to run "Plan articles" again.`,
                    )
                  ) {
                    regateMut.mutate();
                  }
                }}
              >
                {regateMut.isPending ? "Starting…" : "Re-gate"}
              </button>
            </div>
          </div>
        )}
        {!thresholdValid && (
          <p className="form-error">Threshold must be between 0 and 1 (e.g. 0.75).</p>
        )}
        {regateMut.isError && (
          <p className="form-error">
            {friendlyError(regateMut.error, "Couldn’t start the re-gate.")}
          </p>
        )}

        {status && hasResults(status) && session.data && (
          <Outlet
            context={
              { sessionId, topics, topicName, role, contentType: session.data?.content_type, location: session.data?.location, clientId: session.data?.client_id, locationCode: session.data?.location_code, wordpressAvailable: session.data?.publish_available?.wordpress } satisfies SessionCtx
            }
          />
        )}
      </main>
    </AppShell>
  );
}
