"""种子数据:演示账号、候选人、岗位。

演示账号(密码均为 123456):
- recruiter1 / recruiter2  招聘专员
- compliance1 / compliance2 合规人员
- candidate1 / candidate2  候选人
机构接口使用令牌 X-Agency-Token: local-agency-token
"""
from datetime import datetime, timedelta

from .database import Base, SessionLocal, engine
from .models import Authorization, Candidate, Position, User

USERS = [
    ("recruiter1", "王招聘", "recruiter"),
    ("recruiter2", "李招聘", "recruiter"),
    ("compliance1", "赵合规", "compliance"),
    ("compliance2", "钱合规", "compliance"),
    ("candidate1", "张候选", "candidate"),
    ("candidate2", "刘候选", "candidate"),
    ("agency", "本地模拟背调机构", "agency"),
]

CANDIDATES = [
    ("candidate1", "张候选", "110101199501012345", "13800001111", "zhang@example.com"),
    ("candidate2", "刘候选", "310104199302026789", "13900002222", "liu@example.com"),
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return
        users: dict[str, User] = {}
        for username, name, role in USERS:
            u = User(username=username, password="123456", name=name, role=role)
            db.add(u)
            users[username] = u
        db.flush()

        for username, name, id_number, phone, email in CANDIDATES:
            db.add(
                Candidate(
                    user_id=users[username].id,
                    name=name,
                    id_number=id_number,
                    phone=phone,
                    email=email,
                )
            )
        db.flush()

        p1 = Position(title="高级后端工程师", department="技术部", recruiter_id=users["recruiter1"].id)
        p2 = Position(title="财务经理", department="财务部", recruiter_id=users["recruiter1"].id)
        db.add_all([p1, p2])
        db.flush()

        # 一份待同意的授权示例,方便登录后立刻看到授权页
        import json

        db.add(
            Authorization(
                candidate_id=1,
                position_id=p1.id,
                recruiter_id=users["recruiter1"].id,
                scope=json.dumps(["identity", "education", "employment"]),
                viewers=json.dumps([users["recruiter1"].id, users["compliance1"].id]),
                expires_at=datetime.utcnow() + timedelta(days=30),
            )
        )
        db.commit()
        print("[seed] 演示数据已初始化(账号密码均为 123456)")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
