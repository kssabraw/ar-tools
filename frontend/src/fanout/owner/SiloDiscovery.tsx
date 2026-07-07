import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addTopic,
  createSession,
  DEFAULT_LOCATION_CODE,
  SUPPORTED_COUNTRIES,
  deleteTopic,
  disambiguateSession,
  editTopic,
  expandSession,
  finalizeSilos,
  getKeywords,
  getSession,
  getSummary,
  isoForLocationCode,
  overrideAudience,
  planArticles,
  setDeepMine,
  type AddTopicBody,
  type EditTopicBody,
  type PipelineSummary,
  type RelationshipType,
  type Silo,
  type SiloDiscovery as Discovery,
} from "../shared/api";
import { CLIENT_SCOPE } from "../shared/clientScope";
import { AppShell } from "../shared/AppShell";
import { LocationAutocomplete } from "../shared/LocationAutocomplete";
import {
  RELATIONSHIP_LABELS,
  RELATIONSHIP_OPTIONS,
} from "../shared/relationshipTypes";

// A just-finished expansion can briefly read back zero keyword counts: the
// session flips to `awaiting_article_planning` a beat before the gated keyword
// pool is visible on the summary read. Detect that stale snapshot — terminal
// status, zero active, yet clustering clearly produced groups — so the poller
// keeps going instead of locking the UI onto "0 keywords". (Backend has its own
// guard; this is the frontend safety net for when that read still slips through.)
function expansionLooksUnsettled(s: PipelineSummary): boolean {
  if (s.status !== "awaiting_article_planning") return false;
  if ((s.expansion?.counts?.active ?? 0) > 0) return false;
  return (s.expansion?.topics ?? []).some((t) => (t.grouping_count ?? 0) > 0);
}

// The pipeline steps run in the background; "pipeline" is a polling-driven view
// that renders progress / results from the session summary.
type Step = "intent" | "form" | "disambiguation" | "review" | "finalized" | "pipeline";
type Phase = "expanding" | "planning";
type ContentType = "blog_post" | "local_seo_page";

const msg = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function SiloDiscovery({
  onExit,
  initialContentType,
}: {
  onExit: () => void;
  // When the flow is entered from a content-type card (sessions page), the type
  // is preselected and we skip straight to the seed form. Otherwise the flow
  // opens on the chooser so both outputs are visible up front.
  initialContentType?: ContentType;
}) {
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>(initialContentType ? "form" : "intent");
  const [contentType, setContentType] = useState<ContentType>(
    initialContentType ?? "blog_post",
  );
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  // Degraded-mode notes belong to the discovery run, so keep them in state —
  // refetches (after silo edits) must not clear the banners.
  const [degradedNotes, setDegradedNotes] = useState<string[]>([]);
  const [interpretations, setInterpretations] = useState<string[]>([]);

  // form state
  const [seed, setSeed] = useState("");
  const [audience, setAudience] = useState("");
  const [disambHint, setDisambHint] = useState("");
  const [topicCount, setTopicCount] = useState(5);
  const [mode, setMode] = useState<"standard" | "comprehensive">("standard");
  // Per-country locale (E1). Country -> DataForSEO location_code; default US.
  const [locationCode, setLocationCode] = useState<number>(DEFAULT_LOCATION_CODE);
  // Local SEO target area (Service + location typeahead). `location` is the
  // committed (picked) area name; `locationInput` is the raw field text. Carried
  // on the session so the Schedule modal pre-fills it.
  const [location, setLocation] = useState("");
  const [locationInput, setLocationInput] = useState("");
  // §7.8 metrics enrichment toggle (default off; opt in per run to add the
  // DataForSEO volume/CPC/KD cost).
  const [enrichMetrics, setEnrichMetrics] = useState(false);
  const [showOptional, setShowOptional] = useState(false);

  function applyResult(d: Discovery) {
    setSessionId(d.session_id);
    setDegradedNotes(d.degraded_notes);
    if (d.needs_disambiguation) {
      setInterpretations(d.interpretations);
      setStep("disambiguation");
    } else {
      // Seed the cache so Review renders immediately without an extra fetch.
      qc.setQueryData(["session", d.session_id], d);
      setStep("review");
    }
  }

  const createMut = useMutation({
    mutationFn: createSession,
    onSuccess: applyResult,
    onError: (e) => setError(msg(e)),
  });
  const disambigMut = useMutation({
    mutationFn: (choice: string) => disambiguateSession(sessionId!, choice),
    onSuccess: applyResult,
    onError: (e) => setError(msg(e)),
  });
  const finalizeMut = useMutation({
    mutationFn: () => finalizeSilos(sessionId!),
    onSuccess: () => setStep("finalized"),
    onError: (e) => setError(msg(e)),
  });

  // Pipeline runs in the background; we poll the session summary to drive the UI.
  const [phase, setPhase] = useState<Phase>("expanding");
  // Bounds the settling retries so a genuinely-empty run still stops polling.
  const staleSummaryRetries = useRef(0);
  const summaryQ = useQuery({
    queryKey: ["summary", sessionId],
    queryFn: () => getSummary(sessionId!),
    enabled: !!sessionId && step === "pipeline",
    // Poll while a run is in progress; stop once it reaches a terminal status —
    // except keep polling a few more cycles past a stale zero-count read.
    refetchInterval: (q) => {
      const d = q.state.data;
      if (d?.status === "running") { staleSummaryRetries.current = 0; return 4000; }
      if (d && expansionLooksUnsettled(d) && staleSummaryRetries.current < 4) {
        staleSummaryRetries.current += 1;
        return 3000;
      }
      staleSummaryRetries.current = 0;
      return false;
    },
  });

  const expandMut = useMutation({
    // The deep-mine selection (§7.2) is saved, then the pipeline kicks off async.
    mutationFn: async (gatedTopicIds: string[]) => {
      await setDeepMine(sessionId!, gatedTopicIds);
      return expandSession(sessionId!);
    },
    onSuccess: () => {
      setPhase("expanding");
      setStep("pipeline");
      qc.invalidateQueries({ queryKey: ["summary", sessionId] });
    },
    onError: (e) => setError(msg(e)),
  });

  const planMut = useMutation({
    mutationFn: () => planArticles(sessionId!),
    onSuccess: () => {
      setPhase("planning");
      qc.invalidateQueries({ queryKey: ["summary", sessionId] });
    },
    onError: (e) => setError(msg(e)),
  });

  const busy = createMut.isPending || disambigMut.isPending;

  function onSubmitSeed(e: FormEvent) {
    e.preventDefault();
    setError(null);
    createMut.mutate({
      seed_keyword: seed.trim(),
      client_id: CLIENT_SCOPE.clientId ?? undefined,
      audience_hint: audience.trim() || undefined,
      disambiguation_hint: disambHint.trim() || undefined,
      topic_count: topicCount,
      coverage_mode: mode,
      content_type: contentType,
      // Only Local SEO runs carry a target area; prefer the picked suggestion,
      // fall back to whatever was typed (free-text when no client scope).
      location:
        contentType === "local_seo_page"
          ? (location || locationInput).trim() || undefined
          : undefined,
      location_code: locationCode,
      enrich_with_metrics: enrichMetrics,
    });
  }

  return (
    <AppShell>
      <main className="content">
        <div className="workspace-head-row" style={{ marginBottom: 16 }}>
          <h1 className="page-title" style={{ margin: 0 }}>New session</h1>
          <button className="btn btn-ghost" style={{ width: "auto" }} onClick={onExit}>
            Back to sessions
          </button>
        </div>
        {error && <p className="form-error">{error}</p>}

        {busy && (
          <WorkingProgress
            stages={DISCOVERY_STAGES}
            targetS={35}
            estimate="usually 20–40 seconds"
          />
        )}

        {!busy && step === "intent" && (
          <ContentTypeChooser
            hasClient={!!CLIENT_SCOPE.clientId}
            onPick={(c) => {
              setContentType(c);
              setStep("form");
            }}
          />
        )}

        {!busy && step === "form" && (
          <SeedForm
            {...{
              seed,
              setSeed,
              audience,
              setAudience,
              disambHint,
              setDisambHint,
              topicCount,
              setTopicCount,
              mode,
              setMode,
              locationCode,
              setLocationCode,
              location,
              setLocation,
              locationInput,
              setLocationInput,
              clientId: CLIENT_SCOPE.clientId,
              enrichMetrics,
              setEnrichMetrics,
              showOptional,
              setShowOptional,
              contentType,
              onChangeContentType: () => setStep("intent"),
              onSubmit: onSubmitSeed,
            }}
          />
        )}

        {!busy && step === "disambiguation" && (
          <Disambiguation
            seed={seed}
            interpretations={interpretations}
            onPick={(choice) => {
              setError(null);
              disambigMut.mutate(choice);
            }}
          />
        )}

        {!busy && step === "review" && sessionId && (
          <Review
            sessionId={sessionId}
            degradedNotes={degradedNotes}
            finalizing={finalizeMut.isPending}
            onFinalize={() => {
              setError(null);
              finalizeMut.mutate();
            }}
            setError={setError}
          />
        )}

        {step === "finalized" && !expandMut.isPending && sessionId && (
          <DeepMineSelection
            sessionId={sessionId}
            onExit={onExit}
            onRun={(gatedIds) => {
              setError(null);
              expandMut.mutate(gatedIds);
            }}
          />
        )}

        {step === "pipeline" && sessionId && (
          <PipelineView
            phase={phase}
            summary={summaryQ.data ?? null}
            sessionId={sessionId}
            onExit={onExit}
            onPlan={() => {
              setError(null);
              planMut.mutate();
            }}
          />
        )}
      </main>
    </AppShell>
  );
}

// ---------------------------------------------------------------------------
// These pipelines run as a single request, so there's no live per-step signal.
// We show an elapsed timer, a soft progress bar, and step the caption through
// the known stages by elapsed time.
type Stage = { until: number; label: string };

const DISCOVERY_STAGES: Stage[] = [
  { until: 10, label: "Reading top-ranking content for your seed" },
  { until: 16, label: "Sampling search demand" },
  { until: 22, label: "Analyzing competitor site structure" },
  { until: Infinity, label: "Proposing silos" },
];

const EXPANSION_STAGES: Stage[] = [
  { until: 40, label: "Pulling keyword ideas, suggestions, fan-outs, and PAA per silo" },
  { until: 70, label: "Autocomplete enrichment" },
  { until: 110, label: "Mining competitor ranked keywords" },
  { until: 150, label: "Scoring relevance against each silo" },
  { until: Infinity, label: "Clustering keywords per silo" },
];

const PLANNING_STAGES: Stage[] = [
  { until: 40, label: "Fetching SERPs for candidate primary keywords" },
  { until: 95, label: "Planning articles per silo (merge / split / promote / drop)" },
  { until: Infinity, label: "Deduplicating articles across silos" },
];

function WorkingProgress({
  stages,
  targetS,
  estimate,
}: {
  stages: Stage[];
  targetS: number;
  estimate: string;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const stage = stages.find((s) => elapsed < s.until) ?? stages[stages.length - 1];
  // Approach but never reach 100% until the request actually resolves.
  const pct = Math.min(92, Math.round((elapsed / targetS) * 100));

  return (
    <div className="progress-wrap">
      <div className="spinner" aria-hidden="true" />
      <div className="progress-stage">{stage.label}…</div>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="progress-meta">
        Elapsed {elapsed}s · {estimate}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Polling-driven view of a background pipeline run. The work runs server-side
// (past the 5-min edge cap), so we poll the session summary and render progress,
// results, or an error from its status.
function PipelineView(p: {
  phase: Phase;
  summary: PipelineSummary | null;
  sessionId: string;
  onExit: () => void;
  onPlan: () => void;
}) {
  const { summary, phase } = p;
  const status = summary?.status;

  if (!summary || status === "running") {
    return phase === "planning" ? (
      <WorkingProgress stages={PLANNING_STAGES} targetS={120} estimate="usually 1–4 minutes" />
    ) : (
      <WorkingProgress stages={EXPANSION_STAGES} targetS={480} estimate="usually 6–10 minutes" />
    );
  }

  if (status === "error") {
    return (
      <div className="card">
        <h1 className="page-title">The run hit an error</h1>
        <p className="form-error">{summary.last_error ?? "The pipeline failed."}</p>
        <p className="muted">
          Any data collected before the failure was saved. You can start a new session
          or retry from the project list.
        </p>
        <button className="btn btn-primary" style={{ width: "auto" }} onClick={p.onExit}>
          Back to sessions
        </button>
      </div>
    );
  }

  if (status === "complete" && summary.plan) {
    return <PlanResults plan={summary.plan} onExit={p.onExit} />;
  }

  // awaiting_article_planning: expansion done, ready to plan articles.
  return (
    <ExpansionResults
      expansion={summary.expansion}
      sessionId={p.sessionId}
      onExit={p.onExit}
      onPlan={p.onPlan}
    />
  );
}

// ---------------------------------------------------------------------------
function ExpansionResults(p: {
  expansion: PipelineSummary["expansion"];
  sessionId: string;
  onExit: () => void;
  onPlan: () => void;
}) {
  const { expansion } = p;
  const [openTopic, setOpenTopic] = useState<string | null>(null);
  const c = expansion.counts;

  return (
    <>
      <h1 className="page-title">Keyword pipeline complete</h1>
      <p className="muted">
        {c.active.toLocaleString()} relevant keywords across {expansion.topics.length} silos
        {" · "}
        {(c.filtered_relevance + c.filtered_junk + (c.filtered_language ?? 0)).toLocaleString()}{" "}
        filtered out ({c.filtered_relevance.toLocaleString()} off-topic,{" "}
        {c.filtered_junk.toLocaleString()} junk
        {c.filtered_language ? `, ${c.filtered_language.toLocaleString()} non-English` : ""}).
      </p>

      {expansion.topics.map((t) => (
        <div className="silo-card" key={t.topic_id}>
          <div className="silo-head">
            <p className="silo-name">{t.name}</p>
            <div className="silo-actions">
              <span className="muted">
                {t.active.toLocaleString()} keywords · {t.grouping_count} groupings
              </span>
              <button
                className="link-btn"
                onClick={() => setOpenTopic(openTopic === t.topic_id ? null : t.topic_id)}
              >
                {openTopic === t.topic_id ? "Hide" : "View keywords"}
              </button>
            </div>
          </div>
          {openTopic === t.topic_id && (
            <KeywordList sessionId={p.sessionId} topicId={t.topic_id} />
          )}
        </div>
      ))}

      <div className="toolbar">
        <span className="muted">
          Groupings are an internal signal. Plan articles to turn them into a content map.
        </span>
        <div className="silo-actions">
          <button className="btn btn-ghost" style={{ width: "auto" }} onClick={p.onExit}>
            Done
          </button>
          <button className="btn btn-primary" style={{ width: "auto" }} onClick={p.onPlan}>
            Plan articles
          </button>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Read-only article-plan summary (M5 verification). Full table/cluster/
// architecture views + editing land in M7.
function PlanResults(p: { plan: NonNullable<PipelineSummary["plan"]>; onExit: () => void }) {
  const { plan } = p;
  return (
    <>
      <h1 className="page-title">Article plan ready</h1>
      <p className="muted">
        {plan.clusters.toLocaleString()} articles planned across {plan.topics.length} silos
        {" · "}
        {plan.gaps.toLocaleString()} coverage gaps flagged
        {" · "}
        {plan.dropped.toLocaleString()} keywords dropped
        {" · "}
        {plan.collisions.toLocaleString()} cross-silo duplicates merged.
      </p>

      {plan.topics.map((t) => (
        <div className="silo-card" key={t.topic_id}>
          <div className="silo-head">
            <p className="silo-name">{t.name}</p>
            <span className="muted">
              {t.articles} articles · {t.gaps} gaps
            </span>
          </div>
        </div>
      ))}

      <div className="toolbar">
        <span className="muted">
          Open the session to review and edit the table and cluster views.
        </span>
        <button className="btn btn-primary" style={{ width: "auto" }} onClick={p.onExit}>
          Done
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Deep-mine selection (PRD §7.2): the user picks which silos to mine for
// competitor keywords. The seed is always mined and shown as a locked row.
function DeepMineSelection(p: {
  sessionId: string;
  onRun: (gatedTopicIds: string[]) => void;
  onExit: () => void;
}) {
  const q = useQuery({
    queryKey: ["session", p.sessionId],
    queryFn: () => getSession(p.sessionId),
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());

  if (q.isLoading) return <p className="muted">Loading silos…</p>;
  if (q.isError) return <p className="form-error">Failed to load silos.</p>;
  const silos = q.data?.silos ?? [];

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="card">
      <h1 className="page-title">Choose silos to deep-mine</h1>
      <p className="muted">
        Competitor mining pulls the keywords competitors already rank for. The seed is always
        mined; pick the silos worth the extra SERP cost (2–3 is a good budget). You can also
        run with none selected.
      </p>

      <div className="keyword-grid" style={{ marginTop: 16 }}>
        <label className="keyword-row" style={{ opacity: 0.7 }}>
          <span>
            <input type="checkbox" checked disabled style={{ marginRight: 8 }} />
            Seed keyword (always mined)
          </span>
          <span className="keyword-sources">required</span>
        </label>
        {silos.map((s) => (
          <label className="keyword-row" key={s.id} style={{ cursor: "pointer" }}>
            <span>
              <input
                type="checkbox"
                checked={selected.has(s.id)}
                onChange={() => toggle(s.id)}
                style={{ marginRight: 8 }}
              />
              {s.name}
            </span>
            <span className="keyword-sources">
              {RELATIONSHIP_LABELS[s.relationship_type]}
            </span>
          </label>
        ))}
      </div>

      <div className="toolbar" style={{ marginTop: 16 }}>
        <button className="btn btn-ghost" onClick={p.onExit}>
          Back to sessions
        </button>
        <button
          className="btn btn-primary"
          style={{ width: "auto" }}
          onClick={() => p.onRun([...selected])}
        >
          Run keyword pipeline
          {selected.size > 0 ? ` (mine ${selected.size + 1} silos)` : " (seed only)"}
        </button>
      </div>
    </div>
  );
}

function KeywordList(p: { sessionId: string; topicId: string }) {
  const q = useQuery({
    queryKey: ["keywords", p.sessionId, p.topicId],
    queryFn: () => getKeywords(p.sessionId, p.topicId, 200),
  });

  if (q.isLoading) return <p className="muted">Loading keywords…</p>;
  if (q.isError) return <p className="form-error">Failed to load keywords.</p>;
  const rows = q.data ?? [];
  if (rows.length === 0) return <p className="muted">No keywords for this silo.</p>;

  return (
    <div style={{ marginTop: 12 }}>
      <p className="silo-text">Showing first {rows.length} (sources tagged):</p>
      <div className="keyword-grid">
        {rows.map((k) => (
          <div className="keyword-row" key={k.id}>
            <span>{k.keyword}</span>
            <span className="keyword-sources">{k.sources.join(", ")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
function SeedForm(p: {
  seed: string;
  setSeed: (v: string) => void;
  audience: string;
  setAudience: (v: string) => void;
  disambHint: string;
  setDisambHint: (v: string) => void;
  topicCount: number;
  setTopicCount: (v: number) => void;
  mode: "standard" | "comprehensive";
  setMode: (v: "standard" | "comprehensive") => void;
  locationCode: number;
  setLocationCode: (v: number) => void;
  location: string;
  setLocation: (v: string) => void;
  locationInput: string;
  setLocationInput: (v: string) => void;
  clientId: string | null;
  enrichMetrics: boolean;
  setEnrichMetrics: (v: boolean) => void;
  showOptional: boolean;
  setShowOptional: (v: boolean) => void;
  contentType: ContentType;
  onChangeContentType: () => void;
  onSubmit: (e: FormEvent) => void;
}) {
  const isLocalSeo = p.contentType === "local_seo_page";
  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <h1 className="page-title">New research session</h1>

      <div className="banner" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <span>
          Creating <strong>{isLocalSeo ? "Local SEO pages" : "blog content"}</strong>
          {isLocalSeo
            ? " — location-targeted pages with competitor analysis."
            : " — SEO blog articles from your keyword map."}
        </span>
        <button type="button" className="link-btn" onClick={p.onChangeContentType}>
          Change
        </button>
      </div>

      <form onSubmit={p.onSubmit}>
        <label className="field">
          <span className="field-label">{isLocalSeo ? "Service" : "Seed keyword"}</span>
          <input
            className="input"
            value={p.seed}
            onChange={(e) => p.setSeed(e.target.value)}
            placeholder={isLocalSeo ? "e.g. emergency plumber" : "e.g. retatrutide"}
            maxLength={200}
            required
          />
        </label>

        {isLocalSeo && (
          <label className="field">
            <span className="field-label">Location</span>
            <LocationAutocomplete
              country={isoForLocationCode(p.locationCode)}
              clientId={p.clientId}
              value={p.location}
              inputValue={p.locationInput}
              placeholder="Start typing a city or area…"
              onSelect={(loc) => {
                p.setLocation(loc.location_name);
                p.setLocationInput(loc.location_name);
              }}
              onInputChange={(raw) => {
                p.setLocationInput(raw);
                p.setLocation("");
              }}
              onClear={() => {
                p.setLocation("");
                p.setLocationInput("");
              }}
            />
            <span className="field-hint">
              The city/area these pages target. Suggestions match the selected market;
              pre-fills when you schedule.
            </span>
          </label>
        )}

        <label className="field">
          <span className="field-label">{isLocalSeo ? "Search market" : "Country"}</span>
          <select
            className="select"
            value={p.locationCode}
            onChange={(e) => p.setLocationCode(Number(e.target.value))}
          >
            {SUPPORTED_COUNTRIES.map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </select>
        </label>

        {!p.showOptional && (
          <div className="collapse-link">
            <button type="button" className="link-btn" onClick={() => p.setShowOptional(true)}>
              + Add audience or disambiguation hint
            </button>
          </div>
        )}
        {p.showOptional && (
          <>
            <label className="field">
              <span className="field-label">Audience (optional)</span>
              <input
                className="input"
                value={p.audience}
                onChange={(e) => p.setAudience(e.target.value)}
                placeholder="e.g. clinicians researching prescribing decisions"
              />
            </label>
            <label className="field">
              <span className="field-label">Disambiguation (optional)</span>
              <input
                className="input"
                value={p.disambHint}
                onChange={(e) => p.setDisambHint(e.target.value)}
                placeholder="e.g. the chemical element, not the planet"
              />
            </label>
          </>
        )}

        <div className="row">
          <label className="field">
            <span className="field-label">Silos: {p.topicCount}</span>
            <input
              type="range"
              min={3}
              max={10}
              value={p.topicCount}
              onChange={(e) => p.setTopicCount(Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </label>
          <label className="field">
            <span className="field-label">Coverage mode</span>
            <select
              className="select"
              value={p.mode}
              onChange={(e) => p.setMode(e.target.value as "standard" | "comprehensive")}
            >
              <option value="standard">Standard (top 5)</option>
              <option value="comprehensive">Comprehensive (top 10)</option>
            </select>
          </label>
        </div>

        <label className="field" style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
          <input
            type="checkbox"
            checked={p.enrichMetrics}
            onChange={(e) => p.setEnrichMetrics(e.target.checked)}
          />
          <span>
            <span style={{ fontWeight: 600 }}>Fetch volume / CPC / KD</span>
            <span className="muted" style={{ marginLeft: 8 }}>
              · adds ~$0.40–$0.75 per run (DataForSEO)
            </span>
          </span>
        </label>

        <button className="btn btn-primary" type="submit" style={{ marginTop: 8 }}>
          Discover silos
        </button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// First step of the new-session flow: pick what you're creating. Both outputs
// share the same keyword-research pipeline; the choice is carried on the session
// so the Schedule step later defaults to it. Local SEO pages need a client-linked
// session + a target area, so that card explains the requirement.
function ContentTypeChooser(p: {
  hasClient: boolean;
  onPick: (c: ContentType) => void;
}) {
  return (
    <div className="card" style={{ maxWidth: 620 }}>
      <h1 className="page-title">What are you creating?</h1>
      <p className="muted">
        Both start from the same keyword research — pick the output so the writer and
        scheduler default to it. You can still change it when you schedule.
      </p>

      <div className="intent-grid">
        <button type="button" className="intent-card" onClick={() => p.onPick("blog_post")}>
          <span className="intent-card-title">Blog content</span>
          <span className="intent-card-desc">
            SEO blog articles generated from your keyword map. Publish to your site, Google
            Drive, or GitHub.
          </span>
        </button>

        <button type="button" className="intent-card" onClick={() => p.onPick("local_seo_page")}>
          <span className="intent-card-title">Local SEO content</span>
          <span className="intent-card-desc">
            Location-targeted Local SEO pages with competitor analysis and on-page scoring.
            {p.hasClient
              ? " Targets a client's service area."
              : " Needs a client with a Google Business Profile — open from a client workspace to schedule these."}
          </span>
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
function Disambiguation(p: {
  seed: string;
  interpretations: string[];
  onPick: (choice: string) => void;
}) {
  const [custom, setCustom] = useState("");
  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <h1 className="page-title">Which “{p.seed}”?</h1>
      <p className="muted">
        This seed looks ambiguous. Pick the intended interpretation so the silos
        stay on-topic.
      </p>
      <div className="interp-list">
        {p.interpretations.map((i) => (
          <button key={i} className="interp-option" onClick={() => p.onPick(i)}>
            {i}
          </button>
        ))}
      </div>
      <label className="field">
        <span className="field-label">Or describe it yourself</span>
        <div className="row">
          <input
            className="input"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            placeholder="e.g. the chemical element"
          />
          <button
            className="btn btn-primary"
            style={{ width: "auto" }}
            disabled={!custom.trim()}
            onClick={() => p.onPick(custom.trim())}
          >
            Use this
          </button>
        </div>
      </label>
    </div>
  );
}

// ---------------------------------------------------------------------------
function Review(p: {
  sessionId: string;
  degradedNotes: string[];
  finalizing: boolean;
  onFinalize: () => void;
  setError: (v: string | null) => void;
}) {
  const qc = useQueryClient();
  const sessionQuery = useQuery({
    queryKey: ["session", p.sessionId],
    queryFn: () => getSession(p.sessionId),
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["session", p.sessionId] });
  const onErr = (e: unknown) => p.setError(e instanceof Error ? e.message : "Action failed");

  const audienceMut = useMutation({
    mutationFn: (a: string) => overrideAudience(p.sessionId, a),
    onSuccess: invalidate,
    onError: onErr,
  });
  const addMut = useMutation({
    mutationFn: (b: AddTopicBody) => addTopic(p.sessionId, b),
    onSuccess: invalidate,
    onError: onErr,
  });
  const editMut = useMutation({
    mutationFn: (v: { id: string; body: EditTopicBody }) => editTopic(v.id, v.body),
    onSuccess: invalidate,
    onError: onErr,
  });
  const delMut = useMutation({
    mutationFn: (id: string) => deleteTopic(id),
    onSuccess: invalidate,
    onError: onErr,
  });

  const data = sessionQuery.data;
  const silos = data?.silos ?? [];
  const [audienceEdit, setAudienceEdit] = useState<string | null>(null);
  const audienceValue = audienceEdit ?? data?.detected_audience ?? "";

  if (sessionQuery.isLoading) {
    return <div className="state-center">Loading silos…</div>;
  }

  return (
    <>
      <h1 className="page-title">Review proposed silos</h1>

      {p.degradedNotes.map((note) => (
        <div className="banner" key={note}>
          {note}
        </div>
      ))}

      <div className="audience-bar">
        <span>Audience:</span>
        <input
          className="input"
          style={{ maxWidth: 360 }}
          value={audienceValue}
          onChange={(e) => setAudienceEdit(e.target.value)}
        />
        <button
          className="btn btn-ghost"
          disabled={audienceMut.isPending}
          onClick={() => audienceMut.mutate(audienceValue.trim())}
        >
          {audienceMut.isPending ? "Saving…" : "Save"}
        </button>
      </div>

      {silos.map((silo) => (
        <SiloCard
          key={silo.id}
          silo={silo}
          onEdit={(body) => editMut.mutate({ id: silo.id, body })}
          onDelete={() => delMut.mutate(silo.id)}
        />
      ))}

      <AddSiloRow onAdd={(body) => addMut.mutate(body)} adding={addMut.isPending} />

      <div className="toolbar">
        <span className="muted">{silos.length} silos</span>
        <button
          className="btn btn-primary"
          style={{ width: "auto" }}
          disabled={silos.length === 0 || p.finalizing}
          onClick={p.onFinalize}
        >
          {p.finalizing ? (
            <>
              <span className="spinner-sm" aria-hidden="true" />
              Finalizing…
            </>
          ) : (
            "Continue"
          )}
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
function SiloCard(p: {
  silo: Silo;
  onEdit: (body: EditTopicBody) => void;
  onDelete: () => void;
}) {
  const { silo } = p;
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(silo.name);
  const [rationale, setRationale] = useState(silo.rationale ?? "");
  const [rel, setRel] = useState<RelationshipType>(silo.relationship_type);

  if (editing) {
    return (
      <div className="silo-card">
        <label className="field">
          <span className="field-label">Name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Rationale</span>
          <textarea
            className="textarea"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="field-label">Relationship</span>
          <select
            className="select"
            value={rel}
            onChange={(e) => setRel(e.target.value as RelationshipType)}
          >
            {RELATIONSHIP_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {RELATIONSHIP_LABELS[o]}
              </option>
            ))}
          </select>
        </label>
        <div className="silo-actions">
          <button
            className="link-btn"
            onClick={() => {
              p.onEdit({ name: name.trim(), rationale, relationship_type: rel });
              setEditing(false);
            }}
          >
            Save
          </button>
          <button className="link-btn" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="silo-card">
      <div className="silo-head">
        <p className="silo-name">{silo.name}</p>
        <div className="silo-actions">
          <button className="link-btn" onClick={() => setEditing(true)}>
            Edit
          </button>
          <button className="link-btn" onClick={p.onDelete}>
            Remove
          </button>
        </div>
      </div>
      <div className="silo-badges">
        <span className="badge badge-rel">{RELATIONSHIP_LABELS[silo.relationship_type]}</span>
        {silo.is_broader_class && (
          <span
            className="badge badge-warn"
            title="Category-level coverage; include only if niche-strategic"
          >
            broader class
          </span>
        )}
        {silo.source !== "llm_proposed" && <span className="badge">{silo.source}</span>}
      </div>
      {silo.rationale && <p className="silo-text">{silo.rationale}</p>}
      {silo.supporting_evidence && (
        <p className="silo-evidence">Evidence: {silo.supporting_evidence}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function AddSiloRow(p: { onAdd: (body: AddTopicBody) => void; adding: boolean }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [rationale, setRationale] = useState("");
  const [rel, setRel] = useState<RelationshipType>("property_or_mechanism");

  if (!open) {
    return (
      <button className="link-btn" onClick={() => setOpen(true)}>
        + Add custom silo
      </button>
    );
  }

  return (
    <div className="inline-form">
      <label className="field">
        <span className="field-label">Name</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        <span className="field-label">Rationale (optional)</span>
        <textarea
          className="textarea"
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
        />
      </label>
      <label className="field">
        <span className="field-label">Relationship</span>
        <select
          className="select"
          value={rel}
          onChange={(e) => setRel(e.target.value as RelationshipType)}
        >
          {RELATIONSHIP_OPTIONS.map((o) => (
            <option key={o} value={o}>
              {RELATIONSHIP_LABELS[o]}
            </option>
          ))}
        </select>
      </label>
      <div className="silo-actions">
        <button
          className="link-btn"
          disabled={!name.trim() || p.adding}
          onClick={() => {
            p.onAdd({
              name: name.trim(),
              rationale: rationale.trim() || undefined,
              relationship_type: rel,
            });
            setOpen(false);
            setName("");
            setRationale("");
          }}
        >
          {p.adding ? "Adding…" : "Add silo"}
        </button>
        <button className="link-btn" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}
