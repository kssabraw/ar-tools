# AR Tools — Internal Agency Suite

Internal suite of SEO/content tools for the agency team. Multiple modules share one
dashboard, one Supabase database, and one scheduler. See
[`docs/suite-architecture-and-roadmap-v1_0.md`](docs/suite-architecture-and-roadmap-v1_0.md)
for the full scope, locked decisions, and phased roadmap.

## Tools

| Tool | Status | Location |
|---|---|---|
| Blog Writer | 🚧 In Progress | /writer |
| Local SEO content | 📋 Planned (migrate) | TBD |
| KW Research | 📋 Planned (migrate) | /kw-research |
| Organic rank tracker | 📋 Planned | TBD |
| Maps / local-pack ranker | 📋 Planned | TBD |
| Ranking-drop agent | 📋 Planned | TBD |
| VA content scheduler | 📋 Planned | TBD |

## Structure

- `/writer` — Blog content generation platform (first module)
- `/frontend` — Shared frontend for all tools
- `/docs` — PRDs, specs, and the suite architecture roadmap

## Tech Stack

- Backend: Python 3.11+, FastAPI, Railway
- Database: Supabase (shared across all tools)
- Frontend: React + Vite, deployed to Netlify
- LLM: Anthropic Claude
