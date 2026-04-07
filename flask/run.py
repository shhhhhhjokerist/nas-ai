import os

from app import create_app
from flask_script import Manager, Shell
from flask_migrate import Migrate, MigrateCommand

from app.models.media import Media
from app.models.user import User
from app import db

app = create_app(os.getenv('FLASK_CONFIG') or 'default')
manager = Manager(app)
    

def make_shell_context():
    return dict(app=app, db=db, User=User, Media=Media)

manager.add_command("shell", Shell(make_context=make_shell_context))
manager.add_command("db", MigrateCommand)

@manager.command 
def test(): 
    """Run the unit tests.""" 
    import unittest 
    tests = unittest.TestLoader().discover('test') 
    unittest.TextTestRunner(verbosity=2).run(tests)


if __name__ == '__main__':
    manager.run()