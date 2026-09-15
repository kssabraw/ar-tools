"""Brand Guide Generator — Phase 2: the regulated claim-shape input-filter (§5.3a).

The universal guardrail (every client) is a prompt exclusion — synthesis may
invent brand language (swatch names, taglines, aesthetic descriptors) but never a
product claim, efficacy, dosage, safety/therapeutic claim, "FDA", or any fact not
in the pulled assets or captured copy. That lives in the synthesis prompt.

This module is the ADDITIONAL, deterministic protection that fires only for a
regulated client (`clients.content_compliance_mode != 'off'`, PRD §5.3): an
**input-filter, not just an output-scan**. Claim-*shape* sentences are matched
against the synthesis INPUT corpus and excised BEFORE synthesis — closing the
laundering hole where the client's own site copy (not a trusted claim source)
carries a gray-area claim that synthesis could recombine into an agency-branded
PDF.

Two detectors, per the PRD:
  * **Reuse `content_compliance`** — its critical rules already catch the marketing
    shapes (human dosing, branded-drug equivalence, guaranteed results, purchase
    advocacy). We run its `scan_text` per sentence and excise any sentence with a
    critical finding, so the two guardrails share one vocabulary.
  * **A claim-shape net for the broader efficacy pattern** the PRD names — an
    efficacy verb (treats / supports / boosts / reduces / clinically / proven …)
    plus a health-outcome object (weight loss, inflammation, recovery, …) — which
    `content_compliance` (tuned for finished marketing copy) does not fully cover.

Pure + unit-tested: sentence in, kept/excised out, no I/O. Gated entirely on the
regulated mode (PRD §5.3 accepted residual risk) — a non-regulated client's
corpus passes through untouched, and the universal prompt hygiene still applies.
"""

from __future__ import annotations

import re
from typing import Optional

from services import content_compliance

# --------------------------------------------------------------------------
# Sentence segmentation (pure). Split on sentence-final punctuation AND newlines
# (site copy is often line-broken fragments without terminal punctuation), so a
# claim on its own line is its own unit and only that unit is excised.
# --------------------------------------------------------------------------
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\r?\n+")


def split_sentences(text: str) -> list[str]:
    """Split a corpus into sentence-ish units for per-unit filtering. Pure."""
    if not text:
        return []
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


# --------------------------------------------------------------------------
# The efficacy claim-shape net (PRD §5.3a — the shape content_compliance's
# finished-marketing rules don't fully cover).
# --------------------------------------------------------------------------
_EFFICACY_VERB = (
    r"treat|treats|treated|treating|"
    r"support|supports|supported|supporting|"
    r"boost|boosts|boosted|boosting|"
    r"reduce|reduces|reduced|reducing|"
    r"improve|improves|improved|improving|"
    r"increase|increases|increased|increasing|"
    r"promote|promotes|promoted|promoting|"
    r"enhance|enhances|enhanced|enhancing|"
    r"prevent|prevents|prevented|preventing|"
    r"heal|heals|healed|healing|"
    r"cure|cures|cured|"
    r"relieve|relieves|relieved|relieving|"
    r"stimulate|stimulates|stimulated|stimulating|"
    r"regenerate|regenerates|regenerated|regenerating|"
    r"accelerate|accelerates|accelerated|accelerating|"
    r"repair|repairs|repaired|repairing|"
    r"restore|restores|restored|restoring|"
    r"alleviate|alleviates|alleviated|alleviating|"
    r"combat|combats|combated|combating|"
    r"lower|lowers|lowered|lowering|"
    r"burn|burns|burned|burning|"
    r"melt|melts|melted|melting|"
    r"optimize|optimizes|optimise|optimises|"
    r"aid|aids|aided|aiding|"
    r"target|targets|targeted|targeting"
)
_EFFICACY_VERB_RE = re.compile(r"\b(?:" + _EFFICACY_VERB + r")\b", re.IGNORECASE)

_HEALTH_OUTCOME = (
    r"weight(?:\s?loss)?|fat|muscle|lean\s?mass|recovery|healing|inflammation|"
    r"immune|immunity|energy|metabolism|metabolic|libido|sleep|anxiety|depression|"
    r"pain|injur(?:y|ies)|joint|joints|skin|hair|collagen|tissue|cells?|cellular|"
    r"hormone|hormonal|testosterone|estrogen|cognition|cognitive|memory|focus|"
    r"longevity|aging|ageing|anti[\s-]?aging|blood\s?sugar|glucose|insulin|"
    r"cholesterol|appetite|hunger|growth\s?hormone|wound|wounds|cartilage|tendon|"
    r"ligament|gut|digestion|mood|wellness|vitality|performance|endurance|stamina|"
    r"symptoms?|disease|condition|inflammatory|immune\s?system"
)
_HEALTH_OUTCOME_RE = re.compile(r"\b(?:" + _HEALTH_OUTCOME + r")\b", re.IGNORECASE)

# "clinically proven / studied / tested / shown" is a claim signal on its own.
_CLINICAL_CLAIM_RE = re.compile(
    r"\bclinically\s+(?:proven|studied|tested|shown|validated)\b"
    r"|\b(?:proven|shown|demonstrated)\s+to\b"
    r"|\bscientifically\s+proven\b",
    re.IGNORECASE,
)


def claim_shape_reason(sentence: str) -> Optional[str]:
    """A label for why a sentence is a claim-shape, or None. Pure.

    Fires on a standalone clinical-claim signal, OR on an efficacy verb co-occurring
    with a health-outcome object in the same sentence (the gate that keeps a
    plumber's "we support local homeowners" or "reduce your energy bill" — no
    health outcome — from tripping; this filter is regulated-only anyway)."""
    if _CLINICAL_CLAIM_RE.search(sentence):
        return "clinical_claim"
    if _EFFICACY_VERB_RE.search(sentence) and _HEALTH_OUTCOME_RE.search(sentence):
        return "efficacy_health_claim"
    return None


def sentence_excise_reason(sentence: str, mode: str) -> Optional[str]:
    """Combined per-sentence verdict for a regulated `mode`: the claim-shape net
    first, then `content_compliance`'s critical rules (shared vocabulary). Returns
    the reason label to excise on, or None to keep. Pure."""
    reason = claim_shape_reason(sentence)
    if reason:
        return reason
    result = content_compliance.scan_text(sentence, mode=mode)
    if result.critical_count > 0:
        # Name the first critical category so the provenance is legible.
        cat = next((f.category for f in result.findings if f.severity == "critical"), "compliance")
        return f"compliance:{cat}"
    return None


def filter_synthesis_corpus(corpus: str, mode: str) -> tuple[str, list[dict]]:
    """Excise claim-shape sentences from the synthesis input corpus for a regulated
    client (PRD §5.3a). Returns (filtered_corpus, excised[{sentence, reason}]).

    Pure. A non-regulated / unknown mode returns the corpus unchanged and no
    excisions (the resolver reads a blank/unknown mode as 'off'), so this is a
    no-op for every ordinary client and the universal prompt hygiene carries the
    weight there. Kept sentences are re-joined with newlines (segmentation isn't
    reversible, and the corpus is grounding context, not prose to preserve
    verbatim)."""
    active = content_compliance.resolve_mode({"content_compliance_mode": mode})
    if active == "off" or not corpus:
        return corpus, []

    kept: list[str] = []
    excised: list[dict] = []
    for sentence in split_sentences(corpus):
        reason = sentence_excise_reason(sentence, active)
        if reason:
            excised.append({"sentence": sentence[:200], "reason": reason})
        else:
            kept.append(sentence)
    return "\n".join(kept), excised
