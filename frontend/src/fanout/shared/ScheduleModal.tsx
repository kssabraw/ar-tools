import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createSchedule,
  scheduleEstimate,
  isoForLocationCode,
  type ScheduleRequest,
} from "./api";
import { LocationAutocomplete } from "./LocationAutocomplete";

type Mode = "all_at_once" | "drip" | "fixed";
type ContentType = "blog_post" | "local_seo_page" | "service_page";

// M15 — Schedule modal (handoff §9.4). Whole-session ("Schedule all") or a chosen subset
// (clusterIds). Three modes: all-at-once, drip N/day, or a specific delivery date. Live
// preview (count after the double-book filter · finish date · cost) + the VA $90 gate.
export function ScheduleModal(props: {
  sessionId: string;
  clusterIds?: string[];          // omit -> whole session
  baseUrl?: string | null;
  // Stored extra internal-link targets (money pages) — pre-fills the fields below.
  extraLinkUrls?: string[] | null;
  // Content type chosen up front in the new-session flow (carried on the
  // session). Seeds the toggle below; the user can still switch here.
  defaultContentType?: ContentType | null;
  // Local SEO target area chosen at session creation; pre-fills the location
  // field below. The user can still change it here.
  defaultLocation?: string | null;
  // Client + market for this run — scope the Local SEO location typeahead.
  clientId?: string | null;
  locationCode?: number | null;
  // Whether the linked client has WordPress configured (site URL + application
  // password on its card) — gates the direct-to-WordPress option below.
  wordpressAvailable?: boolean;
  onClose: () => void;
  onScheduled?: (scheduled: number) => void;
}) {
  const { sessionId, clusterIds, clientId, locationCode, onClose, onScheduled } = props;
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
  // Up to 3 money-page URLs every article should link to (woven into the
  // internal-link injection). Fixed 3 slots; blanks are dropped on submit.
  const [extraUrls, setExtraUrls] = useState<string[]>(() => {
    const stored = props.extraLinkUrls ?? [];
    return [stored[0] ?? "", stored[1] ?? "", stored[2] ?? ""];
  });
  const [contentType, setContentType] = useState<ContentType>(
    props.defaultContentType ?? "blog_post",
  );
  // Committed (picked) location vs the raw field text. A picked suggestion is the
  // canonical DataForSEO name; we fall back to the raw text so an unmatched area
  // is still submittable (preserves the old free-text behavior).
  const [location, setLocation] = useState(props.defaultLocation ?? "");
  const [locationInput, setLocationInput] = useState(props.defaultLocation ?? "");
  const effectiveLocation = (location.trim() || locationInput.trim());
  // Auto-publish each finished piece to the client's Drive folder. Only offered
  // for client-linked sessions (the publish target is the client's folder).
  const [autoPublish, setAutoPublish] = useState(false);
  // Direct-to-WordPress (blog posts only): each finished article is created on
  // the client's WP site at its cluster slug, as a draft or live.
  const [wpPublish, setWpPublish] = useState(false);
  const [wpStatus, setWpStatus] = useState<"draft" | "publish">("draft");

  const isLocalSeo = contentType === "local_seo_page";
  const isServicePage = contentType === "service_page";
  const showWordPress = contentType === "blog_post" && !!clientId && !!props.wordpressAvailable;
  const locCountry = locationCode ? isoForLocationCode(locationCode) : undefined;

  const body: ScheduleRequest = {
    mode,
    cluster_ids: clusterIds,
    per_day: mode === "drip" ? perDay : undefined,
    start_date: mode === "drip" || mode === "fixed" ? startDate : undefined,
    time_of_day: mode === "drip" || mode === "fixed" ? timeOfDay : undefined,
    timezone,
    content_type: contentType,
    // Only blog posts need a base URL (absolute internal links); Local SEO pages
    // need a target area; service pages are keyword-only.
    site_base_url: contentType === "blog_post" ? baseUrl.trim() || undefined : undefined,
    // Blog only. The fields' current contents win (empty list clears stored extras);
    // undefined on other content types leaves the session's stored value untouched.
    extra_link_urls:
      contentType === "blog_post"
        ? extraUrls.map((u) => u.trim()).filter(Boolean)
        : undefined,
    location: isLocalSeo ? effectiveLocation || undefined : undefined,
    auto_publish: clientId ? autoPublish : undefined,
    wp_publish: showWordPress ? wpPublish : undefined,
    wp_status: showWordPress && wpPublish ? wpStatus : undefined,
  };

  // Live preview — re-estimates as the inputs change.
  const est = useQuery({
    queryKey: ["schedule-estimate", sessionId, mode, perDay, startDate, timeOfDay, clusterIds, contentType],
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

  // Blog posts need a base URL; Local SEO pages need a target area; service
  // pages are keyword-only (the client link is enforced server-side).
  const missingRequirement = isServicePage ? false : isLocalSeo ? !effectiveLocation : !baseUrl.trim();
  const count = est.data?.count ?? 0;
  const noun = isLocalSeo || isServicePage ? "page" : "article";
  const scope = clusterIds ? `${clusterIds.length} selected ${noun}(s)` : "the whole session";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal card" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 className="page-title" style={{ margin: 0 }}>Schedule content</h2>
          <button className="link-btn" onClick={onClose}>Close</button>
        </header>

        <p className="muted" style={{ fontSize: 13, marginTop: 4 }}>
          Scheduling {scope}. Content is generated automatically at its scheduled time.
        </p>

        <div style={{ display: "grid", gap: 14, marginTop: 8 }}>
          <div className="field">
            <span className="field-label">Content type</span>
            <div className="seg-radios">
              {([
                ["blog_post", "Blog post"],
                ["local_seo_page", "Local SEO page"],
                ["service_page", "Service page"],
              ] as [ContentType, string][]).map(([c, label]) => (
                <button
                  key={c}
                  type="button"
                  className={"seg-radio" + (contentType === c ? " seg-radio-active" : "")}
                  onClick={() => setContentType(c)}
                >
                  {label}
                </button>
              ))}
            </div>
            {isLocalSeo && (
              <span className="field-hint">
                Generates suite Local SEO pages (competitor analysis + scoring) for each cluster's
                keyword. Requires this session to be linked to a client with a Google Business Profile.
              </span>
            )}
            {isServicePage && (
              <span className="field-hint">
                Generates conversion-focused suite service pages (brief + writer) for each cluster's
                keyword. Keyword-only. Requires this session to be linked to a client.
              </span>
            )}
          </div>

          {isLocalSeo && (
            <label className="field">
              <span className="field-label">Target area / location</span>
              <LocationAutocomplete
                country={locCountry}
                clientId={clientId}
                value={location}
                inputValue={locationInput}
                placeholder="Start typing a city or area…"
                onSelect={(loc) => { setLocation(loc.location_name); setLocationInput(loc.location_name); }}
                onInputChange={(raw) => { setLocationInput(raw); setLocation(""); }}
                onClear={() => { setLocation(""); setLocationInput(""); }}
              />
              <span className="field-hint">Required — the city/area each Local SEO page targets.</span>
            </label>
          )}
          {contentType === "blog_post" && (
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
          )}
          {contentType === "blog_post" && (
            <div className="field">
              <span className="field-label">Extra link targets (optional)</span>
              {extraUrls.map((u, i) => (
                <input
                  key={i}
                  className="input"
                  style={i > 0 ? { marginTop: 6 } : undefined}
                  placeholder={`https://yoursite.com/your-money-page-${i + 1}/`}
                  value={u}
                  onChange={(e) =>
                    setExtraUrls((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))
                  }
                />
              ))}
              <span className="field-hint">
                Up to 3 URLs (product / service / landing pages) every article should link to.
                Woven into each article's internal links alongside its pillar and related
                articles, within the 5-links-per-page cap.
              </span>
            </div>
          )}

          {clientId && (
            <label className="field" style={{ flexDirection: "row", alignItems: "flex-start", gap: 8 }}>
              <input
                type="checkbox"
                checked={autoPublish}
                onChange={(e) => setAutoPublish(e.target.checked)}
                style={{ marginTop: 2 }}
              />
              <span>
                <span className="field-label">Auto-publish to Google Drive</span>
                <span className="field-hint">
                  Publish each piece to the client's Drive folder as a Google Doc as soon as it
                  finishes — no manual “Save to Drive” needed.
                </span>
              </span>
            </label>
          )}

          {showWordPress && (
            <div className="field">
              <label style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={wpPublish}
                  onChange={(e) => setWpPublish(e.target.checked)}
                  style={{ marginTop: 2 }}
                />
                <span>
                  <span className="field-label">Publish to WordPress</span>
                  <span className="field-hint">
                    Create each finished article on the client's WordPress site at the URL its
                    internal links point at (from the blog reference URL on the client card).
                  </span>
                </span>
              </label>
              {wpPublish && (
                <div className="seg-radios" style={{ marginTop: 8 }}>
                  {([
                    ["draft", "As draft (review in wp-admin)"],
                    ["publish", "Live immediately"],
                  ] as ["draft" | "publish", string][]).map(([v, label]) => (
                    <button
                      key={v}
                      type="button"
                      className={"seg-radio" + (wpStatus === v ? " seg-radio-active" : "")}
                      onClick={() => setWpStatus(v)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

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
                <strong>{count}</strong> {noun}{count === 1 ? "" : "s"}
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
              disabled={create.isPending || missingRequirement || count === 0}
              title={
                missingRequirement
                  ? isLocalSeo ? "Enter a target area first" : "Enter a site base URL first"
                  : count === 0 ? "Nothing to schedule" : ""
              }
              onClick={() => create.mutate()}
            >
              {create.isPending ? "Scheduling…" : `Schedule ${count} ${noun}${count === 1 ? "" : "s"}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
