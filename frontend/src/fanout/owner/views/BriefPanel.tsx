import { useEffect, useRef, useState } from "react";
import { getBrief, startBrief, type BriefReport } from "../../shared/api";

// M13 Brief Generator report (answer-engine-first; owner-only validation surface).
// Starts brief generation on open, polls until the cached brief lands, then renders
// the heading skeleton (H1/H2/H3), intent, scope, format directives and FAQs. Runs
// ~3–5 min on a cache miss (SERP + AIO + LLM-fanout + dual-space MCS).
export default function BriefPanel(props: {
  sessionId: string;
  clusterId: string;
  keyword: string;
  onClose: () => void;
}) {
  const { sessionId, clusterId, keyword, onClose } = props;
  const [status, setStatus] = useState<"running" | "complete" | "error">("running");
  const [brief, setBrief] = useState<BriefReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef<number | null>(null);

  // Elapsed-time counter while the brief generates (reassurance for a ~3–5 min job).
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
        const res = await getBrief(sessionId, clusterId);
        if (cancelled) return;
        if (res.status === "complete" && res.brief) {
          setBrief(res.brief);
          setStatus("complete");
          if (timer.current) window.clearInterval(timer.current);
        }
      } catch {
        // 404 until generated — keep polling, but give up after ~8 min.
        if (attempts > 96 && timer.current) {
          window.clearInterval(timer.current);
          if (!cancelled) {
            setStatus("error");
            setError("Brief timed out. The SERP/AIO/LLM-fanout pass may have failed — check logs.");
          }
        }
      }
    };

    startBrief(sessionId, clusterId)
      .then((res) => {
        if (cancelled) return;
        if (res.status === "complete" && res.brief) {
          setBrief(res.brief);
          setStatus("complete");
        } else {
          timer.current = window.setInterval(poll, 5000);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setStatus("error");
          setError(e instanceof Error ? e.message : "Failed to start brief");
        }
      });

    return () => {
      cancelled = true;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [sessionId, clusterId]);

  const fd = (brief?.format_directives ?? {}) as Record<string, unknown>;
  const num = (k: string) => (typeof fd[k] === "number" ? (fd[k] as number) : undefined);
  const bool = (k: string) => fd[k] === true;
  const indent = (level: string) => (level === "H3" ? 24 : level === "H2" ? 12 : 0);

  // 2b coverage audit: which of the cluster's supporting keywords a heading covers vs.
  // fell through (so clustered research is visible, not silently dropped).
  const coverage = (brief?.metadata?.["cluster_keyword_coverage"] ?? null) as {
    total?: number;
    covered_count?: number;
    uncovered_count?: number;
    used_as_subtopic?: string[];
    uncovered?: { keyword: string; nearest: string | null; cosine: number }[];
  } | null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal card" style={{ maxWidth: 880 }} onClick={(e) => e.stopPropagation()}>
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 className="page-title" style={{ margin: 0 }}>Content brief — {keyword}</h2>
          <button className="link-btn" onClick={onClose}>Close</button>
        </header>

        {status === "running" && (
          <div style={{ textAlign: "center", padding: "24px 0" }}>
            <div className="spinner" />
            <p className="progress-stage">Generating the content brief…</p>
            <p className="progress-meta">
              SERP + AI Overview + LLM fan-out + dual-space MCS · {elapsed}s elapsed
              <br />usually 3–5 min on a cache miss
            </p>
          </div>
        )}
        {status === "error" && <p className="banner banner-error">{error}</p>}

        {brief && (
          <div style={{ display: "grid", gap: 18 }}>
            {brief.intent_review_required && (
              <div className="banner banner-warn">
                Intent confidence is low ({brief.intent_confidence?.toFixed(2) ?? "?"}) — review before writing.
              </div>
            )}

            <section>
              <strong>Title (H1):</strong> {brief.h1 || brief.title}
              <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                Intent: {brief.intent_type ?? "—"}
                {typeof brief.intent_confidence === "number" ? ` (${brief.intent_confidence.toFixed(2)})` : ""}
                {" · schema "}{brief.schema_version}
              </div>
              {brief.scope_statement && (
                <p className="muted" style={{ fontSize: 13, marginTop: 6 }}>{brief.scope_statement}</p>
              )}
            </section>

            <section>
              <h3>Heading structure ({brief.heading_structure.length})</h3>
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 3 }}>
                {brief.heading_structure.map((h, i) => (
                  <li key={i} style={{ marginLeft: indent(h.level), fontSize: 14 }}>
                    <span className="badge badge-rel" style={{ marginRight: 6 }}>{h.level}</span>
                    {h.text}
                    {h.source && <span className="cell-muted" style={{ marginLeft: 6 }}>· {h.source}</span>}
                    {h.exempt && <span className="badge badge-warn" style={{ marginLeft: 6 }}>authority gap</span>}
                    {h.format_directive && (
                      <span className="badge badge-warn" style={{ marginLeft: 6 }}>decision-fit</span>
                    )}
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <h3>Format directives</h3>
              <ul className="muted" style={{ fontSize: 13 }}>
                {num("min_h2_body_words") ? <li>Min H2 body words: {num("min_h2_body_words")}</li> : null}
                {bool("require_tables") ? <li>Requires ≥{num("min_tables_per_article") ?? 1} table(s)</li> : null}
                {bool("require_bulleted_lists") ? <li>Requires ≥{num("min_lists_per_article") ?? 1} list(s)</li> : null}
                {bool("answer_first_paragraphs") ? <li>Answer-first paragraphs</li> : null}
                {num("preferred_paragraph_max_words") ? <li>Preferred paragraph max: {num("preferred_paragraph_max_words")} words</li> : null}
              </ul>
            </section>

            {brief.faqs.length > 0 && (
              <section>
                <h3>FAQs ({brief.faqs.length})</h3>
                <ul>
                  {brief.faqs.map((f, i) => (
                    <li key={i}><strong>{f.question}</strong>{f.answer ? ` — ${f.answer}` : ""}</li>
                  ))}
                </ul>
              </section>
            )}

            {coverage && (coverage.total ?? 0) > 0 && (
              <section>
                <h3>
                  Clustered-keyword coverage{" "}
                  <span className="cell-muted" style={{ fontWeight: 400, fontSize: 13 }}>
                    {coverage.covered_count ?? 0}/{coverage.total} covered
                  </span>
                </h3>
                {(coverage.used_as_subtopic?.length ?? 0) > 0 && (
                  <p className="muted" style={{ fontSize: 13, margin: "2px 0 8px" }}>
                    Used as subtopics: {coverage.used_as_subtopic!.join(", ")}
                  </p>
                )}
                {(coverage.uncovered?.length ?? 0) > 0 ? (
                  <>
                    <div className="muted" style={{ fontSize: 13, marginBottom: 4 }}>
                      Researched but not covered by any heading — consider Split, or accept as out of scope:
                    </div>
                    <ul style={{ fontSize: 13, margin: 0 }}>
                      {coverage.uncovered!.map((u, i) => (
                        <li key={i}>
                          <strong>{u.keyword}</strong>
                          {u.nearest && (
                            <span className="cell-muted">
                              {" "}· nearest: "{u.nearest}" ({u.cosine.toFixed(2)})
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="muted" style={{ fontSize: 13, margin: 0 }}>
                    Every clustered keyword is covered by a heading.
                  </p>
                )}
              </section>
            )}

            {Array.isArray(brief.discarded_headings) && brief.discarded_headings.length > 0 && (
              <section>
                <h3 className="muted" style={{ fontSize: 14 }}>Discarded headings: {brief.discarded_headings.length}</h3>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
