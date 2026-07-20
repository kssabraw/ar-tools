import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteSession,
  listAllSessions,
  listClientSessions,
  patchSession,
  type CopyPlanResult,
  type SessionListItem,
} from "../shared/api";
import { AppShell } from "../shared/AppShell";
import { CLIENT_SCOPE, exitClientScope } from "../shared/clientScope";
import { statusLabel, statusClass, isLiveStatus } from "../shared/sessionStatus";
import { CopyToClientModal } from "./CopyToClientModal";

// While any session in the list is mid-run, poll so it flips to its terminal
// status (e.g. "Ready to plan") on its own — no manual refresh needed. Stops
// once nothing is live.
const LIST_POLL_MS = 5000;
const pollWhileLive = (q: { state: { data?: SessionListItem[] } }) =>
  (q.state.data ?? []).some((s) => isLiveStatus(s.status)) ? LIST_POLL_MS : false;

// Session browser. Research runs are scoped per client (opened from a client's
// Content Scheduler card); the project grouping was removed. When opened without
// a client scope this is a flat owner overview of every session.
export function SessionsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { clientId, clientName } = CLIENT_SCOPE;
  const [showArchived, setShowArchived] = useState(false);
  // The session whose plan is being copied to another client (drives the modal).
  const [copyTarget, setCopyTarget] = useState<SessionListItem | null>(null);

  const onCopied = (result: CopyPlanResult) => {
    setCopyTarget(null);
    alert(
      `Copied ${result.clusters} article${result.clusters === 1 ? "" : "s"} to ` +
        `${result.client_name}. Opening the new plan — schedule it to choose the ` +
        `cadence, start date, and publishing.`,
    );
    navigate(`/fanout/session/${result.new_session_id}`);
  };

  const allSessions = useQuery({
    queryKey: ["all-sessions", showArchived],
    queryFn: () => listAllSessions(showArchived),
    enabled: !clientId,
    refetchInterval: pollWhileLive,
  });
  const clientSessions = useQuery({
    queryKey: ["client-sessions", clientId, showArchived],
    queryFn: () => listClientSessions(clientId!, showArchived),
    enabled: !!clientId,
    refetchInterval: pollWhileLive,
  });
  const sessions = clientId ? clientSessions : allSessions;

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: clientId ? ["client-sessions"] : ["all-sessions"] });
  const mut = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: invalidate,
    onError: (e: Error) => alert(e.message),
  });

  const heading = clientId ? `${clientName ?? "Client"} · Runs` : "Research sessions";
  const emptyText = clientId
    ? "No runs for this client yet."
    : "No research sessions yet.";

  return (
    <AppShell>
      <main className="browser-main">
        <div className="silo-head" style={{ marginBottom: 20 }}>
          <h1 className="page-title" style={{ margin: 0 }}>
            {heading}
          </h1>
          <div className="silo-actions">
            {clientId && (
              <button
                className="btn btn-ghost"
                style={{ width: "auto" }}
                onClick={exitClientScope}
              >
                All clients
              </button>
            )}
            <button
              className="btn btn-primary"
              style={{ width: "auto" }}
              onClick={() => navigate("/fanout/session/new")}
            >
              New research session
            </button>
          </div>
        </div>

        {/* Both content types run on the same keyword research — signpost it so
            the team knows a session can produce either. Each card starts a new
            session with that output preselected. */}
        <div className="intent-grid" style={{ marginBottom: 20 }}>
          <button
            type="button"
            className="intent-card"
            onClick={() => navigate("/fanout/session/new?type=blog_post")}
          >
            <span className="intent-card-title">Blog content</span>
            <span className="intent-card-desc">
              SEO blog articles generated from your keyword research. Publish to your
              site, Google Drive, or GitHub.
            </span>
          </button>
          <button
            type="button"
            className="intent-card"
            onClick={() => navigate("/fanout/session/new?type=local_seo_page")}
          >
            <span className="intent-card-title">Local SEO content</span>
            <span className="intent-card-desc">
              Location-targeted Local SEO pages with competitor analysis and on-page
              scoring, for a client's service area.
            </span>
          </button>
        </div>

        <label className="archived-toggle">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          Show archived
        </label>

        {sessions.isLoading && (
          <div className="project-grid">
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        )}
        {sessions.isError && (
          <p className="form-error">Failed to load sessions. Please try again.</p>
        )}
        {sessions.data && sessions.data.length === 0 && (
          <p className="muted">{emptyText}</p>
        )}
        {sessions.data && sessions.data.length > 0 && (
          <div className="session-list">
            {sessions.data.map((s) => (
              <SessionRow
                key={s.id}
                session={s}
                busy={mut.isPending}
                onOpen={() => navigate(`/fanout/session/${s.id}`)}
                onArchive={(v) => mut.mutate(() => patchSession(s.id, { archived: v }))}
                onDelete={() => mut.mutate(() => deleteSession(s.id))}
                onCopy={() => setCopyTarget(s)}
              />
            ))}
          </div>
        )}

        {copyTarget && (
          <CopyToClientModal
            sessionId={copyTarget.id}
            seedKeyword={copyTarget.seed_keyword}
            clusterCount={copyTarget.cluster_count}
            onClose={() => setCopyTarget(null)}
            onCopied={onCopied}
          />
        )}
      </main>
    </AppShell>
  );
}

function SessionRow({
  session,
  busy,
  onOpen,
  onArchive,
  onDelete,
  onCopy,
}: {
  session: SessionListItem;
  busy: boolean;
  onOpen: () => void;
  onArchive: (archived: boolean) => void;
  onDelete: () => void;
  onCopy: () => void;
}) {
  const [menu, setMenu] = useState(false);

  return (
    <div className={"session-row" + (session.archived ? " session-row-archived" : "")}>
      <button className="session-row-body" onClick={onOpen}>
        <div className="session-row-main">
          <span className="session-row-seed">{session.seed_keyword}</span>
          <span className={"status-pill " + statusClass(session.status)}>
            {statusLabel(session.status)}
          </span>
          {session.archived && <span className="badge">archived</span>}
        </div>
        <div className="session-row-meta">
          <span>{session.coverage_mode}</span>
          <span>·</span>
          <span>{session.cluster_count} articles</span>
          <span>·</span>
          <span>{new Date(session.created_at).toLocaleDateString()}</span>
        </div>
      </button>

      <div className="session-row-actions">
        <button
          className="btn btn-ghost row-menu-btn"
          disabled={busy}
          onClick={() => setMenu((m) => !m)}
        >
          ⋯
        </button>
        {menu && (
          <div className="row-menu" onMouseLeave={() => setMenu(false)}>
            <button onClick={() => { setMenu(false); onCopy(); }}>
              Copy to another client…
            </button>
            <button onClick={() => { setMenu(false); onArchive(!session.archived); }}>
              {session.archived ? "Unarchive" : "Archive"}
            </button>
            <button
              className="row-menu-danger"
              onClick={() => {
                setMenu(false);
                if (confirm(`Permanently delete the "${session.seed_keyword}" session and all its data?`)) onDelete();
              }}
            >
              Delete
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
