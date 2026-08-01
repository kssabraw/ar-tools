# Outreach pipeline — Railway cron service.
#
# This is a JOB, not a server. It starts on a schedule, does one market's work, and exits.
# Railway bills only the minutes it actually runs, which for a semi-monthly pipeline is a few
# cents a month; the same code left running as an always-on service would hold memory around the
# clock for ~$5-6/month to do nothing between cycles.
#
# Railway requires a cron service to TERMINATE and leave no open resources. If the process does
# not exit, subsequent scheduled executions are silently skipped. `run_market.py` is a CLI that
# returns an exit code, which is exactly the right shape — do not turn this into a uvicorn
# process without also removing the cron schedule.

FROM python:3.11-slim

# Which commit this image holds, printed as line one of every run (`OUTREACH_BUILD ...`).
#
# Railway supplies RAILWAY_GIT_COMMIT_SHA to the build, so declaring it as an ARG bakes it in.
# The runtime also checks the env directly, so this working is not load-bearing — and if the
# banner says `sha=unknown` the command list still exposes a stale image, which is the failure
# that actually cost time: a deploy silently built a merged branch's commit and only announced
# itself by rejecting a subcommand that did not exist yet.
ARG RAILWAY_GIT_COMMIT_SHA=""
ENV OUTREACH_BUILD_SHA=$RAILWAY_GIT_COMMIT_SHA

WORKDIR /app

COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r api/requirements.txt

# Whole outreach tree: api/ (code), markets/ (definitions), supabase/, queries/.
# The market definition files are the reason the build context is /outreach and not /outreach/api.
COPY . .

# OUTREACH_COMMAND defaults to `filter`, which is FREE and idempotent.
#
# This default is a spend guard, not a preference. A Railway service re-runs its start command on
# every deploy, so if the default were `run`, an unrelated redeploy — a rollback, a variable
# change, a rebuild — would silently fire a paid Outscraper pull. Set OUTREACH_COMMAND=run
# deliberately when a paid ingest is intended, and set it back afterwards.
#
# `exec` so the CLI is PID 1 and receives SIGTERM directly; sh as PID 1 discards it.
CMD ["sh", "-c", "exec python -m api.scripts.run_market ${OUTREACH_COMMAND:-filter} ${OUTREACH_MARKET:-markets/los-angeles-plumbing.json}"]
