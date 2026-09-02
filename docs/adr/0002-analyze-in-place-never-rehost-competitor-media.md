# Competitor research is analyze-in-place — never download or re-host competitor media

**Status:** accepted (2026-09-02)

The module reverse-engineers what competitors post to inform (never copy) the
client's content. Scraping competitor posts and downloading their video sits on a
copyright/platform-ToS fault line, so we constrain the pipeline to
**analyze-in-place**: Apify reads **public, logged-out** competitor content
(captions, formats, engagement — content, not identities); TwelveLabs analyzes
competitor **video from its public URL** (no download step — it ingests URLs
directly); **cobalt.tools is reserved for the client's own or licensed assets
only**. We store derived **Competitor Signals** plus *links* — never a
competitor's media — and every generated output must be transformative and
original ("transform, never replicate").

## Considered options

- **Download competitor video (cobalt) then analyze/store it.** Rejected:
  downloading and re-hosting others' media is where copyright/ToS liability
  actually lives; it buys nothing over URL-based analysis for competitive intel.
- **Skip competitor video entirely.** Rejected: URL-based analysis is low-risk
  and high-value, so there's no reason to forgo it.

## Consequences

- TwelveLabs is limited to publicly-URL-ingestable competitor video (fine for
  competitive intel).
- cobalt.tools, when used, is self-hosted (its public instance forbids
  programmatic use) and only touches owned/licensed assets — with a
  permission/license provenance requirement on any downloaded asset before it can
  enter a publish flow.
- Personal data in scraped content (handles, reviewer/commenter names) is
  minimized and retention-bounded; signals capture content, not identities.
- The "make our version" action is inspiration for an original draft, never
  reproduction of a competitor post.
