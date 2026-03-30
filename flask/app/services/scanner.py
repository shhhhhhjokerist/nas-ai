import os
from app.models.media import Media
from app.extensions import db

MEDIA_EXTENSIONS = ['.mp4', '.mkv', '.avi']

def scan_directory(path):
    new_files = []
    
    for root, _, files in os.walk(path):
        for file in files:
            if any(file.endswith(ext) for ext in MEDIA_EXTENSIONS):
                full_path = os.path.join(root, file)

                exists = Media.query.filter_by(file_path=full_path).first()
                if not exists:
                    media = Media(
                        title=file,
                        file_path=full_path,
                        media_type='video'
                    )
                    db.session.add(media)
                    new_files.append(full_path)

    db.session.commit()
    return new_files
