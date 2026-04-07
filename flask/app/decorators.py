from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from app.models import TokenBlacklist

def jwt_required_with_blacklist(fn):
    """
    带黑名单检查的 JWT 认证装饰器
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # 验证 JWT
        verify_jwt_in_request()
        
        # 检查 token 是否在黑名单中
        jti = get_jwt()['jti']
        blacklisted = TokenBlacklist.query.filter_by(jti=jti).first()
        
        if blacklisted:
            return jsonify({'error': 'Token 已失效'}), 401
        
        return fn(*args, **kwargs)
    
    return wrapper
