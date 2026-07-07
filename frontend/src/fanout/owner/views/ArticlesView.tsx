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
  setPublishConfig,
  type ArticleListItem,
} from "../../shared/api";
import ArticlePanel from "./ArticlePanel";
import { useSession } from "../SessionWorkspace";

// M15 follow-on — Articles library (owner). Lists every written article (latest per cluster);
// read the full Markdown + Copy / Download .md; bulk .zip; and publish to a GitHub repo as
// Astro content Markdown (single + push-all). Articles live in fanout.article_outputs as the
// source of truth; these are export/publish copies.
export function ArticlesView() {
  const { sessionId } = useSession();
  const [openCluster, setOpenCluster] = useState<{ id: string; name: string } | null>(null);
  const [showGh, setShowGh] = useState(false);

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
  // Publish straight to the linked client's WordPress site as a draft (reuses the
  // suite's WordPress publish); opens the WP editor on success.
  const publishWp = useMutation({
    mutationFn: (clusterId: string) => publishClusterWordpress(sessionId, clusterId, "draft"),
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

  if (q.isLoading) return <p className="muted">Loading articles…</p>;
  if (q.isError) return <p className="form-error">Couldn’t load articles.</p>;

  const articles = q.data?.articles ?? [];
  const gh = session.data?.publish_config?.github ?? {};
  const repoConfigured = !!gh.repo;
  const driveAvailable = !!session.data?.publish_available?.drive;
  const wordpressAvailable = !!session.data?.publish_available?.wordpress;

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

      {articles.length === 0 ? (
        <p className="muted">No articles written yet for this session.</p>
      ) : (
        <table className="kw-table">
          <thead>
            <tr>
              {driveAvailable && (
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
              <th>Article</th><th>Words</th><th>Cost</th><th>Source</th><th>Written</th><th></th>
            </tr>
          </thead>
          <tbody>
            {articles.map((a: ArticleListItem) => {
              const dr = driveResults[a.cluster_id];
              return (
              <tr key={a.cluster_id}>
                {driveAvailable && (
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
                <td className="cell-muted">
                  {a.generated_at ? new Date(a.generated_at).toLocaleString() : "—"}
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="link-btn" onClick={() => setOpenCluster({ id: a.cluster_id, name: a.name })}>
                    Read
                  </button>
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
                      disabled={publishWp.isPending}
                      title="Publish this article to the client's WordPress site as a draft"
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
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
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
