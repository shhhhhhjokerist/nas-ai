from copy import error

from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy
from app.config import config

db = SQLAlchemy()
jwt = JWTManager()

def create_app(config_name):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    db.init_app(app)
    jwt.init_app(app)

    from app.routes import auth, media, scan
    app.register_blueprint(auth.bp)
    app.register_blueprint(media.bp)
    app.register_blueprint(scan.bp)

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        print(error)
        return jsonify({'error': '无效的 token'}), 401
    
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({'error': 'token 已过期'}), 401
    
    @jwt.unauthorized_loader
    def unauthorized_callback(error):
        print(error)
        return jsonify({'error': '缺少认证信息'}), 401


    return app