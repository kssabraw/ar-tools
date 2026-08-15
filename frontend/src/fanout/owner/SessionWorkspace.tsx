import { useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getMe, getSession, getSummary, planArticles, regate, type RegateBody, type Silo } from "../shared/api";
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
  // Re-gate tuning. Threshold trims the pool; granularity (clustering resolution)
  // and per-silo cap control how big a chunk the editorial orchestrator sees — the
  // levers that turn a "planned nothing → error" seed (a near-homogeneous pool the
  // orchestrator can't merge) into a plannable one. All optional; blank = the
  // env default. Owner-only, matching the endpoint.
  const [threshold, setThreshold] = useState("");
  const [resolution, setResolution] = useState("");
  const [perSiloCap, setPerSiloCap] = useState("");
  const [edge, setEdge] = useState("");
  const [siloMargin, setSiloMargin] = useState("");
  const regateBody = (): RegateBody => {
    const body: RegateBody = {};
    const t = parseFloat(threshold);
    if (Number.isFinite(t)) body.relevance_threshold = t;
    const r = parseFloat(resolution);
    if (Number.isFinite(r) && r > 0) body.clustering_resolution = r;
    const c = parseInt(perSiloCap, 10);
    if (Number.isFinite(c) && c > 0) body.active_per_silo_cap = c;
    const ed = parseFloat(edge);
    if (Number.isFinite(ed) && ed > 0) body.clustering_edge_threshold = ed;
    const m = parseFloat(siloMargin);
    if (Number.isFinite(m) && m >= 0) body.silo_margin = m;
    return body;
  };
  const regateMut = useMutation({
    mutationFn: () => regate(sessionId, regateBody()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["summary", sessionId] }),
  });
  const inRange = (v: string, lo: number, hi: number, int = false) => {
    if (v.trim() === "") return true;
    const n = int ? parseInt(v, 10) : parseFloat(v);
    return Number.isFinite(n) && n >= lo && n <= hi;
  };
  const thresholdValid = inRange(threshold, 0.05, 0.99);
  const resolutionValid = inRange(resolution, 0.5, 20);
  const capValid = inRange(perSiloCap, 10, 50000, true);
  const edgeValid = inRange(edge, 0.3, 0.95);
  const marginValid = inRange(siloMargin, 0, 0.5);
  const regateInputsValid =
    thresholdValid && resolutionValid && capValid && edgeValid && marginValid;
  // Shared tuning inputs — rendered both on the errored-session recovery card and
  // the results-view "Tighten the keyword pool" panel, so a run that errored can be
  // recovered with adjusted settings (not just re-tried at the same ones).
  const regateTuningInputs = (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <input
        type="number" min="0.05" max="0.99" step="0.01" placeholder="0.65"
        value={threshold} onChange={(e) => setThreshold(e.target.value)}
        aria-label="Relevance threshold"
        title="Relevance threshold (0–1). Higher = stricter, fewer keywords."
        style={{ width: 84 }}
      />
      <input
        type="number" min="0.5" max="20" step="0.5" placeholder="1.0"
        value={resolution} onChange={(e) => setResolution(e.target.value)}
        aria-label="Cluster granularity"
        title="Cluster granularity (resolution). Higher = more, smaller groupings the orchestrator can plan."
        style={{ width: 84 }}
      />
      <input
        type="number" min="10" step="50" placeholder="1000"
        value={perSiloCap} onChange={(e) => setPerSiloCap(e.target.value)}
        aria-label="Keywords per silo"
        title="Max active keywords per silo. Lower = smaller planning inputs."
        style={{ width: 96 }}
      />
      <input
        type="number" min="0.3" max="0.95" step="0.05" placeholder="0.55"
        value={edge} onChange={(e) => setEdge(e.target.value)}
        aria-label="Edge threshold"
        title="Clustering edge threshold (min cosine for a graph edge). Higher = more, smaller groupings."
        style={{ width: 84 }}
      />
      <input
        type="number" min="0" max="0.5" step="0.01" placeholder="0.0"
        value={siloMargin} onChange={(e) => setSiloMargin(e.target.value)}
        aria-label="Silo margin"
        title="Soft-routing margin (0 = off). Keeps a keyword active in every silo within this cosine of its best — repopulates silos starved by hard argmax. Try 0.03–0.06."
        style={{ width: 84 }}
      />
    </div>
  );

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
                <p className="muted" style={{ margin: "0 0 6px", fontSize: 13 }}>
                  Optional — tune before recovering (threshold · granularity · keywords/silo ·
                  edge · margin; blank = defaults). If a previous attempt planned nothing, raise
                  the granularity or lower the keywords/silo; set margin ~0.05 to repopulate
                  empty silos.
                </p>
                {regateTuningInputs}
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
                  <button
                    className="btn btn-primary"
                    style={{ width: "auto" }}
                    disabled={regateMut.isPending || !regateInputsValid}
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
                {!regateInputsValid && (
                  <p className="form-error">
                    Threshold 0.05–0.99, granularity 0.5–20, keywords/silo ≥ 10, edge 0.3–0.95, margin 0–0.5.
                  </p>
                )}
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
                Re-gate + re-cluster the keywords already collected — no new expansion spend.
                Threshold drops off-topic keywords; granularity and keywords/silo control how
                big a chunk the planner sees (raise granularity / lower keywords/silo if a plan
                came back thin). Blank = defaults. <strong>Clears the current article plan</strong>,
                so run “Plan articles” again afterwards.
              </p>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
              {regateTuningInputs}
              <button
                className="btn btn-ghost"
                style={{ width: "auto" }}
                disabled={regateMut.isPending || !regateInputsValid}
                onClick={() => {
                  if (
                    window.confirm(
                      `Re-gate this session?\n\nThis discards the current article plan and ` +
                        `re-clusters the keyword pool with your settings (blank = defaults). ` +
                        `You'll need to run "Plan articles" again.`,
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
        {!regateInputsValid && (
          <p className="form-error">
            Threshold 0.05–0.99, granularity 0.5–20, keywords/silo ≥ 10, edge 0.3–0.95, margin 0–0.5.
          </p>
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
