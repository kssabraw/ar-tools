import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  downloadAllArticles,
  getSession,
  listArticles,
  publishAllGithub,
  publishClusterDrive,
  publishClusterGithub,
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

  if (q.isLoading) return <p className="muted">Loading articles…</p>;
  if (q.isError) return <p className="form-error">Couldn’t load articles.</p>;

  const articles = q.data?.articles ?? [];
  const gh = session.data?.publish_config?.github ?? {};
  const repoConfigured = !!gh.repo;
  const driveAvailable = !!session.data?.publish_available?.drive;

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
            <tr><th>Article</th><th>Words</th><th>Cost</th><th>Source</th><th>Written</th><th></th></tr>
          </thead>
          <tbody>
            {articles.map((a: ArticleListItem) => (
              <tr key={a.cluster_id}>
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
                      disabled={saveDrive.isPending}
                      title="Save this article to Google Drive as a Google Doc"
                      onClick={() => saveDrive.mutate(a.cluster_id)}
                    >
                      Drive
                    </button>
                  )}
                </td>
              </tr>
            ))}
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
