from flask import Flask
from .database import init_db
from .routes import register_routes


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = 'change-this-secret-key'
    app.config['DATABASE'] = app.instance_path + '/saveplan.db'

    init_db(app)
    register_routes(app)
    return app
