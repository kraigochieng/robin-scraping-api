"""
Application Logging Configuration.

This module sets up the global logging behavior for the application. It configures
where logs are sent (Console + File), how they are formatted, and how files are
rotated to manage disk space. It also filters out verbose noise from third-party libraries.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

from robin_scraping_api.settings import settings


def setup_logging():
    """
    Configures the root logger for the entire application.

    This function performs the following setup:
    1.  **Log Level:** Sets the global logging level based on the environment
        (`DEBUG` for 'dev', `INFO` for 'prod').
    2.  **File Logging:** Writes logs to `basic.log` in the project root.
        -   **Rotation:** Rotates the log file every 7 days (`when="D"`, `interval=7`).
        -   **Retention:** Keeps the last 3 backup files (`backupCount=3`).
    3.  **Console Logging:** Writes logs to `sys.stdout` for container/terminal visibility.
    4.  **Formatting:** Uses a standard format: `Time | Level | Logger:Line | Message`.
    5.  **Noise Reduction:** Explicitly sets the log level to `WARNING` for chatty
        third-party libraries (e.g., `httpx`, `openai`, `aiomysql`) to keep the
        main log output clean.

    Side Effects:
        - Modifies the global `logging` configuration via `basicConfig`.
        - Creates a log file on disk if it does not exist.
    """
    # current_file = Path(__file__).resolve()
    # BASE_DIR = current_file.parent.parent.parent
    # LOG_FILE_PATH = BASE_DIR / "basic.log"

    if settings.environment == "dev":
        logging_level = logging.DEBUG
    elif settings.environment == "prod":
        logging_level = logging.INFO
    else:
        logging_level = logging.INFO

    log_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # file_handler = logging.FileHandler(LOG_FILE_PATH)

    # MAX_LOG_SIZE = 10 * 1024 * 1024
    # BACKUP_COUNT = 3

    # file_handler = RotatingFileHandler(
    #     LOG_FILE_PATH, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT
    # )

    # file_handler = TimedRotatingFileHandler(
    #     LOG_FILE_PATH,
    #     when="D",  # Rotate based on days
    #     interval=7,  # Every 7 days
    #     backupCount=BACKUP_COUNT,
    #     encoding="utf-8",
    # )

    # file_handler.setFormatter(log_formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)

    logging.basicConfig(
        level=logging_level,
        # handlers=[file_handler, console_handler],
        handlers=[console_handler],
        force=True,
    )

    # Silencing noisy logs in debug mode
    libraries_to_be_silenced = [
        "sse_starlette",
        "httpcore",
        "httpx",
        "openai",
        "urllib3",
        "langsmith",
        "aiomysql",
    ]

    for library in libraries_to_be_silenced:
        logging.getLogger(library).setLevel(logging.WARNING)

    # logging.config("numba").setLevel(logging.WARNING)

    # Add a log message to confirm setup
    logger = logging.getLogger(__name__)

    # logger.debug(
    #     f"Logging configured. Level: {logging_level}, File: {LOG_FILE_PATH}, Console: True"
    # )

    logger.debug(f"Logging configured. Level: {logging_level}, Console: True")
