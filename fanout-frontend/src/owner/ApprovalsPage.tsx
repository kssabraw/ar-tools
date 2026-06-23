import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveSession,
  listApprovals,
  rejectSession,
  type ApprovalQueueItem,
} from "../shared/api";
import { AppShell } from "../shared/AppShell";

// Owner approval queue (PRD §11.3 steps 4–7). Lists every VA run parked at the
// cost gate, with a decision modal (approve / reject + optional note). Polls
// every 30s (the §11.3 v1 cadence; real-time push is deferred to v2).
export function ApprovalsPage() {
  const qc = useQueryClient();
  const approvals = useQuery({
    queryKey: ["approvals"],
    queryFn: listApprovals,
    refetchInterval: 30000,
  });
  const [active, setActive] = useState<ApprovalQueueItem | null>(null);

  const decideMut = useMutation({
    mutationFn: (v: { id: string; decision: "approve" | "reject"; note: string }) =>
      v.decision === "approve" ? approveSession(v.id, v.note) : rejectSession(v.id, v.note),
    onSuccess: () => {
      setActive(null);
      qc.invalidateQueries({ queryKey: ["approvals"] });
    },
    onError: (e: Error) => alert(e.message),
  });

  const rows = approvals.data ?? [];

  return (
    <AppShell>
      <div className="content" style={{ maxWidth: 880 }}>
        <h1 className="page-title">Approvals</h1>
        <p className="muted">
          VA runs waiting on your decision. Approving starts the run immediately; rejecting
          returns it to the VA with your note.
        </p>

        {approvals.isLoading && <p className="muted">Loading…</p>}
        {approvals.isError && <p className="form-error">Failed to load the approval queue.</p>}
        {approvals.data && rows.length === 0 && (
          <div className="card" style={{ textAlign: "center" }}>
            <p className="muted">No requests waiting for approval.</p>
          </div>
        )}

        {rows.length > 0 && (
          <div className="session-list">
            {rows.map((r) => (
              <button key={r.session_id} className="approval-row" onClick={() => setActive(r)}>
                <div className="approval-row-main">
                  <span className="session-row-seed">{r.seed_keyword}</span>
                  {r.recursive_fanout && <span className="badge badge-warn">recursive</span>}
                  <span className="approval-cost">
                    {r.estimated_cost_usd != null ? `$${r.estimated_cost_usd.toFixed(2)}` : "—"}
                  </span>
                </div>
                <div className="session-row-meta">
                  <span>{r.va_display_name ?? "VA"}</span>
                  <span>·</span>
                  <span>{r.project_name ?? "—"}</span>
                  <span>·</span>
                  <span>{r.coverage_mode}</span>
                  <span>·</span>
                  <span>{r.deep_mine_count} deep-mined</span>
                  <span>·</span>
                  <span>{new Date(r.submitted_at).toLocaleString()}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {active && (
        <DecisionModal
          item={active}
          busy={decideMut.isPending}
          onClose={() => setActive(null)}
          onDecide={(decision, note) =>
            decideMut.mutate({ id: active.session_id, decision, note })
          }
        />
      )}
    </AppShell>
  );
}

function DecisionModal(p: {
  item: ApprovalQueueItem;
  busy: boolean;
  onClose: () => void;
  onDecide: (decision: "approve" | "reject", note: string) => void;
}) {
  const [note, setNote] = useState("");
  const { item } = p;
  return (
    <div className="modal-backdrop" onClick={p.onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <h2 className="page-title" style={{ marginTop: 0 }}>Review request</h2>
        <dl className="approval-detail">
          <div><dt>Seed</dt><dd>{item.seed_keyword}</dd></div>
          <div><dt>VA</dt><dd>{item.va_display_name ?? "—"}</dd></div>
          <div><dt>Project</dt><dd>{item.project_name ?? "—"}</dd></div>
          <div><dt>Coverage</dt><dd>{item.coverage_mode}</dd></div>
          <div><dt>Silos</dt><dd>{item.topic_count ?? "—"}</dd></div>
          <div><dt>Deep-mined</dt><dd>{item.deep_mine_count}</dd></div>
          <div><dt>Recursive</dt><dd>{item.recursive_fanout ? "yes" : "no"}</dd></div>
          <div>
            <dt>Estimate</dt>
            <dd>{item.estimated_cost_usd != null ? `$${item.estimated_cost_usd.toFixed(2)}` : "—"}</dd>
          </div>
        </dl>

        <label className="field">
          <span className="field-label">Note (optional)</span>
          <textarea
            className="textarea"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Add a note for the VA (shown on reject)"
            maxLength={2000}
          />
        </label>

        <div className="toolbar">
          <button className="btn btn-ghost" style={{ width: "auto" }} disabled={p.busy} onClick={p.onClose}>
            Cancel
          </button>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="btn btn-ghost"
              style={{ width: "auto" }}
              disabled={p.busy}
              onClick={() => p.onDecide("reject", note.trim())}
            >
              Reject
            </button>
            <button
              className="btn btn-primary"
              style={{ width: "auto" }}
              disabled={p.busy}
              onClick={() => p.onDecide("approve", note.trim())}
            >
              {p.busy ? "Working…" : "Approve & run"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
