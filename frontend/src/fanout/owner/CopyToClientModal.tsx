import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  copyPlanToClient,
  listClients,
  type CopyPlanResult,
} from "../shared/api";

// Copy a session's content plan (topics + clusters + primary keywords) onto
// another client, as a fresh UNSCHEDULED session. The user picks the target
// client here; cadence / start date / publishing are chosen later via the normal
// Schedule flow on the new session. The source session is untouched.
export function CopyToClientModal(props: {
  sessionId: string;
  seedKeyword: string;
  clusterCount: number;
  onClose: () => void;
  onCopied: (result: CopyPlanResult) => void;
}) {
  const { sessionId, seedKeyword, clusterCount, onClose, onCopied } = props;
  const [targetClientId, setTargetClientId] = useState("");

  const clients = useQuery({ queryKey: ["copy-clients"], queryFn: listClients });

  const mut = useMutation({
    mutationFn: () => copyPlanToClient(sessionId, targetClientId),
    onSuccess: (result) => onCopied(result),
    onError: (e: Error) => alert(e.message),
  });

  return (
    <div className="modal-overlay">
      <div className="modal card" style={{ maxWidth: 480 }}>
        <header
          style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
        >
          <h2 className="page-title" style={{ margin: 0 }}>
            Copy plan to another client
          </h2>
          <button className="link-btn" onClick={onClose}>
            Close
          </button>
        </header>

        <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
          Copies the <strong>{seedKeyword}</strong> plan ({clusterCount} article
          {clusterCount === 1 ? "" : "s"}) into a new session for the client you pick.
          You'll choose the cadence, start date, and publishing when you schedule it —
          this just sets up the topics. The original is untouched.
        </p>

        <div style={{ display: "grid", gap: 14, marginTop: 12 }}>
          <div className="field">
            <span className="field-label">Target client</span>
            {clients.isLoading && <p className="muted">Loading clients…</p>}
            {clients.isError && (
              <p className="form-error">Failed to load clients. Please try again.</p>
            )}
            {clients.data && (
              <select
                className="input"
                value={targetClientId}
                onChange={(e) => setTargetClientId(e.target.value)}
              >
                <option value="">Select a client…</option>
                {clients.data.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}
            {clients.data && clients.data.length === 0 && (
              <p className="muted" style={{ fontSize: 12 }}>
                No active clients. Create the client first, then copy the plan onto it.
              </p>
            )}
          </div>

          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: 10,
              marginTop: 4,
            }}
          >
            <button
              className="btn btn-ghost"
              style={{ width: "auto" }}
              onClick={onClose}
              disabled={mut.isPending}
            >
              Cancel
            </button>
            <button
              className="btn btn-primary"
              style={{ width: "auto" }}
              disabled={!targetClientId || mut.isPending}
              onClick={() => mut.mutate()}
            >
              {mut.isPending ? "Copying…" : "Copy plan"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
