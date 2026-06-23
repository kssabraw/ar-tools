import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteSession,
  getProjects,
  listSessions,
  patchSession,
  type Project,
  type SessionListItem,
} from "../shared/api";
import { AppShell } from "../shared/AppShell";
import { statusLabel, statusClass } from "../shared/sessionStatus";

// Project + Session Browser (PRD §9.4). Left rail lists projects; the main pane
// lists the selected project's sessions, resumes any of them, and supports the
// §9.4 mutations: archive/unarchive, move to another project, delete.
export function ProjectsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects });
  const [selected, setSelected] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  useEffect(() => {
    if (!selected && projects.data && projects.data.length > 0) {
      setSelected(projects.data[0].id);
    }
  }, [projects.data, selected]);

  const sessions = useQuery({
    queryKey: ["sessions", selected, showArchived],
    queryFn: () => listSessions(selected!, showArchived),
    enabled: !!selected,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["sessions"] });
  const mut = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: invalidate,
    onError: (e: Error) => alert(e.message),
  });

  const selectedProject = projects.data?.find((p) => p.id === selected);

  return (
    <AppShell>
      <div className="browser-layout">
        <aside className="browser-rail">
          <div className="browser-rail-head">Projects</div>
          {projects.isLoading && <p className="muted" style={{ padding: "0 14px" }}>Loading…</p>}
          {projects.data?.map((p) => (
            <button
              key={p.id}
              className={"rail-item" + (p.id === selected ? " rail-item-active" : "")}
              onClick={() => setSelected(p.id)}
            >
              <span className="rail-item-name">{p.name}</span>
              {p.is_scratch && <span className="tag-scratch">Scratch</span>}
            </button>
          ))}
        </aside>

        <main className="browser-main">
          <div className="silo-head" style={{ marginBottom: 20 }}>
            <h1 className="page-title" style={{ margin: 0 }}>
              {selectedProject?.name ?? "Sessions"}
            </h1>
            <button
              className="btn btn-primary"
              style={{ width: "auto" }}
              onClick={() => navigate("/session/new")}
            >
              New research session
            </button>
          </div>

          <label className="archived-toggle">
            <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
            Show archived
          </label>

          {sessions.isLoading && (
            <div className="project-grid">
              <div className="skeleton" />
              <div className="skeleton" />
            </div>
          )}
          {sessions.isError && <p className="form-error">Failed to load sessions. Please try again.</p>}
          {sessions.data && sessions.data.length === 0 && (
            <p className="muted">No sessions in this project yet.</p>
          )}
          {sessions.data && sessions.data.length > 0 && (
            <div className="session-list">
              {sessions.data.map((s) => (
                <SessionRow
                  key={s.id}
                  session={s}
                  projects={projects.data ?? []}
                  currentProjectId={selected!}
                  busy={mut.isPending}
                  onOpen={() => navigate(`/session/${s.id}`)}
                  onArchive={(v) => mut.mutate(() => patchSession(s.id, { archived: v }))}
                  onMove={(pid) => mut.mutate(() => patchSession(s.id, { project_id: pid }))}
                  onDelete={() => mut.mutate(() => deleteSession(s.id))}
                />
              ))}
            </div>
          )}
        </main>
      </div>
    </AppShell>
  );
}

function SessionRow({
  session,
  projects,
  currentProjectId,
  busy,
  onOpen,
  onArchive,
  onMove,
  onDelete,
}: {
  session: SessionListItem;
  projects: Project[];
  currentProjectId: string;
  busy: boolean;
  onOpen: () => void;
  onArchive: (archived: boolean) => void;
  onMove: (projectId: string) => void;
  onDelete: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const otherProjects = projects.filter((p) => p.id !== currentProjectId);

  return (
    <div className={"session-row" + (session.archived ? " session-row-archived" : "")}>
      <button className="session-row-body" onClick={onOpen}>
        <div className="session-row-main">
          <span className="session-row-seed">{session.seed_keyword}</span>
          <span className={"status-pill " + statusClass(session.status)}>{statusLabel(session.status)}</span>
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
        <button className="btn btn-ghost row-menu-btn" disabled={busy} onClick={() => setMenu((m) => !m)}>⋯</button>
        {menu && (
          <div className="row-menu" onMouseLeave={() => setMenu(false)}>
            <button onClick={() => { setMenu(false); onArchive(!session.archived); }}>
              {session.archived ? "Unarchive" : "Archive"}
            </button>
            {otherProjects.length > 0 && (
              <div className="row-menu-sub">
                <span className="row-menu-label">Move to…</span>
                {otherProjects.map((p) => (
                  <button key={p.id} onClick={() => { setMenu(false); onMove(p.id); }}>{p.name}</button>
                ))}
              </div>
            )}
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
