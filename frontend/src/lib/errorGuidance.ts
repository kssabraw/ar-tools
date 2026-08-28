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
  concurrency_limit: {
    title: 'Too many runs at once',
    meaning:
      'The server caps how many generation jobs run at the same time, and ' +
      'that cap is currently reached.',
    steps: [
      'Wait a minute for in-flight work to finish, then try again.',
      'Bulk jobs run at background priority, so a big batch elsewhere can hold the queue briefly.',
    ],
  },
  bulk_limit_exceeded: {
    title: 'Too many pages selected for one batch',
    meaning: 'This bulk request is over the per-batch limit.',
    steps: [
      'Select fewer pages and run it in a couple of smaller batches.',
    ],
  },
  no_valid_keywords: {
    title: 'No usable keywords in this request',
    meaning:
      'None of the selected items had a keyword the generator could use ' +
      '(blank, duplicate, or filtered out).',
    steps: [
      'Check the selection — each page needs a real keyword.',
      'Re-select and try again.',
    ],
  },
  no_valid_items: {
    title: 'Nothing valid to generate',
    meaning: 'None of the selected items could be turned into a page request.',
    steps: ['Re-check the selection and try again.'],
  },
  keyword_required: {
    title: 'A keyword is required',
    meaning: 'This page can’t be generated without a target keyword.',
    steps: ['Enter a keyword, then try again.'],
  },
  location_required: {
    title: 'A location is required',
    meaning: 'A local page needs a target location (city / area).',
    steps: ['Set the location, then try again.'],
  },
  services_required: {
    title: 'At least one service is required',
    meaning: 'A location page needs the services it should cover.',
    steps: ['Add one or more services, then try again.'],
  },
  client_has_no_website: {
    title: 'This client has no website set',
    meaning:
      'This step reads the client’s live site (e.g. to find existing pages), ' +
      'and no website is configured.',
    steps: [
      'Open Client → Edit and add the website URL.',
      'Save, then try again.',
    ],
  },
  client_has_no_gbp_category: {
    title: 'This client has no Google Business Profile category',
    meaning:
      'This step needs the client’s GBP primary category and none is on file.',
    steps: [
      'Connect / select the client’s Google Business Profile (Client → Edit), then try again.',
    ],
  },
  local_seo_provider_error: {
    title: 'The page generator hit an upstream error',
    meaning:
      'The Local SEO generation service (competitor analysis + writer) failed ' +
      'partway. This is usually transient — a slow or rate-limited upstream.',
    steps: [
      'Try again — most provider errors clear on a retry.',
      'If it keeps failing, share the raw code below with the team.',
    ],
  },
  ecommerce_provider_error: {
    title: 'The page generator hit an upstream error',
    meaning:
      'The Ecommerce generation service failed partway. This is usually ' +
      'transient — a slow or rate-limited upstream.',
    steps: [
      'Try again — most provider errors clear on a retry.',
      'If it keeps failing, share the raw code below with the team.',
    ],
  },
  local_seo_no_result: {
    title: 'Generation finished without a page',
    meaning: 'The run completed but produced no usable page.',
    steps: ['Try again; if it repeats, share the raw code below with the team.'],
  },
  ecommerce_no_result: {
    title: 'Generation finished without a page',
    meaning: 'The run completed but produced no usable page.',
    steps: ['Try again; if it repeats, share the raw code below with the team.'],
  },
  apps_script_call_failed: {
    title: 'Couldn’t reach Google Drive',
    meaning:
      'The Apps Script webhook that creates the Google Doc didn’t respond.',
    steps: [
      'Try publishing again — this is often a transient hiccup.',
      'If it persists, it’s a server-side setting — flag it to the team.',
    ],
  },
  apps_script_http_error: {
    title: 'Google Drive returned an error',
    meaning:
      'The Apps Script webhook responded with an error while creating the Doc.',
    steps: [
      'Try again; if it persists, flag the Apps Script deployment to the team.',
    ],
  },
  github_repo_not_set: {
    title: 'No GitHub repo configured for this client',
    meaning: 'Publishing to GitHub needs the client’s repo, which isn’t set.',
    steps: [
      'Open Client → Edit and set the GitHub repository.',
      'Save, then publish again.',
    ],
  },
  github_not_configured: {
    title: 'GitHub publishing isn’t set up on the server',
    meaning: 'The server-side GitHub credentials for site publishing aren’t configured.',
    steps: [
      'This is a server setting — flag it to the team.',
      'Publish to Google Docs or WordPress in the meantime.',
    ],
  },
  wordpress_rest_api_unreachable: {
    title: 'Couldn’t reach the WordPress site',
    meaning:
      'The client’s WordPress REST API didn’t respond — the site may block ' +
      'REST, be behind a firewall, or be temporarily down.',
    steps: [
      'Confirm the site URL is correct and reachable (Client → Edit).',
      'Check that the WordPress REST API isn’t disabled by a security plugin.',
      'Try again once the site responds.',
    ],
  },
  wordpress_image_too_large: {
    title: 'The featured image is too large for WordPress',
    meaning: 'WordPress rejected the image because it exceeds the size limit.',
    steps: [
      'Use a smaller featured image, then publish again.',
    ],
  },
  run_not_resumable: {
    title: 'This run can’t be resumed',
    meaning: 'The run isn’t in a state that supports resuming.',
    steps: [
      'Start a fresh run instead.',
    ],
  },
  not_client_linked: {
    title: 'This session isn’t linked to a client',
    meaning:
      'Scoring / reoptimizing an article needs a client-linked session — an ' +
      'unlinked session has no suite run and no brand-voice / ICP context to ' +
      'reoptimize against.',
    steps: [
      'Link this session to a client (Copy to client / the session’s client selector).',
      'Then run Score / Reoptimize again.',
    ],
  },
  read_only_role: {
    title: 'You don’t have edit access here',
    meaning: 'This action needs an owner role; your account is read-only for it.',
    steps: [
      'Ask an owner/admin to make the change, or to grant you access.',
    ],
  },
  session_not_found: {
    title: 'This session no longer exists',
    meaning: 'The session was deleted or isn’t reachable anymore.',
    steps: [
      'Go back to the sessions list and pick a current session.',
    ],
  },
  article_not_found: {
    title: 'This article couldn’t be found',
    meaning: 'The article was removed or its run no longer resolves.',
    steps: [
      'Refresh the articles list and try again.',
    ],
  },
  cluster_not_in_client: {
    title: 'This article isn’t under the expected client',
    meaning: 'The article’s cluster doesn’t belong to this client’s session.',
    steps: [
      'Refresh and retry from the correct client’s session.',
    ],
  },
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
  content_compliance_violation: {
    title: 'Blocked by the content-compliance guardrail',
    meaning:
      'This client is a regulated (peptide/research-chemical) account, and the ' +
      'finished content contains something that must not be published: human ' +
      'dosing or administration instructions, a claim that the product is ' +
      'equivalent to a branded medication (e.g. Ozempic/Mounjaro/semaglutide), ' +
      'a guaranteed-results/efficacy claim, or buy-it advocacy. The offending ' +
      'phrase(s) are shown below. This is a regulatory block, not a quality ' +
      'preference, so it can’t be overridden from here.',
    steps: [
      'Read the flagged phrase(s) below to see exactly what tripped the guardrail.',
      'Edit or regenerate the content to remove the dosing/equivalence/guarantee/advocacy language — keep it educational only.',
      'Publish again once the content is clean. (If you believe the flag is a genuine false positive, an admin can adjust the client’s compliance mode — but review the phrase first.)',
    ],
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

/**
 * Whether a raw message reads like a backend error code (`snake_case`, no
 * spaces) rather than a human sentence. Lets a surface show tailored/generic
 * guidance for real codes while rendering already-friendly messages plainly.
 * The token before any `":"` is what's judged, so `"voice_violation: cheapest"`
 * still counts as a code.
 */
export function looksLikeErrorCode(raw: string | null | undefined): boolean {
  const head = (raw ?? '').split(':')[0].trim()
  return /^[a-z][a-z0-9_]{2,}$/.test(head)
}

// The backend appends offending values after the code as `"<code>: a | b | c"`.
// Pipe-delimited (not comma) so a distilled never-use phrase with an internal
// comma stays one term. Only pull them for codes we know carry them, so a plain
// sentence that happens to contain a colon isn't mis-parsed into "terms".
function extractTerms(code: string, message: string): string[] {
  if (code !== 'voice_violation' && code !== 'content_compliance_violation') return []
  const idx = message.indexOf(`${code}:`)
  if (idx < 0) return []
  return message
    .slice(idx + code.length + 1)
    .split('|')
    .map(t => t.trim())
    .filter(Boolean)
}
