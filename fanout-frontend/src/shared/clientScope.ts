// Client scope for the Fanout UI when it's opened from an AR Tools client's
// Content Scheduler card (`/fanout/?client_id=<id>&client_name=<name>`).
//
// Captured once from the entry URL at module load, so it survives in-app
// (react-router) navigation without re-threading it through every route. A hard
// refresh on a deep link drops it (the UI falls back to the global view) —
// re-entering from the client card re-scopes. We deliberately avoid browser
// storage for this per the Fanout convention (no localStorage for app data).
const params = new URLSearchParams(window.location.search);

export const CLIENT_SCOPE: { clientId: string | null; clientName: string | null } = {
  clientId: params.get("client_id"),
  clientName: params.get("client_name"),
};

export const hasClientScope = (): boolean => Boolean(CLIENT_SCOPE.clientId);
