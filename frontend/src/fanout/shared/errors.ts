// Turning API rejections into something a user can act on.
//
// Two failures kept looking like "the button does nothing". Some mutations had
// no `onError` at all, so a 400 vanished and the spinner just blinked off (the
// Architecture view's Generate button, reported 2026-08-06). Others caught the
// error but replaced it with generic copy — "Couldn't start planning. Try
// again." — which discards the reason and gives the wrong advice when the real
// cause is that a run is already in progress and retrying will fail identically.
//
// The server's own `detail` strings are close to usable, but they name internal
// routes: "Run /plan-articles first", "Run /expand first". No user has seen
// those — the UI calls them "Plan articles" and "Run keyword pipeline". So the
// translations below exist mainly to name the button the user actually clicks.
//
// Anything without a translation falls through to the server's message rather
// than to generic copy: an untranslated real reason still beats "try again".

const TRANSLATIONS: Array<[RegExp, string]> = [
  [
    /no article plan to build an architecture from/i,
    "There's no article plan yet. Run “Plan articles” first — the architecture is " +
      "built from the articles that step produces.",
  ],
  [
    /a (pipeline )?run is already in progress/i,
    "Something is already running for this session. Wait for it to finish, then try again.",
  ],
  [
    /no statistical clustering to plan from/i,
    "This session has no keywords to plan from yet — the keyword pipeline hasn't " +
      "finished. Run it first, then come back to planning.",
  ],
  [
    /no keywords to (re-gate|preview)/i,
    "This session has no keywords yet. Run the keyword pipeline first.",
  ],
  [
    /no sub-anchors to fan out/i,
    "There's nothing to fan out yet — the keyword pipeline needs to run first so the " +
      "silos have clusters.",
  ],
  [
    /no pipeline run is in progress/i,
    "There's nothing running to cancel — it already finished or was stopped.",
  ],
  [
    /read_only_role/i,
    "Your account is read-only, so it can't make changes here.",
  ],
  [
    /invalid or expired token/i,
    "Your sign-in has expired. Reload the page and sign in again.",
  ],
  [
    /every silo is excluded from the run/i,
    "No silos are selected to run. Tick at least one before starting.",
  ],
];

/**
 * A user-facing sentence for a failed request.
 *
 * `fallback` is used only when there is no message at all (a network drop, or an
 * error that isn't an Error) — never to paper over a message the server sent.
 */
export function friendlyError(e: unknown, fallback = "Something went wrong. Try again."): string {
  const raw = e instanceof Error ? e.message.trim() : typeof e === "string" ? e.trim() : "";
  if (!raw) return fallback;
  for (const [pattern, plain] of TRANSLATIONS) {
    if (pattern.test(raw)) return plain;
  }
  // Untranslated, but real: the fanout API's details are written as sentences,
  // so showing one is strictly more useful than generic copy.
  return raw;
}
