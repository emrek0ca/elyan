# ─────────────────────────────────────────────────────────────
# Elyan v18.0 — Production Docker Image
# Multi-stage: builder + slim runtime
# ─────────────────────────────────────────────────────────────

# ── Stage 1: builder ──────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev libssl-dev libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt setup.py ./
COPY . .

# Install into /install prefix (no venv needed in Docker)
RUN pip install --upgrade pip --no-cache-dir \
 && pip install --prefix=/install --no-cache-dir \
      -r requirements.txt \
 && pip install --prefix=/install --no-deps --no-cache-dir -e .

# ── Stage 2: runtime ──────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Elyan"
LABEL org.opencontainers.image.version="18.0.0"
LABEL org.opencontainers.image.description="Özerk AI Operatör"

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd -m -u 1000 elyan
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local
COPY --chown=elyan:elyan . /app

# Data directories
RUN mkdir -p /data/{memory,projects,logs,skills} \
    && chown -R elyan:elyan /data

USER elyan

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ELYAN_DATA_DIR=/data \
    ELYAN_HEADLESS=1 \
    PYTHONPATH=/app

# Default: gateway (CLI) mode — no UI
EXPOSE 18789

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:18789/api/status || exit 1

CMD ["python", "main.py", "--cli"]
