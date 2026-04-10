import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import app
from app.models.user import User, TokenBlacklist
from app.db import Base, get_db

class TestAuth(unittest.TestCase):
    def setUp(self):
        # 创建测试专用的内存数据库
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        
        # 创建所有表
        Base.metadata.create_all(bind=self.engine)
        
        # 创建测试会话
        self.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # 覆盖依赖注入，使用测试数据库
        def override_get_db():
            try:
                db = self.TestingSessionLocal()
                yield db
            finally:
                db.close()
        
        app.dependency_overrides[get_db] = override_get_db
        
        # 创建测试客户端
        self.client = TestClient(app)
    
    def tearDown(self):
        # 清理数据库
        Base.metadata.drop_all(bind=self.engine)
        # 清除依赖覆盖
        app.dependency_overrides.clear()
    
    def test_register_login(self):
        data = {
            'username': 'testuser',
            'email': 'testuser@example.com',
            'password': 'testpassword'
        }

        response = self.client.post('/auth/register', json=data)
        self.assertEqual(response.status_code, 201)
        self.assertIn('msg', response.json())
        self.assertEqual(response.json()['msg'], 'User created successfully')

        response = self.client.post('/auth/login', json={
            'username': 'testuser',
            'password': 'testpassword'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('msg', response.json())
        self.assertEqual(response.json()['msg'], 'login successful')

        access_token = response.json().get('access_token')
        
        new_password = 'newpassword'
        response = self.client.post('/auth/change-password', json={
            'old_password': 'testpassword',
            'new_password': new_password
        }, headers={'Authorization': f'Bearer {access_token}'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('msg', response.json())
        self.assertEqual(response.json()['msg'], 'Password changed')