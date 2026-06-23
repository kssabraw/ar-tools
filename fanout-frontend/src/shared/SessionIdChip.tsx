import { useState } from "react";

/**
 * Small, copyable session-id display for the workspace header. The id is handy
 * for debugging (Railway logs filter on `session_id`, the owner `/debug`
 * endpoint, ad-hoc API calls), and was previously only discoverable from the URL
 * or a console call.
 */
export function SessionIdChip({ sessionId }: { sessionId: string }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard?.writeText(sessionId).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      },
      () => {
        /* clipboard blocked — the id is still visible to select manually */
      },
    );
  };

  return (
    <button
      type="button"
      className="session-id-chip muted"
      title="Copy session ID"
      onClick={copy}
      style={{
        background: "none",
        border: "none",
        padding: 0,
        marginTop: 2,
        cursor: "pointer",
        font: "inherit",
        fontSize: 12,
        textAlign: "left",
      }}
    >
      {copied ? (
        "Session ID copied ✓"
      ) : (
        <>
          Session ID: <code>{sessionId}</code>
        </>
      )}
    </button>
  );
}
