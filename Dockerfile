# syntax=docker/dockerfile:1

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system leetgo \
    && useradd --system --gid leetgo --home-dir /app leetgo

COPY pyproject.toml README.md LICENSE ./
COPY leetgo ./leetgo

RUN pip install . \
    && mkdir -p /app/data /app/logs \
    && chown -R leetgo:leetgo /app

USER leetgo

ENV DATABASE_PATH=/app/data/leetgo.db \
    LOG_FILE=/app/logs/leetgo.log \
    HEALTH_HOST=0.0.0.0 \
    HEALTH_PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('HEALTH_PORT', '8080') + '/healthz', timeout=3)"]

CMD ["python", "-m", "leetgo"]
