import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createSchedule,
  scheduleEstimate,
  type ScheduleRequest,
} from "./api";

type Mode = "all_at_once" | "drip" | "fixed";

// M15 — Schedule modal (handoff §9.4). Whole-session ("Schedule all") or a chosen subset
// (clusterIds). Three modes: all-at-once, drip N/day, or a specific delivery date. Live
// preview (count after the double-book filter · finish date · cost) + the VA $90 gate.
export function ScheduleModal(props: {
  sessionId: string;
  clusterIds?: string[];          // omit -> whole session
  baseUrl?: string | null;
  onClose: () => void;
  onScheduled?: (scheduled: number) => void;
}) {
  const { sessionId, clusterIds, onClose, onScheduled } = props;
  const qc = useQueryClient();
  const browserTz = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    [],
  );
  const today = new Date().toISOString().slice(0, 10);

  const [mode, setMode] = useState<Mode>("all_at_once");
  const [perDay, setPerDay] = useState(5);
  const [startDate, setStartDate] = useState(today);
  const [timeOfDay, setTimeOfDay] = useState("09:00");
  const [timezone] = useState(browserTz);
  const [baseUrl, setBaseUrl] = useState(props.baseUrl ?? "");

  const body: ScheduleRequest = {
    mode,
    cluster_ids: clusterIds,
    per_day: mode === "drip" ? perDay : undefined,
    start_date: mode === "drip" || mode === "fixed" ? startDate : undefined,
    time_of_day: mode === "drip" || mode === "fixed" ? timeOfDay : undefined,
    timezone,
    site_base_url: baseUrl.trim() || undefined,
  };

  // Live preview — re-estimates as the inputs change.
  const est = useQuery({
    queryKey: ["schedule-estimate", sessionId, mode, perDay, startDate, timeOfDay, clusterIds],
    queryFn: () => scheduleEstimate(sessionId, body),
  });

  const create = useMutation({
    mutationFn: () => createSchedule(sessionId, body),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["schedules", sessionId] });
      qc.invalidateQueries({ queryKey: ["schedule-runs", sessionId] });
      if (res.status === "requires_approval") {
        alert(
          `This batch (~$${res.estimate.cost_estimate_usd}) exceeds the $${res.approval_threshold_usd} ` +
            `limit and needs owner approval. Ask your workspace owner to schedule it.`,
        );
        return;
      }
      onScheduled?.(res.scheduled ?? 0);
      onClose();
    },
    onError: (e: Error) => alert(e.message),
  });

  const needsBaseUrl = !baseUrl.trim();
  const count = est.data?.count ?? 0;
  const scope = clusterIds ? `${clusterIds.length} selected article(s)` : "the whole session";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal card" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 className="page-title" style={{ margin: 0 }}>Schedule articles</h2>
          <button className="link-btn" onClick={onClose}>Close</button>
        </header>

        <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
          Scheduling {scope}. Articles are written automatically at their scheduled time.
        </p>

        <div style={{ display: "grid", gap: 14, marginTop: 8 }}>
          <label className="field">
            <span className="field-label">Site base URL</span>
            <input
              className="input"
              placeholder="https://yoursite.com"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
            <span className="field-hint">Required — internal links are built as absolute URLs.</span>
          </label>

          <div className="field">
            <span className="field-label">When</span>
            <div className="seg-radios">
              {([
                ["all_at_once", "All at once"],
                ["drip", "Drip N/day"],
                ["fixed", "On a specific date"],
              ] as [Mode, string][]).map(([m, label]) => (
                <button
                  key={m}
                  type="button"
                  className={"seg-radio" + (mode === m ? " seg-radio-active" : "")}
                  onClick={() => setMode(m)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {mode === "drip" && (
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <label className="field" style={{ flex: "0 0 90px" }}>
                <span className="field-label">Per day</span>
                <input className="input" type="number" min={1} value={perDay}
                  onChange={(e) => setPerDay(Math.max(1, Number(e.target.value) || 1))} />
              </label>
              <label className="field" style={{ flex: 1 }}>
                <span className="field-label">Start date</span>
                <input className="input" type="date" value={startDate} min={today}
                  onChange={(e) => setStartDate(e.target.value)} />
              </label>
              <label className="field" style={{ flex: "0 0 110px" }}>
                <span className="field-label">Time</span>
                <input className="input" type="time" value={timeOfDay}
                  onChange={(e) => setTimeOfDay(e.target.value)} />
              </label>
            </div>
          )}

          {mode === "fixed" && (
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <label className="field" style={{ flex: 1 }}>
                <span className="field-label">Write on</span>
                <input className="input" type="date" value={startDate} min={today}
                  onChange={(e) => setStartDate(e.target.value)} />
              </label>
              <label className="field" style={{ flex: "0 0 110px" }}>
                <span className="field-label">Time</span>
                <input className="input" type="time" value={timeOfDay}
                  onChange={(e) => setTimeOfDay(e.target.value)} />
              </label>
            </div>
          )}

          {/* Live preview */}
          <div className="schedule-preview">
            {est.isLoading ? (
              <span className="muted">Estimating…</span>
            ) : est.isError ? (
              <span className="form-error">Couldn’t estimate this schedule.</span>
            ) : est.data ? (
              <>
                <strong>{count}</strong> article{count === 1 ? "" : "s"}
                {est.data.mode === "drip" && est.data.days ? <> · {est.data.days} days</> : null}
                {est.data.finish_date ? <> · {est.data.mode === "fixed" ? "writes" : "finishes"} {est.data.finish_date}</> : null}
                {mode !== "all_at_once" ? <> · {timeOfDay} {timezone}</> : null}
                {" · "}~${est.data.cost_estimate_usd}
                {est.data.already_scheduled > 0 && (
                  <div className="muted" style={{ fontSize: 12 }}>
                    {est.data.already_scheduled} already scheduled — skipped.
                  </div>
                )}
                {est.data.requires_approval && (
                  <div className="banner banner-warn" style={{ marginTop: 6, fontSize: 13 }}>
                    Over the ${est.data.approval_threshold_usd} limit — needs owner approval.
                  </div>
                )}
              </>
            ) : null}
          </div>

          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button className="btn btn-ghost" style={{ width: "auto" }} onClick={onClose}>Cancel</button>
            <button
              className="btn btn-primary"
              style={{ width: "auto" }}
              disabled={create.isPending || needsBaseUrl || count === 0}
              title={needsBaseUrl ? "Enter a site base URL first" : count === 0 ? "Nothing to schedule" : ""}
              onClick={() => create.mutate()}
            >
              {create.isPending ? "Scheduling…" : `Schedule ${count} article${count === 1 ? "" : "s"}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
