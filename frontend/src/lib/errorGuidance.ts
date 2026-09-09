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
  not_pace_pm: {
    title: 'That’s a PACE PM action',
    meaning: 'Approving the daily plan and generating a client’s monthly board are limited to PACE PMs (Minda, Kyle, or Ryan). The automatic monthly generation on the 1st still runs on its own.',
    steps: [
      'Ask a PACE PM (Minda, Kyle, or Ryan) to run it.',
      'Or an admin can grant you PM on the Team page.',
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
  // ── Service × location matrix ───────────────────────────────────────────
  matrix_signoff_required: {
    title: 'This matrix needs a sign-off before generating',
    meaning:
      'The whole matrix is over the link-equity sign-off line (200 pages). ' +
      'A grid that large spreads the site’s authority thin, so it needs a ' +
      'deliberate go-ahead — the same line the Website Builder uses.',
    steps: [
      'Review whether every service × location combination is worth a page (prune thin ones from the axes).',
      'If it is, tick the sign-off in the run bar and generate again.',
    ],
  },
  matrix_cell_limit: {
    title: 'Too many cells for one run',
    meaning:
      'One immediate run is capped so a single batch cannot monopolise the ' +
      'worker for a day. Bigger fills go out on a schedule.',
    steps: [
      'Select fewer cells (a row or a column at a time), or',
      'Set up a release schedule to drip the rest out over days or weeks.',
    ],
  },
  matrix_axes_empty: {
    title: 'The matrix needs at least one service and one location',
    meaning: 'Both axes were empty after trimming blank and duplicate lines.',
    steps: ['Add at least one service and one location, one per line, then save.'],
  },
  url_pattern_missing_service_token: {
    title: 'URL pattern must include {service}',
    meaning:
      'Without {service} every location’s cells would share one URL, so the ' +
      'sibling links between pages would point at the wrong page.',
    steps: ['Use a pattern with both tokens, e.g. /{service}-{location}/.'],
  },
  url_pattern_missing_location_token: {
    title: 'URL pattern must include {location}',
    meaning:
      'Without {location} every cell of a service would share one URL, so the ' +
      'sibling links between pages would point at the wrong page.',
    steps: ['Use a pattern with both tokens, e.g. /{service}-{location}/.'],
  },
  url_pattern_unknown_token: {
    title: 'Unknown token in the URL pattern',
    meaning: 'Only {service} and {location} are substituted.',
    steps: ['Remove the unknown token or replace it with {service} / {location}.'],
  },
  hub_pattern_missing_service_token: {
    title: 'Service hub pattern must include {service}',
    meaning:
      'The top-level service page link is built from this pattern, so it needs ' +
      '{service} to point at the right page (e.g. /roof-restoration/).',
    steps: ['Use a pattern with {service}, e.g. /{service}/ or /services/{service}/.'],
  },
  hub_pattern_has_location_token: {
    title: 'Service hub pattern can’t include {location}',
    meaning:
      'The top-level service page is location-agnostic — it’s the page every ' +
      'location page links up to — so {location} doesn’t belong in it.',
    steps: ['Remove {location}; use e.g. /{service}/ or /services/{service}/.'],
  },
  url_pattern_empty: {
    title: 'URL pattern is empty',
    meaning: 'A pattern is needed to plan each page’s URL (it drives the sibling links).',
    steps: ['Pick a preset or type a pattern with {service} and {location}.'],
  },
  matrix_not_found: {
    title: 'Matrix not found',
    meaning: 'It may have been deleted, or belongs to a different client.',
    steps: ['Go back to the matrix list and reopen it.'],
  },
  local_seo_matrix_not_enabled: {
    title: 'The matrix feature is switched off',
    meaning: 'local_seo_matrix_enabled is false on the platform service.',
    steps: ['Ask an admin to enable it on the PLATFORM service and redeploy.'],
  },
  social_not_enabled: {
    title: 'The Social Media module is off',
    meaning: 'The social publishing module is disabled on this environment.',
    steps: ['Ask an admin to set SOCIAL_ENABLED=true on the PLATFORM service and redeploy.'],
  },
  social_spec_violation: {
    title: 'The post doesn’t meet the platform’s rules',
    meaning:
      'The post failed a platform check before publishing — usually an empty ' +
      'post, copy over the character limit, too many images, more than one ' +
      'video, or a platform that requires an image.',
    steps: [
      'Read the detail after the code (e.g. over_char_limit, too_many_images, media_required, empty_post).',
      'Trim the copy, adjust the media to fit the platform, then publish again.',
    ],
  },
  social_copy_generation_failed: {
    title: 'The AI couldn’t draft the copy',
    meaning: 'The copywriting model didn’t return a draft — usually a temporary provider hiccup.',
    steps: ['Try “Draft with AI” again in a moment.', 'If it keeps failing, write the copy manually or tell an admin.'],
  },
  social_angles_failed: {
    title: 'Couldn’t suggest angles',
    meaning: 'The strategist model didn’t return angles — usually a temporary provider hiccup.',
    steps: ['Try “Suggest angles” again, or write your own angle and fan out.'],
  },
  social_fanout_failed: {
    title: 'Couldn’t start the fan-out',
    meaning: 'The request to generate drafts across platforms failed to start.',
    steps: ['Check you picked an angle and at least one platform, then try again.'],
  },
  social_angle_required: {
    title: 'Pick or write an angle first',
    meaning: 'Fanning out needs an angle to base every draft on.',
    steps: ['Select a suggested angle or type your own, then fan out.'],
  },
  social_no_target_platforms: {
    title: 'Pick at least one platform',
    meaning: 'None of the selected platforms match a connected account for this client.',
    steps: ['Tick one or more platforms the client has connected, then fan out.'],
  },
  social_draft_not_found: {
    title: 'Draft not found',
    meaning: 'That draft no longer exists (it may have been deleted).',
    steps: ['Refresh the Drafts list.'],
  },
  social_draft_already_published: {
    title: 'Already published',
    meaning: 'This draft has already been published to an account.',
    steps: ['Check Recent posts on the Compose tab, or create a new draft.'],
  },
  social_account_required: {
    title: 'Pick an account to publish to',
    meaning: 'Publishing a draft needs one connected account of that platform.',
    steps: ['Select an account, then publish. If none is listed, connect one in PostPeer.'],
  },
  social_image_generation_failed: {
    title: 'The AI couldn’t generate the image',
    meaning: 'The image model didn’t return an image — usually a temporary provider hiccup or a prompt it declined.',
    steps: ['Try again, or reword the description.', 'If it keeps failing, upload an image instead or tell an admin.'],
  },
  social_image_budget_exceeded: {
    title: 'This client’s social budget is used up',
    meaning: 'Generating an image would exceed the client’s monthly social spend ceiling, so it was blocked before spending.',
    steps: ['Upload an image instead, wait for next month, or ask an admin to raise the client’s social monthly ceiling.'],
  },
  social_image_not_configured: {
    title: 'AI image generation isn’t set up',
    meaning: 'The image provider key (GEMINI_API_KEY) isn’t configured on this environment.',
    steps: ['Ask an admin to set GEMINI_API_KEY on the PLATFORM service.', 'Meanwhile, upload an image instead.'],
  },
  social_image_description_required: {
    title: 'Describe the image first',
    meaning: 'The image generator needs a description of what to draw.',
    steps: ['Type what the image should show, then generate again.'],
  },
  social_bad_aspect_ratio: {
    title: 'Unsupported image shape',
    meaning: 'The requested aspect ratio isn’t one the image model supports.',
    steps: ['Leave the shape on the platform default, or pick a supported ratio (e.g. 1:1, 4:5, 9:16, 16:9, 2:3).'],
  },
  social_source_empty: {
    title: 'Add something to draft from',
    meaning: 'The topic / notes box was empty, so there’s nothing to write about.',
    steps: ['Type a topic or a few notes, then draft again.'],
  },
  social_source_url_required: {
    title: 'Paste a page URL',
    meaning: 'You chose to draft from a web page but didn’t provide a URL.',
    steps: ['Paste the full https:// URL of the page to repurpose, then draft again.'],
  },
  social_source_id_required: {
    title: 'Pick a source',
    meaning: 'You chose to draft from a blog post or saved page but didn’t select one.',
    steps: ['Choose an item from the dropdown, then draft again.'],
  },
  social_source_not_found: {
    title: 'That source couldn’t be found',
    meaning: 'The selected blog post or saved page doesn’t exist for this client (it may have been deleted).',
    steps: ['Pick a different source, or refresh the page and try again.'],
  },
  social_source_fetch_failed: {
    title: 'Couldn’t read that page',
    meaning: 'The URL couldn’t be fetched or had no readable article content.',
    steps: ['Check the URL opens in a browser.', 'Try a different source, or draft from a topic instead.'],
  },
  social_source_fetch_error: {
    title: 'Couldn’t reach that page',
    meaning: 'Fetching the URL failed (the site was unreachable or blocked the request).',
    steps: ['Try again in a moment, or draft from a topic / blog post instead.'],
  },
  scheduled_in_past: {
    title: 'The scheduled time is in the past',
    meaning: 'A scheduled post needs a time in the future.',
    steps: ['Pick a future date and time, then schedule again.'],
  },
  unsupported_media_type: {
    title: 'Unsupported file type',
    meaning: 'That file isn’t a supported image or video.',
    steps: ['Use JPG, PNG, WebP or GIF for images, or MP4 / MOV for video.'],
  },
  file_too_large: {
    title: 'File is too large',
    meaning: 'The upload is over the per-file size limit (200 MB).',
    steps: ['Compress or trim the file under 200 MB and upload again.'],
  },
  invalid_image: {
    title: 'That image couldn’t be read',
    meaning: 'The file looked like an image but couldn’t be decoded — it may be corrupt.',
    steps: ['Re-export the image and upload it again.'],
  },
  empty_file: {
    title: 'The file was empty',
    meaning: 'The uploaded file had no content.',
    steps: ['Pick the file again and re-upload.'],
  },
  budget_exceeded: {
    title: 'This client’s social budget is used up',
    meaning:
      'Publishing this post would exceed the client’s monthly social spend ' +
      'ceiling, so it was blocked before spending.',
    steps: [
      'Wait for the next month, or ask an admin to raise the client’s social monthly ceiling.',
    ],
  },
  platform_specific_invalid_json: {
    title: 'The advanced options aren’t valid JSON',
    meaning: 'The platform-specific options box must contain valid JSON (or be empty).',
    steps: ['Fix the JSON (or clear the box), then publish again.'],
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
  // ── GBP Profile Editor ─────────────────────────────────────────────────────
  gbp_profile_not_enabled: {
    title: 'GBP Profile Editor isn’t turned on yet',
    meaning:
      'The tool is built but gated off. It needs the agency Google account ' +
      'connected and two server flags set.',
    steps: [
      'Connect the agency Google account (the Connect button above).',
      'Set GBP_API_ENABLED and GBP_PROFILE_ENABLED on the platform service.',
      'Prove the write path with verify_gbp_api_access.py --edit-test first.',
    ],
  },
  empty_draft: {
    title: 'The AI couldn’t draft anything to suggest',
    meaning:
      'The draft came back empty. For services this usually means the listing’s ' +
      'categories offer no Google-approved service types AND there wasn’t enough ' +
      'on the client to write custom services from — or a one-off model hiccup.',
    steps: [
      'Add a few target cities on the client (Client → Edit) so the AI can build a service × location matrix.',
      'Make sure the client’s ICP / services / silo topics are filled in — that’s what custom services are written from.',
      'Try “Suggest with AI” again — a single empty reply can be transient.',
    ],
  },
  gbp_listing_read_only: {
    title: 'The connected account can’t edit this listing',
    meaning:
      'The Google account can SEE this listing (so it lists) but doesn’t have ' +
      'full edit rights on it — usually the listing is unverified or the ' +
      'account is only a Site Manager, not an Owner/Manager.',
    steps: [
      'Confirm the Business Profile is verified.',
      'Have the client add the agency account as an Owner/Manager (not just Site Manager).',
      'Then re-open this page and try the edit again.',
    ],
  },
  cannot_modify_services: {
    title: 'This listing doesn’t allow editing its services',
    meaning:
      'Google reports the services list can’t be modified for this listing ' +
      '(canModifyServiceList is false) — often because the listing’s primary ' +
      'category doesn’t support a services list, or it’s unverified.',
    steps: [
      'Check the listing is verified and its category supports services.',
      'Edit the description or hours instead if you just need to update those.',
    ],
  },
  gbp_listing_unverified: {
    title: 'This Business Profile isn’t verified',
    meaning:
      'An unverified listing has limited editability, so Google rejected the ' +
      'edit.',
    steps: [
      'Verify the Business Profile in the Google dashboard, then retry.',
    ],
  },
  description_too_long: {
    title: 'Description is over 750 characters',
    meaning:
      'Google caps a Business Profile description at 750 characters and ' +
      'rejected this one for length.',
    steps: [
      'Trim the description to 750 characters or fewer (the counter shows the length).',
      'Apply again.',
    ],
  },
  description_contains_url: {
    title: 'Description contains a URL',
    meaning:
      'Google doesn’t allow links in the business description and rejects any ' +
      'that contain one.',
    steps: [
      'Remove the URL from the description (put your website in the profile’s Website field instead).',
      'Apply again.',
    ],
  },
  description_contains_phone: {
    title: 'Description contains a phone number',
    meaning:
      'Google doesn’t allow phone numbers in the business description.',
    steps: [
      'Remove the phone number (the profile’s phone field handles that).',
      'Apply again.',
    ],
  },
  invalid_service_category: {
    title: 'A service has an invalid category',
    meaning:
      'Every free-form service must attach to one of the listing’s own ' +
      'categories, and one here points at a category the listing doesn’t have.',
    steps: [
      'Open the Services editor and pick a valid category for each service (the dropdown lists the listing’s categories).',
      'Apply again once every service has a category.',
    ],
  },
  gbp_edit_pending_review: {
    title: 'Submitted to Google — pending review',
    meaning:
      'The edit was accepted but Google queued it for review rather than ' +
      'publishing it instantly. This isn’t a failure.',
    steps: [
      'Nothing to do — the app re-checks automatically and marks it live when Google approves it.',
      'Use “Refresh status” if you want to check right now.',
    ],
  },
  gbp_edit_live_changed: {
    title: 'The live value changed since you drafted this',
    meaning:
      'Someone edited this field in the Google dashboard after this draft was ' +
      'made, so applying would overwrite that change unseen. The app stopped ' +
      'instead of clobbering it.',
    steps: [
      'Re-open this page to see the current live value.',
      'Re-draft on top of the current value, then apply.',
    ],
  },
  gbp_location_not_found: {
    title: 'Listing not found',
    meaning:
      'Google couldn’t find the listing this edit targets — it may have been ' +
      'removed or its id changed.',
    steps: [
      'Re-open the Business Profile tool and re-register the client’s listing.',
    ],
  },
  invalid_website_url: {
    title: 'That doesn’t look like a valid website URL',
    meaning:
      'The website field needs a real web address (a scheme is added for you, ' +
      'but it has to be an http/https URL with a domain).',
    steps: [
      'Enter the full site URL, e.g. https://www.example.com.',
      'Leave it blank to clear the website from the listing.',
    ],
  },
  too_many_labels: {
    title: 'Too many labels',
    meaning: 'Google allows at most 10 labels on a listing.',
    steps: ['Remove labels until 10 or fewer remain, then apply again.'],
  },
  label_too_long: {
    title: 'A label is too long',
    meaning: 'Each label must be 255 characters or fewer.',
    steps: ['Shorten the flagged label, then apply again.'],
  },
  invalid_more_hours_type: {
    title: 'That additional-hours type isn’t valid for this listing',
    meaning:
      'More-hours types (kitchen, delivery, senior hours…) are specific to the ' +
      'listing’s primary category, and this one isn’t offered for it.',
    steps: [
      'Pick an additional-hours type from the dropdown (only valid ones are listed).',
      'If none fit, this listing’s category doesn’t support extra hours.',
    ],
  },
  invalid_service_area: {
    title: 'The service area couldn’t be set',
    meaning:
      'A service-area write needs each place resolved to a Google place, and one ' +
      'here isn’t resolved (or the business type is invalid).',
    steps: [
      'Re-pick each service area so it resolves to a real place (a ✓ shows when it does).',
      'Remove any place that won’t resolve, then apply again.',
    ],
  },
  invalid_open_status: {
    title: 'Invalid open/closed status',
    meaning:
      'The status must be Open, Temporarily closed, or Permanently closed.',
    steps: ['Pick a valid status, then apply again.'],
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
