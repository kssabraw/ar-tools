"""Content compliance guardrail — the regulatory net over published content.

Some clients (peptide / research-chemical vendors) sell products that are "for
research use only" and must never be marketed with human-usage instructions or
drug-marketing claims. A blog post that tells a person how many milligrams of a
peptide to inject, calls the product "just as good as Ozempic", promises
guaranteed weight loss, or says "buy yours today" is a real regulatory exposure
— and the content pipeline will happily produce all four, because the SEO/voice
scorers reward exactly the specificity that gets a vendor in trouble.

This module is that guardrail. It scans finished content for four forbidden
categories and, for a client in a regulated `content_compliance_mode`, blocks
publishing on any critical finding:

  * ``human_dosing``          — dose amounts directed at a reader, reconstitution
                                / injection how-to, titration schedules, dosing
                                protocols, per-bodyweight dosing, stacking.
  * ``branded_equivalence``   — efficacy-equivalence claims against a branded /
                                approved medication (Ozempic, Mounjaro,
                                semaglutide, tirzepatide, …).
  * ``guaranteed_results``    — guaranteed outcomes, promised weight loss, "cures",
                                "clinically proven to", "no side effects".
  * ``advocacy``              — purchase / try-it advocacy ("you should try",
                                "buy now", "start your journey today").

Deterministic by design. A regulatory finding has to be *provable* on the page
— a matched phrase the team can see — not a model's judgement that can be talked
out of a verdict, and not something that varies run to run. Every finding
carries the exact offending snippet.

The scan (`scan_text`) is pure and has no web-framework dependency, so it is
unit-tested directly. `assert_content_publishable` is the thin gate that turns a
critical result into a 409 at every publish choke point, mirroring
`voice_card_service.assert_voice_publishable`. Both share the "only a provable
critical blocks; `force` is the deliberate override" contract, because the
never-use list here is regex, not an LLM extraction, so a false positive is
rarer but still possible and must not deadlock the team.

Scoping is per-client via `clients.content_compliance_mode`:
  * ``'off'``      — no checks (default; every non-regulated client is untouched).
  * ``'peptide'``  — full guardrail; all four categories block publishing.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException

# Modes that engage the guardrail. Kept as a set so a future 'strict'/'medical'
# alias is one line, and an unknown/typo'd mode reads as "off" (fail-open on
# *scoping* — a mis-set flag must never silently start blocking a client who was
# never meant to be regulated; the block only happens for a mode we recognise).
_ACTIVE_MODES = {"peptide"}

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# Brand NAMES only. These have no legitimate "generic" (they are trade names),
# so "generic/cheaper/budget Ozempic" is always a knockoff-positioning claim.
_BRAND_NAMES = (
    r"ozempic|wegovy|mounjaro|zepbound|rybelsus|saxenda|victoza|trulicity|"
    r"byetta|bydureon"
)
# Brand names + the generic INNs (semaglutide, tirzepatide, …). Used for the
# equivalence-claim rules — "just as good as semaglutide" is the same claim as
# "just as good as Ozempic". NOT used for the generic/price rule, because
# "generic liraglutide" is a real, legitimately-named generic drug, not a
# knockoff of Nova's product.
_BRAND_DRUGS = (
    _BRAND_NAMES + r"|semaglutide|tirzepatide|liraglutide|dulaglutide|exenatide"
)

# Peptides / compounds a regulated vendor sells or writes about. Used to anchor
# "stacking" and bare-dose detection so a generic "combine with a healthy diet"
# or a "$5 mg" price never trips the net.
_PEPTIDES = (
    r"bpc[\s-]?157|tb[\s-]?500|mots[\s-]?c|cjc[\s-]?1295|ipamorelin|retatrutide|"
    r"tesamorelin|sermorelin|hexarelin|ghrp[\s-]?\d*|ghk[\s-]?cu|aod[\s-]?9604|"
    r"ss[\s-]?31|epitalon|semax|selank|melanotan|pt[\s-]?141|kisspeptin|"
    r"thymosin|igf[\s-]?1|hgh|peptide"
)

_DOSE_UNIT = r"(?:mg|mcg|µg|ug|iu|units?)"
_DOSE_AMOUNT = r"\d+(?:\.\d+)?\s?" + _DOSE_UNIT

# Negative lookahead: the unit is NOT a per-volume concentration (mg/dL blood
# glucose, ng/mL, mmol/L). Keeps per-bodyweight (/kg) and per-time (/wk, /day).
_NOT_CONC = r"(?!\s*/\s*(?:d?[lL]|m[lL]|mol|mmol)\b)"


@dataclass(frozen=True)
class _Rule:
    category: str
    severity: str  # "critical" | "warning"
    pattern: re.Pattern
    message: str


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Rules. Order is cosmetic (findings are re-sorted critical-first); each rule
# fires independently and contributes its own matched snippet as evidence.
# ---------------------------------------------------------------------------
_RULES: tuple[_Rule, ...] = (
    # -- human dosing / administration -----------------------------------
    _Rule(
        "human_dosing", "critical",
        _rx(r"\breconstitut(?:e|es|ed|ing|ion)\b"),
        "Reconstitution instructions are human-preparation guidance.",
    ),
    _Rule(
        "human_dosing", "critical",
        _rx(r"\bbacteriostatic\b|\bbac water\b"),
        "Bacteriostatic-water / reconstitution detail is administration guidance.",
    ),
    _Rule(
        "human_dosing", "critical",
        _rx(r"\bhow\s+(?:much|many|to)\b[^.\n]{0,30}\b(?:take|inject|dose|dosed|"
            r"use|reconstitute|administer|mix|run)\b"),
        "Answers 'how much / how to take' — direct usage instruction.",
    ),
    _Rule(
        "human_dosing", "critical",
        _rx(r"\bwhere\s+(?:to|should\s+(?:i|you|we))\b[^.\n]{0,20}\binject"),
        "Injection-site instruction.",
    ),
    # Injection *technique* directed at a person. Uses the verb forms only
    # (inject / injects / injected / injecting) plus a route, so the noun
    # "injectable" / "an injection" describing the drug's form is not a hit.
    _Rule(
        "human_dosing", "critical",
        _rx(r"\binject(?:s|ed|ing)?\b[^.\n]{0,30}\b(?:subcutaneous(?:ly)?|"
            r"intramuscular(?:ly)?|into\s+(?:your|the)|near\s+the\s+(?:injury|site))\b"),
        "Injection-technique instruction.",
    ),
    # A dosing *how-to artifact* (protocol / calculator / chart / guide) is
    # actionable and blocks. A bare "dosing schedule" / "regimen" is common in
    # educational trial descriptions, so it only warns (below).
    _Rule(
        "human_dosing", "critical",
        _rx(r"\b(?:dosing|dosage|titration|injection)\s+"
            r"(?:calculator|chart|guide)\b"),
        "Presents a dosing calculator / chart / guide (actionable how-to).",
    ),
    _Rule(
        "human_dosing", "warning",
        _rx(r"\b(?:dosing|dosage|titration|injection)\s+"
            r"(?:protocol|protocols|schedule|regimen)\b|"
            r"\btitrat(?:e|es|ed|ing|ion)\b|\bdose[\s-]escalation\b|"
            r"\bloading\s+(?:phase|dose)\b|\bmaintenance\s+dose\b"),
        "Dosing-regimen vocabulary (protocol / titration / schedule / "
        "escalation) — educational unless it becomes reader-directed; verify.",
    ),
    _Rule(
        "human_dosing", "critical",
        _rx(r"\b\d+(?:\.\d+)?\s?(?:mg|mcg)\s?/?\s?(?:per\s?)?"
            r"(?:kg|kilogram|lb|pound|body\s?weight)\b"),
        "Per-bodyweight dosing calculation.",
    ),
    # Reader-directed dose amount (second person or an imperative dosing verb
    # within reach of a milligram figure). This is the line between "the trial
    # used 12 mg" (descriptive, a warning below) and "take 12 mg" / "your 12 mg
    # dose" (an instruction to a person).
    _Rule(
        "human_dosing", "critical",
        _rx(r"\b(?:you|your)\b[^.\n]{0,40}\b" + _DOSE_AMOUNT + r"\b"),
        "Dose amount directed at the reader ('you/your').",
    ),
    _Rule(
        "human_dosing", "critical",
        _rx(r"\b" + _DOSE_AMOUNT + r"\b[^.\n]{0,25}\b(?:you|your)\b"),
        "Dose amount directed at the reader ('you/your').",
    ),
    # Note: bare "dose" is deliberately NOT an imperative verb here — it is far
    # more often the noun ("the weight-loss dose is 3 mg"), which is descriptive,
    # not an instruction. Reader-directed / range / how-to rules catch the real
    # instructions.
    _Rule(
        "human_dosing", "critical",
        _rx(r"\b(?:take|inject|administer|self-administer|start\s+(?:with|at)|"
            r"split|divide)\b[^.\n]{0,30}\b" + _DOSE_AMOUNT + r"\b"),
        "Imperative dosing instruction with an amount.",
    ),
    # A dose RANGE ("2 mg to 12 mg", "5–10 mg", "5-10 mg") is a titration/dosing
    # regimen, not a single descriptive figure — it tells a reader the amounts to
    # move between, so it blocks. Both forms: unit on each number, or a bare
    # number range with a single trailing unit ("5-10 mg").
    # `_NOT_CONC` rejects concentration/lab units (mg/dL blood glucose, ng/mL,
    # mmol/L) so a lab reference range like "100–125 mg/dL" is not read as a dose
    # range. Per-bodyweight (mg/kg) and per-time (mg/wk, mg/day) stay dose units.
    _Rule(
        "human_dosing", "critical",
        _rx(r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|µg|ug|iu)" + _NOT_CONC + r"\b\s*"
            r"(?:to|through|–|-)\s*"
            r"\d+(?:\.\d+)?\s?(?:mg|mcg|µg|ug|iu)" + _NOT_CONC + r"\b|"
            r"\b\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?\s?"
            r"(?:mg|mcg|µg|ug|iu)" + _NOT_CONC + r"\b"),
        "Dose range (titration regimen).",
    ),
    # Splitting/spreading a dose across injections or doses is administration
    # guidance ("5-10 mg per week, split across two to three injections").
    _Rule(
        "human_dosing", "critical",
        _rx(r"\b(?:split|divide|spread|space)\b[^.\n]{0,25}"
            r"\b(?:injections?|doses?|shots?)\b"),
        "Splitting a dose across injections — administration guidance.",
    ),
    # Imperative directed at the reader to follow a dosing regimen, even without
    # a number ("follow a loading phase", "start your cycle").
    _Rule(
        "human_dosing", "critical",
        _rx(r"\b(?:follow|start|begin|run|do|complete)\b[^.\n]{0,25}\b(?:loading\s+"
            r"(?:phase|dose)|maintenance\s+dose|titration|dosing\s+schedule|"
            r"cycle|protocol)\b"),
        "Tells the reader to follow a dosing regimen.",
    ),
    # Stacking. "stack" is inherently a multi-compound term, so a peptide near it
    # blocks. A combine/take/use verb only counts as stacking when TWO compounds
    # flank it — so "combining MOTS-c with regular exercise" (one compound + a
    # non-compound) is never a hit, while "combining MOTS-c with retatrutide" is.
    _Rule(
        "human_dosing", "critical",
        _rx(r"\bstack(?:ed|ing)?\b[^.\n]{0,40}\b(?:" + _PEPTIDES + r")\b|"
            r"\b(?:" + _PEPTIDES + r")\b[^.\n]{0,20}\bstack(?:ed|ing)?\b"),
        "Describes stacking compounds for use.",
    ),
    _Rule(
        "human_dosing", "critical",
        _rx(r"\b(?:combin(?:e|ed|ing)|tak(?:e|en|ing)|us(?:e|ed|ing)|"
            r"run(?:ning)?|pair(?:ed|ing)?)\b[^.\n]{0,15}\b(?:" + _PEPTIDES + r")\b"
            r"[^.\n]{0,25}\b(?:with|and|\+|plus|alongside)\b[^.\n]{0,25}"
            r"\b(?:" + _PEPTIDES + r")\b"),
        "Describes combining two compounds for use.",
    ),
    # Descriptive dose mentions (a bare amount near a compound, no reader
    # direction) — a warning, not a block. Educational, but worth a human eye.
    _Rule(
        "human_dosing", "warning",
        _rx(r"\b" + _DOSE_AMOUNT + r"\b[^.\n]{0,20}"
            r"(?:\bper\b[^.\n]{0,10}\b(?:day|week|dose|injection)\b|"
            r"\b(?:daily|weekly|once[\s-]weekly|twice[\s-]weekly|"
            r"every\s+\w+\s+(?:day|week)s?)\b)"),
        "Dose-per-frequency mention — descriptive; verify it isn't instructional.",
    ),
    _Rule(
        "human_dosing", "warning",
        _rx(r"\b(?:cycle|washout|wash[- ]out)\b[^.\n]{0,30}\b(?:" + _PEPTIDES + r")\b"
            r"|\b(?:" + _PEPTIDES + r")\b[^.\n]{0,30}\b(?:cycle|washout)\b"),
        "Cycling / washout language — verify it isn't a usage protocol.",
    ),

    # -- branded-drug equivalence ----------------------------------------
    # Promotional equivalence phrasings ("just as good as", "works like", "a
    # dupe for") are marketing voice, not the neutral register of an educational
    # drug-vs-drug comparison, so these block. A plain superiority comparison
    # ("X is more effective than Y") is common in educational content and only
    # warns — see the warning rule below.
    _Rule(
        "branded_equivalence", "critical",
        _rx(r"\b(?:just\s+as\s+(?:good|effective|potent|strong)\s+as|"
            r"as\s+(?:good|effective|strong|potent)\s+as|"
            r"works\s+(?:just\s+)?like|same\s+(?:results?|effects?)\s+as|"
            r"on\s+par\s+with)\b[^.\n]{0,30}\b(?:" + _BRAND_DRUGS + r")\b"),
        "Claims efficacy equivalence to a branded/approved medication.",
    ),
    # Product-positioning language ("a dupe for", "a replacement for", "cheaper /
    # budget / generic version of / alternative to <brand>") is marketing, not
    # an educational comparison, so it blocks. Note "cheaper alternative to X"
    # is caught here (price-qualified), while a bare "alternative to X" only
    # warns (below) — the latter is common in neutral drug-comparison content.
    _Rule(
        "branded_equivalence", "critical",
        _rx(r"\b(?:" + _BRAND_DRUGS + r")\b[^.\n]{0,20}\b(?:dupe|"
            r"generic\s+version|replacement)\b|"
            r"\b(?:dupe|replacement)\s+(?:for|to)\b"
            r"[^.\n]{0,20}\b(?:" + _BRAND_DRUGS + r")\b"),
        "Positions the product as a dupe/replacement for a branded medication.",
    ),
    _Rule(
        "branded_equivalence", "critical",
        _rx(r"\b(?:generic|cheaper|budget|affordable|low[\s-]cost)\s+"
            r"(?:version\s+of\s+|alternative\s+to\s+)?"
            r"(?:" + _BRAND_NAMES + r")\b"),
        "Positions the product as a cheap/generic version of a branded drug.",
    ),
    # Educational comparisons (bare "alternative to X", "equivalent to X",
    # superiority) — surfaced for review, not blocked: a drug-vs-drug comparison
    # is not a claim about the vendor's own product.
    _Rule(
        "branded_equivalence", "warning",
        _rx(r"\b(?:equivalent\s+to|alternative\s+to|better\s+than|"
            r"more\s+effective\s+than|stronger\s+than|outperforms?|"
            r"superior\s+to)\b[^.\n]{0,25}\b(?:" + _BRAND_DRUGS + r")\b|"
            r"\b(?:" + _BRAND_DRUGS + r")\b[^.\n]{0,15}\b(?:alternative|equivalent)\b"),
        "Comparison to a branded drug — verify it isn't a product claim.",
    ),

    # -- guaranteed results / efficacy claims ----------------------------
    # Positive promissory guarantee only. The negation guards keep a disclaimer
    # ("results aren't guaranteed", "no guarantee of results", "not guaranteed")
    # — which is the *opposite* claim, and exactly the honest hedging educational
    # content should use — from tripping the rule.
    _Rule(
        "guaranteed_results", "critical",
        _rx(r"(?<!not )(?<!n't )(?<!no )\bguarantee(?:d|s)?\b[^.\n]{0,30}"
            r"\b(?:results?|weight\s*loss|success|outcomes?)\b|"
            r"\b(?:results?|weight\s*loss)\b[^.\n]{0,15}"
            r"(?<!not )(?<!n't )(?<!no )\bguaranteed\b"),
        "Guarantees results / outcomes.",
    ),
    _Rule(
        "guaranteed_results", "critical",
        _rx(r"\byou(?:'ll|\s+will)\b[^.\n]{0,25}\b(?:lose|drop|shed|burn)\b"
            r"[^.\n]{0,20}\b\d+\s?(?:lbs?|pounds?|kg|kilograms?|%|percent)\b"),
        "Promises a specific amount of weight loss.",
    ),
    _Rule(
        "guaranteed_results", "critical",
        _rx(r"\b(?:will|guaranteed\s+to)\b[^.\n]{0,20}\b(?:cure|reverse|eliminate|"
            r"melt|burn\s+away|get\s+rid\s+of)\b"),
        "Promises a cure / definitive outcome.",
    ),
    _Rule(
        "guaranteed_results", "critical",
        _rx(r"\bclinically\s+proven\s+to\b|\bproven\s+to\s+"
            r"(?:work|deliver|cause|produce|melt|burn|cure|treat)\b"),
        "Claims proven efficacy / outcome.",
    ),
    # Qualified so an honest hedge ("no medicine is risk-free", "not without
    # side effects") does not read as an absolute-safety claim.
    _Rule(
        "guaranteed_results", "critical",
        _rx(r"\bno\s+(?:known\s+)?side\s+effects\b|"
            r"\b(?:completely|totally|100%|entirely|absolutely)\s+"
            r"risk[\s-]?free\b|\b100%\s?(?:safe|effective|guaranteed)\b"),
        "Absolute safety / efficacy claim.",
    ),
    _Rule(
        "guaranteed_results", "warning",
        _rx(r"\bmiracle\b"),
        "'Miracle' framing — promotional; verify context.",
    ),

    # -- advocacy / product promotion ------------------------------------
    # "consider" / "get" deliberately excluded: "you should consider talking to
    # a doctor" is safe advice, not product advocacy.
    _Rule(
        "advocacy", "critical",
        _rx(r"\byou\s+should\s+(?:try|take|use|buy|start|order|purchase)\b"),
        "Advocacy — tells the reader they should use/buy the product.",
    ),
    _Rule(
        "advocacy", "critical",
        _rx(r"\bwe\s+recommend\s+(?:you\s+)?(?:try|take|use|start|buy|order)\b"),
        "Advocacy — recommends the reader use/buy the product.",
    ),
    _Rule(
        "advocacy", "critical",
        _rx(r"\b(?:buy|order|shop)\b[^.\n]{0,10}\b(?:now|today|yours|here)\b|"
            r"\bget\s+yours\b|\badd\s+to\s+cart\b|\bshop\s+now\b|"
            r"\btry\s+(?:it|this)?\s*(?:today|now|risk[\s-]?free)\b"),
        "Purchase call-to-action ('buy now', 'get yours', 'try it today').",
    ),
    _Rule(
        "advocacy", "critical",
        _rx(r"\bstart\s+your\b[^.\n]{0,20}\b(?:journey|transformation|"
            r"weight[\s-]?loss)\b"),
        "Promotional 'start your journey' framing.",
    ),
)


@dataclass
class Finding:
    category: str
    severity: str
    message: str
    evidence: str

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass
class ComplianceResult:
    mode: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def passed(self) -> bool:
        """No critical finding — safe to publish."""
        return self.critical_count == 0

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "passed": self.passed,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "findings": [f.as_dict() for f in self.findings],
        }


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def _normalize(text: str) -> str:
    """Flatten HTML/markdown to readable text so patterns match regardless of
    the source format. Blog bodies arrive as markdown, nlp pages as HTML; a
    ``**5 mg**`` or ``<strong>inject</strong>`` must still be seen. Newlines are
    preserved (the ``[^.\\n]`` windows in the rules use them as clause bounds).
    """
    if not text:
        return ""
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    # Drop markdown emphasis/heading punctuation that can wedge between words.
    text = text.replace("*", "").replace("`", "").replace("#", "")
    text = _WS_RE.sub(" ", text)
    return text


def _snippet(match: re.Match, source: str, width: int = 90) -> str:
    """A short, single-line context window around a match, for the team to see
    exactly what tripped the rule."""
    start = max(0, match.start() - 12)
    end = min(len(source), match.end() + 12)
    frag = source[start:end].strip()
    frag = _WS_RE.sub(" ", frag.replace("\n", " "))
    if len(frag) > width:
        frag = frag[: width - 1].rstrip() + "…"
    return frag


def scan_text(text: str, mode: str = "peptide") -> ComplianceResult:
    """Scan finished content for forbidden regulated-marketing patterns.

    Pure: no I/O, no framework. `mode` selects the ruleset; today every active
    mode runs the full ruleset, but the parameter is threaded so a lighter mode
    can subset the rules later without touching callers. An inactive/unknown
    mode returns an empty (passing) result.

    Findings are de-duplicated by (category, evidence) so the same phrase caught
    by two overlapping rules is reported once, and returned critical-first.
    """
    result = ComplianceResult(mode=mode)
    if mode not in _ACTIVE_MODES:
        return result

    source = _normalize(text)
    if not source.strip():
        return result

    # De-duplicate by (category, evidence): the same phrase caught by two
    # overlapping rules is reported once. On collision the CRITICAL wins — a
    # warning rule whose snippet happens to coincide with a critical one (e.g.
    # "loading phase" vs "Follow a loading phase") must never suppress the block.
    by_key: dict[tuple[str, str], Finding] = {}
    for rule in _RULES:
        for match in rule.pattern.finditer(source):
            evidence = _snippet(match, source)
            key = (rule.category, evidence.lower())
            existing = by_key.get(key)
            if existing is not None and not (
                rule.severity == "critical" and existing.severity == "warning"
            ):
                continue
            by_key[key] = Finding(
                category=rule.category,
                severity=rule.severity,
                message=rule.message,
                evidence=evidence,
            )

    result.findings = sorted(
        by_key.values(), key=lambda f: (f.severity != "critical", f.category)
    )
    return result


def scan_content(title: str, body: str, mode: str = "peptide") -> ComplianceResult:
    """Scan a title + body together (the two are joined so a dosing headline is
    caught even when the body is clean)."""
    joined = "\n".join(p for p in (title or "", body or "") if p)
    return scan_text(joined, mode=mode)


def resolve_mode(client: Optional[dict]) -> str:
    """The client's compliance mode, defaulting to 'off'. A None/blank/unknown
    value reads as 'off' so only an explicitly regulated client is ever gated."""
    if not isinstance(client, dict):
        return "off"
    mode = (client.get("content_compliance_mode") or "off")
    mode = str(mode).strip().lower()
    return mode if mode in _ACTIVE_MODES else "off"


def is_enabled(client: Optional[dict]) -> bool:
    return resolve_mode(client) != "off"


def _critical_evidence(result: ComplianceResult) -> list[str]:
    """Compact, de-duplicated labels for the critical findings, for the 409
    detail string — same shape trick as `voice_card_service._critical_terms`."""
    seen: list[str] = []
    for f in result.findings:
        if f.severity != "critical":
            continue
        label = f"{f.category}: {f.evidence}"
        if label.lower() not in {s.lower() for s in seen}:
            seen.append(label)
    return seen


def assert_publishable(result: ComplianceResult, force: bool = False) -> None:
    """Refuse to publish content with a critical compliance finding.

    Raises 409 ``content_compliance_violation`` (pipe-delimited critical
    evidence in the detail, mirroring `assert_voice_publishable` so the same
    ErrorDetails accordion renders it). Only a critical blocks; warnings are
    advisory. `force` is the deliberate override for a rare false positive —
    the regex is provable, so an override is a considered second action, never
    a routine bypass.
    """
    if force or result.passed:
        return
    labels = _critical_evidence(result)
    detail = (
        "content_compliance_violation: " + " | ".join(labels)
        if labels else "content_compliance_violation"
    )
    raise HTTPException(status_code=409, detail=detail)


def assert_content_publishable(
    client: Optional[dict],
    title: str,
    body: str,
    force: bool = False,
) -> ComplianceResult:
    """Convenience gate for a publish choke point: resolve the client's mode,
    scan the title+body, and block on a critical finding.

    Returns the `ComplianceResult` (so a caller can log/attach it) and raises
    409 on a critical finding for a regulated client. A client in 'off' mode is
    a no-op that returns a passing result.
    """
    mode = resolve_mode(client)
    result = scan_content(title, body, mode=mode)
    assert_publishable(result, force=force)
    return result
