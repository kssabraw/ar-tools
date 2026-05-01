FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m nltk.downloader -d /usr/local/share/nltk_data wordnet omw-1.4 punkt_tab averaged_perceptron_tagger_eng

ENV NLTK_DATA=/usr/local/share/nltk_data

COPY . .

EXPOSE 8000
# Bind to :: so Railway private networking (IPv6-only) can reach this service.
# Linux dual-stack will still accept IPv4 connections via IPv4-mapped addresses.
CMD uvicorn main:app --host :: --port ${PORT:-8000}
