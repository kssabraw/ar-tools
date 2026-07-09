import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelSchedule,
  cancelScheduleRun,
  getClusters,
  getSession,
  listScheduleRuns,
  listSchedules,
  pauseSchedule,
  reinstateScheduleRun,
  resumeSchedule,
  updateScheduleCadence,
  updateSchedulePublishTargets,
  type ContentSchedule,
  type ScheduleRequest,
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
          extraLinkUrls={session.data?.extra_link_urls}
          defaultContentType={session.data?.content_type}
          defaultLocation={session.data?.location}
          clientId={session.data?.client_id}
          locationCode={session.data?.location_code}
          wordpressAvailable={session.data?.publish_available?.wordpress}
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
              clientLinked={!!session.data?.client_id}
              wordpressAvailable={!!session.data?.publish_available?.wordpress}
              onPause={() => act.mutate(() => pauseSchedule(sessionId, s.id))}
              onResume={() => act.mutate(() => resumeSchedule(sessionId, s.id))}
              onCancel={() => {
                if (confirm("Cancel this schedule? Pending articles won’t be written (already-written ones stay)."))
                  act.mutate(() => cancelSchedule(sessionId, s.id));
              }}
              onUpdateTargets={(body) =>
                act.mutate(() => updateSchedulePublishTargets(sessionId, s.id, body))}
              onUpdateCadence={(body) =>
                act.mutate(() => updateScheduleCadence(sessionId, s.id, body))}
            />
          ))}
        </div>
      )}

      {runs.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Scheduled articles ({runs.length})</h3>
          <table className="kw-table">
            <thead>
              <tr><th>Article</th><th>Scheduled</th><th>Status</th><th>Note</th><th></th></tr>
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
                  <td style={{ textAlign: "right" }}>
                    {r.status === "queued" && (
                      <button
                        className="link-btn link-danger"
                        disabled={act.isPending}
                        onClick={() => {
                          if (confirm(`Cancel “${clusterName(r.cluster_id)}”? The rest move up to fill its slot.`))
                            act.mutate(() => cancelScheduleRun(sessionId, r.id));
                        }}
                      >
                        Cancel
                      </button>
                    )}
                    {r.status === "cancelled" && (
                      <button
                        className="link-btn"
                        disabled={act.isPending}
                        onClick={() => act.mutate(() => reinstateScheduleRun(sessionId, r.id))}
                      >
                        Reinstate
                      </button>
                    )}
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
  clientLinked: boolean;
  wordpressAvailable: boolean;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onUpdateTargets: (body: { auto_publish?: boolean; wp_publish?: boolean; wp_status?: "draft" | "publish" }) => void;
  onUpdateCadence: (body: {
    mode: ScheduleRequest["mode"]; per_day?: number; start_date?: string;
    time_of_day?: string; timezone?: string; weekday?: number; weekdays?: number[];
    day_of_month?: number; week_of_month?: number;
  }) => void;
}) {
  const { s } = p;
  // Publish destinations are editable only while paused (forward-only — applies to
  // articles not yet written). Blog/local-SEO/service all support both targets on a
  // client-linked session; WordPress additionally needs the client WP-configured.
  const canEditTargets = s.status === "paused";
  const pr = s.progress ?? {};
  const done = (pr.complete ?? 0) + (pr.failed ?? 0) + (pr.cancelled ?? 0);
  const total = pr.total ?? s.total_count;
  const label =
    s.mode === "all_at_once" ? "All at once"
      : s.mode === "fixed" ? `On ${s.start_date}`
        : s.mode === "weekly" ? `${s.per_day}/week from ${s.start_date}`
          : s.mode === "monthly_date" ? `${s.per_day}/month from ${s.start_date}`
            : s.mode === "monthly_weekday" ? `${s.per_day}/month from ${s.start_date}`
              : `Drip ${s.per_day}/day from ${s.start_date}`;
  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "12px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600 }}>
            {label} <span className={"badge " + scheduleBadge(s.status)}>{s.status}</span>
            {s.auto_publish && (
              <span className="badge badge-rel" style={{ marginLeft: 6 }} title="Each finished piece is auto-published to the client's Google Drive folder">
                ⬆ Drive
              </span>
            )}
            {s.wp_publish && (
              <span
                className="badge badge-rel"
                style={{ marginLeft: 6 }}
                title={
                  s.wp_status === "publish"
                    ? "Each finished article goes live on the client's WordPress site"
                    : "Each finished article is created as a draft on the client's WordPress site"
                }
              >
                ⬆ WordPress{s.wp_status === "publish" ? " (live)" : " (draft)"}
              </span>
            )}
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

      {canEditTargets && (p.clientLinked || p.wordpressAvailable) && (
        <div style={{ borderTop: "1px solid var(--border, #e5e7eb)", paddingTop: 8 }}>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
            Publish destinations for the remaining articles (paused — takes effect on resume):
          </div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
            {p.clientLinked && (
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14 }}>
                <input
                  type="checkbox"
                  disabled={p.busy}
                  checked={!!s.auto_publish}
                  onChange={(e) => p.onUpdateTargets({ auto_publish: e.target.checked })}
                />
                Google Drive
              </label>
            )}
            {p.wordpressAvailable && (
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14 }}>
                <input
                  type="checkbox"
                  disabled={p.busy}
                  checked={!!s.wp_publish}
                  onChange={(e) => p.onUpdateTargets({ wp_publish: e.target.checked })}
                />
                WordPress
              </label>
            )}
            {p.wordpressAvailable && s.wp_publish && (
              <select
                className="input"
                style={{ width: "auto", fontSize: 13, padding: "2px 6px" }}
                disabled={p.busy}
                value={s.wp_status ?? "draft"}
                onChange={(e) => p.onUpdateTargets({ wp_status: e.target.value as "draft" | "publish" })}
              >
                <option value="draft">As draft</option>
                <option value="publish">Live</option>
              </select>
            )}
          </div>
        </div>
      )}

      {canEditTargets && (
        <CadenceEditor s={s} busy={p.busy} onApply={p.onUpdateCadence} />
      )}
    </div>
  );
}

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const CADENCE_MODES: [ScheduleRequest["mode"], string][] = [
  ["all_at_once", "All at once"],
  ["drip", "N/day"],
  ["weekly", "N/week"],
  ["monthly_date", "N/month (date)"],
  ["monthly_weekday", "N/month (weekday)"],
  ["fixed", "On a date"],
];

// Re-time the remaining articles of a PAUSED schedule (forward-only). Compact cadence
// form; seeded from the schedule's current values, applied via the cadence endpoint.
function CadenceEditor(p: {
  s: ContentSchedule;
  busy: boolean;
  onApply: (body: {
    mode: ScheduleRequest["mode"]; per_day?: number; start_date?: string;
    time_of_day?: string; timezone?: string; weekday?: number; weekdays?: number[];
    day_of_month?: number; week_of_month?: number;
  }) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const tz = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", []);
  const [mode, setMode] = useState<ScheduleRequest["mode"]>(p.s.mode as ScheduleRequest["mode"]);
  const [perDay, setPerDay] = useState(p.s.per_day ?? 1);
  const [startDate, setStartDate] = useState(p.s.start_date ?? today);
  const [timeOfDay, setTimeOfDay] = useState(p.s.time_of_day?.slice(0, 5) ?? "09:00");
  const [weekday, setWeekday] = useState(0);
  const [weekdays, setWeekdays] = useState<number[]>([0]);
  const [dayOfMonth, setDayOfMonth] = useState(1);
  const [weekOfMonth, setWeekOfMonth] = useState(1);
  const toggleWeekday = (i: number) =>
    setWeekdays((prev) => (prev.includes(i) ? prev.filter((d) => d !== i) : [...prev, i]).sort((a, b) => a - b));

  const periodic = mode === "drip" || mode === "weekly"
    || mode === "monthly_date" || mode === "monthly_weekday";
  const usesDate = periodic || mode === "fixed";
  const applyDisabled = p.busy || (mode === "weekly" && weekdays.length === 0);

  const apply = () => p.onApply({
    mode,
    per_day: periodic ? perDay : undefined,
    start_date: usesDate ? startDate : undefined,
    time_of_day: usesDate ? timeOfDay : undefined,
    timezone: tz,
    weekday: mode === "monthly_weekday" ? weekday : undefined,
    weekdays: mode === "weekly" ? weekdays : undefined,
    day_of_month: mode === "monthly_date" ? dayOfMonth : undefined,
    week_of_month: mode === "monthly_weekday" ? weekOfMonth : undefined,
  });

  return (
    <div style={{ borderTop: "1px solid var(--border, #e5e7eb)", paddingTop: 8 }}>
      <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
        Cadence for the remaining articles (paused — takes effect on resume):
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <select className="input" style={{ width: "auto", fontSize: 13 }} value={mode}
          disabled={p.busy} onChange={(e) => setMode(e.target.value as ScheduleRequest["mode"])}>
          {CADENCE_MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>

        {periodic && (
          <input className="input" type="number" min={1} value={perDay}
            style={{ width: 70, fontSize: 13 }} disabled={p.busy}
            onChange={(e) => setPerDay(Math.max(1, Number(e.target.value) || 1))}
            title={mode === "drip" ? "Per day" : mode === "weekly" ? "Per selected day, each week" : "Per month"} />
        )}
        {mode === "weekly" && (
          <div className="seg-radios" style={{ flexWrap: "wrap" }}>
            {WEEKDAYS.map((d, i) => (
              <button
                key={i}
                type="button"
                className={"seg-radio" + (weekdays.includes(i) ? " seg-radio-active" : "")}
                disabled={p.busy}
                onClick={() => toggleWeekday(i)}
              >
                {d.slice(0, 3)}
              </button>
            ))}
          </div>
        )}
        {mode === "monthly_weekday" && (
          <select className="input" style={{ width: "auto", fontSize: 13 }} value={weekday}
            disabled={p.busy} onChange={(e) => setWeekday(Number(e.target.value))}>
            {WEEKDAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
          </select>
        )}
        {mode === "monthly_weekday" && (
          <select className="input" style={{ width: "auto", fontSize: 13 }} value={weekOfMonth}
            disabled={p.busy} onChange={(e) => setWeekOfMonth(Number(e.target.value))}>
            {[[1, "First"], [2, "Second"], [3, "Third"], [4, "Fourth"], [-1, "Last"]]
              .map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        )}
        {mode === "monthly_date" && (
          <input className="input" type="number" min={1} max={31} value={dayOfMonth}
            style={{ width: 70, fontSize: 13 }} disabled={p.busy}
            onChange={(e) => setDayOfMonth(Math.min(31, Math.max(1, Number(e.target.value) || 1)))}
            title="Day of month" />
        )}
        {usesDate && (
          <input className="input" type="date" value={startDate} min={today}
            style={{ width: "auto", fontSize: 13 }} disabled={p.busy}
            onChange={(e) => setStartDate(e.target.value)} />
        )}
        {usesDate && (
          <input className="input" type="time" value={timeOfDay}
            style={{ width: "auto", fontSize: 13 }} disabled={p.busy}
            onChange={(e) => setTimeOfDay(e.target.value)} />
        )}
        <button className="btn btn-sm" disabled={applyDisabled} onClick={apply}
          title={mode === "weekly" && weekdays.length === 0 ? "Pick at least one weekday" : ""}>
          Apply cadence
        </button>
      </div>
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
