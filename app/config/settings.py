import os
from dotenv import load_dotenv

load_dotenv()


SECRET_KEY = os.getenv("SECRET_KEY")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///app.db"
)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )


GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_SECRET = os.getenv("GOOGLE_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")



GEMINI_API_KEYS = [
    k for k in [os.getenv(f"GEMINI_API_{i}") for i in range(1, 11)]
    if k
]

OPENROUTER_API_KEYS = [
    k for k in [os.getenv(f"OPENROUTER_API_{i}") for i in range(1, 6)]
    if k
]


def configure_app(app) -> None:
    """Apply the application's configuration to a Flask instance."""
    from datetime import timedelta

    app.config.update(
        SECRET_KEY=SECRET_KEY,
        SQLALCHEMY_DATABASE_URI=DATABASE_URL,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )
