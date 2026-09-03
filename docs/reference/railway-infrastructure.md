# Railway infrastructure — service & environment reference

> **Read the live config; do not trust this file for anything that changes.**
> This file records only the **durable identifiers and topology** — the values that
> almost never change and that otherwise cost a `list-services` round-trip every
> session. It deliberately does **not** record variable *values*, which feature
> flags are on, deploy SHAs, or health status. Those must always come from a live
> read (`get-service-config`, `list-variables`, `environment-status`), per the
> "read the live config, do not infer it" rule in `CLAUDE.md`. A remembered
> snapshot of volatile state is exactly the trap that section warns against.
>
> _Last verified against live config: 2026-09-03._

## Project

| | Value |
|---|---|
| Project name | `ar-tools` |
| Project ID | `2c718e53-73c8-4de8-bef8-7136f06b6ead` |
| Workspace | `kssabraw's Projects` (`4fe35644-90e9-4e2d-a1cf-5f7792704156`) |
| Environment | `production` (`7bd2e88e-8ead-4806-a0e0-673d34d66323`) — only one environment |
| Railway account | `kssabraw` / `kssabraw@gmail.com` |

## Services

| Service | Service ID | Root dir | Builder | Public domain |
|---|---|---|---|---|
| **PLATFORM** | `af877ebf-35aa-43af-a6aa-9fd60f2812c0` | `/writer/platform-api` | RAILPACK¹ | `platform-production-a5c5.up.railway.app:8080` |
| **pipeline** | `e98080ec-de6d-4df4-89bc-d2826d511445` | `writer/pipeline-api` | RAILPACK¹ | `pipeline-production-c063.up.railway.app:8080` |
| **nlp** | `5477a749-39ef-43f0-99fc-bf245cd6d0d5` | `writer/nlp-api` | DOCKERFILE (`writer/nlp-api/Dockerfile`) | `nlp-production-0e3c.up.railway.app:8080` ² |
| **outreach** | `928c84bc-d7ca-416a-bd61-39e91cc64872` | — | — | cron job (0 replicas between runs) |

All services deploy from `kssabraw/ar-tools` on branch **`main`**, region **us-west2**, **1 replica** each.

¹ The config API can report `RAILPACK` even when a `railway.toml` / Dockerfile is what actually
builds. Treat the builder field as advisory for PLATFORM/pipeline; confirm from the repo if it matters.

² Per `CLAUDE.md`, `nlp` is meant to be **private-only** (reached at `nlp.railway.internal:8080`,
no public domain, no deploy healthcheck). Railway still auto-generates the `up.railway.app` domain
shown here — **verify it isn't actually serving publicly** before relying on the "private" assumption.

## Private network endpoints

| Service | Private endpoint (as reported by config) |
|---|---|
| PLATFORM | `perfect-transformation` |
| pipeline | `ar-tools` |
| nlp | *(none listed — internal DNS is `nlp.railway.internal`)* |

## Things to check live, never assume from this file

- **Start command overrides** — a dashboard `startCommand` can silently replace the
  image `CMD` and drop flags. As of the last verify there were **none**; re-check with
  `get-service-config` before diagnosing a wrong-command run.
- **Variable values** — via the OAuth connector, `list-variables` returns **names only**,
  never secrets. Confirming a value (e.g. a Slack channel id, a time budget) needs the
  Railway dashboard, or a session/API-token connection.
- **Source branch** — should be `main` on all four; a stale pointer means Deploy builds old code.
- **Health / deploy state** — use `environment-status`; a crashed job can still report SUCCESS
  under `restartPolicy: NEVER`, so check the job's own DB marker (e.g. `OUTREACH_RESULT`), not status.

## How to re-verify

```
list-services        projectId=2c718e53-73c8-4de8-bef8-7136f06b6ead
get-service-config   projectId=… serviceId=…      # source, builder, start cmd, var names
list-variables       projectId=… serviceId=…      # var names (values redacted for OAuth)
environment-status   projectId=… includeSuccessful=true
```
