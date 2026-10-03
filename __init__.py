from flask import Flask

from .commands import register_commands
from .config import Config, validate_config
from .db import init_db
from .web.routes import web
from .stats import prepare_visitor, record_visit


def create_app(config_class: type[Config] = Config) -> Flask:
    """Create and configure the ICT Lab Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    validate_config(app.config)
    init_db(app)
    app.register_blueprint(web)
    register_commands(app)

    @app.after_request
    def track_visitor(response):
        visitor = prepare_visitor()

        if visitor:
            visitor_id, is_new = visitor
            record_visit(visitor_id)

            if is_new:
                response.set_cookie(
                    "metol_visitor_id",
                    visitor_id,
                    max_age=315360000,
                    httponly=True,
                    secure=True,
                    samesite="Lax",
                )

        return response

    return app
