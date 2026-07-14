
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import app
from app.models.user import User, TokenBlacklist
from app.db import Base, get_db


class TestUser(unittest.TestCase):
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
        
        # Admin
        admin_user = User(
            username="admin",
            email="admin@example.com",
            role="admin",
            is_active=True
        )
        admin_user.set_password("adminpassword")
        db = self.TestingSessionLocal()
        db.add(admin_user)
        db.commit()
        db.close()

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
    
    def test_create_user(self):
        from app.models.user import UserCreate
        user_in = UserCreate()
        user_in.username = "testuser"
        user_in.email = "testuser@example.com"
        user_in.password = "testpassword"
        user_in.role = "user"
        user_in.is_active = True

        response = self.client.post("/user/", json=user_in.model_dump())
        self.assertEqual(response.status_code, 200)

    def test_get_users(self):
        response = self.client.get("/user/users")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()