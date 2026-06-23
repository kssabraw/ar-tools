// Client scope for the Fanout UI when it's opened from an AR Tools client's
// Content Scheduler card (`/fanout/?client_id=<id>&client_name=<name>`).
//
// Sticky within the tab: captured from the entry URL, then mirrored to
// sessionStorage so a hard refresh (or a deep link without the query) keeps the
// scope. A fresh card click for a different client overrides it. We use
// sessionStorage (not localStorage) so the scope is per-tab and clears when the
// tab closes — this is routing/scope state, not the app data the Fanout
// convention keeps server-side.
const STORAGE_KEY = "fanout.clientScope";

type Scope = { clientId: string | null; clientName: string | null };

function readInitial(): Scope {
  const params = new URLSearchParams(window.location.search);
  const urlId = params.get("client_id");
  if (urlId) {
    const scope: Scope = { clientId: urlId, clientName: params.get("client_name") };
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(scope));
    } catch {
      /* storage unavailable — fall back to URL-only scope */
    }
    return scope;
  }
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const s = JSON.parse(raw) as Scope;
      if (s && typeof s.clientId === "string") {
        return { clientId: s.clientId, clientName: s.clientName ?? null };
      }
    }
  } catch {
    /* ignore */
  }
  return { clientId: null, clientName: null };
}

export const CLIENT_SCOPE: Scope = readInitial();

export const hasClientScope = (): boolean => Boolean(CLIENT_SCOPE.clientId);

// Drop the sticky scope and return to the global (all-runs) view. Captured at
// module load, so callers reload after clearing to re-read scope.
export function exitClientScope(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  window.location.assign("/fanout/");
}
