from fastapi import FastAPI

from robin_scraping_api.logging_config import setup_logging
from robin_scraping_api.routers import fetch

setup_logging()

app = FastAPI(
    title="Robin Scraping API",
    description="Stealthy browser-based scraping with optional persistent profiles.",
    version="1.0.0",
)

app.include_router(fetch.router)
