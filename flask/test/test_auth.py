import unittest

from app import create_app, db
from app.models.user import User, TokenBlacklist

class TestAuth(unittest.TestCase):
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

    def test_register_login(self):
        data = {
            'username': 'testuser',
            'email': 'testuser@example.com',
            'password': 'testpassword'
        }

        response = self.client.post('/auth/register', json=data)
        self.assertEqual(response.status_code, 201)
        self.assertIn('msg', response.get_json())
        self.assertEqual(response.get_json()['msg'], 'user created successfully')

        response = self.client.post('/auth/login', json={
            'username': 'testuser',
            'password': 'testpassword'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('msg', response.get_json())
        self.assertEqual(response.get_json()['msg'], 'login successful')

        access_token = response.get_json().get('access_token')
        
        new_password = 'newpassword'
        response = self.client.post('/auth/change-password', json={
            'old_password': 'testpassword',
            'new_password': new_password
        }, headers={'Authorization': f'Bearer {access_token}'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('msg', response.get_json())
        self.assertEqual(response.get_json()['msg'], 'password changed successfully')

