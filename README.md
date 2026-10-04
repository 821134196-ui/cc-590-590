# 企业招聘背调授权与结果封存系统

招聘专员在**候选人同意**后发起背景调查；合作机构回传结果；合规人员处理异常；
候选人可清楚知悉**调查项目、结果可见人、授权期限**，并可随时撤回授权。

- 后端：Python · FastAPI · SQLAlchemy 2 · SQLite
- 前端：Vue 3（免构建，静态页由 FastAPI 托管）
- 外部机构接口、通知接口均为**本地模拟**（机构账号回传 + 站内通知表）
- 一条命令启动，无需外部服务

## 快速开始

```bash
./run.sh          # 启动后访问 http://localhost:8000  （端口可用 PORT=9000 ./run.sh）
./run.sh test     # 运行 19 项权限/流程测试
```

首次运行会自动安装 Python 依赖（用户目录）并把 Vue 运行时缓存到 `frontend/vendor/`。
SQLite 数据文件位于 `backend/data/backcheck.db`，删除即重置演示数据。

## 演示账号（顶栏切换，本地模拟登录）

| 账号 | 角色 |
|---|---|
| cand_li / cand_wang | 候选人（李明 / 王芳） |
| rec_zhao / rec_sun | 招聘专员（赵倩 / 孙磊） |
| comp_zhou / comp_wu | 合规人员（周敏 / 吴昊） |
| ag_dingxin / ag_anjian | 两家合作机构操作员 |

## 推荐演示路径

1. **赵倩（招聘）**→「拟定候选人授权」：勾选调查项目（如身份、学历、工作履历）、
   指定完整材料可见人（如周敏）、授权期限 30 天 → 生成授权。
2. **赵倩**→「发起背调」：只能勾选授权范围内的项目（超范围在后端强制拦截，
   返回 `OUT_OF_SCOPE`）→ 选择鼎信机构下发。
3. **鼎信机构**→ 打开任务 →「填充模拟数据」→ 回传；再次点回传即记为
   **重复回传**（不覆盖原结果，时间线留痕）。
4. **赵倩** 查看结果：默认**脱敏**，身份证号/薪酬等显示 `******`；
   点「完整材料」会被拒绝（`FULL_MATERIAL_DENIED`）；她没有「原始回执」按钮。
5. **周敏（合规）**：脱敏/完整/原始回执三级均可看；**每次查看原始回执写访问记录**，
   招聘/候选人尝试查看原始回执的拒绝记录也在「访问记录」中可见。
6. **赵倩** 对异常结果「登记异常结论」（须填依据）→ 招聘无权批准；
   切到 **周敏** 批准；若异常是合规本人登记的（如吴昊登记），
   吴昊自己批准会被拒（`SELF_APPROVAL`，回避原则），须另一名合规处理。
7. **李明（候选人）**：查看本人脱敏结果 → 对字段（如工作履历·薪酬）申请更正 →
   **周敏**核实批准 → 结果中呈现更正后值，同时保留原值与更正时间线。
8. **李明**「撤回授权」：赵倩再发起背调被阻止（`CONSENT_WITHDRAWN`）；
   已有背调单**封存**——招聘无法再查看，合规仍可审计、候选人可看本人脱敏版；
   机构对封存单回传也被拒绝。
9. 岗位取消（招聘/合规操作）效果相同：阻止新查询、封存已有结果。
10. 任意背调单点「时间线」可查看：发起 → 回传 → 重复回传 / 异常 / 更正 →
    撤回 / 岗位取消 → 封存的完整链路。

## 权限模型（核心）

| 能力 | 候选人本人 | 发起招聘 | 授权列明可见人 | 合规 | 承办机构 |
|---|---|---|---|---|---|
| 发起背调（仅授权范围内） | ✗ | ✓（仅本人授权） | ✗ | ✗ | ✗ |
| 脱敏结果 | ✓ | ✓ | ✓ | ✓ | ✓（仅本机构单） |
| 完整材料（敏感字段明文） | ✗ | ✗ | ✓ | ✓ | ✗ |
| 机构原始回执（逐次留痕） | ✗ | ✗ | ✗ | ✓ | ✗ |
| 登记异常 | ✗ | ✓ | ✗ | ✓ | ✗ |
| 批准异常（不得自批） | ✗ | ✗ | ✗ | ✓（非提交人） | ✗ |
| 更正申请 / 处理更正 | ✓ 申请 | ✗ | ✗ | ✓ 处理 | ✗ |
| 撤回授权 | ✓ | ✗ | ✗ | ✗ | ✗ |
| 封存后查看 | 仅脱敏 | ✗ | ✗ | ✓ | ✗ |

字段分级见 `backend/app/catalog.py`：每个字段标为 `visible`（招聘相关）或
`sensitive`（与招聘无关的敏感字段，脱敏视图默认隐藏）。

## 关键接口

- `POST /api/consents`、`POST /api/consents/{id}/withdraw`、
  `POST /api/consents/{id}/cancel-position`
- `POST /api/checks`（范围/撤回/到期/岗位取消校验）
- `POST /api/checks/result`（机构回传；重复回传标记保留）
- `GET  /api/checks/{id}/result?view=masked|full|raw`（三级权限，均写访问记录）
- `POST /api/anomalies`、`POST /api/anomalies/{id}/decision`
- `POST /api/corrections`、`POST /api/corrections/{id}/decision`
- `GET  /api/checks/{id}/timeline`、`GET /api/access-logs`、`GET /api/notifications`

所有请求以 `X-User-Id: <用户id>` 头模拟登录。规则违例统一返回
`{"error":{"code":"OUT_OF_SCOPE", ...}}`，主要 code：
`OUT_OF_SCOPE` / `CONSENT_WITHDRAWN` / `CONSENT_EXPIRED` / `POSITION_CANCELLED` /
`FULL_MATERIAL_DENIED` / `RAW_DENIED` / `SELF_APPROVAL` /
`APPROVER_NOT_COMPLIANCE` / `CHECK_SEALED` / `AGENCY_MISMATCH`。

## 目录结构

```
backend/app/
  main.py       # 路由与业务编排
  security.py   # 范围/字段/回避规则（纯函数，便于测试）
  catalog.py    # 调查项目目录与字段敏感分级
  models.py     # SQLAlchemy 模型（授权/背调/结果/异常/更正/访问记录/时间线/通知）
  schemas.py    # Pydantic 模型
  services.py   # 通知与时间线辅助（本地模拟）
  seed.py       # 演示账号种子数据
backend/tests/  # 19 项测试
frontend/       # Vue 3 单页（index.html + app.js + styles.css + vendor/）
run.sh          # 一键启动 / ./run.sh test
```
