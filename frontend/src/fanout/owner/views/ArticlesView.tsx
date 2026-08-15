import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  downloadAllArticles,
  getSession,
  listArticles,
  publishAllGithub,
  publishClusterDrive,
  publishClusterGithub,
  publishClusterWordpress,
  reoptimizeArticle,
  reoptJobsStatus,
  scoreArticle,
  setPublishConfig,
  type ArticleListItem,
} from "../../shared/api";
import ArticlePanel from "./ArticlePanel";
import { useSession } from "../SessionWorkspace";
import { ReoptimizePanel } from "../../../components/reoptimize/ReoptimizePanel";
import { fanoutAdapter } from "../../../components/reoptimize/adapters";

// Per-row reoptimize state for the inline Score / Reoptimize actions.
type ReoptRow =
  | { status: "working"; kind: "score" | "reopt" }
  | { status: "done"; kind: "score" | "reopt"; prev?: number | null; next?: number | null }
  | { status: "failed"; error: string };

// M15 follow-on — Articles library (owner). Lists every written article (latest per cluster);
// read the full Markdown + Copy / Download .md; bulk .zip; and publish to a GitHub repo as
// Astro content Markdown (single + push-all). Articles live in fanout.article_outputs as the
// source of truth; these are export/publish copies.
export function ArticlesView() {
  const { sessionId, clientId } = useSession();
  const [openCluster, setOpenCluster] = useState<{ id: string; name: string } | null>(null);
  const [showGh, setShowGh] = useState(false);
  const [showReopt, setShowReopt] = useState(false);
  // WordPress publish status for both the single "Website" button and the bulk
  // action: draft (default, safe) or publish (live).
  const [wpStatus, setWpStatus] = useState<"draft" | "publish">("draft");

  const session = useQuery({ queryKey: ["session", sessionId], queryFn: () => getSession(sessionId) });
  const q = useQuery({
    queryKey: ["articles", sessionId],
    queryFn: () => listArticles(sessionId),
    refetchInterval: 20000,
  });
  const downloadAll = useMutation({
    mutationFn: () => downloadAllArticles(sessionId),
    onSuccess: (res) => window.open(res.download_url, "_blank", "noopener"),
    onError: (e: Error) => alert(e.message),
  });
  const pushAll = useMutation({
    mutationFn: () => publishAllGithub(sessionId),
    onSuccess: (res) => alert(`Committed ${res.committed} article(s) to GitHub.`),
    onError: (e: Error) => alert(e.message),
  });
  const pushOne = useMutation({
    mutationFn: (clusterId: string) => publishClusterGithub(sessionId, clusterId),
    onSuccess: (res) => res.html_url && window.open(res.html_url, "_blank", "noopener"),
    onError: (e: Error) => alert(e.message),
  });
  const saveDrive = useMutation({
    mutationFn: (clusterId: string) => publishClusterDrive(sessionId, clusterId),
    onSuccess: (res) => res.url && window.open(res.url, "_blank", "noopener"),
    onError: (e: Error) => alert(e.message),
  });
  // Publish straight to the linked client's WordPress site (reuses the suite's
  // WordPress publish); opens the WP editor/post on success. `wpStatus` picks
  // draft (default) vs live.
  const publishWp = useMutation({
    mutationFn: (clusterId: string) => publishClusterWordpress(sessionId, clusterId, wpStatus),
    onSuccess: (res) => {
      const link = res.edit_url || res.url;
      if (link) window.open(link, "_blank", "noopener");
    },
    onError: (e: Error) => alert(e.message),
  });

  // Bulk "Save to Drive": tick articles, then publish them all to Google Docs in
  // one action. Client-side fan-out over the per-article endpoint (small
  // concurrency cap) so no new backend surface is needed; per-row outcomes are
  // tracked in `driveResults`.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [driveResults, setDriveResults] = useState<
    Record<string, { status: "done" | "failed"; url?: string | null; error?: string }>
  >({});
  const [wpResults, setWpResults] = useState<
    Record<string, { status: "done" | "failed"; url?: string | null; edit_url?: string | null; error?: string }>
  >({});

  // Inline per-row reoptimize: Score (re-run the blog/AEO scorer) or Reoptimize
  // (score → rewrite-to-threshold → reflect the improved article back). Each runs
  // as a background job; we poll it and refetch the list so the score badge
  // updates. Leaving the tab keeps the job running server-side (async_jobs).
  const [reoptRows, setReoptRows] = useState<Record<string, ReoptRow>>({});

  const pollReoptJob = async (clusterId: string, jobId: string, kind: "score" | "reopt") => {
    for (;;) {
      await new Promise((r) => setTimeout(r, 5000));
      try {
        const { jobs } = await reoptJobsStatus(sessionId, [jobId]);
        const st = jobs.find((j) => j.job_id === jobId);
        if (!st) continue;
        if (st.status === "complete") {
          const res = st.result ?? {};
          setReoptRows((r) => ({
            ...r,
            [clusterId]:
              kind === "score"
                ? { status: "done", kind, next: res.composite_score ?? null }
                : { status: "done", kind, prev: res.prev_score ?? null, next: res.new_score ?? null },
          }));
          void q.refetch();
          return;
        }
        if (st.status === "failed") {
          setReoptRows((r) => ({ ...r, [clusterId]: { status: "failed", error: st.error ?? "Failed" } }));
          return;
        }
      } catch {
        // transient poll failure — keep waiting
      }
    }
  };

  const startReopt = async (clusterId: string, kind: "score" | "reopt") => {
    setReoptRows((r) => ({ ...r, [clusterId]: { status: "working", kind } }));
    try {
      const { job_id } =
        kind === "score"
          ? await scoreArticle(sessionId, clusterId)
          : await reoptimizeArticle(sessionId, clusterId);
      void pollReoptJob(clusterId, job_id, kind);
    } catch (e) {
      setReoptRows((r) => ({
        ...r,
        [clusterId]: { status: "failed", error: e instanceof Error ? e.message : "Failed" },
      }));
    }
  };

  if (q.isLoading) return <p className="muted">Loading articles…</p>;
  if (q.isError) return <p className="form-error">Couldn’t load articles.</p>;

  const articles = q.data?.articles ?? [];
  const gh = session.data?.publish_config?.github ?? {};
  const repoConfigured = !!gh.repo;
  const driveAvailable = !!session.data?.publish_available?.drive;
  const wordpressAvailable = !!session.data?.publish_available?.wordpress;
  // The tick-boxes drive both bulk actions (Drive + WordPress), so show them when
  // either destination is available.
  const bulkSelectable = driveAvailable || wordpressAvailable;

  const allIds = articles.map((a: ArticleListItem) => a.cluster_id);
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id));
  const selectedCount = selected.size;
  const toggleOne = (id: string, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
  const toggleAll = (on: boolean) => setSelected(on ? new Set(allIds) : new Set());

  const bulkSaveDrive = async () => {
    const queue = articles
      .filter((a: ArticleListItem) => selected.has(a.cluster_id))
      .map((a: ArticleListItem) => a.cluster_id);
    if (!queue.length || bulkBusy) return;
    setBulkBusy(true);
    setDriveResults({});
    const CONCURRENCY = 3;
    let next = 0;
    const succeeded: string[] = [];
    const worker = async () => {
      for (;;) {
        const cur = next++;
        if (cur >= queue.length) return;
        const id = queue[cur];
        try {
          const res = await publishClusterDrive(sessionId, id);
          succeeded.push(id);
          setDriveResults((r) => ({ ...r, [id]: { status: "done", url: res.url } }));
        } catch (e) {
          setDriveResults((r) => ({
            ...r,
            [id]: { status: "failed", error: e instanceof Error ? e.message : "Failed" },
          }));
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker));
    setBulkBusy(false);
    // Drop the ones that published cleanly; leave failures ticked for retry.
    setSelected((prev) => {
      const n = new Set(prev);
      for (const id of succeeded) n.delete(id);
      return n;
    });
  };

  // Bulk "Publish to Website": tick articles, then publish them all to the
  // client's WordPress site in one action (draft or live per `wpStatus`).
  // Client-side fan-out over the per-article endpoint at a small concurrency so
  // the freshly-whitelisted site isn't hit with a burst; per-row outcomes in
  // `wpResults`.
  const bulkPublishWp = async () => {
    const queue = articles
      .filter((a: ArticleListItem) => selected.has(a.cluster_id))
      .map((a: ArticleListItem) => a.cluster_id);
    if (!queue.length || bulkBusy) return;
    setBulkBusy(true);
    setWpResults({});
    const CONCURRENCY = 2;
    let next = 0;
    const succeeded: string[] = [];
    const worker = async () => {
      for (;;) {
        const cur = next++;
        if (cur >= queue.length) return;
        const id = queue[cur];
        try {
          const res = await publishClusterWordpress(sessionId, id, wpStatus);
          succeeded.push(id);
          setWpResults((r) => ({ ...r, [id]: { status: "done", url: res.url, edit_url: res.edit_url } }));
        } catch (e) {
          setWpResults((r) => ({
            ...r,
            [id]: { status: "failed", error: e instanceof Error ? e.message : "Failed" },
          }));
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker));
    setBulkBusy(false);
    // Drop the ones that published cleanly; leave failures ticked for retry.
    setSelected((prev) => {
      const n = new Set(prev);
      for (const id of succeeded) n.delete(id);
      return n;
    });
  };

  return (
    <div>
      <div className="edit-toolbar">
        <button
          className="btn btn-ghost"
          style={{ width: "auto" }}
          disabled={articles.length === 0 || downloadAll.isPending}
          title="Download every written article as a .zip of Markdown files"
          onClick={() => downloadAll.mutate()}
        >
          {downloadAll.isPending ? "Zipping…" : "Download all (.zip)"}
        </button>
        <button className="btn btn-ghost" style={{ width: "auto" }} onClick={() => setShowGh((s) => !s)}>
          Publish settings
        </button>
        {clientId && (
          <button
            className="btn btn-ghost"
            style={{ width: "auto" }}
            title="Score and rewrite existing articles to fix their weaknesses (bulk)"
            onClick={() => setShowReopt((s) => !s)}
          >
            {showReopt ? "Hide reoptimize" : "Reoptimize articles"}
          </button>
        )}
        <button
          className="btn btn-ghost"
          style={{ width: "auto" }}
          disabled={!repoConfigured || articles.length === 0 || pushAll.isPending}
          title={repoConfigured ? "Commit every article to the repo in one commit" : "Configure a GitHub repo first"}
          onClick={() => pushAll.mutate()}
        >
          {pushAll.isPending ? "Pushing…" : "Push all to GitHub"}
        </button>
        {driveAvailable && (
          <button
            className="btn btn-primary"
            style={{ width: "auto" }}
            disabled={selectedCount === 0 || bulkBusy}
            title="Save the ticked articles to Google Drive as Google Docs"
            onClick={() => void bulkSaveDrive()}
          >
            {bulkBusy ? "Saving…" : selectedCount ? `Save ${selectedCount} to Drive` : "Save to Drive"}
          </button>
        )}
        {wordpressAvailable && (
          <>
            <select
              className="input"
              style={{ width: "auto" }}
              value={wpStatus}
              disabled={bulkBusy}
              title="Publish WordPress posts as drafts (review before going live) or live"
              onChange={(e) => setWpStatus(e.target.value as "draft" | "publish")}
            >
              <option value="draft">WordPress: Draft</option>
              <option value="publish">WordPress: Live</option>
            </select>
            <button
              className="btn btn-primary"
              style={{ width: "auto" }}
              disabled={selectedCount === 0 || bulkBusy}
              title={`Publish the ticked articles to the client's WordPress site as ${wpStatus === "publish" ? "live posts" : "drafts"}`}
              onClick={() => void bulkPublishWp()}
            >
              {bulkBusy
                ? "Publishing…"
                : selectedCount
                  ? `Publish ${selectedCount} to Website`
                  : "Publish to Website"}
            </button>
          </>
        )}
        <span className="muted">
          {articles.length} written article{articles.length === 1 ? "" : "s"} · stored in the app.
        </span>
      </div>

      {showGh && (
        <PublishSettings
          sessionId={sessionId}
          gh={gh}
          driveFolder={session.data?.publish_config?.drive?.folder_id ?? ""}
          driveAvailable={driveAvailable}
          onSaved={() => session.refetch()}
        />
      )}

      {showReopt && clientId && (
        <div style={{ marginBottom: 14 }}>
          <ReoptimizePanel adapter={fanoutAdapter(clientId)} />
        </div>
      )}

      {articles.length === 0 ? (
        <p className="muted">No articles written yet for this session.</p>
      ) : (
        <div className="scroll-x">
          <table className="kw-table">
            <thead>
              <tr>
                {bulkSelectable && (
                  <th style={{ width: 28 }}>
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={(e) => toggleAll(e.target.checked)}
                      disabled={bulkBusy}
                      title="Select all"
                    />
                  </th>
                )}
                <th>Article</th><th>Words</th><th>Cost</th><th>Source</th><th>Score</th><th>Written</th><th></th>
              </tr>
            </thead>
            <tbody>
              {articles.map((a: ArticleListItem) => {
                const dr = driveResults[a.cluster_id];
                const wr = wpResults[a.cluster_id];
                const rr = reoptRows[a.cluster_id];
                return (
                <tr key={a.cluster_id}>
                  {bulkSelectable && (
                    <td>
                      <input
                        type="checkbox"
                        checked={selected.has(a.cluster_id)}
                        onChange={(e) => toggleOne(a.cluster_id, e.target.checked)}
                        disabled={bulkBusy}
                      />
                    </td>
                  )}
                  <td>{a.name}</td>
                  <td>{a.total_word_count ?? "—"}</td>
                  <td>{a.cost_usd != null ? `$${Number(a.cost_usd).toFixed(2)}` : "—"}</td>
                  <td><span className="badge">{a.scheduled ? "scheduled" : "ad-hoc"}</span></td>
                  <td>{a.composite_score != null ? Math.round(a.composite_score) : "—"}</td>
                  <td className="cell-muted">
                    {a.generated_at ? new Date(a.generated_at).toLocaleString() : "—"}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="link-btn" onClick={() => setOpenCluster({ id: a.cluster_id, name: a.name })}>
                      Read
                    </button>
                    {a.reoptimizable && (
                      <>
                        <button
                          className="link-btn"
                          style={{ marginLeft: 10 }}
                          disabled={rr?.status === "working"}
                          title="Score this article against the blog/AEO rubric"
                          onClick={() => void startReopt(a.cluster_id, "score")}
                        >
                          Score
                        </button>
                        <button
                          className="link-btn"
                          style={{ marginLeft: 10 }}
                          disabled={rr?.status === "working"}
                          title="Score, then rewrite this article to fix its weaknesses"
                          onClick={() => void startReopt(a.cluster_id, "reopt")}
                        >
                          Reoptimize
                        </button>
                        {rr?.status === "working" && (
                          <span style={{ marginLeft: 10, color: "#64748b" }}>
                            {rr.kind === "score" ? "Scoring…" : "Reoptimizing…"}
                          </span>
                        )}
                        {rr?.status === "done" && (
                          <span style={{ marginLeft: 10, color: "#16a34a", fontWeight: 600 }}>
                            {rr.kind === "score"
                              ? `Scored ${rr.next != null ? Math.round(rr.next) : "—"}`
                              : `${rr.prev != null ? Math.round(rr.prev) : "—"} → ${rr.next != null ? Math.round(rr.next) : "—"}`}
                          </span>
                        )}
                        {rr?.status === "failed" && (
                          <span style={{ marginLeft: 10, color: "#dc2626" }} title={rr.error}>Reopt failed</span>
                        )}
                      </>
                    )}
                    {repoConfigured && (
                      <button
                        className="link-btn"
                        style={{ marginLeft: 10 }}
                        disabled={pushOne.isPending}
                        title="Commit this article to the GitHub repo"
                        onClick={() => pushOne.mutate(a.cluster_id)}
                      >
                        GitHub
                      </button>
                    )}
                    {driveAvailable && (
                      <button
                        className="link-btn"
                        style={{ marginLeft: 10 }}
                        disabled={saveDrive.isPending || bulkBusy}
                        title="Save this article to Google Drive as a Google Doc"
                        onClick={() => saveDrive.mutate(a.cluster_id)}
                      >
                        Drive
                      </button>
                    )}
                    {wordpressAvailable && (
                      <button
                        className="link-btn"
                        style={{ marginLeft: 10 }}
                        disabled={publishWp.isPending || bulkBusy}
                        title={`Publish this article to the client's WordPress site as ${wpStatus === "publish" ? "a live post" : "a draft"}`}
                        onClick={() => publishWp.mutate(a.cluster_id)}
                      >
                        Website
                      </button>
                    )}
                    {dr?.status === "done" && (
                      dr.url
                        ? <a href={dr.url} target="_blank" rel="noopener noreferrer" className="link-btn" style={{ marginLeft: 10, color: "#16a34a" }}>Open Doc ↗</a>
                        : <span style={{ marginLeft: 10, color: "#16a34a", fontWeight: 600 }}>Saved</span>
                    )}
                    {dr?.status === "failed" && (
                      <span style={{ marginLeft: 10, color: "#dc2626" }} title={dr.error}>Failed</span>
                    )}
                    {wr?.status === "done" && (
                      (wr.edit_url || wr.url)
                        ? <a href={wr.edit_url || wr.url || undefined} target="_blank" rel="noopener noreferrer" className="link-btn" style={{ marginLeft: 10, color: "#16a34a" }}>Open post ↗</a>
                        : <span style={{ marginLeft: 10, color: "#16a34a", fontWeight: 600 }}>Published</span>
                    )}
                    {wr?.status === "failed" && (
                      <span style={{ marginLeft: 10, color: "#dc2626" }} title={wr.error}>WP failed</span>
                    )}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {openCluster && (
        <ArticlePanel
          sessionId={sessionId}
          clusterId={openCluster.id}
          keyword={openCluster.name}
          readOnly
          onClose={() => setOpenCluster(null)}
        />
      )}
    </div>
  );
}

function PublishSettings(p: {
  sessionId: string;
  gh: { repo?: string; branch?: string; content_path?: string };
  driveFolder: string;
  driveAvailable: boolean;
  onSaved: () => void;
}) {
  const [repo, setRepo] = useState(p.gh.repo ?? "");
  const [branch, setBranch] = useState(p.gh.branch ?? "main");
  const [path, setPath] = useState(p.gh.content_path ?? "src/content/blog");
  const [folder, setFolder] = useState(p.driveFolder);
  const save = useMutation({
    mutationFn: () => setPublishConfig(p.sessionId, {
      github_repo: repo.trim(), github_branch: branch.trim(), github_content_path: path.trim(),
      drive_folder_id: folder.trim(),
    }),
    onSuccess: () => p.onSaved(),
    onError: (e: Error) => alert(e.message),
  });
  return (
    <div className="card" style={{ display: "grid", gap: 12, marginBottom: 14, maxWidth: 560 }}>
      <strong style={{ fontSize: 14 }}>GitHub</strong>
      <div className="muted" style={{ fontSize: 13, marginTop: -6 }}>
        Articles commit as Astro content Markdown to{" "}
        <code>{path || "src/content/blog"}/&#123;silo&#125;/&#123;slug&#125;.md</code>. The server needs a
        GitHub token with Contents:write on this repo.
      </div>
      <label className="field">
        <span className="field-label">Repo (owner/name)</span>
        <input className="input" placeholder="owner/repo" value={repo} onChange={(e) => setRepo(e.target.value)} />
      </label>
      <div style={{ display: "flex", gap: 12 }}>
        <label className="field" style={{ flex: 1 }}>
          <span className="field-label">Branch</span>
          <input className="input" value={branch} onChange={(e) => setBranch(e.target.value)} />
        </label>
        <label className="field" style={{ flex: 2 }}>
          <span className="field-label">Content path</span>
          <input className="input" value={path} onChange={(e) => setPath(e.target.value)} />
        </label>
      </div>

      <strong style={{ fontSize: 14, marginTop: 4 }}>Google Drive</strong>
      <div className="muted" style={{ fontSize: 13, marginTop: -6 }}>
        {p.driveAvailable
          ? "Save articles as Google Docs into this folder (leave blank for your Drive root)."
          : "Not configured on the server yet (needs the Google OAuth credentials)."}
      </div>
      <label className="field">
        <span className="field-label">Drive folder ID</span>
        <input className="input" placeholder="folder id from the Drive URL" value={folder}
          onChange={(e) => setFolder(e.target.value)} disabled={!p.driveAvailable} />
      </label>

      <div>
        <button className="btn btn-primary" style={{ width: "auto" }} disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
