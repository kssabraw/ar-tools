FROM python:3.11-slim

WORKDIR /app

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
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
