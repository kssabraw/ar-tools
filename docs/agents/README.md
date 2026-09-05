# SerMaStr — where its "training material" lives (and how to edit it)

This is the map of everything that shapes how **SerMaStr** (the Search Marketing
Strategist agent) reasons. If you want to change what it knows or how it thinks,
the thing you edit is in one of the three layers below.

There are **two surfaces**, and they don't read the same things:

- **The strategist** — the weekly / on-demand / escalation / goal-recovery run
  that produces a `strategy_reviews` row (owner-facing; `services/strategist.py`).
- **The conversational SerMaStr** — the Slack + `/assistant` web chat
  (`services/slack_assistant/`).

Know which surface you're changing before you edit, or you'll change the wrong
one. (Common trap: keyword research shows up in the *chat* but is **not** in the
strategist's digest — so a keyword-research module card would describe data the
strategist never sees. It belongs in the chat's inline block instead.)

---

## Layer 1 — Markdown docs (edit these freely; no code risk)

### Module cards — "how to read each instrument"
- **Edit here (canonical):** `docs/agents/module-cards/*.md`
- **Vendored copy (must match byte-for-byte):** `writer/platform-api/agent_docs/module-cards/*.md`
- **Who reads them:** the **strategist only**. Every card is concatenated whole
  into every strategist run (`sop_library.load_module_cards()`).
- **What a card is for:** the mental model + the misreading traps for one module
  ("`average_rank` without `found_pins` is a lie"; "competitor RD is a tool read,
  ≈ ×10"). Not a field catalog — teach how to read the number, not what fields
  exist. Follow the shape of the existing cards: *What it measures → Direction →
  How to read the fields → Known blind spots → a Worked misreading.*

> ⚠️ **Do not put any non-card `.md` file in `module-cards/`.** The loader globs
> `*.md` and injects **everything** in that directory into the prompt — a stray
> README or notes file would be fed to the model as if it were a card (and the
> sync-guard test would then demand a vendored copy of it too). That is exactly
> why *this* README lives one level up, in `docs/agents/`.

### SOP corpus — the strategy + execution playbooks
- **Edit here (canonical):** `docs/sops/*.md` (start with `docs/sops/README.md`
  and `docs/sops/_ORCHESTRATOR.md`)
- **Vendored copy (must match byte-for-byte):** `writer/platform-api/agent_docs/sops/*.md`
- **Who reads them:** **both** surfaces. The strategist selects a budgeted subset
  keyed to the client's active signals; the chat pulls them for strategy-shaped
  questions. Per-client DB overrides (`services/sop_store.py`) take precedence
  over the repo corpus.
- **Style note:** SOPs are written to be *reasoned with*, not just executed.
  Where a claim is the agency's operating theory rather than settled fact, label
  it `(working model)` — SerMaStr is told to cite those as theory, and (since the
  2026-09-05 reasoning pass) to flag them when a client's measured data
  contradicts them. Keep that convention when you add or edit an SOP.

### The vendoring rule (the gotcha that bites everyone)
The `docs/…` copies are canonical; the `agent_docs/…` copies exist because the
platform-api Docker image can't see repo-root `docs/`. **They must stay
byte-identical**, and a unit test enforces it
(`writer/platform-api/tests/test_sop_library.py` →
`test_vendored_module_cards_match_canonical` /
`test_vendored_sops_match_canonical`). After editing a card or an SOP, re-copy:

```bash
# from the repo root
cp docs/agents/module-cards/*.md writer/platform-api/agent_docs/module-cards/
cp docs/sops/*.md               writer/platform-api/agent_docs/sops/
```

If you forget, the test fails with `agent_docs drifted from … Re-copy the docs`.

---

## Layer 2 — The prompts (these are code; edit carefully, tests gate them)

- **Strategist system prompt:** `writer/platform-api/services/strategist.py`, the
  `_SYSTEM` string. Its role/altitude, `WHAT YOU'RE FOR` priorities, `HARD RULES`
  (guardrails, also enforced in code by `sanitize_review`), the instrument-reading
  pointer, and the "question the working model" seam. Changing stance,
  priorities, or permissions happens here.
- **Conversational system prompt(s):** `writer/platform-api/services/slack_assistant/prompts.py`.
  This surface has its **own** inline `HOW TO READ THE INSTRUMENTS` block (it does
  not load the module-card files), plus the portfolio- and director-mode prompts.
  An instrument-reading rule that must apply in **chat** goes here — mirror it
  from the matching module card so the two surfaces agree.

---

## Layer 3 — What data it can even see (add this before it can reason about a new module)

A card or a prompt rule is useless if the module's data never reaches the agent.
The data comes from provider registries:

- **Strategist digest:** `writer/platform-api/services/strategy_digest.py` — one
  `_prov_<module>` per module, listed in `_CONTEXT_PROVIDERS` at the bottom. Each
  is isolated (a failing module degrades to a gap, never breaks the digest) and
  carries its own `note` / `TRAP` text.
- **Conversational context:** `writer/platform-api/services/slack_assistant/context.py`
  — one `_ctx_<module>` per module.
- **Strategist investigation tools:** `writer/platform-api/services/strategist_tools.py`
  — the read-only drill-down tools it can call mid-run; each tool description
  restates the instrument's traps so a result can't be misread.

So the full recipe to teach it about a **new** module is: add a provider
(Layer 3) → add a card and/or a chat instrument rule (Layers 1–2) → re-vendor
the card → run the tests.

---

## Quick "I want to…" table

| Goal | Edit | Also do |
|---|---|---|
| Add/expand a "how to read this module" card (strategist) | `docs/agents/module-cards/<module>.md` | re-copy to `agent_docs/module-cards/`; if the rule matters in chat too, add a line to the inline block in `slack_assistant/prompts.py` |
| Add/change an agency SOP (both surfaces) | `docs/sops/<sop>.md` | re-copy to `agent_docs/sops/`; label agency theory `(working model)` |
| Change the strategist's stance / priorities / permissions | `services/strategist.py` `_SYSTEM` | run `tests/test_strategist.py` |
| Change how the **chat** reads an instrument | `services/slack_assistant/prompts.py` | keep it consistent with the matching module card |
| Let it reason about a **new** module at all | add a `_prov_*` (strategist) and/or `_ctx_*` (chat) provider | then add the card / prompt rule above |

## Test before you ship
From `writer/platform-api/`:
```bash
python -m pytest tests/test_sop_library.py tests/test_strategist.py \
                 tests/test_strategy_digest.py tests/test_interventions.py -q
```
`test_sop_library.py` is the one that catches an un-synced vendored copy.
