from flask import Blueprint, request, jsonify
from app.models.user import User
from app.extensions import db
from flask_login import login_user

bp = Blueprint('auth', __name__, url_prefix='/auth')

@bp.route("/login", methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(username=data['username']).first()

    if user and user.password == data["password"]:
        login_user(user)
        return jsonify({"msg": "login_succcess"})
    
    return jsonify({"msg": "login failed"}), 401