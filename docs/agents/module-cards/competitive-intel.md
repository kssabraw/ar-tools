# Module card — Competitive Intelligence (assembled competitor profiles)

**What it measures:** for each competitor in the client's registry, a single
profile **joined across every module the suite already captured** — local-pack
presence, GBP (rating / reviews / categories), backlinks (RD/DR), organic
keyword overlap, 30-day review velocity, and newly-published pages. It is the
"who is beating us, where, and what are they doing about it" read. Distinct from
the **domain-intelligence** card: that is a paid domain-vs-domain gap tool you
point at one named domain; THIS is the standing, multi-module portrait of the
client's actual competitive field.

**How to read the fields (per competitor — `competitors[]`):**
- A **null module is missing capture, not an absent competitor** — `gbp: null`
  means the suite hasn't pulled that rival's GBP yet, not that they have none.
  Never read a null as a strength or a gap; it is unknown.
- `sources` says how the competitor entered the registry (maps leaderboard /
  recurring organic top-10 / AI-visibility list / manual). A one-source
  competitor is a narrower signal than one showing up across channels.
- Competitor **RD/DR are tool reads** — true RD ≈ **×10** the displayed number
  (the SOP shared definition; same discount as the domain-intelligence card).
  Never compare a competitor's tool-read RD against the client's *true* RD.
- `review_velocity_30d` vs the client's own is the prominence-momentum read: a
  rival adding reviews far faster is gaining a local-pack lever, not just a
  higher count today.
- `new_pages_30d` / `recent_pages` are **non-baseline** URLs first seen in the
  last 30 days — genuinely new content, not the whole site. An unanswered
  content push is a real signal; the first-ever crawl of a competitor is a
  baseline and surfaces nothing.

**`page_targeting` (the land-grab read):** `contested` names places BOTH a
competitor is building for AND the client cares about (a weak grid zone, a
declared target/ICP service area, or a place the client already has a page
for = head-to-head). `open_places` are places the client cares about that no
tracked competitor is contesting yet — first-mover room. This is the section
that turns "they're bigger" into a specific, place-anchored proposal.

**Known blind spots:** the registry is only as complete as discovery + manual
adds — a competitor nobody added is invisible here; the join reflects the last
capture of each module, so a fast-moving rival can be staler in one channel than
another; "overlap" keywords are where you *both* rank, not the full set they
outrank you on (that is the domain-intelligence keyword gap).

**Worked misreading:** "Competitor X has 480 RD to our 60 — we're outgunned 8:1,
propose a big link push." Wrong on two counts: their 480 is a tool read (~48
true RD) and the client's 60 may already be a true RD — the real gap can be
small or reversed. Read RD only against another tool read, and check
`page_targeting` for where they're actually winning before proposing links as
the lever.
