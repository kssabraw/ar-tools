import type { SummaryCost } from "./api";

// Postgres `numeric` can arrive as a string through the API, so coerce before
// any arithmetic / .toFixed (a string .toFixed would throw and white-screen the
// whole view). Returns null for null/undefined/non-finite.
function toNum(v: number | string | null | undefined): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

// Live cost banner (PRD §8.4 / §15.1): real cost accumulated so far vs. the
// pre-run estimate. The summary poll refreshes `actual_cost_usd` as the
// background job flushes it (~10s cadence), so this climbs during a run.
export function CostBanner({ cost, running }: { cost: SummaryCost | undefined; running: boolean }) {
  if (!cost) return null;
  const actual = toNum(cost.actual_cost_usd);
  const estimate = toNum(cost.estimated_cost_usd);
  // Nothing to show before any spend and with no estimate (e.g. a fresh session).
  if (actual == null && estimate == null) return null;

  const pct =
    actual != null && estimate != null && estimate > 0
      ? Math.min(100, Math.round((actual / estimate) * 100))
      : null;
  const over = actual != null && estimate != null && actual > estimate;

  return (
    <div className={"cost-banner" + (over ? " cost-banner-over" : "")}>
      <div className="cost-banner-row">
        <span className="cost-banner-label">
          {running ? "Cost so far" : "Run cost"}
        </span>
        <span className="cost-banner-figures">
          <strong>${(actual ?? 0).toFixed(2)}</strong>
          {estimate != null && (
            <span className="muted"> / est. ${estimate.toFixed(2)}</span>
          )}
          {pct != null && <span className="muted"> · {pct}%</span>}
        </span>
      </div>
      {pct != null && (
        <div className="cost-banner-track" aria-hidden>
          <div
            className="cost-banner-fill"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
      {over && (
        <p className="cost-banner-note">
          Actual cost has exceeded the estimate (the estimate is non-binding).
        </p>
      )}
    </div>
  );
}
