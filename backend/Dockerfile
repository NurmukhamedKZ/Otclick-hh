# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# System deps for Playwright Chromium runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer)
# Build context = repo root (see docker-compose.yml `context: ..`)
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv pip install --system --no-cache .

# Playwright Chromium + OS deps. Browsers go to PLAYWRIGHT_BROWSERS_PATH (shared, world-readable)
# so the non-root `app` user below can find them.
RUN playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

# App code
COPY backend/app ./app
COPY backend/worker_main.py ./worker_main.py

# Non-root user
RUN useradd -m -u 1000 app && chown -R app:app /app /home/app
USER app

EXPOSE 8000

# Default = API. Worker overrides via compose command.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
