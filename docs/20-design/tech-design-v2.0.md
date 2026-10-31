# b_platform 技术设计 V2.0

**项目：** b_platform（通用业务底座平台·控制面）  
**版本：** V2.0  
**状态：** 设计基线（待评审）  
**对应需求：** `docs/10-requirements/requirements-v2.0.md`  
**关联决策：** ADR-001 ~ ADR-010

---

## 1. 文档定位

本文档回答 b_platform “用什么做、怎么组织、怎么保证边界”，是 Go 项目骨架、迁移脚本、Repository、中间件和测试代码的直接依据。

不在本文档重复的内容：

- 业务做什么：见需求规格 V2.0。
- 表结构与索引：见数据库设计 V2.0。
- 权限语义：见权限模型 V2.0。
- 状态转换：见状态机 V2.0。
- API 字段：见 OpenAPI V2.0。

---

## 2. 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 | Go 1.23+ | 不使用泛型滥用；错误显式返回 |
| HTTP 路由 | `chi/v5` | 轻量、标准 `net/http` 兼容 |
| 契约/校验 | `huma/v2` + OpenAPI 3.1 | 请求/响应结构由 Go 类型生成 |
| 数据库 | PostgreSQL 16+ | RLS、部分唯一索引、JSONB |
| 驱动 | `pgx/v5` + `pgxpool` | 原生协议、批量、事务控制 |
| 查询生成 | `sqlc` | SQL-first，禁止运行时拼接 |
| 迁移 | `goose` | 单文件 up/down；生产 expand/contract |
| 认证 | `golang-jwt/jwt/v5` + JWKS | RS256，密钥轮换 |
| 密码 | `argon2id`（`golang.org/x/crypto/argon2`） | 参数见 §6.2 |
| 队列 | `river`（Postgres） | 复用数据库，避免额外中间件 |
| 日志 | `log/slog` | JSON 输出，字段稳定 |
| 可观测 | OpenTelemetry（trace/metric）+ Prometheus | OTLP 导出 |
| 测试 | `testcontainers-go` + `pgTAP` + `testify` | 集成测试必须真实 PostgreSQL |
| 静态检查 | `golangci-lint`、`staticcheck`、`govulncheck` | CI 阻断 |
| 部署 | 多阶段构建 + distroless | 迁移独立 Job |

**明确不用：**

- 重型 ORM（GORM、Ent 生成式隐式查询）。
- 运行时 SQL 字符串拼接（除白名单排序字段）。
- 在请求处理中使用 `SET ROLE` 切换权限。
- 内存数据库（SQLite）替代 PostgreSQL 做隔离测试。

---

## 3. 代码结构

```text
b_platform/
├── cmd/
│   ├── platform/main.go          # API 进程
│   ├── worker/main.go            # Outbox / Webhook / 清理
│   └── migrate/main.go           # 迁移 Job
├── internal/
│   ├── core/
│   │   ├── tenant/
│   │   │   ├── service.go
│   │   │   ├── repository.go      # 接口
│   │   │   ├── postgres.go        # sqlc 实现
│   │   │   └── model.go
│   │   ├── identity/
│   │   ├── organization/
│   │   ├── membership/
│   │   ├── authz/
│   │   ├── audit/
│   │   ├── config/
│   │   ├── extension/
│   │   ├── serviceaccount/
│   │   └── outbox/
│   ├── platform/                  # 组合根
│   │   ├── http/
│   │   │   ├── router.go
│   │   │   ├── middleware/
│   │   │   └── handler/
│   │   ├── db/
│   │   │   ├── pools.go           # 按角色分池
│   │   │   ├── tx.go              # 租户事务
│   │   │   └── context.go
│   │   ├── auth/
│   │   └── config/
│   ├── ext/                       # 编译期扩展模块
│   └── worker/
├── db/
│   ├── migrations/                # goose
│   ├── queries/                   # sqlc 输入
│   ├── sqlc.yaml
│   └── seeds/
├── api/openapi/openapi-v2.0.yaml  # 发布产物：从 docs/30-api 同步，禁止手改
├── deploy/
├── test/
│   ├── integration/
│   ├── rls/
│   └── contract/
└── docs/
```

### 3.1 模块依赖规则

OpenAPI 以 [`docs/30-api/openapi-v2.0.yaml`](../30-api/openapi-v2.0.yaml) 为唯一手写来源；`api/openapi/openapi-v2.0.yaml` 仅在发布时由构建脚本复制生成，不手工维护，避免双份契约漂移。

```text
platform/http  →  core/*/service  →  core/*/repository(interface)
                                            ↓
                                   platform/db (pgx + sqlc)
```

| 规则 | 说明 |
|---|---|
| R1 | `core/*` 不 import 其他模块的 `postgres.go`，只 import 其接口包 |
| R2 | `core/audit` 不被任何业务模块反向依赖；业务模块通过 `audit.Writer` 接口写入 |
| R3 | `core/authz` 可依赖 `identity`、`tenant`、`organization` 的只读接口 |
| R4 | 扩展模块只能 import `core/extension` 暴露的 SPI 包 |
| R5 | Handler 不直接访问 `pgxpool`，只调用 Service |
| R6 | 禁止跨模块 JOIN；需要组合数据时由 Service 编排或建只读视图 |

CI 用 `go list -deps` 或 `depguard` 检查 R1~R5。

---

## 4. 请求生命周期

### 4.1 中间件顺序

```text
Recover
  → RequestID
  → AccessLog
  → Trace（OTel）
  → RateLimit（登录/注册/API Key 路径）
  → BodyLimit
  → Authentication（JWT / API Key / Service Token）
  → Principal（构建调用主体）
  → ScopeResolver（解析 tenant / organization 上下文）
  → MembershipGuard（校验成员关系与状态）
  → PermissionGuard（权限点判定）
  → IdempotencyGuard（关键写操作）
  → Handler
```

**关键约束：**

1. 租户上下文只能由 `ScopeResolver` 依据“已认证主体 + 已验证成员关系”产生，不能直接信任请求头。
2. `X-Tenant-Id` 只是“请求作用域提示”，必须与 Token 中的 `tid` 或平台授权范围交叉校验。
3. 平台入口 `/api/platform/v1` 使用独立 audience 与独立数据库连接池（`platform_control`）。
4. 认证失败返回 `401`，权限不足返回 `403`，作用域不存在或不可见统一返回 `404`，避免枚举。

### 4.2 主体与作用域

```go
type Principal struct {
    Type             PrincipalType // USER | SERVICE_ACCOUNT | SYSTEM
    ID               uuid.UUID
    Audience         Audience      // USER | PLATFORM | SERVICE
    PermissionVersion PermissionVersion // u/t/m/o/om 五层拆分，结构见权限模型 §6
    SessionID        uuid.UUID
    Scopes           []string      // 服务账号 OAuth scope
}

type Scope struct {
    TenantID       *uuid.UUID
    OrganizationID *uuid.UUID
    IsPlatform     bool
    GrantIDs       []uuid.UUID // 命中的平台授权
}
```

- `Scope` 由服务端解析，不进入客户端可写字段。
- Handler 只能通过 `platform/request.ScopeFrom(ctx)` 读取，禁止从 `context.Value` 取任意字符串。
- 平台跨租户操作在 `Scope` 中带 `IsPlatform=true` 与目标 `TenantID`，并在事务内写审计。

### 4.3 请求到事务

```text
Handler
  → Service (业务校验、权限二次判定)
  → db.WithTenantTx(ctx, tenantID, func(tx pgx.Tx) error {
        repo := postgres.New(tx)
        ... 业务写入 ...
        audit.Write(ctx, tx, event)
        outbox.Enqueue(ctx, tx, event)
        return nil
    })
```

- 每个请求最多一个写事务；读请求使用只读事务或直连（仍带租户上下文）。
- 事务内所有 Repository 必须使用同一个 `pgx.Tx`，禁止从池中另取连接。
- 事务提交后不写审计、不发事件：二者必须同事务。
- 重试只允许对幂等操作，且使用新事务。

---

## 5. 数据库访问与 RLS

### 5.1 连接池按角色拆分

```go
type Pools struct {
    Auth    *pgxpool.Pool // platform_auth
    Core    *pgxpool.Pool // platform_core
    Control *pgxpool.Pool // platform_control
    Audit   *pgxpool.Pool // platform_audit_reader（只读）
}
```

| 池 | 角色 | 使用范围 |
|---|---|---|
| Auth | `platform_auth` | 注册、登录、刷新、验证、会话 |
| Core | `platform_core` | 租户内业务：组织、成员、角色、配置、审计写入 |
| Control | `platform_control` | `/api/platform/v1`：租户管理、平台授权、扩展、服务账号 |
| Audit | `platform_audit_reader` | 平台审计查询（只读） |

- 每个池独立 `MaxConns`，避免平台批量任务挤占业务连接。
- 池初始化时执行 `SET application_name`，便于 `pg_stat_activity` 审计。
- 禁止跨池事务。

### 5.2 租户事务上下文

```go
func WithTenantTx(ctx context.Context, pool *pgxpool.Pool, tenantID uuid.UUID, fn func(pgx.Tx) error) error {
    tx, err := pool.BeginTx(ctx, pgx.TxOptions{})
    if err != nil {
        return err
    }
    defer tx.Rollback(ctx)

    if _, err := tx.Exec(ctx,
        `SELECT set_config('app.tenant_id', $1, true)`, tenantID.String()); err != nil {
        return err
    }
    if err := fn(tx); err != nil {
        return err
    }
    return tx.Commit(ctx)
}
```

规则：

1. 只用 `set_config(..., true)`（等价 `SET LOCAL`），事务结束自动失效。
2. 禁止 `SET app.tenant_id = ...`（会话级），防止连接池串租户。
3. 未设置上下文的查询在 RLS 表上返回 0 行，而非报错；服务层必须把“0 行”视为不可见。
4. 平台跨租户操作：`WithTenantTx(controlPool, targetTenantID, ...)`，并在同一事务写 `platform.audit.cross_tenant_access`。
5. 后台任务必须显式传入 `tenantID`，不得从任务 payload 中未校验字段推断。

### 5.3 RLS 与角色边界

- 所有租户表：`ENABLE` + `FORCE ROW LEVEL SECURITY`。
- 策略函数：`app_current_tenant_id()` 读取 `app.tenant_id`。
- 运行时角色全部 `NOBYPASSRLS`。
- `platform_control` 的跨租户能力通过“按表显式策略 + 目标租户上下文”实现，不使用全局绕过。
- 表级授权按表、按操作显式授予，禁止 `GRANT ... ON ALL TABLES`。

详见数据库设计 §5~§7。

### 5.4 SQL 规范

- 所有 SQL 写入 `db/queries/*.sql`，由 `sqlc` 生成。
- 动态条件使用 `sqlc.narg`，不拼接字符串。
- 动态排序字段必须白名单映射，禁止直接拼入 `ORDER BY`。
- 批量写入使用 `pgx.Batch` 或 `CopyFrom`。
- 长事务禁止：单事务目标 < 2s；报表查询走只读副本或离线任务。
- 所有多行锁按固定顺序：`tenant` → `organization`（按 id 排序）→ `membership` → `role`。

---

## 6. 认证与授权

### 6.1 Token 设计

| Token | 形式 | TTL | 说明 |
|---|---|---|---|
| Access Token | JWT RS256 | 15 min | 无状态校验，携带上下文与 `pv` |
| Refresh Token | 随机 256-bit | 30 day | 数据库存 SHA-256 哈希，旋转 |
| Service Token | JWT RS256 | 15 min | `aud=service`，含 `scopes` |
| API Key | 随机 256-bit | 可配置 | 数据库存哈希，仅显示一次 |

Access Token 声明：

```json
{
  "iss": "https://platform.example.com",
  "sub": "0192f0c4-...",
  "aud": "user",
  "jti": "0192f0c5-...",
  "iat": 1767225600,
  "exp": 1767226500,
  "tid": "0192f0c6-...",
  "oid": "0192f0c7-...",
  "mid": "0192f0c8-...",
  "roles": ["tenant_admin"],
  "scopes": ["tenant.member.invite"],
  "pv": { "u": 42, "t": 7, "m": 3, "o": 5, "om": 2 }
}
```

- `aud` 分离：`user`、`platform`、`service`。
- `tid`/`oid`/`mid` 是“当前作用域”，切换作用域需重新签发。
- `roles`/`scopes` 仅用于展示与粗过滤，最终判定以服务端权限计算为准。
- `pv` 是权限版本对象（`u` 用户、`t` 租户、`m` 租户成员、`o` 组织、`om` 组织成员），用于检测各层权限是否过期；语义见权限模型 V2.0 §7.3。

### 6.2 密码与密钥

| 项 | 参数 |
|---|---|
| Argon2id | memory 64 MiB, iterations 3, parallelism 2, salt 16B, key 32B |
| Refresh Token | 32 字节随机，Base64URL；库中存 SHA-256 |
| API Key | 前缀 8 字符明文 + 32 字节随机；库中存 SHA-256 |
| JWT 签名 | RS256，2048-bit 起；`kid` 轮换 |
| Webhook HMAC | HMAC-SHA256，密钥加密存储 |

- 密码哈希升级：登录成功时检测参数版本，必要时 rehash。
- 密钥轮换：JWKS 保留旧公钥至少 2×Access Token TTL。
- 所有密钥通过环境变量/Secret Manager 注入，禁止入库明文、禁止提交仓库。

### 6.3 授权判定

统一入口：

```go
type Authorizer interface {
    Authorize(ctx context.Context, p Principal, s Scope, permission string) error
    EffectivePermissions(ctx context.Context, p Principal, s Scope) (PermissionSet, error)
}
```

判定顺序：

1. 校验 `Principal` 有效、账号/服务账号状态允许。
2. 校验 Token `pv` 与服务端当前 `permission_version`。
3. 校验 `Scope` 与 Token 一致，且成员关系 `ACTIVE`。
4. 合并三层权限：平台授权（范围内）、租户角色、组织角色（当前组织及可选祖先）。
5. 判定权限点是否在集合内；不在则 `403`。
6. 高风险权限（`is_dangerous=true`）语义见权限模型 §8.2：一期仅审计增强；二期启用 step-up（未满足返回 `403 STEP_UP_REQUIRED`）。

禁止：

- `if role == "admin"`。
- 在 SQL 中直接判断角色名。
- 用 `scopes` 声明替代服务端判定。

### 6.4 权限版本（pv）

`platform_user`、`tenant`、`tenant_membership`、`organization`、`organization_membership` 均维护 `permission_version`。

递增时机：

- 成员角色分配/撤销。
- 成员状态变化（邀请接受、暂停、移除）。
- 角色权限变更（影响该角色所有持有者）。
- 平台角色授予/撤销/范围变更。
- 用户禁用/启用。
- 租户冻结/解冻/关闭。
- 组织冻结/解冻/归档。

处理策略：

- Access Token 中 `pv` 各字段小于服务端当前值 → `401 PERMISSION_VERSION_STALE`，客户端刷新 Token。
- 本地权限缓存键包含 `pv` 各字段，版本变化自然失效。
- 缓存 TTL ≤ 60s，仅作为性能优化，不作为正确性来源。

---

## 7. 模块设计要点

### 7.1 tenant

- 负责 `tenant` 生命周期、租户配置、租户级 `permission_version`。
- 创建租户是平台控制面操作，使用 `platform_control` 池，同一事务创建：
  - `tenant`
  - 初始 `tenant_membership`（owner）
  - `tenant_owner` 角色分配
  - 审计 + Outbox
- 冻结租户：置状态 + 递增 `pv` + 审计；不删除数据。
- 租户不物理删除。

### 7.2 identity

- 负责 `platform_user`、`user_session`、`one_time_token`、登录限流。
- 不依赖 organization。
- 登录成功后不直接决定租户上下文；上下文由 `/auth/context/switch` 或登录参数选择。
- 用户禁用时递增 `pv` 并撤销所有会话。

### 7.3 organization

- 负责组织树、闭包表、审批、冻结、所有权转让。
- 父子组织同租户由复合外键保证。
- 闭包表更新在同一事务内完成：插入自身 `(ancestor=self, descendant=self, depth=0)`，再复制父节点祖先。
- 组织创建可配置为“直接创建”或“待审批”，由租户配置 `organization.require_approval` 决定。
- 审批人必须是租户管理员或具备 `tenant.organization.approve` 的成员。

### 7.4 membership

- 负责租户成员与组织成员。
- 组织成员必须先是租户成员：应用层校验 + 数据库复合外键。
- 移除成员使用状态 `INACTIVE`，保留历史；重新加入创建新记录。
- 成员变更递增对应 `permission_version`。

### 7.5 authz

- 负责权限点、角色、角色权限、三层授权与判定。
- 角色分为 `PLATFORM` / `TENANT` / `ORGANIZATION`，由 `role.scope` 与约束保证。
- 所有者角色 `is_owner_role=true`，只能通过所有权转让流程变更。
- 提权防护：操作者有效权限集合必须是目标角色权限集合的超集；平台超级管理员授予统一使用 `platform.role.grant`（权限模型 §8.4），不设专用权限点。
- 扩展权限只允许 `ext.<module>.*`，作用域只能是 `TENANT`/`ORGANIZATION`。

### 7.6 audit

- 提供 `audit.Writer`，只允许事务内写入。
- 审计 `action` 编码以 [审计动作目录](audit-catalog-v2.0.md) 为唯一清单；新增动作必须先更新目录。
- 事件结构固定：`action`、`target_type`、`target_id`、`tenant_id`、`organization_id`、`result`、`request_id`、`detail`。
- 敏感字段在写入前脱敏：密码、Token、密钥、完整手机号/邮箱按策略掩码。
- 审计查询走只读池；租户查询受 RLS，平台查询使用 `platform_audit_reader`。
- 审计写入失败必须使业务事务失败。

### 7.7 config

- 平台参数：`platform_param`，区分 `is_public`。
- 租户配置：`tenant_config`，JSON Schema 校验。
- 配置读取带缓存，TTL ≤ 30s；变更**不写 Outbox 广播**（事件目录 §4.6），仅递增版本/更新时间，缓存按 TTL 或轮询失效。
- 配置项必须有默认值、类型、范围、是否可热更新。

### 7.8 extension

- 启动时加载编译期扩展，读取 `extension_registry` 校验版本与状态。
- 注册权限、路由、迁移、事件、配置 schema。
- 禁用扩展：路由不挂载、事件不投递、权限保留但不可授予新角色（可配置）。
- 扩展迁移由独立 Job 执行，schema 为 `ext_<module>`。
- 扩展不得 import 核心 `postgres` 包。

### 7.9 serviceaccount

- 平台级与租户级服务账号。
- Client Credentials：`client_id` + `client_secret`，签发 `aud=service` Token。
- API Key：仅存哈希，支持前缀检索、过期、撤销、最后使用时间。
- 一期服务账号权限来自显式 `scopes`，不引入服务账号角色绑定；API Key 继承所属服务账号权限。二期如引入绑定角色，按 `scopes ∩ 角色权限` 收敛（见权限模型 §7.2）。

### 7.10 outbox

- 业务事务内写 `outbox_event`；`event_type` 编码以 [事件目录](event-catalog-v2.0.md) 为唯一清单，新增触发点必须同步目录。
- Worker 使用 `FOR UPDATE SKIP LOCKED` 批量取事件。
- 至少一次投递；消费者幂等。
- 失败重试指数退避，超过阈值进入 `DEAD` 并告警。
- Webhook 投递单独记录，HMAC 签名包含时间戳，防重放。

---

## 8. 错误模型

统一 Problem Details 风格，响应结构与错误码定义见 [错误码目录](error-codes-v2.0.md)（唯一权威清单），本文仅保留关键规则：

```json
{
  "type": "https://platform.example.com/problems/permission-denied",
  "title": "Permission denied",
  "status": 403,
  "code": "PERMISSION_DENIED",
  "detail": "Missing permission tenant.member.invite",
  "instance": "/api/v1/tenants/0192.../members",
  "request_id": "0192...",
  "trace_id": "4bf92f..."
}
```

规则：

- 不返回堆栈、SQL、内部表名。
- 资源不存在与无权访问统一 `404`。
- 幂等冲突 `409 IDEMPOTENCY_CONFLICT`。
- 版本冲突 `409 VERSION_CONFLICT` 或 `412 PRECONDITION_FAILED`。
- 限流 `429`，带 `Retry-After`。
- 内部错误 `500`，只记录日志与 trace。

---

## 9. 幂等与并发

### 9.1 幂等

- 关键写接口要求 `Idempotency-Key`。
- 键：`(principal_type, principal_id, endpoint, idem_key)`。
- 首次请求在业务事务内插入 `IN_PROGRESS`，提交前写入响应快照。
- 重复请求同哈希返回原响应；不同哈希返回 `409`。
- 过期时间默认 24h，清理任务删除。

### 9.2 乐观锁

- 可变实体带 `version bigint`（可选）或 `updated_at`。
- 更新语句使用 `WHERE id=$1 AND version=$2`，影响行数为 0 返回 `409`。
- 高风险实体（角色、授权、所有者）强制乐观锁。

### 9.3 悲观锁

- 所有权转让、组织审批、租户冻结使用 `SELECT ... FOR UPDATE`。
- 锁顺序固定，禁止跨表逆序加锁。
- 锁等待超时 `lock_timeout=3s`，失败返回 `409 CONCURRENT_MODIFICATION`。

---

## 10. 测试策略

| 层次 | 工具 | 是否真实 PostgreSQL |
|---|---|---|
| 单元 | `go test` + `testify` | 否 |
| 集成 | `testcontainers-go` | 是，每次全新迁移 |
| RLS 矩阵 | `pgTAP` + Go | 是 |
| 契约 | OpenAPI 校验 + `huma` | 否 |
| 端到端 | `httptest` + Testcontainers | 是 |
| 负载 | `k6` | 是（预发） |

必测安全场景：

1. 租户 A 成员读取租户 B 资源 → `404`/空。
2. 伪造 `X-Tenant-Id` → 不改变 RLS 上下文。
3. 连接池复用：A 事务结束，B 复用连接，不残留 `app.tenant_id`。
4. `platform_core` 执行 `SET ROLE platform_control` → 拒绝。
5. `platform_core` 更新/删除 `audit_log` → 拒绝。
6. 未设置上下文查询 RLS 表 → 0 行。
7. 提权：授予自身没有的权限 → 拒绝。
8. 所有者角色直接改派 → 拒绝，只能走转让。
9. 过期 `pv` Token → `401`。
10. 扩展注册 `platform.*` 权限 → 启动失败。
11. 扩展迁移修改核心表 → 迁移 Job 拒绝。
12. 幂等重放 / 冲突 → 原响应 / `409`。

详见运维与测试文档。

---

## 11. 可观测性

| 信号 | 内容 |
|---|---|
| 日志 | JSON；`request_id`、`trace_id`、`tenant_id`、`principal_id`、`route`、`status`、`latency_ms` |
| 指标 | 请求量/延迟/错误率、DB 池使用、RLS 拒绝、登录失败、Outbox 积压、Webhook 失败 |
| Trace | HTTP → Service → SQL span；SQL 不记录参数值 |
| 审计 | 安全事件独立于日志，不可篡改 |

禁止在日志中输出：密码、Token、API Key、完整身份证/银行卡、完整邮箱/手机号（按掩码）。

---

## 12. 部署与运行

### 12.1 进程

| 进程 | 职责 | 副本 |
|---|---|---|
| `platform-api` | HTTP API | ≥2 |
| `platform-worker` | Outbox、Webhook、清理、分区维护 | ≥1（River 自带锁） |
| `platform-migrate` | 迁移 Job | 单次 |

### 12.2 启动顺序

1. 加载配置，校验必填项。
2. 连接数据库，校验角色与 `current_user`。
3. 校验迁移版本（API 启动要求 schema 版本匹配）。
4. 加载扩展 Manifest，校验权限命名空间。
5. 启动 HTTP server / Worker。
6. 注册优雅关闭：停止接收新请求 → 等待在途请求 → 关闭池。

### 12.3 健康检查

- `/healthz`：进程存活，不查数据库。
- `/readyz`：数据库可用、迁移版本匹配、扩展加载完成。
- 平台入口与用户入口共享健康检查，不暴露内部细节。

---

## 13. AI 编程约束

生成或修改 b_platform 代码时必须遵守：

1. 新增租户表必须包含 `tenant_id`、启用 RLS、添加策略、添加索引、补充 pgTAP 用例。
2. 新增表必须显式授权给最小角色集合，禁止 `ON ALL TABLES`。
3. 新增权限点必须更新权限模型文档与种子数据，编码不可变。
4. 新增写接口必须声明权限点、幂等要求、审计事件。
5. 禁止在 Handler 中直接写 SQL 或访问连接池。
6. 禁止使用 `SET`（会话级）设置租户上下文。
7. 禁止使用 `BYPASSRLS`、`SECURITY DEFINER` 绕过授权（除非文档明确并评审）。
8. 禁止跨模块直接 JOIN 或 import 其他模块的 `postgres` 包。
9. 禁止在日志/错误响应中输出敏感字段。
10. 修改 API 必须先改 OpenAPI，再改实现与测试。
11. 所有时间使用 `timestamptz`，统一 UTC。
12. 所有 ID 使用 UUIDv7，禁止自增主键。

---

## 14. 相关文档

- [总体架构](../00-architecture/architecture-v2.0.md)
- [架构决策](../00-architecture/decisions-v2.0.md)
- [扩展 SPI](../00-architecture/extension-spi-v2.0.md)
- [需求规格](../10-requirements/requirements-v2.0.md)
- [数据库设计](database-design-v2.0.md)
- [权限模型](permission-model-v2.0.md)
- [状态机](state-machines-v2.0.md)
- [OpenAPI](../30-api/openapi-v2.0.yaml)
- [运维与测试](../40-operations/operations-v2.0.md)
