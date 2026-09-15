"""Deterministic per-client term substitution for FINAL generated content.

Some clients must never publish certain words but still want content researched
and planned around them — e.g. Nova Life Peptides researches "retatrutide" demand
(keywords, briefs, SERP analysis all keep the real name), but every *published*
page must read "glp3-rt" instead, a regulated-compound compliance rule.

A brand-voice never-use *ban* only tells the writer to avoid the word; it does
not guarantee a specific coded replacement, and on some paths (the Fanout blog
writer) it is not even auto-corrected — so a ban alone cannot make the swap
mandatory. This module is the guarantee: a pure, word-boundary, case-preserving
find/replace applied to the final rendered content at each generator's write
seam, AFTER generation and BEFORE the voice check + persist. Because the raw
term is gone before the deterministic voice check runs, the never-use finding
resolves on its own too.

Driven by a per-client map ``clients.term_substitutions`` ({from: to}); a client
with an empty map is a no-op, so this is inert for every client but the few that
opt in. It is applied ONLY to written output — never to keywords, briefs,
clusters, or SERP reads, which deliberately see the real term.

Pure + unit-tested; the two public entry points are:
  * ``substitute_text``  — plain text (title, meta, FAQ, CTA, markdown, slug)
  * ``substitute_html``  — visible text nodes only, leaving tags/attributes/URLs
    (``href``/``src``) untouched so internal links are not rewritten.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Word characters we treat as part of a term for boundary purposes. The compound
# names are plain ASCII letters, so the default \b works; the optional trailing
# (s?) catches a rare plural without swallowing the next word.


def parse_substitutions(raw: Any) -> dict[str, str]:
    """Normalize a stored ``term_substitutions`` value into a clean {from: to} map.

    Tolerates ``None`` / non-dict / blank entries (returns ``{}`` or drops them),
    trims whitespace, and drops any pair where ``from`` == ``to`` (a no-op that
    would only cost a regex pass). Keys are kept in their original casing; the
    match itself is case-insensitive.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        term = k.strip()
        repl = v.strip()
        if term and repl and term.lower() != repl.lower():
            out[term] = repl
    return out


def _match_case(sample: str, replacement: str) -> str:
    """Carry the matched term's casing style onto the replacement.

    ``RETATRUTIDE`` -> ``GLP3-RT`` (all caps), ``Retatrutide`` -> ``Glp3-rt``
    (leading cap), ``retatrutide`` -> ``glp3-rt`` (as given). A single-letter
    all-caps match is treated as leading-cap, not shout-case.
    """
    if len(sample) > 1 and sample.isupper():
        return replacement.upper()
    if sample[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _compiled(subs: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    """Compile (pattern, replacement) pairs, longest term first so a term that is
    a prefix of another is not pre-empted. Matches an optional trailing plural
    ``s`` so ``retatrutides`` is caught too."""
    pairs = sorted(subs.items(), key=lambda kv: len(kv[0]), reverse=True)
    compiled: list[tuple[re.Pattern[str], str]] = []
    for term, repl in pairs:
        pattern = re.compile(r"\b" + re.escape(term) + r"(s?)\b", re.IGNORECASE)
        compiled.append((pattern, repl))
    return compiled


def _apply(text: str, compiled: list[tuple[re.Pattern[str], str]]) -> str:
    for pattern, repl in compiled:
        def _sub(m: re.Match[str], _repl: str = repl) -> str:
            whole = m.group(0)
            plural = m.group(1)
            core = whole[: len(whole) - len(plural)]
            return _match_case(core, _repl) + plural
        text = pattern.sub(_sub, text)
    return text


def substitute_text(text: Optional[str], subs: dict[str, str]) -> Optional[str]:
    """Apply the substitution map to a plain-text string (title, meta, FAQ, CTA,
    markdown body, URL slug). ``None``/empty text or an empty map is a no-op.

    Idempotent: the coded replacement never matches any source term, so applying
    twice is safe (a requeue/retry can re-run it without harm).
    """
    if not text or not subs:
        return text
    return _apply(text, _compiled(subs))


def substitute_html(html: Optional[str], subs: dict[str, str]) -> Optional[str]:
    """Apply the substitution map to the VISIBLE TEXT of an HTML fragment only.

    Tags, attributes (including ``href``/``src`` URLs), ``<script>`` and
    ``<style>`` contents are left untouched, so internal links are not rewritten
    (a page that links to ``/retatrutide-kit`` keeps that href even though its
    visible copy is switched — renaming the linked page is a separate step). Falls
    back to a plain-text pass if BeautifulSoup is unavailable, which is safe for
    the fragments the generators emit (no term appears inside a URL there in
    practice) but noted so the caller can prefer ``substitute_text`` on raw URLs.
    """
    if not html or not subs:
        return html
    try:
        from bs4 import BeautifulSoup, NavigableString  # lazy — heavy import
    except Exception:  # pragma: no cover - bs4 always present in platform-api
        return substitute_text(html, subs)

    compiled = _compiled(subs)
    soup = BeautifulSoup(html, "html.parser")
    skip = {"script", "style"}
    for node in list(soup.find_all(string=True)):
        if node.parent is not None and node.parent.name in skip:
            continue
        original = str(node)
        replaced = _apply(original, compiled)
        if replaced != original:
            node.replace_with(NavigableString(replaced))
    return str(soup)


# ── Voice-verdict reconciliation ───────────────────────────────────────────
# On the Local SEO / Ecommerce paths the page is scored for brand voice inside
# nlp-api on the RAW generated content, then the platform substitutes the coded
# term into the content before persisting. That leaves a stored voice verdict
# reporting a never-use term ("retatrutide") the shipped page no longer
# contains — a false critical that also mis-fires the Director's
# "content_shipped_degraded" seam. This reconciles the verdict to the page that
# actually shipped: it drops ONLY the never-use findings for terms the
# substitution provably removed, then recomputes the critical count and the
# pass state. Every other dimension (tone, audience fit, the numeric score) is
# left untouched — the substitution changes the words, not the writing quality —
# so a page that is genuinely off-voice for other reasons still reads as such.

_VOICE_PASS_THRESHOLD = 80.0  # mirrors nlp-api voice_card VOICE_PASS_THRESHOLD


def reconcile_voice_verdict(verdict: Any, subs: dict[str, str]) -> Any:
    """Remove never-use criticals for substituted terms from a stored voice
    verdict and recompute ``critical_count`` / ``needs_rewrite`` / ``passed``.

    A no-op when there is no verdict, no substitution map, or the verdict is not
    the expected dict shape. Returns a shallow-copied, corrected verdict.
    """
    if not subs or not isinstance(verdict, dict):
        return verdict
    sub_keys = {k.lower() for k in subs}

    violations = verdict.get("violations")
    if not isinstance(violations, list):
        return verdict

    kept: list[Any] = []
    changed = False
    for v in violations:
        if isinstance(v, dict) and v.get("check") in ("never_use_terms", "never_use"):
            terms = v.get("terms")
            if isinstance(terms, list) and terms:
                remaining = [t for t in terms if not (isinstance(t, str) and t.lower() in sub_keys)]
                if not remaining:
                    changed = True
                    continue  # every banned term here was substituted → drop it
                if len(remaining) != len(terms):
                    changed = True
                    v = {**v, "terms": remaining}
        kept.append(v)

    if not changed:
        return verdict

    out = dict(verdict)
    out["violations"] = kept
    critical_count = sum(
        1 for v in kept if isinstance(v, dict) and v.get("severity") == "critical"
    )
    out["critical_count"] = critical_count
    score = out.get("score")
    score_ok = not isinstance(score, (int, float)) or score >= _VOICE_PASS_THRESHOLD
    passed = critical_count == 0 and score_ok
    out["passed"] = passed
    out["needs_rewrite"] = not passed
    return out


def substitute_page_result(result: Any, subs: dict[str, str]) -> Any:
    """Code an nlp page-generation result dict IN PLACE (Local SEO / Ecommerce
    share the same shape): ``content_html`` (visible text only — hrefs to the
    client's real, already-compliant page slugs are preserved), ``page_title``,
    ``schema_json`` (a JSON string or an object), then reconcile the stored voice
    verdict (nlp scored the raw term). No-op for an empty map or a non-dict.
    Idempotent — safe to re-run on a retry."""
    if not subs or not isinstance(result, dict):
        return result
    if result.get("content_html"):
        result["content_html"] = substitute_html(result["content_html"], subs)
    if result.get("page_title"):
        result["page_title"] = substitute_text(result["page_title"], subs)
    sj = result.get("schema_json")
    if isinstance(sj, str) and sj:
        result["schema_json"] = substitute_text(sj, subs)
    elif isinstance(sj, (dict, list)):
        import json

        try:
            result["schema_json"] = json.loads(substitute_text(json.dumps(sj), subs))
        except Exception:  # noqa: BLE001 — leave schema untouched on any parse issue
            pass
    if result.get("voice_compliance"):
        result["voice_compliance"] = reconcile_voice_verdict(result["voice_compliance"], subs)
    return result
