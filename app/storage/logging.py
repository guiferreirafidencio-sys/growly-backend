"""Application logging with a small rotating file for production diagnostics."""

import logging
from logging.handlers import RotatingFileHandler

from .paths import LOGS_DIR


def configure_logging() -> None:
    logger = logging.getLogger("growly")
    if logger.handlers:
        return
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOGS_DIR / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"growly.{name}")
