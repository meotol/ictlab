from flask import Flask

from .commands import register_commands
from .config import Config, validate_config
from .db import init_db
from .web.routes import web


def create_app(config_class: type[Config] = Config) -> Flask:
    """Create and configure the ICT Lab Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    validate_config(app.config)
    init_db(app)
    app.register_blueprint(web)
    register_commands(app)
    return app
