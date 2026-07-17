"""Compound / public-spec auto-research for the ecommerce writer.

The ecommerce writer never invents facts — a missing spec goes to
CONTENT_GAPS_REPORT for a human to supply. That is exactly right for
*vendor* facts (this store's price, review count, testing lab, shipping and
returns terms). But it over-gates the *invariant, publicly-documented*
properties of the product/compound itself — a peptide's CAS number, molecular
weight, formula, amino-acid sequence, solubility, standard reconstitution and
post-reconstitution stability are the SAME whoever sells it, are documented in
public databases (PubChem/ChemSpider/DrugBank/NCBI), and are precisely the
"verifiable number-entity" facts the MCS/AEO methodology rewards.

This module carries the pure pieces of a bounded web-search research pass that
fills those invariant specs *with a citation*, so they land in the spec table
instead of the gap list — while vendor facts stay gated to the user. The impure
Anthropic call lives in `main.py::_research_public_facts`; everything here is
pure and unit-tested.

Safety line (encoded in `classify_gap` + the research prompt):
  - PUBLIC  → invariant molecular/product properties, researchable + citable.
  - STORE   → vendor-specific claims; NEVER researched, always a user gap.
Ambiguous defaults to STORE (never research something we're unsure about).
"""

from __future__ import annotations

import re
from typing import Optional

# ── The public/vendor safety line ──────────────────────────────────────────
# A gap is only auto-researched when it is clearly a PUBLIC, invariant spec.
# Vendor hints win ties: it is always safe to leave a fact for the user, and
# never safe to auto-fill a price/review/lab claim.

_STORE_HINTS = (
    "price", "pricing", "cost", "$", "msrp", "discount", "coupon", "sale",
    "shipping", "deliver", "transit", "fulfil", "dispatch", "sla",
    "return", "refund", "guarantee", "warranty", "exchange",
    "review", "rating", "testimonial", "star",
    "stock", "in stock", "availability", "inventory", "sku", "gtin", "upc",
    "third-party lab", "third party lab", "testing lab", "laboratory name",
    "accredit", "iso 17025", "certificate of analysis", "coa",
    "phone", "address", "hours", "contact", "vendor", "seller", "brand name",
)

_PUBLIC_HINTS = (
    "cas number", "cas no", "cas registry", "cas ",
    "molecular weight", "molecular formula", "molar mass", "mol. wt",
    "empirical formula", "chemical formula", "molecular mass",
    "amino acid", "sequence", "peptide sequence", "residues", "sequence length",
    "solubility", "soluble", "reconstitution", "reconstitute", "diluent",
    "stability", "shelf life", "half-life", "half life",
    "storage temp", "storage temperature", "store at", "melting point",
    "boiling point", "density", "purity", "hplc", "mass spec", "mass-spec",
    "inchi", "smiles", "iupac", "pubchem", "chemspider", "drugbank",
    "pka", "isoelectric", "receptor target", "molecular", "compound identity",
)


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def classify_gap(gap: dict) -> str:
    """Classify a CONTENT_GAPS_REPORT item as 'public' or 'store'.

    'public'  → an invariant, publicly-documented property of the product/
                compound (safe to research + cite).
    'store'   → a vendor-specific fact (never researched — stays a user gap).

    Vendor hints win over public hints (safer to gate), and anything without a
    clear public signal defaults to 'store'.
    """
    blob = _norm(f"{gap.get('category','')} {gap.get('missing','')} {gap.get('how_to_add','')}") if isinstance(gap, dict) else _norm(gap)
    if not blob:
        return "store"
    if any(h in blob for h in _STORE_HINTS):
        return "store"
    if any(h in blob for h in _PUBLIC_HINTS):
        return "public"
    return "store"


def public_gap_labels(content_gaps: list) -> list[str]:
    """The 'missing' labels of the gaps that are public specs — a focus list the
    research pass can prioritise. De-duplicated, order-preserving."""
    out: list[str] = []
    seen: set[str] = set()
    for g in content_gaps or []:
        if not isinstance(g, dict):
            continue
        if classify_gap(g) != "public":
            continue
        label = str(g.get("missing") or g.get("category") or "").strip()
        key = _norm(label)
        if label and key not in seen:
            seen.add(key)
            out.append(label)
    return out


# ── The research tool (Anthropic client tool) ──────────────────────────────
# The model searches the web (server-side web_search tool) and then calls this
# to emit the structured, cited result. Only high/medium-confidence facts WITH
# a source survive `parse_researched_facts`.

RESEARCH_TOOL = {
    "name": "emit_researched_facts",
    "description": (
        "Emit the invariant, publicly-documented product/compound specifications "
        "you verified against public sources. Only include a spec you could source "
        "to an authoritative public page and provide its URL. Do NOT include any "
        "vendor-specific fact (price, review count, this store's testing lab, "
        "shipping or returns terms)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "spec name, e.g. 'CAS number', 'Molecular weight'"},
                        "value": {"type": "string", "description": "the verified value, e.g. '2381089-83-2', '4731.32 Da'"},
                        "unit": {"type": "string", "description": "unit if separable, else empty"},
                        "source_name": {"type": "string", "description": "e.g. 'PubChem', 'DrugBank'"},
                        "source_url": {"type": "string", "description": "the exact public page the value came from"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["field", "value", "source_url", "confidence"],
                },
            }
        },
        "required": ["facts"],
    },
}

RESEARCH_SYSTEM_PROMPT = (
    "You are a product-data researcher for an ecommerce page. Your ONE job is to "
    "find the INVARIANT, publicly-documented specifications of a named product or "
    "compound — the properties that are TRUE of the item itself no matter which "
    "store sells it — and report each with an authoritative public citation.\n\n"
    "RESEARCH (use web_search) and report ONLY facts like:\n"
    "  • Chemical identity: CAS number, molecular weight, molecular formula, "
    "InChI/SMILES, IUPAC name\n"
    "  • Peptide/biologic: amino-acid sequence, sequence length/residue count, "
    "receptor targets\n"
    "  • Physical/handling: solubility (water/DMSO), standard reconstitution "
    "practice, post-reconstitution stability, storage temperature, purity assay "
    "norms (HPLC/MS)\n"
    "  • For non-chemical products: only manufacturer specs that are invariant "
    "across sellers (documented dimensions, materials, standardised ratings).\n\n"
    "NEVER report vendor-specific facts — price, discounts, review counts or "
    "ratings, THIS store's testing lab identity/accreditation, shipping or "
    "returns terms, stock. Those belong to the store, not the product.\n\n"
    "RULES:\n"
    "  1. Only report a value you can source to an authoritative public page "
    "(PubChem, ChemSpider, DrugBank, NIH/NCBI, peer-reviewed literature, an "
    "official manufacturer datasheet). Always include the source_url.\n"
    "  2. If you cannot find a reliable source for a spec, DO NOT report it. "
    "A missing fact is fine; a wrong fact is not.\n"
    "  3. Prefer exact number-entity values with units.\n"
    "  4. confidence: 'high' only when an authoritative database or multiple "
    "sources agree; 'medium' for a single decent source; 'low' if unsure "
    "(low-confidence facts are discarded).\n"
    "  5. When done, call emit_researched_facts exactly once with your results "
    "(an empty array if you found nothing citable)."
)


def build_research_user_prompt(entity: str, page_type: str, focus: Optional[list[str]] = None) -> str:
    """The user turn for the research pass. `focus` (optional) lists specific
    specs already known to be missing so the search prioritises them."""
    lines = [
        f"Product / compound to research: {entity}",
        f"Page type: {page_type}",
        "",
        "Find the invariant, publicly-documented specifications for this item and "
        "report them with citations via emit_researched_facts. Remember: product "
        "properties only — no vendor price/review/lab/shipping facts.",
    ]
    focus = [f for f in (focus or []) if str(f).strip()]
    if focus:
        lines += ["", "Prioritise finding these specifically:"]
        lines += [f"  - {f}" for f in focus[:12]]
    return "\n".join(lines)


# ── Parsing + rendering ────────────────────────────────────────────────────

_MAX_FACTS = 14


def parse_researched_facts(raw_facts: list) -> list[dict]:
    """Validate + clean the tool's `facts` array.

    Keeps only items with a field, a value, a source_url, and confidence in
    {high, medium}. De-dupes by normalised field (first wins). Caps the count.
    Returns clean dicts: {field, value, unit, source_name, source_url, confidence}.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_facts or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        value = str(item.get("value") or "").strip()
        source_url = str(item.get("source_url") or "").strip()
        confidence = _norm(item.get("confidence"))
        if not (field and value and source_url):
            continue
        if confidence not in ("high", "medium"):
            continue
        if not source_url.lower().startswith(("http://", "https://")):
            continue
        key = _norm(field)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "field": field,
            "value": value,
            "unit": str(item.get("unit") or "").strip(),
            "source_name": str(item.get("source_name") or "").strip(),
            "source_url": source_url,
            "confidence": confidence,
        })
        if len(out) >= _MAX_FACTS:
            break
    return out


def _fact_line(fact: dict) -> str:
    value = fact["value"]
    unit = fact.get("unit") or ""
    if unit and unit.lower() not in value.lower():
        value = f"{value} {unit}".strip()
    src = fact.get("source_name") or "public source"
    return f"  - {fact['field']}: {value}  [source: {src} — {fact['source_url']}]"


def render_researched_facts_block(facts: list[dict]) -> str:
    """The authoritative prompt block injected into the writer's user message.
    Empty string when there are no researched facts (so the prompt is unchanged
    and behaviour degrades to the old gate)."""
    if not facts:
        return ""
    lines = [
        "VERIFIED PUBLIC SPECIFICATIONS (researched from public sources — AUTHORITATIVE):",
        "These are invariant, publicly-documented properties of this product/compound, "
        "each confirmed against the cited public source below. USE THESE EXACT VALUES "
        "where relevant (e.g. in the specifications table, as verifiable number-entity "
        "facts). Do NOT list any of these in CONTENT_GAPS_REPORT — they are already "
        "sourced. Store/vendor facts (price, your reviews, your testing lab, shipping, "
        "returns) are NOT researched here — still record those as gaps when missing.",
    ]
    lines += [_fact_line(f) for f in facts]
    return "\n".join(lines)


def filter_researched_gaps(content_gaps: list, facts: list[dict]) -> list:
    """Safety net: drop any content-gap the research already covered, so a
    researched spec never resurfaces as a 'missing' item even if the writer
    re-listed it. Only public gaps are eligible for removal; store gaps always
    stay. Matches a gap to a fact when the fact's field tokens appear in the
    gap text (or vice-versa)."""
    if not content_gaps or not facts:
        return content_gaps or []
    fact_keys = [_norm(f["field"]) for f in facts]
    kept: list = []
    for g in content_gaps:
        if isinstance(g, dict) and classify_gap(g) == "public":
            blob = _norm(f"{g.get('category','')} {g.get('missing','')}")
            if any(fk and (fk in blob or blob in fk) for fk in fact_keys):
                continue  # covered by a researched fact — drop it
        kept.append(g)
    return kept
