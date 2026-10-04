"""演示种子数据：两家机构、候选人、两位招聘、两位合规。"""
from datetime import timedelta
from sqlalchemy.orm import Session

from .database import Base, engine
from .models import User, Agency, utcnow


def init_db():
    Base.metadata.create_all(engine)


def seed(db: Session):
    if db.query(User).count() > 0:
        return

    a1 = Agency(name="鼎信背调服务有限公司", contact="service@dingxin.example")
    a2 = Agency(name="安鉴征信调查中心", contact="ops@anjian.example")
    db.add_all([a1, a2])
    db.flush()

    users = [
        User(username="cand_li",  display_name="候选人·李明", role="candidate"),
        User(username="cand_wang", display_name="候选人·王芳", role="candidate"),
        User(username="rec_zhao", display_name="招聘专员·赵倩", role="recruiter"),
        User(username="rec_sun",  display_name="招聘专员·孙磊", role="recruiter"),
        User(username="comp_zhou", display_name="合规·周敏", role="compliance"),
        User(username="comp_wu",   display_name="合规·吴昊", role="compliance"),
        User(username="ag_dingxin", display_name="鼎信机构操作员", role="agency", agency_id=a1.id),
        User(username="ag_anjian",  display_name="安鉴机构操作员", role="agency", agency_id=a2.id),
    ]
    db.add_all(users)
    db.commit()
