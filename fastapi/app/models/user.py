from datetime import datetime, timezone

import bcrypt

from sqlalchemy import Column, TEXT, INT, BIGINT, DATETIME, INTEGER, BOOLEAN, String
from sqlalchemy.ext.declarative import declarative_base
from app.db import Base

class User(Base):
    __tablename__ = 'users'

    id = Column(INTEGER, primary_key=True)
    username = Column(TEXT(50), unique=True, nullable=False)
    email = Column(TEXT(120), unique=True, nullable=False)
    password_hash = Column(TEXT(128), nullable=False)
    role = Column(TEXT(10), default='user')  # 'user' 或 'admin'
    is_active = Column(BOOLEAN, default=True)
    created_at = Column(DATETIME, default=datetime.utcnow)
    # created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DATETIME, default=datetime.utcnow, onupdate=datetime.utcnow)
    # updated_at = Column(DATETIME, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    def set_password(self, password):
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    
    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }
    
class TokenBlacklist(Base):
    __tablename__ = 'token_blacklist'

    id = Column(INT, primary_key=True)
    jti = Column(TEXT(36), unique=True, nullable=False)
    created_at = Column(TEXT, default=datetime.utcnow)

    def __init__(self, jti):
        self.jti = jti