# Module card — LABS / AI Visibility (Brand Strength)

**What it measures:** whether the brand appears when **AI assistants answer
the client's keywords** — six engines: ChatGPT, Claude, Gemini, Perplexity,
Google AI Overview, Google AI Mode. Channel: AI answers (AEO/AIO) — not a
ranking; a mention/citation outcome per question asked.

**The win definition (SOP): mention AND link.** A mention without a citation
is partial credit; track both (`brand_mention_history`: mentioned?, cited?,
which competitors appeared, which third-party sources were cited).

**Direction:** higher = better (visibility %, mention rate).

**How to read it:**
- **Single results are noisy by design.** The same question re-asked can
  produce a different answer (retrieval, wording, model variance) — the SOP
  itself says one-time checks are insufficient. **Never treat one engine
  flipping on one keyword as a trend**; read the rollup across a scan batch,
  and trends across batches.
- **Engines are not interchangeable:** Google AI Overview / AI Mode heavily
  favor **GBP data** and the top-20 organic results; ChatGPT leans on **Bing**
  (Bing Places matters there); Perplexity/Claude/Gemini cite web sources with
  different retrieval habits. "Invisible in ChatGPT but cited in AIO" points
  at engine-specific levers (see the AIO SOP's platform-influence matrix), not
  a general visibility problem.
- Competitor visibility is **re-classified from the same raw answer** — it's a
  fair comparison on identical retrieval, not a separate scan.
- Invisible keywords get a cached `invisibility_diagnosis`; read it before
  re-deriving why.
- Scans are **paid** (per keyword × engine) and run weekly/monthly per the
  schedule — data is only as fresh as the last batch; check `checked_at`.

**Known blind spots:** no Copilot engine (possible future); answers reflect
the engine's index lag, not today's site; a keyword nobody asks AI about can
be "invisible" with zero business impact — weigh against demand from the rank
tracker.

**Worked misreading:** "We lost ChatGPT visibility on 'emergency plumber' —
yesterday it mentioned us, today it doesn't." That's within normal run-to-run
variance. A real signal looks like: mention rate across the whole keyword set
falling across two-plus consecutive batches, or a competitor consistently
appearing where the client consistently doesn't.
