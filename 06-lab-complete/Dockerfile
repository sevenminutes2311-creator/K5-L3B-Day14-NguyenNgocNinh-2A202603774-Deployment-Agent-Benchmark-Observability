# ============================================================
# Production Dockerfile — multi-stage, non-root, healthcheck, PORT từ env
#
#   Stage 1 (builder): tạo venv và cài dependencies
#   Stage 2 (runtime): chỉ copy venv + code cần để chạy, chạy bằng user `app`
#
# Build (từ thư mục này):  docker build -t agent .
# Chạy:                     docker run -p 8000:8000 --env-file .env agent
# ============================================================

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.11-slim AS runtime

RUN groupadd -r app && useradd -r -g app -d /app -s /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app/ ./app/
COPY utils/ ./utils/

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'), timeout=4)" || exit 1

# exec form + `exec` trong sh: uvicorn là PID 1, nhận SIGTERM khi `docker stop`
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
