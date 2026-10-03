from collections.abc import Callable
from functools import wraps
import secrets
from urllib.parse import urlsplit

from flask import abort, redirect, request, session, url_for


def admin_login_required(view: Callable):
    """Require a server-verified administrator session."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("web.admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf() -> None:
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not secrets.compare_digest(expected, supplied):
        abort(400)


def safe_next_url(value: str | None) -> str:
    if value:
        parsed = urlsplit(value)
        if not parsed.scheme and not parsed.netloc and value.startswith("/"):
            return value
    return url_for("web.admin_content_new")
