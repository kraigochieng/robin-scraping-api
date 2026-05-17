FROM python:3.11-slim

WORKDIR /app

# System dependencies for Chromium/Playwright
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies only (no project), then copy source and install project
RUN uv sync --frozen --no-install-project

COPY src/ ./src/

RUN uv sync --frozen --no-editable

CMD ["uv", "run", "uvicorn", "robin_scraping_api.main:app", "--host", "0.0.0.0", "--port", "8080"]