import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelSchedule,
  getClusters,
  getSession,
  listScheduleRuns,
  listSchedules,
  pauseSchedule,
  resumeSchedule,
  type ContentSchedule,
} from "../../shared/api";
import { ScheduleModal } from "../../shared/ScheduleModal";
import { useSession } from "../SessionWorkspace";

// M15 Schedule overview (handoff §9.7): the session's batches with live progress + the runs
// table. "Schedule all" opens the modal for the whole session. Both roles (VAs schedule on
// own sessions, §9.9 #4); the $90 gate lives in the modal/API.
export function ScheduleView() {
  const { sessionId } = useSession();
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);

  const session = useQuery({ queryKey: ["session", sessionId], queryFn: () => getSession(sessionId) });
  const clustersQ = useQuery({ queryKey: ["clusters", sessionId], queryFn: () => getClusters(sessionId) });
  const schedulesQ = useQuery({
    queryKey: ["schedules", sessionId],
    queryFn: () => listSchedules(sessionId),
    refetchInterval: 15000,
  });
  const runsQ = useQuery({
    queryKey: ["schedule-runs", sessionId],
    queryFn: () => listScheduleRuns(sessionId),
    refetchInterval: 15000,
  });

  const clusterName = useMemo(() => {
    const m = new Map<string, string>();
    clustersQ.data?.clusters.forEach((c) => m.set(c.id, c.name));
    return (id: string) => m.get(id) ?? id.slice(0, 8);
  }, [clustersQ.data]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["schedules", sessionId] });
    qc.invalidateQueries({ queryKey: ["schedule-runs", sessionId] });
  };
  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: invalidate,
    onError: (e: Error) => alert(e.message),
  });

  const schedules = schedulesQ.data?.schedules ?? [];
  const runs = runsQ.data?.runs ?? [];

  return (
    <div>
      <div className="edit-toolbar">
        <button className="btn btn-primary" style={{ width: "auto" }} onClick={() => setShowModal(true)}>
          Schedule all…
        </button>
        <span className="muted">Articles write automatically at their scheduled time (a few drain at once).</span>
      </div>

      {showModal && (
        <ScheduleModal
          sessionId={sessionId}
          baseUrl={session.data?.site_base_url}
          onClose={() => setShowModal(false)}
          onScheduled={(n) => { invalidate(); alert(`Scheduled ${n} article(s).`); }}
        />
      )}

      {schedules.length === 0 ? (
        <p className="muted">No schedules yet. “Schedule all” to queue articles for automatic writing.</p>
      ) : (
        <div style={{ display: "grid", gap: 10, marginBottom: 18 }}>
          {schedules.map((s) => (
            <ScheduleCard key={s.id} s={s} busy={act.isPending}
              onPause={() => act.mutate(() => pauseSchedule(sessionId, s.id))}
              onResume={() => act.mutate(() => resumeSchedule(sessionId, s.id))}
              onCancel={() => {
                if (confirm("Cancel this schedule? Pending articles won’t be written (already-written ones stay)."))
                  act.mutate(() => cancelSchedule(sessionId, s.id));
              }}
            />
          ))}
        </div>
      )}

      {runs.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Runs ({runs.length})</h3>
          <table className="kw-table">
            <thead>
              <tr><th>Article</th><th>Scheduled</th><th>Status</th><th>Note</th></tr>
            </thead>
            <tbody>
              {runs.slice(0, 500).map((r) => (
                <tr key={r.id}>
                  <td>{clusterName(r.cluster_id)}</td>
                  <td>{new Date(r.scheduled_at).toLocaleString()}</td>
                  <td><span className={"badge " + statusBadge(r.status)}>{r.status}</span></td>
                  <td className="cell-muted" style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {r.error ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ScheduleCard(p: {
  s: ContentSchedule;
  busy: boolean;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
}) {
  const { s } = p;
  const pr = s.progress ?? {};
  const done = (pr.complete ?? 0) + (pr.failed ?? 0) + (pr.cancelled ?? 0);
  const total = pr.total ?? s.total_count;
  const label =
    s.mode === "all_at_once" ? "All at once"
      : s.mode === "fixed" ? `On ${s.start_date}`
        : `Drip ${s.per_day}/day from ${s.start_date}`;
  return (
    <div className="card" style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px" }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600 }}>
          {label} <span className={"badge " + scheduleBadge(s.status)}>{s.status}</span>
        </div>
        <div className="muted" style={{ fontSize: 13 }}>
          {done} / {total} done
          {pr.failed ? ` · ${pr.failed} failed` : ""}
          {pr.running ? ` · ${pr.running} writing` : ""}
        </div>
      </div>
      {s.status === "active" && (
        <button className="btn btn-sm" disabled={p.busy} onClick={p.onPause}>Pause</button>
      )}
      {s.status === "paused" && (
        <button className="btn btn-sm" disabled={p.busy} onClick={p.onResume}>Resume</button>
      )}
      {(s.status === "active" || s.status === "paused") && (
        <button className="link-btn link-danger" disabled={p.busy} onClick={p.onCancel}>Cancel</button>
      )}
    </div>
  );
}

function statusBadge(s: string): string {
  if (s === "complete") return "badge-rel";
  if (s === "failed") return "badge-warn";
  if (s === "running") return "badge-rel";
  if (s === "cancelled") return "badge-warn";
  return "";
}
function scheduleBadge(s: string): string {
  if (s === "complete") return "badge-rel";
  if (s === "cancelled" || s === "paused") return "badge-warn";
  return "badge-rel";
}
