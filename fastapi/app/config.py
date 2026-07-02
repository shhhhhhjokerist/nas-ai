import os
basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'data.sqlite')

    MEDIA_DIR = os.environ.get('MEDIA_DIR') or 'F:\\movies'   # NAS 主目录

    # ── RAG / Document Indexing ──
    # 文档扫描复用 MEDIA_DIR（NAS 主目录），不再单独设置 DOCUMENTS_DIR
    CHROMA_DB_DIR = os.environ.get('CHROMA_DB_DIR') or \
        os.path.join(os.path.dirname(basedir), 'chroma_db')
    EMBEDDING_MODEL_NAME = os.environ.get('EMBEDDING_MODEL') or 'BAAI/bge-small-zh-v1.5'
    CHUNK_SIZE = int(os.environ.get('CHUNK_SIZE') or '500')
    CHUNK_OVERLAP = int(os.environ.get('CHUNK_OVERLAP') or '50')
    RETRIEVAL_TOP_K = int(os.environ.get('RETRIEVAL_TOP_K') or '5')

    @staticmethod
    def init_app(app):
        pass


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'data-dev.sqlite')


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or \
        'sqlite://'


class ProductionConfig(Config):
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'data.sqlite')


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
