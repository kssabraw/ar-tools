import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteSession,
  listAllSessions,
  listClientSessions,
  patchSession,
  type SessionListItem,
} from "../shared/api";
import { AppShell } from "../shared/AppShell";
import { CLIENT_SCOPE, exitClientScope } from "../shared/clientScope";
import { statusLabel, statusClass } from "../shared/sessionStatus";

// Session browser. Research runs are scoped per client (opened from a client's
// Content Scheduler card); the project grouping was removed. When opened without
// a client scope this is a flat owner overview of every session.
export function SessionsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { clientId, clientName } = CLIENT_SCOPE;
  const [showArchived, setShowArchived] = useState(false);

  const allSessions = useQuery({
    queryKey: ["all-sessions", showArchived],
    queryFn: () => listAllSessions(showArchived),
    enabled: !clientId,
  });
  const clientSessions = useQuery({
    queryKey: ["client-sessions", clientId, showArchived],
    queryFn: () => listClientSessions(clientId!, showArchived),
    enabled: !!clientId,
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
              onClick={() => navigate("/session/new")}
            >
              New research session
            </button>
          </div>
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
                onOpen={() => navigate(`/session/${s.id}`)}
                onArchive={(v) => mut.mutate(() => patchSession(s.id, { archived: v }))}
                onDelete={() => mut.mutate(() => deleteSession(s.id))}
              />
            ))}
          </div>
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
}: {
  session: SessionListItem;
  busy: boolean;
  onOpen: () => void;
  onArchive: (archived: boolean) => void;
  onDelete: () => void;
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
