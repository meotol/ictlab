import os

from dotenv import load_dotenv


load_dotenv()


class Config:
    """Base application configuration loaded from environment variables."""

    SERVICE_NAME = "ICT Lab"
    SERVICE_DOMAIN = "ict.metol.cloud"
    ENVIRONMENT = os.getenv("ICTLAB_ENV", "development").lower()
    SECRET_KEY = os.getenv("SECRET_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL")
    DATABASE_ENGINE_OPTIONS = {}


def validate_config(config) -> None:
    """Validate required settings and apply development-only defaults."""
    environment = str(config.get("ENVIRONMENT", "development")).lower()

    if environment == "production" and not config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set when ICTLAB_ENV=production")

    if not config.get("SECRET_KEY"):
        config["SECRET_KEY"] = "development-only-change-me"
