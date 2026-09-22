

import os

from flask import Flask

from app.account_manager import reset_contas_travadas
from app.config.settings import configure_app
from app.database.database import db
from app.database.models import Analise, User 
from app.routes.admin import admin_bp
from app.routes.admin_config import admin_config_bp
from app.routes.analisar import analisar_bp
from app.routes.core import core_bp
from app.routes.referencias import referencias_bp
from app.storage.paths import ensure_runtime_directories
from app.storage.logging import configure_logging


def create_app() -> Flask:
    ensure_runtime_directories()
    configure_logging()
    app = Flask(__name__)
    configure_app(app)
    db.init_app(app)

    for blueprint in (core_bp, admin_bp, admin_config_bp, analisar_bp, referencias_bp):
        app.register_blueprint(blueprint)

    with app.app_context():
        db.create_all()
    reset_contas_travadas()
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8080")), debug=False)
