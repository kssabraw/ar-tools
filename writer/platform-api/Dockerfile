FROM python:3.11-slim

WORKDIR /app

# System libraries for WeasyPrint (HTML/CSS -> PDF, Client Reporting module):
# pango/cairo/gdk-pixbuf + base fonts. Without these, `import weasyprint` fails
# at runtime. Own layer so the dependency install below stays cached.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libffi-dev shared-mime-info fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Upgrade pip, then install. The two-command form also changes this layer's
# BuildKit cache key so a stale pre-consolidation pip layer (which had the old
# openai without the Responses API) can't be reused on a same-commit rebuild.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Topic Fanout SIE module: the spaCy lemmatizer model (en_core_web_sm),
# baked into the image at build time (matches the installed spaCy minor).
RUN python -m spacy download en_core_web_sm

COPY . .

EXPOSE 8000
# `exec` is load-bearing: shell-form CMD makes `sh` PID 1, and PID 1 with no
# handler DISCARDS SIGTERM — uvicorn never saw Railway's redeploy signal, so the
# lifespan shutdown (in-flight job drain, fanout scheduler stop) never ran and
# every deploy was effectively a hard kill. `exec` replaces sh with uvicorn as
# PID 1 (uvicorn installs its own SIGTERM handler). --timeout-graceful-shutdown
# bounds uvicorn's wait for open connections (SSE chat/score streams would
# otherwise hold shutdown until SIGKILL, starving the drain); 5s leaves the
# drain's DB writes headroom inside Railway's kill grace (extend the grace via
# the RAILWAY_DEPLOYMENT_DRAINING_SECONDS service variable if ever needed).
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-graceful-shutdown 5"]
