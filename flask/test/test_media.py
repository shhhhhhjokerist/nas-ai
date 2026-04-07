import unittest

from app import create_app, db
from app.models.media import Media, FileNode
from app.config import Config

class TestMedia(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_scan(self):
        response = self.client.post('/media/scan', json={'media_root': Config.MEDIA_DIR})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('msg', data)
        self.assertEqual(data['msg'], 'scan_complete')

    