import json
import ssl
import threading
import urllib.request
import uuid
from pathlib import Path

import certifi

from flask import request

STATS_URL = "https://stats.metol.cloud/api/visit"
SITE_CODE = "ict"
COOKIE_NAME = "metol_visitor_id"
KEY_FILE = Path.home() / ".config" / "metol-stats" / "ict.key"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

_stats_key = None


def get_stats_key():
    global _stats_key

    if _stats_key is None:
        _stats_key = KEY_FILE.read_text(encoding="utf-8").strip()

    return _stats_key


def valid_uuid(value):
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def prepare_visitor():
    if request.method != "GET":
        return None

    if "text/html" not in request.headers.get("Accept", ""):
        return None

    hostname = request.host.split(":", 1)[0].lower()
    if hostname != "ict.metol.cloud":
        return None

    visitor_id = request.cookies.get(COOKIE_NAME)

    if valid_uuid(visitor_id):
        return visitor_id, False

    return str(uuid.uuid4()), True


def _send_visit(visitor_id):
    try:
        payload = json.dumps({
            "site": SITE_CODE,
            "visitorId": visitor_id,
        }).encode("utf-8")

        req = urllib.request.Request(
            STATS_URL,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-stats-key": get_stats_key(),
                "User-Agent": "Mozilla/5.0",
            },
        )

        with urllib.request.urlopen(req, timeout=3, context=SSL_CONTEXT):
            pass
    except Exception as error:
        print(f"Stats visit failed: {error}")


def record_visit(visitor_id):
    threading.Thread(
        target=_send_visit,
        args=(visitor_id,),
        daemon=True,
    ).start()
