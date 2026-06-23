import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addTopic,
  cancelApproval,
  createSession,
  DEFAULT_LOCATION_CODE,
  SUPPORTED_COUNTRIES,
  deleteTopic,
  disambiguateSession,
  editTopic,
  expandSession,
  finalizeSilos,
  getCostEstimate,
  getProjects,
  getSession,
  getSummary,
  overrideAudience,
  planArticles,
  setDeepMine,
  submitForApproval,
  type AddTopicBody,
  type EditTopicBody,
  type RelationshipType,
  type Silo,
  type SiloDiscovery as Discovery,
} from "../shared/api";
import { AppShell } from "../shared/AppShell";
import { CancelRunButton } from "../shared/CancelRunButton";
import { CostBanner } from "../shared/CostBanner";
import { RELATIONSHIP_LABELS, RELATIONSHIP_OPTIONS } from "../shared/relationshipTypes";

// VA Mode (PRD §10): a linear, step-gated wizard. It's a restricted reskin of the
// Owner creation flow — same backend, fewer controls, sensible locked defaults.
// Steps that don't apply are skipped (disambiguation only fires on ambiguous
// seeds). Server-side role checks back up every UI restriction (PRD §10.3).

// The VA may deep-mine the seed plus at most this many silos (PRD §10.2 / §15.2
// §7.2 #3). Mirrors the backend cap (config.va_deep_mine_max_silos).
const VA_DEEP_MINE_MAX = 2;

type Step =
  | "project"
  | "seed"
  | "disambiguation"
  | "review"
  | "deepmine"
  | "cost"
  | "waiting"
  | "progress";

// The visible step rail (PRD §10.1). Disambiguation is conditional, so it's not a
// fixed rail entry — it slots between Seed and Review only when needed.
const RAIL: { key: Step; label: string }[] = [
  { key: "project", label: "Project" },
  { key: "seed", label: "Seed & settings" },
  { key: "review", label: "Review silos" },
  { key: "deepmine", label: "Deep-mine" },
  { key: "cost", label: "Confirm" },
  { key: "progress", label: "Run" },
];

const msg = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");
// Soft English-only check (PRD §10.2). Permissive: flags non-Latin scripts but
// allows accents/punctuation. Not a hard block — grounding handles real cases.
const NON_LATIN = /[^\u0000-\u024f\u2000-\u206f]/;

export function Wizard() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("project");
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [degradedNotes, setDegradedNotes] = useState<string[]>([]);
  const [interpretations, setInterpretations] = useState<string[]>([]);

  // Step 1
  const [projectId, setProjectId] = useState<string>("");
  // Step 2
  const [seed, setSeed] = useState("");
  const [audience, setAudience] = useState("");
  const [disambHint, setDisambHint] = useState("");
  const [showAudience, setShowAudience] = useState(false);
  const [showDisamb, setShowDisamb] = useState(false);
  // Step 3 (folded into the seed screen)
  const [topicCount, setTopicCount] = useState(5);
  const [mode, setMode] = useState<"standard" | "comprehensive">("standard");
  // Per-country locale (E1). Country -> DataForSEO location_code; default US.
  const [locationCode, setLocationCode] = useState<number>(DEFAULT_LOCATION_CODE);
  // §7.8 metrics enrichment — adds ~$0.40/run for a 5-silo standard run.
  // Defaults on per workspace; the toggle just lets the user opt out.
  const [enrichMetrics, setEnrichMetrics] = useState(true);
  // Deep-mine selection (step 6), carried into the cost confirmation (step 7) so
  // "Run now" can submit it.
  const [gated, setGated] = useState<string[]>([]);

  function applyDiscovery(d: Discovery) {
    setSessionId(d.session_id);
    setDegradedNotes(d.degraded_notes);
    if (d.needs_disambiguation) {
      setInterpretations(d.interpretations);
      setStep("disambiguation");
    } else {
      qc.setQueryData(["session", d.session_id], d);
      setStep("review");
    }
  }

  const createMut = useMutation({
    mutationFn: createSession,
    onSuccess: applyDiscovery,
    onError: (e) => setError(msg(e)),
  });
  const disambigMut = useMutation({
    mutationFn: (choice: string) => disambiguateSession(sessionId!, choice),
    onSuccess: applyDiscovery,
    onError: (e) => setError(msg(e)),
  });
  const finalizeMut = useMutation({
    mutationFn: () => finalizeSilos(sessionId!),
    onSuccess: () => setStep("deepmine"),
    onError: (e) => setError(msg(e)),
  });
  const runMut = useMutation({
    mutationFn: async (gatedIds: string[]) => {
      await setDeepMine(sessionId!, gatedIds);
      return expandSession(sessionId!);
    },
    onSuccess: () => {
      setStep("progress");
      qc.invalidateQueries({ queryKey: ["summary", sessionId] });
    },
    onError: (e) => setError(msg(e)),
  });
  // Over-cap / recursive runs go to the Owner instead of starting (PRD §11.3).
  // Persist the deep-mine selection first (same as run-now) so the approved run
  // mines the right silos.
  const submitMut = useMutation({
    mutationFn: async (gatedIds: string[]) => {
      await setDeepMine(sessionId!, gatedIds);
      return submitForApproval(sessionId!);
    },
    onSuccess: () => {
      setStep("waiting");
      qc.invalidateQueries({ queryKey: ["summary", sessionId] });
    },
    onError: (e) => setError(msg(e)),
  });

  const working = createMut.isPending || disambigMut.isPending;

  function submitSeed(e: FormEvent) {
    e.preventDefault();
    setError(null);
    createMut.mutate({
      seed_keyword: seed.trim(),
      project_id: projectId || undefined,
      audience_hint: audience.trim() || undefined,
      disambiguation_hint: disambHint.trim() || undefined,
      topic_count: topicCount,
      coverage_mode: mode,
      location_code: locationCode,
      enrich_with_metrics: enrichMetrics,
    });
  }

  return (
    <AppShell>
      <div className="content" style={{ maxWidth: 720 }}>
        <StepRail current={step} />
        {error && <p className="form-error">{error}</p>}

        {working && (
          <div className="card" style={{ textAlign: "center" }}>
            <div className="spinner" />
            <p className="muted">Discovering silos for “{seed.trim()}”… usually 20–40 seconds.</p>
          </div>
        )}

        {!working && step === "project" && (
          <ProjectStep
            projectId={projectId}
            setProjectId={setProjectId}
            onNext={() => {
              setError(null);
              setStep("seed");
            }}
          />
        )}

        {!working && step === "seed" && (
          <SeedStep
            {...{
              seed, setSeed, audience, setAudience, disambHint, setDisambHint,
              showAudience, setShowAudience, showDisamb, setShowDisamb,
              topicCount, setTopicCount, mode, setMode,
              locationCode, setLocationCode,
              enrichMetrics, setEnrichMetrics,
              onBack: () => setStep("project"),
              onSubmit: submitSeed,
            }}
          />
        )}

        {!working && step === "disambiguation" && (
          <DisambiguationStep
            seed={seed}
            interpretations={interpretations}
            onPick={(choice) => {
              setError(null);
              disambigMut.mutate(choice);
            }}
          />
        )}

        {!working && step === "review" && sessionId && (
          <ReviewStep
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

        {step === "deepmine" && sessionId && (
          <DeepMineStep
            sessionId={sessionId}
            onBack={() => setStep("review")}
            onNext={(ids) => {
              setError(null);
              setGated(ids);
              setStep("cost");
            }}
          />
        )}

        {step === "cost" && sessionId && (
          <CostStep
            sessionId={sessionId}
            gatedCount={gated.length}
            running={runMut.isPending}
            submitting={submitMut.isPending}
            onBack={() => setStep("deepmine")}
            onRun={() => {
              setError(null);
              runMut.mutate(gated);
            }}
            onSubmitForApproval={() => {
              setError(null);
              submitMut.mutate(gated);
            }}
          />
        )}

        {step === "waiting" && sessionId && (
          <WaitingStep
            sessionId={sessionId}
            onCancelled={() => {
              setError(null);
              setStep("deepmine");
            }}
            onAdjust={() => {
              setError(null);
              setStep("deepmine");
            }}
            onApproved={() => setStep("progress")}
            setError={setError}
          />
        )}

        {step === "progress" && sessionId && (
          <ProgressStep sessionId={sessionId} onDone={() => navigate(`/session/${sessionId}`)} />
        )}
      </div>
    </AppShell>
  );
}

// ---------------------------------------------------------------------------
function StepRail({ current }: { current: Step }) {
  // Map the conditional disambiguation step onto the "Review silos" rail entry so
  // the rail stays stable whether or not disambiguation fires; the approval
  // "waiting" screen stays on the "Confirm" rail entry.
  const activeKey: Step =
    current === "disambiguation" ? "review" : current === "waiting" ? "cost" : current;
  const idx = RAIL.findIndex((r) => r.key === activeKey);
  return (
    <ol className="wizard-rail">
      {RAIL.map((r, i) => (
        <li
          key={r.key}
          className={
            "wizard-rail-step" +
            (i === idx ? " wizard-rail-current" : "") +
            (i < idx ? " wizard-rail-done" : "")
          }
        >
          <span className="wizard-rail-num">{i + 1}</span>
          <span className="wizard-rail-label">{r.label}</span>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------------------
function ProjectStep(p: {
  projectId: string;
  setProjectId: (v: string) => void;
  onNext: () => void;
}) {
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects });

  // Default to the Scratch project (or the first available) once loaded.
  useEffect(() => {
    if (!p.projectId && projects.data && projects.data.length > 0) {
      const scratch = projects.data.find((x) => x.is_scratch) ?? projects.data[0];
      p.setProjectId(scratch.id);
    }
  }, [projects.data, p]);

  return (
    <div className="card" style={{ maxWidth: 520 }}>
      <h1 className="page-title">Pick a project</h1>
      <p className="muted">Your research session will be saved under this project.</p>
      {projects.isLoading && <p className="muted">Loading projects…</p>}
      {projects.data && (
        <label className="field">
          <span className="field-label">Project</span>
          <select
            className="select"
            value={p.projectId}
            onChange={(e) => p.setProjectId(e.target.value)}
          >
            {projects.data.map((proj) => (
              <option key={proj.id} value={proj.id}>
                {proj.name}
                {proj.is_scratch ? " (Scratch)" : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="toolbar">
        <span className="muted" />
        <button
          className="btn btn-primary"
          style={{ width: "auto" }}
          disabled={!p.projectId}
          onClick={p.onNext}
        >
          Continue
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
function SeedStep(p: {
  seed: string;
  setSeed: (v: string) => void;
  audience: string;
  setAudience: (v: string) => void;
  disambHint: string;
  setDisambHint: (v: string) => void;
  showAudience: boolean;
  setShowAudience: (v: boolean) => void;
  showDisamb: boolean;
  setShowDisamb: (v: boolean) => void;
  topicCount: number;
  setTopicCount: (v: number) => void;
  locationCode: number;
  setLocationCode: (v: number) => void;
  mode: "standard" | "comprehensive";
  setMode: (v: "standard" | "comprehensive") => void;
  enrichMetrics: boolean;
  setEnrichMetrics: (v: boolean) => void;
  onBack: () => void;
  onSubmit: (e: FormEvent) => void;
}) {
  const trimmed = p.seed.trim();
  const tooLong = trimmed.length > 200;
  const nonLatin = NON_LATIN.test(trimmed);
  const valid = trimmed.length > 0 && !tooLong;

  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <h1 className="page-title">What do you want to research?</h1>
      <form onSubmit={p.onSubmit}>
        <label className="field">
          <span className="field-label">Seed keyword</span>
          <input
            className="input"
            value={p.seed}
            onChange={(e) => p.setSeed(e.target.value)}
            placeholder="e.g. retatrutide"
            maxLength={200}
            required
          />
        </label>
        {tooLong && <p className="form-error">Keep the seed under 200 characters.</p>}
        {nonLatin && !tooLong && (
          <p className="field-hint">This tool works best with English seeds.</p>
        )}

        {!p.showAudience ? (
          <div className="collapse-link">
            <button type="button" className="link-btn" onClick={() => p.setShowAudience(true)}>
              Specify audience
            </button>
          </div>
        ) : (
          <label className="field">
            <span className="field-label">Audience (optional)</span>
            <input
              className="input"
              value={p.audience}
              onChange={(e) => p.setAudience(e.target.value)}
              placeholder="e.g. clinicians researching prescribing decisions"
            />
          </label>
        )}

        {!p.showDisamb ? (
          <div className="collapse-link">
            <button type="button" className="link-btn" onClick={() => p.setShowDisamb(true)}>
              Seed is ambiguous?
            </button>
          </div>
        ) : (
          <label className="field">
            <span className="field-label">Disambiguation (optional)</span>
            <input
              className="input"
              value={p.disambHint}
              onChange={(e) => p.setDisambHint(e.target.value)}
              placeholder="e.g. the chemical element, not the planet"
            />
          </label>
        )}

        <div className="row" style={{ marginTop: 8 }}>
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
            <span className="field-label">Coverage</span>
            <select
              className="select"
              value={p.mode}
              onChange={(e) => p.setMode(e.target.value as "standard" | "comprehensive")}
            >
              <option value="standard">Standard</option>
              <option value="comprehensive">Comprehensive</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">Country</span>
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
        </div>

        <label className="field" style={{ display: "flex", alignItems: "center", gap: 10 }}>
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

        <div className="locked-settings">
          <span className="locked-row">
            <span>Relevance threshold</span>
            <span className="badge">Workspace default · locked</span>
          </span>
        </div>

        <div className="toolbar">
          <button type="button" className="btn btn-ghost" style={{ width: "auto" }} onClick={p.onBack}>
            Back
          </button>
          <button className="btn btn-primary" type="submit" style={{ width: "auto" }} disabled={!valid}>
            Discover silos
          </button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
function DisambiguationStep(p: {
  seed: string;
  interpretations: string[];
  onPick: (choice: string) => void;
}) {
  const [custom, setCustom] = useState("");
  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <h1 className="page-title">Which “{p.seed}”?</h1>
      <p className="muted">This seed looks ambiguous. Pick the intended meaning so the silos stay on-topic.</p>
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
function ReviewStep(p: {
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
  const tooFew = silos.length < 3;

  if (sessionQuery.isLoading) return <div className="state-center">Loading silos…</div>;

  return (
    <div>
      <h1 className="page-title">Review proposed silos</h1>
      {p.degradedNotes.map((note) => (
        <div className="banner" key={note}>{note}</div>
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
          onDelete={() => {
            if (silos.length <= 3 && !confirm("This drops you below 3 silos — you'll need to add one before continuing. Remove anyway?")) return;
            delMut.mutate(silo.id);
          }}
        />
      ))}

      <AddSiloRow onAdd={(body) => addMut.mutate(body)} adding={addMut.isPending} />

      <div className="toolbar">
        <span className="muted">
          {silos.length} silos{tooFew && " · need at least 3 to continue"}
        </span>
        <button
          className="btn btn-primary"
          style={{ width: "auto" }}
          disabled={tooFew || p.finalizing}
          title={tooFew ? "Add at least 3 silos to continue" : undefined}
          onClick={p.onFinalize}
        >
          {p.finalizing ? (
            <><span className="spinner-sm" aria-hidden="true" />Finalizing…</>
          ) : (
            "Continue"
          )}
        </button>
      </div>
    </div>
  );
}

function SiloCard(p: { silo: Silo; onEdit: (body: EditTopicBody) => void; onDelete: () => void }) {
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
          <textarea className="textarea" value={rationale} onChange={(e) => setRationale(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Relationship</span>
          <select className="select" value={rel} onChange={(e) => setRel(e.target.value as RelationshipType)}>
            {RELATIONSHIP_OPTIONS.map((o) => (
              <option key={o} value={o}>{RELATIONSHIP_LABELS[o]}</option>
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
          <button className="link-btn" onClick={() => setEditing(false)}>Cancel</button>
        </div>
      </div>
    );
  }

  return (
    <div className="silo-card">
      <div className="silo-head">
        <p className="silo-name">{silo.name}</p>
        <div className="silo-actions">
          <button className="link-btn" onClick={() => setEditing(true)}>Edit</button>
          <button className="link-btn" onClick={p.onDelete}>Remove</button>
        </div>
      </div>
      <div className="silo-badges">
        <span className="badge badge-rel">{RELATIONSHIP_LABELS[silo.relationship_type]}</span>
        {silo.is_broader_class && (
          <span className="badge badge-warn" title="Category-level coverage; include only if niche-strategic">
            broader class
          </span>
        )}
      </div>
      {silo.rationale && <p className="silo-text">{silo.rationale}</p>}
      {silo.supporting_evidence && <p className="silo-evidence">Evidence: {silo.supporting_evidence}</p>}
    </div>
  );
}

function AddSiloRow(p: { onAdd: (body: AddTopicBody) => void; adding: boolean }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [rationale, setRationale] = useState("");
  const [rel, setRel] = useState<RelationshipType>("property_or_mechanism");

  if (!open) {
    return (
      <button className="link-btn" onClick={() => setOpen(true)}>+ Add silo</button>
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
        <textarea className="textarea" value={rationale} onChange={(e) => setRationale(e.target.value)} />
      </label>
      <label className="field">
        <span className="field-label">Relationship</span>
        <select className="select" value={rel} onChange={(e) => setRel(e.target.value as RelationshipType)}>
          {RELATIONSHIP_OPTIONS.map((o) => (
            <option key={o} value={o}>{RELATIONSHIP_LABELS[o]}</option>
          ))}
        </select>
      </label>
      <div className="silo-actions">
        <button
          className="link-btn"
          disabled={!name.trim() || p.adding}
          onClick={() => {
            p.onAdd({ name: name.trim(), rationale: rationale.trim() || undefined, relationship_type: rel });
            setOpen(false);
            setName("");
            setRationale("");
          }}
        >
          {p.adding ? "Adding…" : "Add silo"}
        </button>
        <button className="link-btn" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
function DeepMineStep(p: {
  sessionId: string;
  onBack: () => void;
  onNext: (gatedTopicIds: string[]) => void;
}) {
  const q = useQuery({ queryKey: ["session", p.sessionId], queryFn: () => getSession(p.sessionId) });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // Live cost estimate as boxes are checked (PRD §7.2 #2). React Query caches per
  // selection count, so toggling is instant after the first fetch of each count.
  const est = useQuery({
    queryKey: ["cost-estimate", p.sessionId, selected.size],
    queryFn: () => getCostEstimate(p.sessionId, selected.size),
  });

  if (q.isLoading) return <p className="muted">Loading silos…</p>;
  if (q.isError) return <p className="form-error">Failed to load silos.</p>;
  const silos = q.data?.silos ?? [];
  const atCap = selected.size >= VA_DEEP_MINE_MAX;

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < VA_DEEP_MINE_MAX) next.add(id);
      return next;
    });

  return (
    <div className="card">
      <h1 className="page-title">Choose silos to deep-mine</h1>
      <p className="muted">
        Competitor mining pulls the keywords competitors already rank for. The seed is always
        mined. You can add up to {VA_DEEP_MINE_MAX} more silos.
      </p>

      <div className="keyword-grid" style={{ marginTop: 16 }}>
        <label className="keyword-row" style={{ opacity: 0.7 }}>
          <span>
            <input type="checkbox" checked disabled style={{ marginRight: 8 }} />
            Seed keyword (always mined)
          </span>
          <span className="keyword-sources">required</span>
        </label>
        {silos.map((s) => {
          const on = selected.has(s.id);
          const disabled = !on && atCap;
          return (
            <label
              key={s.id}
              className="keyword-row"
              style={{ cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1 }}
              title={disabled ? `VA mode allows the seed plus ${VA_DEEP_MINE_MAX} silos` : undefined}
            >
              <span>
                <input
                  type="checkbox"
                  checked={on}
                  disabled={disabled}
                  onChange={() => toggle(s.id)}
                  style={{ marginRight: 8 }}
                />
                {s.name}
              </span>
              <span className="keyword-sources">{RELATIONSHIP_LABELS[s.relationship_type]}</span>
            </label>
          );
        })}
      </div>

      <p className="field-hint" style={{ marginTop: 12 }}>
        {est.data ? (
          <>
            Estimated cost: ${est.data.estimated_cost_usd.toFixed(2)}
            {est.data.requires_approval
              ? " — above your workspace cap, so this needs Owner approval."
              : " — within your workspace cap."}
          </>
        ) : (
          "Estimating cost…"
        )}
      </p>

      <div className="toolbar" style={{ marginTop: 16 }}>
        <button className="btn btn-ghost" style={{ width: "auto" }} onClick={p.onBack}>Back</button>
        <button className="btn btn-primary" style={{ width: "auto" }} onClick={() => p.onNext([...selected])}>
          Continue
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 7 — cost confirmation (PRD §10.2 step 7 / §11.3). The authoritative
// estimate comes from the backend (§8.1 model). Under the soft cap → "Run now";
// over the cap (or recursive) → "Submit for approval", which parks the run for
// the Owner rather than starting it.
function CostStep(p: {
  sessionId: string;
  gatedCount: number;
  running: boolean;
  submitting: boolean;
  onBack: () => void;
  onRun: () => void;
  onSubmitForApproval: () => void;
}) {
  const est = useQuery({
    queryKey: ["cost-estimate", p.sessionId, p.gatedCount],
    queryFn: () => getCostEstimate(p.sessionId, p.gatedCount),
  });
  const busy = p.running || p.submitting;

  if (est.isLoading) return <div className="card"><p className="muted">Estimating cost…</p></div>;
  if (est.isError || !est.data)
    return (
      <div className="card">
        <p className="form-error">Couldn’t estimate the cost. Go back and try again.</p>
        <button className="btn btn-ghost" style={{ width: "auto" }} onClick={p.onBack}>Back</button>
      </div>
    );

  const e = est.data;
  const needsApproval = e.requires_approval;

  return (
    <div className="card" style={{ maxWidth: 520 }}>
      <h1 className="page-title">Confirm and run</h1>
      <p className="muted">
        Mining the seed{p.gatedCount > 0 ? ` plus ${p.gatedCount} silo${p.gatedCount > 1 ? "s" : ""}` : ""}
        {" · "}{e.coverage_mode} coverage · {e.silo_count} silos.
      </p>

      <div className="cost-summary">
        <span className="cost-figure">${e.estimated_cost_usd.toFixed(2)}</span>
        <span className="muted"> estimated · cap ${e.va_soft_cap_usd.toFixed(2)}</span>
      </div>

      {needsApproval ? (
        <p className="field-hint">
          This run is above your workspace cap
          {e.recursive_fanout ? " (recursive deep research)" : ""}, so it needs Owner approval
          before it can start. You’ll be notified when the Owner decides.
        </p>
      ) : (
        <p className="field-hint">Under the workspace cap, so no approval is needed.</p>
      )}

      <div className="toolbar">
        <button className="btn btn-ghost" style={{ width: "auto" }} disabled={busy} onClick={p.onBack}>
          Back
        </button>
        {needsApproval ? (
          <button
            className="btn btn-primary"
            style={{ width: "auto" }}
            disabled={busy}
            onClick={p.onSubmitForApproval}
          >
            {p.submitting ? "Submitting…" : "Submit for approval"}
          </button>
        ) : (
          <button className="btn btn-primary" style={{ width: "auto" }} disabled={busy} onClick={p.onRun}>
            {p.running ? "Starting…" : "Run now"}
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Approval waiting screen (PRD §11.3 / §10.2 step 7). Polls the summary every 30s
// (the §11.3 cadence). When the Owner approves, the session leaves
// pending_approval → running/awaiting_article_planning/complete and we hand off
// to the progress screen; on reject we show the Owner's note and let the VA
// adjust + resubmit.
function WaitingStep(p: {
  sessionId: string;
  onCancelled: () => void;
  onAdjust: () => void;
  onApproved: () => void;
  setError: (v: string | null) => void;
}) {
  const qc = useQueryClient();
  const summaryQ = useQuery({
    queryKey: ["summary", p.sessionId],
    queryFn: () => getSummary(p.sessionId),
    refetchInterval: (q) => (q.state.data?.status === "pending_approval" ? 30000 : false),
  });
  const cancelMut = useMutation({
    mutationFn: () => cancelApproval(p.sessionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["summary", p.sessionId] });
      p.onCancelled();
    },
    onError: (e) => p.setError(msg(e)),
  });

  const status = summaryQ.data?.status;

  // Once the request is decided and the run is moving, hand off to the progress
  // screen, which owns every post-approval status (running / awaiting / complete
  // AND error — a fast-failing approved run can skip straight to error between
  // 30s polls, and ProgressStep is what surfaces last_error). Only the two
  // gate states (pending_approval, rejected) stay on this screen.
  useEffect(() => {
    if (status && status !== "pending_approval" && status !== "rejected") {
      p.onApproved();
    }
  }, [status, p]);

  if (status === "rejected") {
    const note = summaryQ.data?.approval.note;
    return (
      <div className="card" style={{ maxWidth: 520 }}>
        <h1 className="page-title">Request not approved</h1>
        <p className="muted">The Owner didn’t approve this run.</p>
        {note && <div className="banner">Note from the Owner: {note}</div>}
        <p className="field-hint">
          You can adjust the run — fewer silos or standard coverage often brings the cost under
          the cap — and resubmit.
        </p>
        <div className="toolbar">
          <button className="btn btn-primary" style={{ width: "auto" }} onClick={p.onAdjust}>
            Adjust &amp; resubmit
          </button>
        </div>
      </div>
    );
  }

  const est = summaryQ.data?.approval.estimated_cost_usd;
  return (
    <div className="card" style={{ textAlign: "center", maxWidth: 520 }}>
      <div className="spinner" />
      <h1 className="page-title" style={{ marginTop: 12 }}>Waiting for approval</h1>
      <p className="muted">
        Your run{est != null ? ` (estimated $${est.toFixed(2)})` : ""} is with the Owner for
        approval. This screen updates automatically when they decide.
      </p>
      <div className="toolbar" style={{ justifyContent: "center" }}>
        <button
          className="btn btn-ghost"
          style={{ width: "auto" }}
          disabled={cancelMut.isPending}
          onClick={() => cancelMut.mutate()}
        >
          {cancelMut.isPending ? "Cancelling…" : "Cancel request"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 8 — progress. The pipeline runs server-side; poll the summary. Expansion
// finishes at awaiting_article_planning, where we auto-kick article planning so
// the VA flow stays linear (PRD §10.1). On complete, hand off to the results view.
const EXPANSION_STAGES = [
  "Expanding keywords per silo",
  "Autocomplete enrichment",
  "Mining competitor keywords",
  "Scoring relevance",
  "Clustering",
];
const PLANNING_STAGES = ["Fetching SERPs", "Planning articles", "Deduplicating across silos"];

function ProgressStep(p: { sessionId: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [planKicked, setPlanKicked] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  const summaryQ = useQuery({
    queryKey: ["summary", p.sessionId],
    queryFn: () => getSummary(p.sessionId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "running" || s === "awaiting_article_planning" ? 4000 : false;
    },
  });

  const planMut = useMutation({
    mutationFn: () => planArticles(p.sessionId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["summary", p.sessionId] }),
  });

  const status = summaryQ.data?.status;
  const phase: "expanding" | "planning" = planKicked || status === "complete" ? "planning" : "expanding";

  useEffect(() => {
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Auto-chain expansion -> article planning once expansion lands.
  useEffect(() => {
    if (status === "awaiting_article_planning" && !planKicked && !planMut.isPending) {
      setPlanKicked(true);
      planMut.mutate();
    }
  }, [status, planKicked, planMut]);

  if (status === "error") {
    return (
      <div className="card">
        <h1 className="page-title">The run hit a problem</h1>
        <p className="form-error">{summaryQ.data?.last_error ?? "The pipeline failed."}</p>
        <p className="muted">Anything collected before the failure was saved. Try a new session.</p>
      </div>
    );
  }

  if (status === "cancelled") {
    return (
      <div className="card">
        <h1 className="page-title">Run cancelled</h1>
        <p className="muted">
          The pipeline stopped at your request. Any partial work and cost spent before
          cancellation are preserved. Start a new session to try again.
        </p>
      </div>
    );
  }

  if (status === "complete") {
    return (
      <div className="card" style={{ textAlign: "center" }}>
        <h1 className="page-title">Your keyword map is ready</h1>
        <p className="muted">
          {summaryQ.data?.plan?.clusters ?? 0} articles planned across{" "}
          {summaryQ.data?.plan?.topics.length ?? 0} silos.
        </p>
        <button className="btn btn-primary" style={{ width: "auto" }} onClick={p.onDone}>
          View results
        </button>
      </div>
    );
  }

  const stages = phase === "planning" ? PLANNING_STAGES : EXPANSION_STAGES;
  const stage = stages[Math.min(stages.length - 1, Math.floor(elapsed / 25))];

  return (
    <div className="card" style={{ textAlign: "center" }}>
      <div className="spinner" />
      <h1 className="page-title" style={{ marginTop: 12 }}>
        {phase === "planning" ? "Planning your articles" : "Building your keyword pool"}
      </h1>
      <p className="muted">{stage}… · elapsed {elapsed}s</p>
      <p className="field-hint">This usually takes a few minutes. You can leave this open.</p>
      <CostBanner cost={summaryQ.data?.cost} running />
      {status === "running" && (
        <div style={{ marginTop: 12 }}>
          <CancelRunButton sessionId={p.sessionId} />
        </div>
      )}
    </div>
  );
}
