import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { cancelRun } from "./api";

// Confirm-then-cancel button surfaced wherever a run is in progress (Owner
// workspace head, VA wizard progress screen). Cooperative cancellation: the
// /cancel endpoint flips status to 'cancelled' atomically and signals the
// background worker, which exits at its next external-call checkpoint. An
// in-flight HTTP request may still complete (worst case ≈ one DataForSEO
// timeout, ~60s), but no new calls are made after the check fires.
export function CancelRunButton({
  sessionId,
  size = "md",
}: {
  sessionId: string;
  size?: "sm" | "md";
}) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const mut = useMutation({
    mutationFn: () => cancelRun(sessionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["summary", sessionId] });
      qc.invalidateQueries({ queryKey: ["session", sessionId] });
      setConfirming(false);
    },
    onError: () => setConfirming(false),
  });

  const btnClass = "btn btn-ghost" + (size === "sm" ? " btn-sm" : "");

  if (!confirming) {
    return (
      <button
        type="button"
        className={btnClass}
        style={{ width: "auto" }}
        onClick={() => setConfirming(true)}
        disabled={mut.isPending}
      >
        Cancel run
      </button>
    );
  }

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span className="muted" style={{ fontSize: "0.9em" }}>
        Cancel? In-flight API calls may still bill.
      </span>
      <button
        type="button"
        className={"btn btn-danger" + (size === "sm" ? " btn-sm" : "")}
        style={{ width: "auto" }}
        onClick={() => mut.mutate()}
        disabled={mut.isPending}
      >
        {mut.isPending ? "Cancelling…" : "Yes, cancel"}
      </button>
      <button
        type="button"
        className={btnClass}
        style={{ width: "auto" }}
        onClick={() => setConfirming(false)}
        disabled={mut.isPending}
      >
        Keep running
      </button>
      {mut.isError && (
        <span className="form-error" style={{ fontSize: "0.9em" }}>
          {mut.error instanceof Error ? mut.error.message : "Couldn’t cancel."}
        </span>
      )}
    </span>
  );
}
