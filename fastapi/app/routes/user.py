

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException

from app.models.user import User
from db import get_db
from fastapi.app.jwt_helper import AuthJWT

from models import user


router = APIRouter(prefix="/user", tags=["user"])


def get_current_user(session: Session = Depends(get_db), authorize: AuthJWT = Depends()):
    authorize.jwt_required()
    current_user_id = authorize.get_jwt_subject()

    user = session.get(User, int(current_user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Invalid user")
    return user


def get_current_admin(session: Session = Depends(get_db), authorize: AuthJWT = Depends()):
    user = get_current_user(session, authorize)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    return user
    

@router.get("/users", Depends(get_current_admin))
def get_users(sesssion: Session = Depends(get_db), offset: int = 0, limit: int = 10, authorize: AuthJWT = Depends()):
    users = sesssion.query(User).offset(offset).limit(limit).all()
    return {"users": [u.to_dict() for u in users]}


@router.post("/", Depends(get_current_admin))
def create_user(session: Session = Depends(get_db), user_in: user.UserCreate = Depends()):
    new_user = User(
        username=user_in.username,
        email=user_in.email,
        role=user_in.role,
        is_active=user_in.is_active
    )
    new_user.set_password(user_in.password)
    session.add(new_user)
    session.commit()
    return {"user": new_user.to_dict()}


@router.patch("/me")
def update_current_user(session: Session = Depends(get_db), user_in: user.UserUpdateMe = Depends(), current_user: User = Depends(get_current_user)):
    current_user.username = user_in.username
    current_user.email = user_in.email
    session.commit()
    return {"user": current_user.to_dict()}


@router.patch("/me/password")
def update_password(session: Session = Depends(get_db), user_in: user.UserUpdatePassword = Depends(), current_user: User = Depends(get_current_user)):
    if not current_user.check_password(user_in.old_password):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    current_user.password_hash_old = current_user.password_hash
    current_user.set_password(user_in.new_password)
    session.commit()
    return {"msg": "Password updated successfully"}


@router.get("/me")
def get_current_user_info(current_user: User = Depends(get_current_user)):
    return {"user": current_user.to_dict()}


@router.delete("me")
def delete_current_user(session: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session.delete(current_user)
    session.commit()
    return {"msg": "User deleted successfully"}


@router.patch("/{user_id}", Depends(get_current_admin))
def update_user(user_id: int, session: Session = Depends(get_db), user_in: user.UserUpdate = Depends()):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.username = user_in.username
    user.email = user_in.email
    user.role = user_in.role
    user.is_active = user_in.is_active
    session.commit()
    
    return {"user": user.to_dict()}


@router.delete("/{user_id}", Depends(get_current_admin))
def delete_user(user_id: int, session: Session = Depends(get_db)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    session.delete(user)
    session.commit()
    
    return {"msg": "User deleted successfully"}
