import os

from dotenv import load_dotenv


load_dotenv()
load_dotenv(".env.admin")


class Config:
    """Base application configuration loaded from environment variables."""

    SERVICE_NAME = "ICT Lab"
    SERVICE_DOMAIN = "ict.metol.cloud"
    ENVIRONMENT = os.getenv("ICTLAB_ENV", "development").lower()
    SECRET_KEY = os.getenv("SECRET_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")
    DATABASE_ENGINE_OPTIONS = {}


def validate_config(config) -> None:
    """Validate required settings and apply development-only defaults."""
    environment = str(config.get("ENVIRONMENT", "development")).lower()

    if environment == "production" and not config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set when ICTLAB_ENV=production")

    if environment == "production" and (
        not config.get("ADMIN_USERNAME") or not config.get("ADMIN_PASSWORD_HASH")
    ):
        raise RuntimeError("Administrator credentials must be configured in production")

    if not config.get("SECRET_KEY"):
        config["SECRET_KEY"] = "development-only-change-me"

    config["SESSION_COOKIE_HTTPONLY"] = True
    config["SESSION_COOKIE_SAMESITE"] = "Lax"
    config["SESSION_COOKIE_SECURE"] = environment == "production"
