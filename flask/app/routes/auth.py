from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, 
    create_refresh_token,
    jwt_required, 
    get_jwt_identity,
    get_jwt
)
from app.models.user import User, TokenBlacklist
from app import db
from flask_login import login_user, logout_user, login_required, current_user

from datetime import timedelta
import re

bp = Blueprint('auth', __name__, url_prefix='/auth')

def validate_email(email):
    """ 验证邮箱格式 """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_username(username):
    """ 验证用户名格式 """
    pattern = r'^[a-zA-Z0-9_]{3,20}$'
    return re.match(pattern, username) is not None

@bp.route("/register", methods=['POST'])
def register():
    """ 
    注册
    username email password
    """
    try:
        data = request.get_json()
        if not all(k in data for k in ("username", "email", "password")):
            return jsonify({"msg": "missing required fields"}), 400

        username = data['username']
        email = data['email']
        password = data['password']

        if not validate_username(username):
            return jsonify({"msg": "invalid username format"}), 400
        
        if not validate_email(email):
            return jsonify({"msg": "invalid email format"}), 400
        
        if User.query.filter_by(username=username).first():
            return jsonify({"msg": "username already exists"}), 400
        
        if User.query.filter_by(email=email).first():
            return jsonify({"msg": "email already exists"}), 400
        
        user = User(username=username, email=email)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        return jsonify({
            "msg": "user created successfully",
            "user": user.to_dict()
            }), 201
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@bp.route("/login", methods=['POST'])
def login():
    """
    登录
    username/email password
    """

    try:
        data = request.get_json()
        if not all(k in data for k in ("username", "password")):
            return jsonify({"msg": "missing required fields"}), 400

        identifier = data['username']
        password = data['password']

        user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
        if user is None or not user.check_password(password):
            return jsonify({"msg": "invalid username/email or password"}), 401
        
        if not user.is_active:
            return jsonify({"msg": "account is inactive"}), 403
        
        access_token = create_access_token(
            identity=str(user.id),
            expires_delta=timedelta(hours=24)
        )
        refresh_token = create_refresh_token(
            identity=str(user.id),
            expires_delta=timedelta(days=30)
        )

        return jsonify({
            "msg": "login successful",
            "access_token": access_token,
            "refresh_token": refresh_token,
            'user': user.to_dict()
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route("/refresh", methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """
    刷新 token
    refresh_token to get new access_token
    """
    try:
        current_user_id = get_jwt_identity()

        user = User.query.get(current_user_id)
        if not user or not user.is_active:
            return jsonify({"msg": "account does not exist or is inactive"}), 403
        
        new_access_token = create_access_token(
            identity=str(current_user_id),
            expires_delta=timedelta(hours=24)
        )

        return jsonify({
            "msg": "token refreshed successfully",
            "access_token": new_access_token
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@bp.route("/me", methods=['POST'])
@jwt_required()
def get_current_user():
    """
    获取当前用户信息
    access_token to get user info
    """
    try:
        current_user_id = get_jwt_identity()

        user = User.query.get(current_user_id)
        if not user or not user.is_active:
            return jsonify({"msg": "account does not exist or is inactive"}), 403
        
        return jsonify({
            "msg": "user info retrieved successfully",
            "user": user.to_dict()
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@bp.route("/logout", methods=['POST'])
@jwt_required()
def logout():
    """
    退出登录
    access_token to logout
    """
    try:
        jti = get_jwt()['jti']

        db.session.add(TokenBlacklist(jti=jti))
        db.session.commit()

        return jsonify({"msg": "logout successful"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@bp.route("/change-password", methods=['POST'])
@jwt_required()
def change_password():
    """
    修改密码
    old_password new_password
    """
    try:
        data = request.get_json()
        if not all(k in data for k in ("old_password", "new_password")):
            return jsonify({"msg": "missing required fields"}), 400
        
        old_password = data['old_password']
        new_password = data['new_password']

        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not user or not user.is_active:
            return jsonify({"msg": "account does not exist or is inactive"}), 403
        
        if not user.check_password(old_password):
            return jsonify({"msg": "old password is incorrect"}), 401
        
        if old_password == new_password:
            return jsonify({"msg": "new password cannot be the same as old password"}), 400
        
        user.set_password(new_password)
        db.session.commit()
        return jsonify({"msg": "password changed successfully"}), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
