"""QA Agent — the deterministic signal layer (qa-agent-plan §3, Phase 1).

Pure checks over supplied text/HTML — no DB, no network, no LLM — so every
rule from ``docs/sops/QA_Checklists.md`` is unit-testable in isolation. The
impure orchestration (fetching pages, reading sheets, storage, the one
map-embed LLM judgement, persisting verdicts) lives in ``qa_service``.

Layer contract (mirrors the suite's "the LLM never counts" discipline): the
verdict is decided HERE, deterministically, from the blocking-check results.
``qa_service``'s LLM synthesis (later phase) may phrase findings; it never
sets scores or verdicts.

Each rubric check returns the standard shape:

    {"key": str, "label": str, "ok": bool | None, "blocking": bool, "note": str}

``ok=None`` means "could not verify" (page blocked, keyword unknown) — per the
SOP's fail-open policy an unverifiable BLOCKING check makes the whole review
``needs_human``, never an auto-fail.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Verdicts + rubric routing
# ---------------------------------------------------------------------------
PASS = "pass"
FAIL = "fail"
NEEDS_HUMAN = "needs_human"
SKIPPED = "skipped"

# Rubric keys. 'skip' = owner ruled QA must not check; 'handoff_sermastr' =
# out of QA's scope, points at the strategist; 'generic' = no checklist —
# routed needs_human (never auto-passed or auto-bounced).
RUBRIC_BLOG = "blog_article"
RUBRIC_PAGE = "website_page"
RUBRIC_GBP_POSTS = "gbp_posts"
RUBRIC_CITATIONS = "citations"
RUBRIC_GUEST_POST = "guest_posts"
RUBRIC_NICHE_EDIT = "niche_edits"
RUBRIC_PRESS_RELEASE = "press_release"
RUBRIC_MAP_EMBEDS = "map_embeds"
RUBRIC_SKIP = "skip"
RUBRIC_HANDOFF = "handoff_sermastr"
RUBRIC_GENERIC = "generic"

# Owner rulings from QA_Checklists.md — matched against the task/library name
# (casefold substring, first match wins; order matters: "hyperlocal gbp blast"
# must hit before "gbp blast" would, so both live in the skip set anyway).
_NAME_RULES: list[tuple[str, str]] = [
    ("hyperlocal gbp blast", RUBRIC_SKIP),
    ("gbp blast", RUBRIC_SKIP),
    ("blog post scheduling", RUBRIC_SKIP),
    ("service silo", RUBRIC_HANDOFF),
    ("seo neo", RUBRIC_GENERIC),           # owner: flag for human review
    ("gbp post", RUBRIC_GBP_POSTS),
    ("citation", RUBRIC_CITATIONS),
    ("guest post", RUBRIC_GUEST_POST),
    ("niche edit", RUBRIC_NICHE_EDIT),
    ("press release", RUBRIC_PRESS_RELEASE),
    ("map embed", RUBRIC_MAP_EMBEDS),
    ("website pages posted", RUBRIC_PAGE),
    ("blog post", RUBRIC_BLOG),
]


def rubric_for(task: dict[str, Any]) -> str:
    """Route a task to its QA rubric. Producer source wins (a content_run task
    is a blog article regardless of its name); then the library/task name;
    unknown → generic (needs_human — QA never guesses a standard). Pure."""
    if (task.get("source") or "") == "content_run":
        return RUBRIC_BLOG
    name = " ".join(
        ((task.get("library_task_name") or task.get("name") or "").casefold()).split()
    )
    for needle, rubric in _NAME_RULES:
        if needle in name:
            return rubric
    return RUBRIC_GENERIC


# ---------------------------------------------------------------------------
# Small text primitives
# ---------------------------------------------------------------------------
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

# Astral-plane emoji + the common BMP pictographs (☎ ✅ ⭐ …). Deliberately
# generous — the GBP check only needs "at least one".
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF⬀-⯿←-⇿✀-➿]"
)

# CTA heuristic: an imperative contact/action phrase or a tel: link. Generous
# by design — QA is a first-pass filter, not a copywriting judge.
_CTA_PATTERNS = re.compile(
    r"\b(call|contact|book|schedule|get a (free )?(quote|estimate)|request a quote|"
    r"learn more|visit (us|our)|reach out|enquire|inquire|get in touch|claim your|"
    r"order now|shop now|sign up|get started|free consultation)\b",
    re.IGNORECASE,
)


def extract_urls(text: Optional[str]) -> list[str]:
    """Every http(s) URL in a blob of text, deduped, order-preserved. Pure."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;:!?")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def normalize_ws(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def keyword_present(text: Optional[str], keyword: Optional[str]) -> Optional[bool]:
    """Case/whitespace-insensitive keyword containment; None when the keyword
    is unknown (→ the check reads 'could not verify')."""
    kw = normalize_ws(keyword).casefold()
    if not kw:
        return None
    return kw in normalize_ws(text).casefold()


def has_emoji(text: Optional[str]) -> bool:
    return bool(_EMOJI_RE.search(text or ""))


def has_cta(text: Optional[str]) -> bool:
    body = text or ""
    return bool(_CTA_PATTERNS.search(body)) or "tel:" in body.casefold()


def sample_spread(items: list, k: int) -> list:
    """Deterministic spread sample: first / evenly-spaced middles / last.
    Deterministic (not random) so a re-run of the same review checks the same
    rows — idempotent verdicts. Pure."""
    if k <= 0 or not items:
        return []
    if len(items) <= k:
        return list(items)
    if k == 1:
        return [items[0]]
    step = (len(items) - 1) / (k - 1)
    idx = sorted({round(i * step) for i in range(k)})
    return [items[i] for i in idx]


# ---------------------------------------------------------------------------
# NAP normalization + matching (QA_Checklists cross-cutting #4)
# ---------------------------------------------------------------------------
_PHONE_DIGITS = re.compile(r"\d")

# Common US/AU street + directional abbreviations, both directions.
_ADDR_ABBREV = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "drive": "dr",
    "road": "rd", "lane": "ln", "court": "ct", "place": "pl", "suite": "ste",
    "highway": "hwy", "parkway": "pkwy", "north": "n", "south": "s",
    "east": "e", "west": "w", "circle": "cir", "terrace": "ter",
}
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_phone(phone: Optional[str]) -> str:
    """Digits only, minus a leading country code — so '+1 (555) 010-2000',
    '555.010.2000' and '15550102000' all normalize to '5550102000'. Pure."""
    digits = "".join(_PHONE_DIGITS.findall(phone or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) > 10 and digits.startswith("61"):  # AU country code
        digits = digits[2:].lstrip("0") or digits[2:]
    return digits


def _norm_addr_tokens(text: Optional[str]) -> list[str]:
    toks = _PUNCT_RE.sub(" ", (text or "").casefold()).split()
    return [_ADDR_ABBREV.get(t, t) for t in toks]


def nap_match(
    page_text: str,
    business_name: Optional[str],
    address: Optional[str],
    phone: Optional[str],
) -> dict[str, Any]:
    """Fuzzy-but-deterministic NAP presence on a page vs the client card.

    Match rule (per the SOP: normalized, never exact-string): the business
    NAME must appear, plus at least one of PHONE (digit-normalized substring)
    or ADDRESS (≥60% of normalized address tokens present — survives 'St' vs
    'Street' and dropped suite numbers). Fields missing on the client card
    are skipped, not failed. Pure."""
    norm_page = normalize_ws(page_text).casefold()
    page_addr_tokens = set(_norm_addr_tokens(page_text))
    page_phone = "".join(_PHONE_DIGITS.findall(page_text))

    name_ok: Optional[bool] = None
    if normalize_ws(business_name):
        name_ok = normalize_ws(business_name).casefold() in norm_page

    phone_ok: Optional[bool] = None
    p = normalize_phone(phone)
    if p:
        phone_ok = p in page_phone

    addr_ok: Optional[bool] = None
    ref_tokens = [t for t in _norm_addr_tokens(address) if len(t) > 1 or t.isdigit()]
    if ref_tokens:
        hit = sum(1 for t in ref_tokens if t in page_addr_tokens)
        addr_ok = hit / len(ref_tokens) >= 0.6

    checked = [v for v in (name_ok, phone_ok, addr_ok) if v is not None]
    if not checked:
        matched: Optional[bool] = None  # nothing on the client card to compare
    elif name_ok is None:
        matched = any(checked)  # no name on file — any located field counts
    else:
        matched = bool(name_ok and (phone_ok or addr_ok or (phone_ok is None and addr_ok is None)))
    return {"matched": matched, "name": name_ok, "phone": phone_ok, "address": addr_ok}


# ---------------------------------------------------------------------------
# HTML primitives (bs4 parse only — no fetching here)
# ---------------------------------------------------------------------------
def visible_text_of(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def page_title_of(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else ""


def extract_anchors(html: str) -> list[dict[str, str]]:
    """[{href, text}] for every anchor. Pure parse."""
    soup = BeautifulSoup(html or "", "html.parser")
    return [
        {"href": a.get("href") or "", "text": a.get_text(" ", strip=True)}
        for a in soup.find_all("a")
    ]


def domain_of(url: Optional[str]) -> str:
    m = re.match(r"https?://(?:www\.)?([^/:?#]+)", (url or "").strip(), re.IGNORECASE)
    return (m.group(1) if m else "").casefold()


def links_to_domain(anchors: list[dict[str, str]], domain: str) -> list[dict[str, str]]:
    d = (domain or "").casefold().lstrip("www.")
    if not d:
        return []
    return [a for a in anchors if d in (a.get("href") or "").casefold()]


def has_map_embed(html: str) -> bool:
    low = (html or "").casefold()
    if "google.com/maps/embed" in low or "maps.google" in low and "<iframe" in low:
        return True
    soup = BeautifulSoup(html or "", "html.parser")
    for iframe in soup.find_all("iframe"):
        src = (iframe.get("src") or "").casefold()
        if "maps" in src and ("google" in src or "gmap" in src):
            return True
    return False


# ---------------------------------------------------------------------------
# Google-Sheet CSV parsing (cross-cutting #1: public link → CSV export)
# ---------------------------------------------------------------------------
_SHEET_URL_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([\w\-]+)", re.IGNORECASE)
_URL_HEADERS = ("live url", "citation url", "url", "link", "live link", "placement url")


def sheet_id_of(url: Optional[str]) -> Optional[str]:
    m = _SHEET_URL_RE.search(url or "")
    return m.group(1) if m else None


def sheet_csv_export_url(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"


def urls_from_sheet_csv(csv_text: str) -> list[str]:
    """The deliverable URLs out of an exported sheet: prefer a known URL-header
    column (QA_Checklists cross-cutting #1); fall back to the column with the
    most URL-shaped cells; last resort scan every cell. Pure."""
    try:
        rows = list(csv.reader(io.StringIO(csv_text or "")))
    except csv.Error:
        rows = []
    if not rows:
        return []
    header = [normalize_ws(h).casefold() for h in rows[0]]
    col: Optional[int] = None
    for name in _URL_HEADERS:
        if name in header:
            col = header.index(name)
            break
    body = rows[1:] if col is not None or any(header) else rows
    if col is None:
        # Column with the most URL-looking cells wins (≥1 hit required).
        width = max((len(r) for r in body), default=0)
        best, best_hits = None, 0
        for c in range(width):
            hits = sum(1 for r in body if len(r) > c and _URL_RE.search(r[c] or ""))
            if hits > best_hits:
                best, best_hits = c, hits
        col = best
    urls: list[str] = []
    if col is not None:
        for r in body:
            if len(r) > col:
                urls.extend(extract_urls(r[col]))
    if not urls:  # last resort: any cell anywhere
        for r in body:
            for cell in r:
                urls.extend(extract_urls(cell))
    # dedupe, order-preserved
    seen: set[str] = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ---------------------------------------------------------------------------
# Check builders (one per rubric; each returns the standard check list)
# ---------------------------------------------------------------------------
def _check(key: str, label: str, ok: Optional[bool], *, blocking: bool = True, note: str = "") -> dict:
    return {"key": key, "label": label, "ok": ok, "blocking": blocking, "note": note}


def check_gbp_post(text: Optional[str], keyword: Optional[str]) -> list[dict]:
    """QA_Checklists §GBP Posts: keyword in body, a CTA, ≥1 emoji — all blocking."""
    return [
        _check("keyword_in_body", "Target keyword present in the body",
               keyword_present(text, keyword),
               note=f'keyword: “{keyword}”' if keyword else "no target keyword found on the task"),
        _check("cta", "A CTA is present", has_cta(text) if text else None),
        _check("emoji", "At least one emoji", has_emoji(text) if text else None),
    ]


def check_link_back(html: str, client_domain: str) -> list[dict]:
    """QA_Checklists §Guest Posts / §Niche Edits: body links back to the client site."""
    if not client_domain:
        return [_check("link_back", "Link back to the client's site", None,
                       note="client has no website on file")]
    ok = bool(links_to_domain(extract_anchors(html), client_domain))
    return [_check("link_back", "Link back to the client's site", ok)]


def check_press_release(
    html: str, keyword: Optional[str],
    business_name: Optional[str], address: Optional[str], phone: Optional[str],
    client_domain: str = "",
) -> list[dict]:
    """QA_Checklists §Press Release: keyword in title + body, ≥1 non-exact-match
    anchor, NAP included — bounce if ANY fail."""
    text = visible_text_of(html)
    title = page_title_of(html)
    anchors = extract_anchors(html)
    kw = normalize_ws(keyword).casefold()

    # Non-exact-match anchor: judged over the links pointing at the client's
    # site when any exist (the anchors that matter for over-optimization),
    # else over all body links.
    pool = links_to_domain(anchors, client_domain) or [a for a in anchors if a.get("href", "").startswith("http")]
    if not kw:
        anchor_ok: Optional[bool] = None
    elif not pool:
        anchor_ok = False
    else:
        anchor_ok = any(normalize_ws(a["text"]).casefold() != kw for a in pool)

    nap = nap_match(text, business_name, address, phone)
    return [
        _check("keyword_in_title", "Target keyword in the title",
               keyword_present(title, keyword),
               note=f'keyword: “{keyword}”' if keyword else "no target keyword found on the task"),
        _check("keyword_in_body", "Target keyword in the body", keyword_present(text, keyword)),
        _check("non_exact_anchor", "At least one non-exact-match anchor", anchor_ok),
        _check("nap", "NAP included", nap["matched"],
               note=_nap_note(nap)),
    ]


def check_map_embed_page(
    html: str,
    business_name: Optional[str], address: Optional[str], phone: Optional[str],
    assertion_ok: Optional[bool] = None,
    assertion_note: str = "",
) -> list[dict]:
    """QA_Checklists §Map Embeds: assertion sentence (LLM-judged upstream —
    passed in), NAP, a maps embed — bounce if ANY missing."""
    text = visible_text_of(html)
    nap = nap_match(text, business_name, address, phone)
    return [
        _check("assertion", "Plain-English 'client provides service' sentence",
               assertion_ok, note=assertion_note),
        _check("nap", "NAP included", nap["matched"], note=_nap_note(nap)),
        _check("map_embed", "Map embed present", has_map_embed(html)),
    ]


def check_citation_page(
    page_text: str,
    business_name: Optional[str], address: Optional[str], phone: Optional[str],
    url: str = "",
) -> dict:
    """One sampled citation's NAP verdict (QA_Checklists §Citations)."""
    nap = nap_match(page_text, business_name, address, phone)
    return _check(
        "nap", f"NAP matches the client card ({url})" if url else "NAP matches the client card",
        nap["matched"], note=_nap_note(nap),
    )


def _nap_note(nap: dict[str, Any]) -> str:
    parts = []
    for field in ("name", "phone", "address"):
        v = nap.get(field)
        if v is not None:
            parts.append(f"{field}: {'found' if v else 'NOT found'}")
    return ", ".join(parts)


# --- Blog article structural checks (lightweight R1–R7 reads over markdown) --
_H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_HEADING_RE = re.compile(r"^#{2,4}\s+(.+)$", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")


def check_blog_markdown(md: Optional[str], keyword: Optional[str] = None) -> list[dict]:
    """Structural presence reads over the finished article, mirroring the
    content-quality PRD's R-checks QA can re-verify cheaply: Key Takeaways,
    a CTA, no duplicate headings (blocking); paragraph-length cap and external
    citation coverage (advisory — the pipeline already enforced them, a re-read
    flags regressions without bouncing)."""
    text = md or ""
    headings = [normalize_ws(h).casefold() for h in _HEADING_RE.findall(text)]
    dupes = {h for h in headings if headings.count(h) > 1}
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip() and not p.lstrip().startswith("#")]
    long_paras = [p for p in paragraphs if len(p.split()) > 150]
    ext_links = _MD_LINK_RE.findall(text)
    checks = [
        _check("key_takeaways", "Key Takeaways section present",
               any("key takeaway" in h for h in headings) if text else None),
        _check("cta", "CTA present", has_cta(text) if text else None),
        _check("no_dup_headings", "No duplicate headings",
               (not dupes) if text else None,
               note=("duplicates: " + ", ".join(sorted(dupes))) if dupes else ""),
        _check("paragraph_length", "Paragraphs within length cap",
               (not long_paras) if text else None, blocking=False,
               note=f"{len(long_paras)} paragraph(s) over 150 words" if long_paras else ""),
        _check("citations", "External citations present",
               (len(ext_links) > 0) if text else None, blocking=False,
               note=f"{len(ext_links)} external link(s)"),
    ]
    if keyword:
        checks.append(_check("keyword_in_body", "Target keyword present",
                             keyword_present(text, keyword), blocking=False))
    return checks


# --- Website page checks (the extras the 8-engine scorer can't see) ---------
def check_website_page(html: str, client_domain: str,
                       business_name: Optional[str]) -> list[dict]:
    """QA_Checklists §Website Pages Posted, deterministic subset: meta title +
    description, internal link, images-with-alt (blocking); client name present
    (advisory — service pages legitimately vary). Structural fidelity + the
    8-engine score are attached by qa_service where available."""
    soup = BeautifulSoup(html or "", "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    desc_tag = soup.find("meta", attrs={"name": "description"})
    desc = (desc_tag.get("content") or "").strip() if desc_tag else ""
    imgs = soup.find_all("img")
    missing_alt = [i for i in imgs if not (i.get("alt") or "").strip()]
    internal = links_to_domain(extract_anchors(html), client_domain) if client_domain else []
    name_ok: Optional[bool] = None
    if normalize_ws(business_name):
        name_ok = normalize_ws(business_name).casefold() in visible_text_of(html).casefold()
    return [
        _check("meta_title", "Meta title present", bool(title)),
        _check("meta_description", "Meta description present", bool(desc)),
        _check("internal_link", "Internal link to the client's site",
               bool(internal) if client_domain else None,
               note="" if client_domain else "client has no website on file"),
        _check("images_alt", "Images have alt text",
               (not missing_alt) if imgs else True,
               note=f"{len(missing_alt)} of {len(imgs)} image(s) missing alt" if missing_alt else ""),
        _check("client_name", "Client name on the page", name_ok, blocking=False),
    ]


# ---------------------------------------------------------------------------
# Verdict assembly — the deterministic decision (never the LLM's)
# ---------------------------------------------------------------------------
def build_verdict(checks: list[dict]) -> dict[str, Any]:
    """Fold a check list into the review verdict:
    - any blocking check ok=False        → FAIL (bounce with those items)
    - else any blocking check ok=None    → NEEDS_HUMAN (fail-open, never guess)
    - else                               → PASS
    Advisory checks never change the verdict; failed ones ride along as notes."""
    failed = [c for c in checks if c.get("blocking") and c.get("ok") is False]
    unknown = [c for c in checks if c.get("blocking") and c.get("ok") is None]
    advisories = [c for c in checks if not c.get("blocking") and c.get("ok") is False]
    if failed:
        verdict = FAIL
    elif unknown:
        verdict = NEEDS_HUMAN
    else:
        verdict = PASS
    return {
        "verdict": verdict,
        "failed": [c["label"] + (f" — {c['note']}" if c.get("note") else "") for c in failed],
        "unverified": [c["label"] + (f" — {c['note']}" if c.get("note") else "") for c in unknown],
        "advisories": [c["label"] + (f" — {c['note']}" if c.get("note") else "") for c in advisories],
    }


# ---------------------------------------------------------------------------
# Task-side conventions (keyword + deliverable-links extraction)
# ---------------------------------------------------------------------------
_KEYWORD_LINE_RE = re.compile(r"\bkeywords?\s*[:\-]\s*(.+)", re.IGNORECASE)
_NAME_SEPS = ("—", "–", ":", "|", " - ")
_SEP_STRIP = " \t-—–:|·,"


def keyword_from_task(task: dict[str, Any]) -> Optional[str]:
    """The target keyword 'on the task' (owner convention 2026-07-12: the
    keyword is entered into the TASK NAME). Resolution order, pure:

    1. An explicit 'Keyword: …' line in the description (unambiguous override).
    2. The task name minus its template name — handles both shapes:
       'GBP Posts — emergency roof repair' (template + separator + keyword)
       and a fully renamed task ('emergency roof repair' whose
       library_task_name still says which template it is).
    3. A bare 'Template — keyword' name split when no library link exists.

    A bare template name ('GBP Posts') yields None → the keyword checks read
    'could not verify' → needs_human, never a guess."""
    m = _KEYWORD_LINE_RE.search(task.get("description") or "")
    if m:
        kw = normalize_ws(m.group(1).split("\n")[0])
        if kw:
            return kw
    name = normalize_ws(task.get("name"))
    lib = normalize_ws(task.get("library_task_name"))
    if not name:
        return None
    if lib:
        if lib.casefold() in name.casefold():
            remainder = re.sub(re.escape(lib), "", name, count=1, flags=re.IGNORECASE)
            remainder = normalize_ws(remainder.strip(_SEP_STRIP))
            return remainder or None
        return name  # fully renamed: the whole name IS the keyword
    # No library link: the name must carry a recognizable template prefix for
    # the rubric to have matched at all — take what follows the separator.
    for sep in _NAME_SEPS:
        if sep in name:
            tail = normalize_ws(name.split(sep, 1)[1].strip(_SEP_STRIP))
            if tail:
                return tail
    return None


def is_deliverable_subtask(name: Optional[str]) -> bool:
    """The 'Deliverable links' subtask convention (QA_Checklists cross-cutting
    #1). task_service.is_work_item already excludes 'deliverable*' names from
    the work-item set, so this can't collide with auto-advance. Pure."""
    return "deliverable" in " ".join((name or "").casefold().split())


def new_rework_names(failed_labels: list[str], open_subtask_names: list[str]) -> list[str]:
    """The 'QA fix: …' subtasks a failed review should CREATE: one per failed
    blocking check, minus any that already exist as an OPEN subtask (repeated
    fails on the same check must not stack duplicates — hardening #1). A
    previously-ticked fix that fails again IS re-created: the completed row
    stops blocking auto-advance, so the regression needs a fresh work item.
    Case/whitespace-insensitive match. Pure."""
    existing = {normalize_ws(n).casefold() for n in open_subtask_names}
    out: list[str] = []
    for lbl in failed_labels:
        name = f"QA fix: {lbl}"
        if normalize_ws(name).casefold() not in existing:
            out.append(name)
    return out


def narrative_of(rubric: str, verdict: dict[str, Any], urls: list[str]) -> str:
    """A short deterministic summary for the qa_reviews row + notification."""
    v = verdict["verdict"]
    if v == PASS:
        head = "QA passed — all blocking checks clear."
    elif v == FAIL:
        head = f"QA failed — {len(verdict['failed'])} blocking issue(s): " + "; ".join(verdict["failed"])
    else:
        head = "QA needs a human — could not verify: " + "; ".join(verdict["unverified"])
    if verdict.get("advisories"):
        head += " Advisory: " + "; ".join(verdict["advisories"])
    if urls:
        head += f" (checked {len(urls)} URL(s))"
    return head
