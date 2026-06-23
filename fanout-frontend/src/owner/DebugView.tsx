import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getSessionDebug } from "../shared/api";
import { AppShell } from "../shared/AppShell";

// Owner debug view (PRD §15.3 #8): review the orchestrator's decisions + the raw
// statistical clustering for any session, plus the per-step cost attribution
// (§16.4). Owner-only — the backend `/debug` endpoint 403s a VA, and this route
// is only registered under OwnerRoutes.
export function DebugView() {
  const { id } = useParams<{ id: string }>();
  const sessionId = id!;
  const debug = useQuery({
    queryKey: ["debug", sessionId],
    queryFn: () => getSessionDebug(sessionId),
  });

  const breakdown = debug.data?.cost_breakdown ?? {};
  const breakdownRows = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);

  return (
    <AppShell>
      <div className="workspace-head">
        <div className="workspace-head-row">
          <h1 className="page-title" style={{ margin: 0 }}>
            Debug · {debug.data?.seed_keyword ?? "Session"}
          </h1>
          <Link to={`/session/${sessionId}`} className="debug-link">
            ← Back to session
          </Link>
        </div>
      </div>

      <main className="content content-wide">
        {debug.isLoading && <p className="muted">Loading debug data…</p>}
        {debug.isError && <p className="form-error">Couldn’t load debug data.</p>}

        {debug.data && (
          <>
            <section className="card">
              <h2 className="section-title">Cost attribution (§16.4)</h2>
              <p className="muted" style={{ marginTop: 0 }}>
                Estimated ${(debug.data.estimated_cost_usd ?? 0).toFixed(2)} · Actual{" "}
                <strong>${(debug.data.actual_cost_usd ?? 0).toFixed(2)}</strong>
              </p>
              {breakdownRows.length > 0 ? (
                <table className="debug-table">
                  <thead>
                    <tr>
                      <th>Step</th>
                      <th style={{ textAlign: "right" }}>Cost (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {breakdownRows.map(([step, cost]) => (
                      <tr key={step}>
                        <td>{step}</td>
                        <td style={{ textAlign: "right" }}>${cost.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="muted">No per-step cost recorded yet.</p>
              )}
            </section>

            <section className="card">
              <h2 className="section-title">Architecture link health (§15.2 #3)</h2>
              {debug.data.architecture_link_health ? (
                (() => {
                  const lh = debug.data.architecture_link_health;
                  const ok =
                    lh.orphan_articles === 0 &&
                    lh.orphan_pillars === 0 &&
                    lh.dangling_links === 0;
                  return (
                    <p className="muted" style={{ marginTop: 0 }}>
                      <strong style={{ color: ok ? "inherit" : "#c0392b" }}>
                        {ok ? "✓ Healthy" : "⚠ Issues found"}
                      </strong>{" "}
                      · orphan articles: {lh.orphan_articles} · orphan pillars:{" "}
                      {lh.orphan_pillars} · dangling links: {lh.dangling_links}
                    </p>
                  );
                })()
              ) : (
                <p className="muted">No architecture generated yet.</p>
              )}
            </section>

            <section className="card">
              <h2 className="section-title">Orchestrator log</h2>
              <p className="field-hint" style={{ marginTop: 0 }}>
                Per-topic merge / split / drop rationales and cross-topic dedup
                collisions.
              </p>
              <pre className="debug-json">
                {debug.data.orchestrator_log
                  ? JSON.stringify(debug.data.orchestrator_log, null, 2)
                  : "No orchestrator log — article planning hasn’t run for this session."}
              </pre>
            </section>

            <section className="card">
              <h2 className="section-title">Statistical clustering log</h2>
              <p className="field-hint" style={{ marginTop: 0 }}>
                Raw Louvain groupings per silo (representatives, cohesion, sizes).
              </p>
              <pre className="debug-json">
                {debug.data.statistical_clustering_log
                  ? JSON.stringify(debug.data.statistical_clustering_log, null, 2)
                  : "No clustering log — expansion hasn’t run for this session."}
              </pre>
            </section>
          </>
        )}
      </main>
    </AppShell>
  );
}
