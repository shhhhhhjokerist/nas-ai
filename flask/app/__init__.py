from flask import Flask
from .extensions import db, login_manager

def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')
    
    db.init_app(app)
    login_manager.init_app(app)

    from app.routes import auth, media, scan
    app.register_blueprint(auth.bp)
    app.register_blueprint(media.bp)
    app.register_blueprint(scan.bp)

    return app