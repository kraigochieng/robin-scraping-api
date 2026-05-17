FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright/Scrapling
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen

COPY src/ ./src/

CMD ["uv", "run", "uvicorn", "robin_scraping_api.main:app", "--host", "0.0.0.0", "--port", "8080"]