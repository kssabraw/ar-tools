import { useEffect, useRef, useState } from "react";
import {
  getArticle,
  splitUncovered,
  startArticle,
  type ArticleOutput,
} from "../../shared/api";

// M14 Content Writer — owner-only article readout. Starts generation on open (ensures
// the Brief + SIE as stage 1, then writes), polls until the article lands, then renders
// the Markdown + word count + cost. Runs ~1–3 min on a cache hit of brief+SIE, longer
// on a cold cache (brief + SIE both run first).
export default function ArticlePanel(props: {
  sessionId: string;
  clusterId: string;
  keyword: string;
  onClose: () => void;
  // Library reader: load the existing article (GET) instead of (re)generating on open.
  readOnly?: boolean;
}) {
  const { sessionId, clusterId, keyword, onClose, readOnly } = props;
  const [status, setStatus] = useState<"running" | "complete" | "error">("running");
  const [article, setArticle] = useState<ArticleOutput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [forceNext, setForceNext] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (status !== "running") return;
    const id = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => window.clearInterval(id);
  }, [status]);

  const run = (force: boolean) => {
    setStatus("running");
    setArticle(null);
    setError(null);
    setElapsed(0);
    let cancelled = false;
    let attempts = 0;

    const poll = async () => {
      attempts += 1;
      try {
        const res = await getArticle(sessionId, clusterId);
        if (cancelled) return;
        if (res.status === "complete" && res.article) {
          setArticle(res.article);
          setStatus("complete");
          if (timer.current) window.clearInterval(timer.current);
        }
      } catch {
        // 404 until generated — keep polling, give up after ~10 min.
        if (attempts > 120 && timer.current) {
          window.clearInterval(timer.current);
          if (!cancelled) {
            setStatus("error");
            setError("Generation timed out. The brief/SIE/writer pass may have failed — check logs.");
          }
        }
      }
    };

    // Read-only open (the Articles library): just fetch the existing article, never generate.
    if (readOnly && !force) {
      getArticle(sessionId, clusterId)
        .then((res) => {
          if (cancelled) return;
          if (res.status === "complete" && res.article) {
            setArticle(res.article);
            setStatus("complete");
          } else {
            setStatus("error");
            setError("No article found for this cluster.");
          }
        })
        .catch((e) => {
          if (!cancelled) {
            setStatus("error");
            setError(e instanceof Error ? e.message : "No article found.");
          }
        });
      return () => { cancelled = true; };
    }

    startArticle(sessionId, clusterId, force ? { force_refresh: true } : undefined)
      .then((res) => {
        if (cancelled) return;
        if (res.status === "complete" && res.article) {
          setArticle(res.article);
          setStatus("complete");
        } else {
          timer.current = window.setInterval(poll, 5000);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setStatus("error");
          setError(e instanceof Error ? e.message : "Failed to start generation");
        }
      });

    return () => {
      cancelled = true;
      if (timer.current) window.clearInterval(timer.current);
    };
  };

  useEffect(() => {
    const cleanup = run(forceNext);
    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, clusterId, forceNext]);

  const meta = (article?.metadata ?? {}) as Record<string, unknown>;
  const num = (k: string) => (typeof meta[k] === "number" ? (meta[k] as number) : undefined);

  const fileSlug = keyword.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "article";
  const copyMarkdown = () => {
    if (article) navigator.clipboard?.writeText(article.article_markdown);
  };
  const downloadMarkdown = () => {
    if (!article) return;
    const blob = new Blob([article.article_markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${fileSlug}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // In-app prompt: clustered keywords that no heading covered. Owner confirms to write
  // each (grouped) one as its own article.
  const unused = (Array.isArray(meta["unused_keywords"]) ? meta["unused_keywords"] : []) as string[];
  const [splitState, setSplitState] = useState<"idle" | "running" | "done" | "dismissed">("idle");
  const [splitMsg, setSplitMsg] = useState<string | null>(null);
  const confirmSplit = async () => {
    setSplitState("running");
    try {
      const res = await splitUncovered(sessionId, clusterId);
      setSplitMsg(
        `Started ${res.submitted} new article${res.submitted === 1 ? "" : "s"} from ${res.uncovered} unused keyword(s).`,
      );
      setSplitState("done");
    } catch (e) {
      setSplitMsg(e instanceof Error ? e.message : "Failed to start split articles");
      setSplitState("idle");
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal card" style={{ maxWidth: 900 }} onClick={(e) => e.stopPropagation()}>
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 className="page-title" style={{ margin: 0 }}>Article — {keyword}</h2>
          <button className="link-btn" onClick={onClose}>Close</button>
        </header>

        {status === "running" && (
          <div style={{ textAlign: "center", padding: "24px 0" }}>
            <div className="spinner" />
            {readOnly ? (
              <p className="progress-stage">Loading article…</p>
            ) : (
              <>
                <p className="progress-stage">Generating the article…</p>
                <p className="progress-meta">
                  Brief + SIE (stage 1) → Writer · {elapsed}s elapsed
                  <br />several minutes on a cold cache
                </p>
              </>
            )}
          </div>
        )}
        {status === "error" && <p className="banner banner-error">{error}</p>}

        {article && (
          <div style={{ display: "grid", gap: 14 }}>
            <div className="muted" style={{ fontSize: 13 }}>
              {num("total_word_count") ?? "?"} words · {num("section_count") ?? "?"} sections ·{" "}
              {num("faq_count") ?? "?"} FAQs · intent {article.intent_type}
              {Array.isArray(meta["under_length_h2_sections"]) &&
                (meta["under_length_h2_sections"] as unknown[]).length > 0 && (
                  <span className="badge badge-warn" style={{ marginLeft: 8 }}>
                    {(meta["under_length_h2_sections"] as unknown[]).length} short section(s)
                  </span>
                )}
            </div>
            {unused.length > 0 && splitState !== "dismissed" && (
              <div className="banner banner-warn" style={{ display: "grid", gap: 8 }}>
                <div>
                  <strong>{unused.length} researched keyword{unused.length === 1 ? "" : "s"} weren't covered by this article:</strong>{" "}
                  <span style={{ fontSize: 13 }}>{unused.join(", ")}</span>
                </div>
                {splitState === "done" ? (
                  <div style={{ fontSize: 13 }}>{splitMsg}</div>
                ) : (
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <button className="btn btn-sm" disabled={splitState === "running"} onClick={confirmSplit}>
                      {splitState === "running" ? "Starting…" : "Write these as separate articles"}
                    </button>
                    <button className="link-btn" onClick={() => setSplitState("dismissed")}>
                      Dismiss
                    </button>
                    {splitMsg && splitState === "idle" && (
                      <span className="form-error" style={{ fontSize: 13 }}>{splitMsg}</span>
                    )}
                  </div>
                )}
              </div>
            )}
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-sm" onClick={() => setForceNext((f) => !f)}>Regenerate</button>
              <button className="btn btn-sm" onClick={copyMarkdown}>Copy Markdown</button>
              <button className="btn btn-sm" onClick={downloadMarkdown}>Download .md</button>
            </div>
            <pre
              style={{
                whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "inherit",
                fontSize: 14, lineHeight: 1.5, background: "var(--surface-2, #f6f8fa)",
                padding: 16, borderRadius: 8, maxHeight: "60vh", overflowY: "auto", margin: 0,
              }}
            >
              {article.article_markdown}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
