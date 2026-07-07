import { useEffect, useRef, useState } from "react";
import {
  getTermAnalysis,
  startTermAnalysis,
  type SieReport,
  type SieUsageRec,
} from "../../shared/api";

// M12 SIE Term & Entity report (owner-only validation surface, plan §6). Starts the
// analysis on open, polls until the cached report lands, then renders it.
export default function TermAnalysisPanel(props: {
  sessionId: string;
  clusterId: string;
  keyword: string;
  onClose: () => void;
}) {
  const { sessionId, clusterId, keyword, onClose } = props;
  const [status, setStatus] = useState<"running" | "complete" | "error">("running");
  const [report, setReport] = useState<SieReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef<number | null>(null);

  // Elapsed-time counter while the analysis runs (reassurance for a ~1–3 min job).
  useEffect(() => {
    if (status !== "running") return;
    const id = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => window.clearInterval(id);
  }, [status]);

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;

    const poll = async () => {
      attempts += 1;
      try {
        const res = await getTermAnalysis(sessionId, clusterId);
        if (cancelled) return;
        if (res.status === "complete" && res.report) {
          setReport(res.report);
          setStatus("complete");
          if (timer.current) window.clearInterval(timer.current);
        }
      } catch {
        // 404 until analyzed — keep polling, but give up after ~5 min.
        if (attempts > 60 && timer.current) {
          window.clearInterval(timer.current);
          if (!cancelled) {
            setStatus("error");
            setError("Analysis timed out. The SERP/scrape pass may have failed — check logs.");
          }
        }
      }
    };

    startTermAnalysis(sessionId, clusterId)
      .then((res) => {
        if (cancelled) return;
        if (res.status === "complete" && res.report) {
          setReport(res.report);
          setStatus("complete");
        } else {
          timer.current = window.setInterval(poll, 5000);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setStatus("error");
          setError(e instanceof Error ? e.message : "Failed to start analysis");
        }
      });

    return () => {
      cancelled = true;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [sessionId, clusterId]);

  const usageByTerm = new Map<string, SieUsageRec>(
    (report?.usage_recommendations ?? []).map((u) => [u.term, u]),
  );
  const range = (r?: { min: number; target: number; max: number }) =>
    r ? `${r.min}–${r.max} (≈${r.target})` : "—";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal card" style={{ maxWidth: 880 }} onClick={(e) => e.stopPropagation()}>
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 className="page-title" style={{ margin: 0 }}>Term analysis — {keyword}</h2>
          <button className="link-btn" onClick={onClose}>Close</button>
        </header>

        {status === "running" && (
          <div style={{ textAlign: "center", padding: "24px 0" }}>
            <div className="spinner" />
            <p className="progress-stage">Analyzing the top-20 SERP…</p>
            <p className="progress-meta">
              scrape + n-grams + entities · {elapsed}s elapsed
              <br />usually 1–3 min on a cache miss
            </p>
          </div>
        )}
        {status === "error" && <p className="banner banner-error">{error}</p>}

        {report && (
          <div style={{ display: "grid", gap: 18 }}>
            {report.warnings.length > 0 && (
              <div className="banner banner-warn">
                {report.warnings.map((w, i) => <div key={i}>{w}</div>)}
              </div>
            )}

            <section>
              <strong>Recommended length:</strong> {report.word_count.target} words
              {" "}(range {report.word_count.min}–{report.word_count.max})
            </section>

            <section>
              <h3>Required terms ({report.terms.required.length})</h3>
              <table className="data-table">
                <thead>
                  <tr><th>Term</th><th>Score</th><th>Entity</th><th>H2</th><th>H3</th><th>Paragraphs</th></tr>
                </thead>
                <tbody>
                  {report.terms.required.map((t) => {
                    const u = usageByTerm.get(t.term);
                    return (
                      <tr key={t.term}>
                        <td>{t.term}</td>
                        <td>{t.recommendation_score.toFixed(2)}</td>
                        <td>{t.is_entity ? (t.entity_category ?? "entity") : "—"}</td>
                        <td>{range(u?.h2)}</td>
                        <td>{range(u?.h3)}</td>
                        <td>{range(u?.paragraphs)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>

            {report.terms.avoid.length > 0 && (
              <section>
                <h3>Avoid</h3>
                <p className="muted">{report.terms.avoid.join(", ")}</p>
              </section>
            )}

            {report.entities.length > 0 && (
              <section>
                <h3>Entities ({report.entities.length})</h3>
                <ul>
                  {report.entities.map((e) => (
                    <li key={e.term}>
                      <strong>{e.term}</strong>
                      {e.entity_category ? ` · ${e.entity_category}` : ""}
                      {e.example_context ? ` — ${e.example_context}` : ""}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h3>Pages</h3>
              <ul className="muted" style={{ fontSize: 13 }}>
                {report.pages.map((p, i) => (
                  <li key={i}>
                    {p.included ? "✓" : "✗"} {p.rank ? `#${p.rank} ` : ""}{p.url}
                    {p.reason ? ` — ${p.reason}` : ""}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
