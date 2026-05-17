FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock README.md ./

# Install dependencies only (no project)
RUN uv sync --frozen --no-install-project

COPY src/ ./src/

# Install project
RUN uv sync --frozen --no-editable

# Install Playwright browsers and their system dependencies
RUN uv run playwright install chromium
RUN uv run playwright install-deps chromium

CMD ["uv", "run", "uvicorn", "robin_scraping_api.main:app", "--host", "0.0.0.0", "--port", "8080"]