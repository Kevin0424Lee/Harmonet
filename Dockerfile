FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-prod.txt* ./
RUN pip install --upgrade pip && \
    if [ -f requirements-prod.txt ]; then \
        pip install --no-cache-dir --prefix=/install -r requirements-prod.txt; \
    else \
        pip install --no-cache-dir --prefix=/install -r requirements.txt; \
    fi


FROM python:3.11-slim AS runtime

RUN groupadd -r harmonet && useradd -r -g harmonet -d /app -s /sbin/nologin harmonet

WORKDIR /app

COPY --from=builder /install /usr/local
COPY harmonet/ ./harmonet/
COPY benchmark/ ./benchmark/

RUN chown -R harmonet:harmonet /app

USER harmonet

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    HARMONET_LOG_LEVEL=INFO \
    HARMONET_LOG_FORMAT=json \
    HARMONET_TRACING=false \
    REDIS_HOST=redis \
    REDIS_PORT=6379

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz', timeout=3).read()" || exit 1

CMD ["python", "-m", "harmonet.health", "--host", "0.0.0.0", "--port", "8080"]


FROM runtime AS dev

USER root
RUN pip install --no-cache-dir \
    pytest pytest-asyncio pytest-cov \
    ruff \
    locust
USER harmonet

CMD ["bash"]
