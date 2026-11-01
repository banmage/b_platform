# b_platform

**通用业务底座平台（控制面）**  
**版本：V2.0 设计基线（待评审）**  
**技术基线：PostgreSQL 16+ / Go / 模块化单体 / 扩展模块 SPI / 独立控制面**

---

## 1. 项目定位

`b_platform` 是一个独立开发、独立部署、独立演进的**业务基础平台**。

它不是一个行业应用，也不是某个项目的根组织，而是多个业务系统共同依赖的**控制面（Control Plane）**：

- 租户（Tenant）
- 用户与身份认证（Identity）
- 组织目录（Organization Directory）
- 成员关系（Membership）
- 角色与权限（RBAC / Scope）
- 审计（Audit）
- 平台配置（Platform Config）
- 扩展模块注册（Extension Registry）
- 服务账号与 API Key（Service Account）
- 事件出口（Outbox / Webhook）

它不负责：

- 资源目录、资源发布
- 预订/预约
- 论坛
- 计费/结算
- 行业业务数据

这些能力由 Bufaa、Tufaa、MuPlan 或后续项目作为**扩展模块/独立服务**实现。

---

## 2. 核心架构决定

| 编号 | 决策 | 说明 |
|---|---|---|
| ADR-001 | PostgreSQL 16+ | 使用 RLS、部分唯一索引、JSONB、`SECURITY DEFINER`、`FOR UPDATE` 等能力 |
| ADR-002 | Go 1.23+ | 与 Bufaa/Tufaa 技术栈对齐；`pgx` + `sqlc`；单二进制部署 |
| ADR-003 | 模块化单体 | 先单体，模块边界清晰；后续可按模块拆分服务 |
| ADR-004 | 独立控制面 | Platform 不是根组织，不进入租户组织树 |
| ADR-005 | Tenant 与 Organization 解耦 | Tenant 是数据隔离边界，Organization 是租户内的业务组织 |
| ADR-006 | 扩展模块 SPI | 核心不硬编码资源、预订、论坛等业务域 |
| ADR-007 | UUIDv7 | 对外 ID 使用 UUIDv7，避免雪花 ID 协调和 JS `int64` 精度问题 |
| ADR-008 | 不使用 `BYPASSRLS` / 不用 GUC 做授权 | 跨租户访问通过独立数据库角色 + 租户上下文 + 审计 |
| ADR-009 | API-first | OpenAPI 3.1；`/api/v1` 与 `/api/platform/v1` |
| ADR-010 | 核心最小化 | 核心只做控制面；业务能力通过扩展模块接入 |

详细决策见 [`docs/00-architecture/decisions-v2.0.md`](docs/00-architecture/decisions-v2.0.md)。

---

## 3. 架构关系

```text
                    ┌──────────────────────────────────┐
                    │            b_platform            │
                    │          Control Plane           │
                    │                                  │
                    │  Tenant / Identity / Org         │
                    │  Membership / RBAC / Audit       │
                    │  Config / Extension Registry     │
                    │  Service Account / Outbox        │
                    └───────────────┬──────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
       ┌─────────────┐       ┌─────────────┐       ┌─────────────┐
       │   Bufaa     │       │   Tufaa     │       │   MuPlan    │
       │ 行业应用     │       │ 业务内核     │       │ 调度内核     │
       └─────────────┘       └─────────────┘       └─────────────┘
```

集成方式：

- OpenAPI / REST
- JWT + JWKS
- Webhook / Outbox 事件
- Service Account / API Key
- 不共享数据库，不直接读对方表

---

## 4. 文档地图

| 文档 | 内容 |
|---|---|
| [`docs/00-architecture/architecture-v2.0.md`](docs/00-architecture/architecture-v2.0.md) | 总体架构、控制面/数据面、模块边界 |
| [`docs/00-architecture/decisions-v2.0.md`](docs/00-architecture/decisions-v2.0.md) | ADR-001 ~ ADR-010 |
| [`docs/00-architecture/extension-spi-v2.0.md`](docs/00-architecture/extension-spi-v2.0.md) | 扩展模块 SPI、生命周期、权限/路由/迁移注册 |
| [`docs/00-architecture/pre-review-decisions-v2.0.md`](docs/00-architecture/pre-review-decisions-v2.0.md) | 设计预评审决议记录（D-01~D-11，正式评审接口） |
| [`docs/10-requirements/requirements-v2.0.md`](docs/10-requirements/requirements-v2.0.md) | V2.0 需求规格 |
| [`docs/20-design/tech-design-v2.0.md`](docs/20-design/tech-design-v2.0.md) | Go 技术设计、请求生命周期、RLS、模块边界 |
| [`docs/20-design/database-design-v2.0.md`](docs/20-design/database-design-v2.0.md) | PostgreSQL DDL、RLS、数据库角色、迁移 |
| [`docs/20-design/permission-model-v2.0.md`](docs/20-design/permission-model-v2.0.md) | 三层权限模型：Platform / Tenant / Organization |
| [`docs/20-design/state-machines-v2.0.md`](docs/20-design/state-machines-v2.0.md) | 租户、组织、成员、角色、转让、扩展状态机 |
| [`docs/20-design/audit-catalog-v2.0.md`](docs/20-design/audit-catalog-v2.0.md) | 审计动作编码唯一清单 |
| [`docs/20-design/event-catalog-v2.0.md`](docs/20-design/event-catalog-v2.0.md) | Outbox/Webhook 事件编码与版本化规则 |
| [`docs/20-design/error-codes-v2.0.md`](docs/20-design/error-codes-v2.0.md) | API 错误码唯一清单与重试语义 |
| [`docs/10-requirements/traceability-v2.0.md`](docs/10-requirements/traceability-v2.0.md) | 61 条 FR → 接口/权限/审计/事件/测试追溯矩阵 |
| [`docs/30-api/openapi-v2.0.yaml`](docs/30-api/openapi-v2.0.yaml) | 核心 OpenAPI 契约 |
| [`docs/40-operations/operations-v2.0.md`](docs/40-operations/operations-v2.0.md) | 部署、运维、测试、安全、SLO |
| [`docs/90-archive/README.md`](docs/90-archive/README.md) | V1.x 历史文档说明 |

V1.x 原始文档未随 V2.0 基线纳入本仓库（归档在项目组外部存储），仅用于追溯，不再作为开发基线；
归档清单与 V2.0 替代关系见 [`docs/90-archive/README.md`](docs/90-archive/README.md)。

**基线一致性门禁（2026-11-01 入库）：** [`scripts/spec-check/`](scripts/spec-check/README.md)
对上述文档做 17 项机器校验（operationId 唯一性、`$ref` 可解析、授权声明覆盖、错误码/事件/权限点
双向对齐、FR 派生关系与追溯、幂等豁免、链接有效性等），CI 见
[`.github/workflows/spec-check.yml`](.github/workflows/spec-check.yml)。运行
`python3 scripts/spec-check/spec_check.py` 即可本地复现。

**清单与契约对齐状态（已机器验证，2026-10-31）：**

- `audit-catalog` / `event-catalog` / `error-codes` / `permission-model` 四份目录为各自编码的**唯一权威清单**，已与状态机、技术设计、数据库设计、追溯矩阵全量核对，编码零游离、属性一致；
- `docs/30-api/openapi-v2.0.yaml` 已机器校验：Problem.code 枚举 41 码与错误码目录零差异；Webhook 订阅走 `WebhookEventType` 白名单、Outbox 行只允许具体编码；全部受保护 operation 声明 `x-permission` 或 `x-subject-authz`（主体式授权）；
- 目录与契约冲突时，以 `docs/20-design/` 四份目录为准，OpenAPI 枚举/白名单为快照——目录升版必须同步契约。

---

## 5. 核心模块

```text
internal/core/
├── tenant/           # 租户生命周期、租户配置
├── identity/         # 用户、认证、会话、密码、验证
├── organization/     # 组织树、审批、冻结、所有权转让
├── membership/       # 租户成员、组织成员、邀请、加入
├── authz/            # 权限点、角色、授权、判定
├── audit/            # 审计写入、查询、导出
├── config/           # 平台参数、租户配置
├── extension/        # 扩展注册表、SPI
├── serviceaccount/   # 服务账号、API Key
└── outbox/           # 事务性事件、Webhook 投递
```

模块规则：

1. 模块之间通过接口/事件协作，不直接访问对方表。
2. 核心模块不依赖任何扩展模块。
3. 扩展模块只能通过 SPI 注册，不修改核心表结构。
4. 所有租户数据表必须包含 `tenant_id` 并启用 RLS。
5. 所有关键审计必须与业务事务同事务写入。

---

## 6. 开发基线

### 6.1 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Go 1.23+ |
| HTTP | `chi` + `huma`（或 `echo`） |
| OpenAPI | 3.1 + `oapi-codegen` |
| 数据库 | PostgreSQL 16+ |
| 数据访问 | `pgx/v5` + `sqlc` |
| 迁移 | `goose` / `atlas` |
| 认证 | `golang-jwt/jwt/v5` / `go-jose`，RS256 + JWKS |
| 密码 | `argon2id` |
| 队列 | `river`（Postgres）或 `asynq`（Redis） |
| 日志 | `slog` + OpenTelemetry |
| 测试 | `testcontainers-go` + `pgTAP` |
| 部署 | Docker + Docker Compose（一期）/ Kubernetes（后续） |

### 6.2 数据库角色

| 角色 | 用途 |
|---|---|
| `platform_migrator` | 迁移、DDL、表所有者，仅迁移任务使用 |
| `platform_auth` | 用户、会话、令牌、登录尝试 |
| `platform_core` | 租户、组织、成员、角色、授权、幂等、Outbox |
| `platform_control` | 平台控制面：平台参数、平台角色授予、扩展、服务账号 |
| `platform_audit_reader` | 审计只读 |

运行时不使用 `BYPASSRLS`。跨租户访问通过 `platform_control` + 目标租户上下文 + 审计实现。

### 6.3 环境要求

- Go 1.23+
- PostgreSQL 16+
- Docker / Docker Compose
- `golangci-lint`
- `sqlc`
- `goose` 或 `atlas`

---

## 7. 版本与兼容

- API 使用 URL 主版本：`/api/v1`、`/api/platform/v1`。
- OpenAPI 契约是唯一 API 权威来源。
- 事件使用版本化 schema（`event_type` + `event_version`）。
- 扩展模块声明 `api_version`，核心按兼容性策略加载。
- 废弃接口使用 `Deprecation` / `Sunset` 响应头，并保留至少一个主版本周期。

---

## 8. 当前状态

**V2.0 设计基线已完成，待评审。** 本文档地图中的设计、接口与运维文档均已落地；V1.x 文档已归档，不再作为开发基线。

- [x] V2.0 架构决策冻结
- [x] 需求、技术、数据库、权限、状态机文档修订
- [x] OpenAPI 核心契约
- [x] V1.x 文档归档与差异说明
- [x] 四份权威清单（审计动作 / 事件 / 错误码 / 权限点）全库对齐与补齐
- [x] OpenAPI 契约机器可校验：`Problem.code` enum（41 码，与错误码目录零差异）、`WebhookEventType` 事件订阅白名单、`405 NOT_SUPPORTED` / `409 STATE_CONFLICT` 语义声明
- [x] 状态机各节“审计动作”概要与审计目录双向同步
- [x] 预评审完成（2026-10-31）：对抗性复核发现的 8 项 P1（ext 命名段数统一、is_dangerous 语义残留×4、13 个主体式操作 `x-subject-authz` 定义、OutboxEvent 通配洞、`archiveOrganization` 端点、one_time_token 撤销语义、force_managed 谓词、Principal 结构体统一）已全部修复并复验
- [ ] 设计基线评审通过（不再重审全库一致性；仅对[预评审决议记录](docs/00-architecture/pre-review-decisions-v2.0.md) D-01~D-11 逐条确认）
- [x] 建立远程 Git 仓库并提交设计基线（决议 D-10，开发启动前）——已完成 2026-11-01，tag `v2.0-design-baseline` 已推送至 `origin`
- [x] 基线一致性校验入库并接入 CI（`scripts/spec-check/`，17 项校验 + 变异自测，2026-11-01）
- [ ] Go 项目骨架
- [ ] 数据库迁移实现
- [ ] 核心模块实现
- [ ] 扩展 SPI 参考实现
- [ ] 与 Bufaa/Tufaa/MuPlan 的接入示例

**下一步：** 完成设计基线评审后，按 `docs/20-design/tech-design-v2.0.md` 创建 Go 项目骨架和 `0001_init.sql` 第一版迁移；评审通过前禁止开始编码。
