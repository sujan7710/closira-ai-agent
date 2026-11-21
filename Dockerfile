# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    CLOSIRA_DB=/data/closira.db \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user; /data holds the SQLite database (mount a volume there).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data && chown appuser:appuser /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=4)"

# One worker on purpose: chat sessions and the rate limiter are in memory.
# Threads handle concurrency; LLM calls are I/O bound.
CMD exec gunicorn app:app \
    --bind 0.0.0.0:${PORT} \
    --workers 1 --threads 8 \
    --timeout 60 \
    --access-logfile - --error-logfile -
