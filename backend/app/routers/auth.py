"""登录与当前用户。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import LoginIn, UserOut
from ..security import create_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or user.password != body.password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(db, user)
    return {"token": token, "user": UserOut.model_validate(user)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/demo-users", response_model=list[UserOut])
def demo_users(db: Session = Depends(get_db)):
    """本地演示:列出可登录账号(机构角色除外,机构走令牌接口)。"""
    return db.query(User).filter(User.role != "agency").order_by(User.id).all()
