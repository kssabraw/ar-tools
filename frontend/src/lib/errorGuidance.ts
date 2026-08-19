// Turns a raw backend error code into something a human can act on.
//
// The backend speaks in short string codes (`voice_violation`,
// `missing_google_drive_folder_id`, …) per the standardized error envelope.
// Those are precise but opaque to a VA staring at a red box. This registry maps
// each known code to a friendly headline, a plain-English explanation, and a
// numbered plan of action — the raw material the <ErrorDetails> accordion
// renders under the error line.
//
// Adding a new code: append an entry keyed by the exact code the backend
// raises. Anything unmatched falls through to a generic-but-honest default, so
// an unmapped code degrades to "here's the raw code, here's what to try" rather
// than a dead end.

export interface ErrorGuidance {
  /** Friendly one-line headline shown in place of the bare code. */
  title: string
  /** "What this means" — one or two plain sentences. */
  meaning: string
  /** "How to fix it" — ordered steps, most-likely-fix first. */
  steps: string[]
  /**
   * When the failure has a deliberate one-click override (e.g. "Publish
   * anyway" past a brand-voice block), the label for that button. The caller
   * decides whether an override is actually wired up; this only names it.
   */
  override?: string
}

export interface ParsedError {
  /** The matched error code, or `unknown` when nothing matched. */
  code: string
  /** The raw message as received. */
  raw: string
  /**
   * Specific offending values pulled out of the message where the backend
   * includes them (today: the forbidden words on a `voice_violation`).
   */
  terms: string[]
  guidance: ErrorGuidance
}

const GENERIC: ErrorGuidance = {
  title: 'Something went wrong',
  meaning:
    'The server refused this action and returned an error code. It hasn’t ' +
    'been given a friendly explanation yet.',
  steps: [
    'Try the action once more — some failures are transient (a deploy or a slow upstream).',
    'If it keeps failing, share the raw error code below with the team.',
  ],
}

// Keyed by the exact backend code. Order matters only for `matchGuidance`,
// which returns the first code that appears in the message — so list more
// specific codes before any that are substrings of others.
const REGISTRY: Record<string, ErrorGuidance> = {
  voice_violation: {
    title: 'Blocked by the client’s brand guide',
    meaning:
      'The finished page uses wording the client’s brand guide marks as ' +
      '“never use”. Only a forbidden word blocks publishing — a low voice ' +
      'score or a missing preferred phrase never does. The never-use list is ' +
      'distilled from the guide, so occasionally it flags a word the client ' +
      'is actually fine with.',
    steps: [
      'Open the Brand voice panel to see the exact forbidden word(s) and where they appear.',
      'If the flag is right, reoptimize or regenerate the page to remove the word, then publish again.',
      'If the flag is wrong (a mis-read of the guide), use “Publish anyway” to override — it’s a deliberate second click.',
    ],
    override: 'Publish anyway',
  },
  client_frozen: {
    title: 'This client is frozen',
    meaning:
      'The client is under a freeze (a confirmed manual action or ' +
      'deindexing), so all content creation and publishing is paused. ' +
      'Monitoring keeps running; output does not.',
    steps: [
      'Check the freeze banner at the top of the client workspace for the reason.',
      'Recovery is Admin-owned — an Admin lifts the freeze once the underlying issue is resolved.',
      'Publishing works again automatically once the freeze is lifted.',
    ],
  },
  missing_google_drive_folder_id: {
    title: 'No Google Drive folder set for this client',
    meaning:
      'Publishing to Google Docs saves into the client’s Drive folder, and ' +
      'this client doesn’t have one configured yet.',
    steps: [
      'Open Client → Edit and set the client’s Google Drive folder.',
      'Save, then publish again.',
    ],
  },
  publish_not_configured: {
    title: 'Google Docs publishing isn’t set up on the server',
    meaning:
      'The Apps Script webhook that creates Google Docs isn’t configured, so ' +
      'the server can’t publish there.',
    steps: [
      'This is a server-side setting (the Apps Script URL) — flag it to the team.',
      'In the meantime you can publish to WordPress or GitHub instead, if configured.',
    ],
  },
  wordpress_not_configured: {
    title: 'No WordPress connection for this client',
    meaning:
      'Publishing to WordPress needs the client’s site URL and an Application ' +
      'Password, which aren’t set yet.',
    steps: [
      'Open Client → Edit and add the WordPress site + Application Password.',
      'Save, then publish again.',
    ],
  },
  wordpress_auth_failed: {
    title: 'WordPress rejected the credentials',
    meaning:
      'WordPress refused the username / Application Password for this client’s site.',
    steps: [
      'Re-check the WordPress username and Application Password in Client → Edit.',
      'Generate a fresh Application Password in WordPress if you’re unsure it’s still valid.',
      'Save, then publish again.',
    ],
  },
  run_not_complete: {
    title: 'This run hasn’t finished yet',
    meaning: 'The page can only be published once its run has completed successfully.',
    steps: [
      'Wait for the run to reach “complete”, then publish.',
      'If the run errored, open it to see which stage failed and re-run it.',
    ],
  },
  github_publish_failed: {
    title: 'Publishing to GitHub failed',
    meaning:
      'The commit to the client’s configured GitHub repo didn’t go through.',
    steps: [
      'Confirm the client has a GitHub repo configured (Client → Edit).',
      'Try publishing again — the image-generation + commit job can fail transiently.',
      'If it keeps failing, share the raw error below with the team.',
    ],
  },
}

/**
 * Match a raw error message to its guidance. Uses substring containment so an
 * enriched detail like `"voice_violation: cheapest"` still matches the
 * `voice_violation` entry, and pulls out any trailing terms after the colon.
 */
export function parseError(raw: string | null | undefined): ParsedError {
  const message = (raw ?? '').trim()
  for (const code of Object.keys(REGISTRY)) {
    if (message.includes(code)) {
      return {
        code,
        raw: message,
        terms: extractTerms(code, message),
        guidance: REGISTRY[code],
      }
    }
  }
  return { code: 'unknown', raw: message, terms: [], guidance: GENERIC }
}

// The backend appends offending values after the code as `"<code>: a, b, c"`.
// Only pull them for codes we know carry them, so a plain sentence that happens
// to contain a colon isn't mis-parsed into "terms".
function extractTerms(code: string, message: string): string[] {
  if (code !== 'voice_violation') return []
  const idx = message.indexOf(`${code}:`)
  if (idx < 0) return []
  return message
    .slice(idx + code.length + 1)
    .split(',')
    .map(t => t.trim())
    .filter(Boolean)
}
