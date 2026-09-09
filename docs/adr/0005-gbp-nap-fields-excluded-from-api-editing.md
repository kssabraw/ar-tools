# GBP NAP identity fields are excluded from API editing

**Status:** accepted (2026-09-09)

The GBP Profile Editor module (`docs/modules/gbp-profile-editor-prd-v1_0.md`)
was expanded in v1.1 (owner, 2026-09-09) from three fields
(description / services / hours) to the full editable Business-Profile surface —
`websiteUri`, `labels`, `specialHours`, `moreHours`, `serviceArea`, `openInfo`,
`categories`, `attributes`, and `media` (photos / logo / cover). The one group
deliberately **left out** is the **NAP identity triplet**: the business
**`title`** (name), **`storefrontAddress`**, and **`phoneNumbers`**. This tool
does not edit those fields via the API in v1.1.

## Why

The Business Information API *can* patch all three (`updateMask=title`,
`storefrontAddress`, `phoneNumbers`), so this is a product/safety boundary, not a
technical one.

- **NAP edits are the classic trigger for GBP re-verification or suspension.**
  Changing a name, address, or primary phone on an *established, verified*
  listing routinely sends it back into review — and on a sensitive listing can
  suspend it. A suspended listing disappears from Maps and Search until a manual
  reinstatement, which is exactly the outcome the suite's Freeze Protocol exists
  to prevent, not cause.
- **It is the highest-blast-radius mistake the tool could make.** A wrong
  description or a bad services list is embarrassing and fixable; a wrong
  business name or address is an identity error that can misroute customers,
  break NAP citation consistency across the web (which the suite tracks
  separately), and invalidate the listing's verification.
- **The suite already treats NAP as authoritative-input, not tool-output.** NAP
  flows *into* the suite (GBP capture, the Website Builder's Settings tab where
  human-typed NAP values win and are stamped `provenance:"user"`); nothing in the
  suite has ever *written NAP back to Google*, and this module is not the place
  to start.
- **The rest of the editable set does not carry this risk.** Description,
  services, hours, website, labels, special/more hours, service area, open info,
  categories, and attributes either don't touch verification or (categories,
  open-info closures) are already gated behind the extra-confirm step and the
  "AI never drafts a closure/primary-category downgrade" rule. NAP is a different
  kind of field and gets a different answer.

## Considered options

- **Fold NAP into the Tier-A editor like website/labels.** Rejected: it puts the
  suspension-sensitive identity fields behind the same lightweight review as a
  URL edit. The failure mode (re-verification / suspension) is categorically
  worse than any other field's.
- **Include NAP behind an extra confirm (like hours).** Rejected for v1.1: an
  extra "are you sure" click does not mitigate a *Google-side* re-verification —
  the risk isn't a typo the operator can catch, it's Google's response to *any*
  identity change, correct or not. A confirm step is the wrong tool for that
  risk.
- **Exclude NAP from API editing entirely (chosen).** NAP changes remain manual,
  done deliberately in the Google dashboard by a human who understands the
  re-verification consequence. The tool absorbs the *safe* dashboard work and
  leaves the one genuinely dangerous surface alone.

## Consequences

- The GBP Profile Editor never sends `title`, `storefrontAddress`, or
  `phoneNumbers` in a `locations.patch` `updateMask`. The field set is closed to
  those three.
- If NAP editing is ever revisited, it does **not** get folded into the existing
  editor. It gets its own hardened flow: an unverified-listing hard block, an
  explicit typed-value re-entry confirm ("type the new phone number again"),
  probably an owner-only permission, and a loud warning that the change may send
  the listing to re-verification. That is a separate, deliberate build — a future
  ADR, not a scope tweak.
- This decision is consistent with ADR 0004 (no auto-apply): both draw the same
  line — the higher the blast radius of the outward act, the more a human, not
  the tool, owns it. NAP is simply the far end of that line.

## Related

- `docs/adr/0004-gbp-profile-edits-never-auto-applied.md` — the sibling boundary
  (no auto-apply on any field).
- `docs/modules/gbp-profile-editor-prd-v1_0.md` — the v1.1 amendments block (the
  full tiered scope; the "still OUT" list points here).
- Root `decisions.md`, "GBP Profile Editor module" — the terse decision log.
