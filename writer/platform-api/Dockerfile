FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Topic Fanout SIE module: the spaCy lemmatizer model (en_core_web_sm),
# baked into the image at build time (matches the installed spaCy minor).
RUN python -m spacy download en_core_web_sm

COPY . .

EXPOSE 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
