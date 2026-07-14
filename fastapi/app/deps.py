

from fastapi import Depends
from typing_extensions import Annotated

from db import get_db


from sqlalchemy.orm import Session


sessionDep = Annotated[Session, Depends(get_db)]

