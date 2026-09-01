FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

COPY freqtrade /tmp/freqtrade
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -e /tmp/freqtrade \
    && freqtrade install-ui

COPY user_data/ ./user_data/
COPY config.example.json .
COPY scripts/ ./scripts/
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh ./scripts/*.sh ./scripts/list_accounts.py 2>/dev/null || true

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/v1/ping || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["trade"]
