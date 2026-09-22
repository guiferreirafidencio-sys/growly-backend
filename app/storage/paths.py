"""Centralized paths for files generated while the application runs."""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", PROJECT_DIR / "sessions"))
LOGS_DIR = Path(os.getenv("LOGS_DIR", PROJECT_DIR / "logs"))
INSTANCE_DIR = PROJECT_DIR / "instance"


def ensure_runtime_directories() -> None:
    """Create writable directories without moving existing account sessions."""
    for directory in (SESSIONS_DIR, LOGS_DIR, INSTANCE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
