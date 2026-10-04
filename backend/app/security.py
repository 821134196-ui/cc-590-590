"""鉴权与权限判定。

权限模型(两类结果权限分别控制):
- results:view_masked  查看脱敏结果 —— 授权的 viewers 名单内的招聘专员、全体合规、候选人本人
- results:view_raw     查看原始回执(完整材料)—— 仅合规人员,且每次访问写入 AccessLog
封存(撤回/岗位取消)后:招聘专员一律不可见,合规保留审计查看权(原始回执仍记录)。
"""
import json
import uuid

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import Authorization, SessionToken, User

# 本地模拟机构接口令牌(替代真实机构鉴权)
AGENCY_API_TOKEN = "local-agency-token"


def create_token(db: Session, user: User) -> str:
    token = uuid.uuid4().hex
    db.add(SessionToken(token=token, user_id=user.id))
    db.commit()
    return token


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或缺少访问令牌")
    token = authorization.removeprefix("Bearer ").strip()
    row = db.get(SessionToken, token)
    if row is None:
        raise HTTPException(status_code=401, detail="访问令牌无效")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="当前角色无权执行此操作")
        return user

    return checker


def auth_viewer_ids(auth: Authorization) -> list[int]:
    return json.loads(auth.viewers)


def auth_scope(auth: Authorization) -> list[str]:
    return json.loads(auth.scope)


def can_view_masked(user: User, auth: Authorization) -> bool:
    """脱敏结果查看权。封存后招聘专员不可见,合规保留。"""
    if user.role == "compliance":
        return True
    if user.role == "candidate":
        return auth.candidate is not None and auth.candidate.user_id == user.id
    if user.role == "recruiter":
        if auth.status in ("revoked", "cancelled", "expired"):
            return False  # 已封存:招聘专员不可再查看
        return user.id in auth_viewer_ids(auth)
    return False


def can_view_raw(user: User, auth: Authorization) -> bool:
    """原始回执(完整材料)查看权:仅合规人员,独立于脱敏权限控制。"""
    return user.role == "compliance"


def verify_agency_token(x_agency_token: str | None = Header(default=None)) -> None:
    if x_agency_token != AGENCY_API_TOKEN:
        raise HTTPException(status_code=401, detail="机构令牌无效")
