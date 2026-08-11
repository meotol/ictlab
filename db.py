from flask import Flask, current_app, g
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for future SQLAlchemy models."""


def init_db(app: Flask) -> None:
    """Initialize one engine and session factory for a Flask application."""
    database_url = app.config.get("DATABASE_URL")
    if not database_url:
        app.extensions["ictlab_db"] = None
        app.teardown_appcontext(close_db_session)
        return

    engine_options = dict(app.config.get("DATABASE_ENGINE_OPTIONS", {}))
    engine_options.setdefault("pool_pre_ping", True)
    engine = create_engine(database_url, **engine_options)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    app.extensions["ictlab_db"] = {
        "engine": engine,
        "session_factory": session_factory,
    }
    app.teardown_appcontext(close_db_session)


def get_db_engine() -> Engine:
    """Return the application engine or fail when the database is unconfigured."""
    database = current_app.extensions.get("ictlab_db")
    if database is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return database["engine"]


def get_db_session() -> Session:
    """Return the SQLAlchemy session owned by the current request/app context."""
    database = current_app.extensions.get("ictlab_db")
    if database is None:
        raise RuntimeError("DATABASE_URL is not configured")

    if "db_session" not in g:
        g.db_session = database["session_factory"]()
    return g.db_session


def close_db_session(exception: BaseException | None = None) -> None:
    """Roll back failed work and close the current context's session."""
    session = g.pop("db_session", None)
    if session is None:
        return
    if exception is not None:
        session.rollback()
    session.close()
