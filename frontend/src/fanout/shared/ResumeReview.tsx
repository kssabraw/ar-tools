import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addTopic,
  deleteTopic,
  editTopic,
  expandSession,
  finalizeSilos,
  getCostEstimate,
  getSession,
  overrideAudience,
  setDeepMine,
  submitForApproval,
  type AddTopicBody,
  type EditTopicBody,
  type RelationshipType,
  type Silo,
} from "./api";
import { RELATIONSHIP_LABELS, RELATIONSHIP_OPTIONS } from "./relationshipTypes";

// Resume silo review for a session that stalled at `awaiting_silo_review`
// (or a `rejected` run being adjusted). The creation flow (VA Wizard / owner
// SiloDiscovery) holds the review → deep-mine → confirm steps in in-memory step
// state, reachable only in the beat after createSession/disambiguate — so a
// session opened later from the sessions list had no way to review its silos.
// This mounts the same flow in the workspace, keyed off the persisted session,
// reaching parity with the creation flow (edit silos → finalize → pick
// deep-mine → run / submit-for-approval). Role-aware: a VA is capped at the
// seed plus VA_DEEP_MINE_MAX silos and routes over-cap runs through approval;
// the owner runs directly. Server-side checks back up every restriction.

// Mirrors the backend VA deep-mine cap (config.va_deep_mine_max_silos) and the
// creation-flow constant in va/Wizard.tsx.
const VA_DEEP_MINE_MAX = 2;

const msg = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

type Step = "review" | "deepmine" | "cost";

export function ResumeReview(p: { sessionId: string; role: "owner" | "va" }) {
  const [step, setStep] = useState<Step>("review");
  const [error, setError] = useState<string | null>(null);
  // Deep-mine selection carried from the deepmine step into the confirm step.
  const [gated, setGated] = useState<string[]>([]);

  return (
    <div style={{ maxWidth: 720 }}>
      {error && <p className="form-error">{error}</p>}

      {step === "review" && (
        <ReviewStep
          sessionId={p.sessionId}
          onFinalize={() => {
            setError(null);
            setStep("deepmine");
          }}
          setError={setError}
        />
      )}

      {step === "deepmine" && (
        <DeepMineStep
          sessionId={p.sessionId}
          role={p.role}
          // Seed from the carried selection so returning here from Confirm
          // (Back) preserves the ticked silos instead of resetting to empty.
          initialGated={gated}
          onBack={() => setStep("review")}
          onNext={(ids) => {
            setError(null);
            setGated(ids);
            setStep("cost");
          }}
        />
      )}

      {step === "cost" && (
        <CostStep
          sessionId={p.sessionId}
          role={p.role}
          gated={gated}
          onBack={() => setStep("deepmine")}
          setError={setError}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function ReviewStep(p: {
  sessionId: string;
  onFinalize: () => void;
  setError: (v: string | null) => void;
}) {
  const qc = useQueryClient();
  const sessionQuery = useQuery({
    queryKey: ["session", p.sessionId],
    queryFn: () => getSession(p.sessionId),
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["session", p.sessionId] });
  const onErr = (e: unknown) => p.setError(msg(e));

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
  const finalizeMut = useMutation({
    mutationFn: () => finalizeSilos(p.sessionId),
    onSuccess: p.onFinalize,
    onError: onErr,
  });

  const data = sessionQuery.data;
  const silos = data?.silos ?? [];
  const [audienceEdit, setAudienceEdit] = useState<string | null>(null);
  const audienceValue = audienceEdit ?? data?.detected_audience ?? "";
  const tooFew = silos.length < 3;

  if (sessionQuery.isLoading) return <div className="state-center">Loading silos…</div>;
  if (sessionQuery.isError) return <p className="form-error">Couldn’t load this session’s silos.</p>;

  return (
    <div>
      <h1 className="page-title">Review proposed silos</h1>
      <p className="muted" style={{ marginTop: -4 }}>
        This run stopped for silo review. Edit the silos below, then finalize to
        continue into deep-mine selection and the run.
      </p>

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
          // Backend requires a non-empty audience (min_length=1); disable rather
          // than let an empty save round-trip to a 422.
          disabled={audienceMut.isPending || !audienceValue.trim()}
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
            if (
              silos.length <= 3 &&
              !confirm(
                "This drops you below 3 silos — you'll need to add one before continuing. Remove anyway?",
              )
            )
              return;
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
          disabled={tooFew || finalizeMut.isPending}
          title={tooFew ? "Add at least 3 silos to continue" : undefined}
          onClick={() => finalizeMut.mutate()}
        >
          {finalizeMut.isPending ? (
            <>
              <span className="spinner-sm" aria-hidden="true" />
              Finalizing…
            </>
          ) : (
            "Continue"
          )}
        </button>
      </div>
    </div>
  );
}

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
  // Re-seed the form from the current persisted silo whenever it opens/closes,
  // so an abandoned edit (or a since-updated prop) never resurfaces stale text.
  const resetFields = () => {
    setName(silo.name);
    setRationale(silo.rationale ?? "");
    setRel(silo.relationship_type);
  };

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
          <button
            className="link-btn"
            onClick={() => {
              resetFields();
              setEditing(false);
            }}
          >
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
          <button
            className="link-btn"
            onClick={() => {
              resetFields();
              setEditing(true);
            }}
          >
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
      </div>
      {silo.rationale && <p className="silo-text">{silo.rationale}</p>}
      {silo.supporting_evidence && (
        <p className="silo-evidence">Evidence: {silo.supporting_evidence}</p>
      )}
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
      <button className="link-btn" onClick={() => setOpen(true)}>
        + Add silo
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

// ---------------------------------------------------------------------------
function DeepMineStep(p: {
  sessionId: string;
  role: "owner" | "va";
  initialGated: string[];
  onBack: () => void;
  onNext: (gatedTopicIds: string[]) => void;
}) {
  const q = useQuery({
    queryKey: ["session", p.sessionId],
    queryFn: () => getSession(p.sessionId),
  });
  // Initialize from the carried selection (runs once per mount): re-entering
  // this step from Confirm keeps the previously ticked silos.
  const [selected, setSelected] = useState<Set<string>>(() => new Set(p.initialGated));
  // Live cost estimate as boxes are checked (PRD §7.2 #2). Cached per selection
  // count, so toggling is instant after the first fetch of each count.
  const est = useQuery({
    queryKey: ["cost-estimate", p.sessionId, selected.size],
    queryFn: () => getCostEstimate(p.sessionId, selected.size),
  });

  if (q.isLoading) return <p className="muted">Loading silos…</p>;
  if (q.isError) return <p className="form-error">Failed to load silos.</p>;
  const silos = q.data?.silos ?? [];
  // Owner is uncapped; a VA may deep-mine the seed plus VA_DEEP_MINE_MAX silos.
  const cap = p.role === "owner" ? silos.length : VA_DEEP_MINE_MAX;
  const atCap = selected.size >= cap;

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < cap) next.add(id);
      return next;
    });

  return (
    <div className="card">
      <h1 className="page-title">Choose silos to deep-mine</h1>
      <p className="muted">
        Competitor mining pulls the keywords competitors already rank for. The seed is always
        mined.
        {p.role === "owner"
          ? " Select any additional silos to mine."
          : ` You can add up to ${VA_DEEP_MINE_MAX} more silos.`}
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
              title={
                disabled && p.role !== "owner"
                  ? `VA mode allows the seed plus ${VA_DEEP_MINE_MAX} silos`
                  : undefined
              }
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
            {p.role !== "owner" &&
              (est.data.requires_approval
                ? " — above your workspace cap, so this needs Owner approval."
                : " — within your workspace cap.")}
          </>
        ) : (
          "Estimating cost…"
        )}
      </p>

      <div className="toolbar" style={{ marginTop: 16 }}>
        <button className="btn btn-ghost" style={{ width: "auto" }} onClick={p.onBack}>
          Back
        </button>
        <button
          className="btn btn-primary"
          style={{ width: "auto" }}
          onClick={() => p.onNext([...selected])}
        >
          Continue
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confirm + run. The authoritative estimate comes from the backend (§8.1). An
// owner always runs directly; a VA whose run trips the workspace cap must route
// it through Owner approval (submit-for-approval) instead of starting it — the
// backend enforces the same gate (a VA /expand over the cap is a 403).
function CostStep(p: {
  sessionId: string;
  role: "owner" | "va";
  gated: string[];
  onBack: () => void;
  setError: (v: string | null) => void;
}) {
  const qc = useQueryClient();
  const est = useQuery({
    queryKey: ["cost-estimate", p.sessionId, p.gated.length],
    queryFn: () => getCostEstimate(p.sessionId, p.gated.length),
  });

  // Run: persist the deep-mine selection first (same as the creation flow), then
  // kick off expansion. The workspace polls the summary, so invalidating flips it
  // out of this resume panel into the running view.
  const runMut = useMutation({
    mutationFn: async () => {
      await setDeepMine(p.sessionId, p.gated);
      return expandSession(p.sessionId);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["summary", p.sessionId] });
      qc.invalidateQueries({ queryKey: ["session", p.sessionId] });
    },
    onError: (e) => p.setError(msg(e)),
  });
  const submitMut = useMutation({
    mutationFn: async () => {
      await setDeepMine(p.sessionId, p.gated);
      return submitForApproval(p.sessionId);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["summary", p.sessionId] });
      qc.invalidateQueries({ queryKey: ["session", p.sessionId] });
    },
    onError: (e) => p.setError(msg(e)),
  });
  const busy = runMut.isPending || submitMut.isPending;

  if (est.isLoading)
    return (
      <div className="card">
        <p className="muted">Estimating cost…</p>
      </div>
    );
  if (est.isError || !est.data)
    return (
      <div className="card">
        <p className="form-error">Couldn’t estimate the cost. Go back and try again.</p>
        <button className="btn btn-ghost" style={{ width: "auto" }} onClick={p.onBack}>
          Back
        </button>
      </div>
    );

  const e = est.data;
  // Owner runs directly regardless of the estimate; only a VA is gated to approval.
  const needsApproval = p.role !== "owner" && e.requires_approval;
  const gatedCount = p.gated.length;

  return (
    <div className="card" style={{ maxWidth: 520 }}>
      <h1 className="page-title">Confirm and run</h1>
      <p className="muted">
        Mining the seed
        {gatedCount > 0 ? ` plus ${gatedCount} silo${gatedCount > 1 ? "s" : ""}` : ""}
        {" · "}
        {e.coverage_mode} coverage · {e.silo_count} silos.
      </p>

      <div className="cost-summary">
        <span className="cost-figure">${e.estimated_cost_usd.toFixed(2)}</span>
        {p.role !== "owner" && (
          <span className="muted"> estimated · cap ${e.va_soft_cap_usd.toFixed(2)}</span>
        )}
      </div>

      {needsApproval ? (
        <p className="field-hint">
          This run is above your workspace cap
          {e.recursive_fanout ? " (recursive deep research)" : ""}, so it needs Owner approval
          before it can start. You’ll be notified when the Owner decides.
        </p>
      ) : (
        <p className="field-hint">
          {p.role === "owner"
            ? "This starts the keyword pipeline now."
            : "Under the workspace cap, so no approval is needed."}
        </p>
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
            onClick={() => {
              p.setError(null);
              submitMut.mutate();
            }}
          >
            {submitMut.isPending ? "Submitting…" : "Submit for approval"}
          </button>
        ) : (
          <button
            className="btn btn-primary"
            style={{ width: "auto" }}
            disabled={busy}
            onClick={() => {
              p.setError(null);
              runMut.mutate();
            }}
          >
            {runMut.isPending ? "Starting…" : "Run now"}
          </button>
        )}
      </div>
    </div>
  );
}
