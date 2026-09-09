# GBP Business Description SOP — enforcement map

The **standard itself** (how to write + audit a GBP description) is the canonical
agency SOP: **`docs/sops/GBP_Description_SOP.md`** (vendored into
`writer/platform-api/agent_docs/sops/` and selectable by SerMaStr via the `gbp`
SOP-library domain). This file is the implementation reference — **where the
suite enforces that SOP** — for a developer changing the GBP Profile Editor.

## Where the SOP is enforced in code

| SOP concern | Code |
|---|---|
| Rewrite / AI draft follows the SOP architecture + rules | `services/gbp_profile_service.py::_DESC_SYSTEM` (draft system prompt) |
| Drafted output is corrected against the SOP trip-wires | `services/gbp_profile_service.py::_content_violations` (feeds the corrective rewrite loop) |
| Audit flags a present-but-weak description | `services/gbp_audit.py::audit` → `description_quality.issues` |
| SOP trip-wire detectors (pure) | `services/gbp_audit.py`: `find_superlatives`, `find_marketing_filler`, `has_generic_opening`, `overused_terms` |
| Inline editor advisories while composing | `services/gbp_profile_api.py::lint_description` |
| Audit recommendations / Action Plan / strategist hints | `services/gbp_profile_audit.py::_recommendations`, `services/reopt_planner.py` (`_dq_hint`), `services/strategy_digest.py` |
| SerMaStr grounding (cites the SOP) | `services/sop_library.py` (`gbp` domain → `GBP_Description_SOP.md`); triggered by `services/slack_assistant/helpers.py::sop_domains` (GBP-description vocabulary) and `services/strategy_digest.py::active_signal_domains` (a weak/missing description) |

`description_quality.issues` keys: `too_short`, `missing_service_keyword`,
`missing_location`, `keyword_stuffed`, `promotional_superlatives`,
`marketing_filler`, `generic_opening`. Every check is **best-effort and
high-precision** — it fires only when its input exists (e.g. the location checks
need captured location terms), so a naturally-written description is never
false-flagged. The verdict is deterministic; the LLM only phrases the rewrite.

*Standard adapted from the SED Society GBP Description guide provided by the owner
(2026-09-09).*
