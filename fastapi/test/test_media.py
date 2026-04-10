import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import app
from app.db import Base, get_db  # 导入 Base 和 get_db
from app.models.media import Media, FileNode
from app.config import Config


class TestMedia(unittest.TestCase):
    def setUp(self):
        # 创建测试专用的内存数据库
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        
        # 使用 Base 创建所有表
        Base.metadata.create_all(bind=self.engine)
        
        # 创建测试会话
        self.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # 覆盖 get_db 依赖，使用测试数据库
        def override_get_db():
            db = self.TestingSessionLocal()
            try:
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

    def test_scan(self):
        response = self.client.post('/media/scan', json={'media_root': Config.MEDIA_DIR})
        self.assertEqual(response.status_code, 200)
        data = response.json()  # FastAPI 使用 .json() 而不是 .get_json()
        self.assertIn('msg', data)
        self.assertEqual(data['msg'], 'scan_complete')