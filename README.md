# 企业招聘背调授权与结果封存系统

招聘专员在候选人同意后发起背景调查,合作机构回传结果,合规人员处理异常,候选人可随时查看调查范围与授权期限并撤回授权。全程留痕:时间线、访问记录、处理依据。

## 一条命令启动

```bash
./start.sh
```

启动后访问 **http://127.0.0.1:8000**(API 文档见 `/docs`)。脚本会自动安装依赖、初始化 SQLite(`backend/bgc.db`)与演示数据、启动 FastAPI(同时托管 Vue 前端,无外网依赖)。

## 演示账号(密码均为 `123456`)

| 账号 | 角色 | 能力 |
|---|---|---|
| `recruiter1` / `recruiter2` | 招聘专员 | 建岗位、发起授权、获批范围内发起查询、看脱敏结果、提交异常结论 |
| `compliance1` / `compliance2` | 合规人员 | 审批异常(留依据)、办结更正、调阅原始回执(留访问记录)、看访问日志 |
| `candidate1` / `candidate2` | 候选人 | 查看授权页(项目/可见人/期限)、同意/撤回授权、申请更正 |
| 机构模拟控制台 | 背调机构 | 页面右上角进入;接口令牌 `X-Agency-Token: local-agency-token` |

## 核心规则

- **授权页明示**:调查项目、哪些人能看结果、到期时间;候选人同意后授权才生效。
- **范围管控**:招聘专员只能发起获批范围内的查询,超范围返回 403。
- **撤回即封锁**:候选人撤回后禁止任何新查询,待查单取消,已有结果按权限封存(招聘专员不可见,合规保留审计调阅)。
- **到期即失效**:授权过期自动封存,新查询被拒绝。
- **默认脱敏**:结果页默认隐藏身份证号、手机号、住址、征信分等敏感字段;**原始回执仅合规可查看**,每次访问写入 `access_logs` 并记入时间线。完整材料与脱敏结果两个权限分别控制。
- **职责分离**:任何人不能批准自己提交的异常结论;合规审批必须填写处理依据。
- **全程时间线**:岗位取消、机构重复回传(隔离存档)、候选人更正、封存等事件全部保留。

## 运行测试

```bash
cd backend && python3 -m pytest tests/ -v
```

覆盖:超范围查询、撤回后新查询被阻止、到期阻止、敏感字段脱敏、原始回执权限与访问记录、自审拦截、重复回传隔离、岗位取消级联、更正流转、越权访问。

## 目录结构

```
backend/app/          FastAPI 应用
  ├── models.py       SQLAlchemy 模型(授权/查询/结果/异常/访问记录/时间线/通知)
  ├── security.py     登录令牌 + 两类结果权限判定
  ├── masking.py      敏感字段脱敏
  ├── services.py     时间线 / 本地模拟通知 / 封存
  ├── routers/        auth·positions·authorizations·checks·results·anomalies·corrections·agency·misc
  └── seed.py         演示数据
backend/tests/        pytest 业务规则测试
frontend/             Vue 3 单页(本地 vendor,无构建步骤)
start.sh              一键启动
```

## 外部接口的本地模拟

- **机构接口**:`GET /api/agency/tasks`、`POST /api/agency/results`,请求头 `X-Agency-Token: local-agency-token`;重复回传自动隔离为 duplicate 并留痕。
- **通知接口**:`services.notify()` 落库 `notifications` 表并打印到控制台,前端铃铛可查看。
