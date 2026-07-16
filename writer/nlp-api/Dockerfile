FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import nltk; nltk.download('stopwords', download_dir='/usr/local/share/nltk_data'); nltk.download('punkt', download_dir='/usr/local/share/nltk_data'); nltk.download('punkt_tab', download_dir='/usr/local/share/nltk_data')" \
    && python -m spacy download en_core_web_sm

ENV NLTK_DATA=/usr/local/share/nltk_data

COPY . .

EXPOSE 8080
# Bind to :: so Railway private networking (IPv6-only) can reach this service.
# Linux dual-stack still accepts IPv4 via IPv4-mapped addresses.
CMD uvicorn main:app --host :: --port ${PORT:-8080}
