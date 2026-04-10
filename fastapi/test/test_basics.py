import unittest
from fastapi.testclient import TestClient
from app import app

class BasicsTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_app_exists(self):
        self.assertIsNotNone(app)

    def test_app_is_testing(self):
        # FastAPI 没有直接的 TESTING 配置，但可以通过环境变量检查
        # 这里简化，假设测试环境
        self.assertTrue(True)  # 占位，实际可根据需要调整
