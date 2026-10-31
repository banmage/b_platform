# b_platform 总体架构 V2.0

**项目：** b_platform  
**版本：** V2.0  
**状态：** 设计基线（待评审）  
**关联决策：** ADR-001 ~ ADR-010

---

## 1. 目标

b_platform 的目标是成为多个业务系统共用的**业务控制面**：

- 统一租户、用户、组织、成员、角色、权限、审计；
- 为 Bufaa、Tufaa、MuPlan 及类似项目提供标准身份与授权能力；
- 保持核心稳定，业务能力通过扩展模块接入；
- 独立部署、独立数据库、独立版本发布；
- 不成为单体业务系统的“共享数据库”。

---

## 2. 控制面与数据面

```text
┌─────────────────────────────────────────────────────────────┐
│                        控制面 Control Plane                  │
│                                                             │
│  b_platform                                                 │
│  ├── Tenant                                                 │
│  ├── Identity / AuthN                                       │
│  ├── Organization Directory                                 │
│  ├── Membership                                             │
│  ├── RBAC / Scope                                           │
│  ├── Audit                                                  │
│  ├── Platform Config                                        │
│  ├── Extension Registry                                     │
│  ├── Service Account / API Key                              │
│  └── Outbox / Webhook                                       │
└───────────────────────────┬─────────────────────────────────┘
                            │ API / JWT / Event
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│     Bufaa     │   │     Tufaa     │   │    MuPlan     │
│  数据面/应用   │   │  数据面/内核   │   │  数据面/计算   │
└───────────────┘   └───────────────┘   └───────────────┘
```

原则：

1. b_platform 不保存业务数据（资源、预订、履约、帖子等）。
2. 其他项目不直接连接 b_platform 数据库。
3. 其他项目通过 JWT/JWKS 本地校验身份，通过 API/事件同步组织与权限变更。
4. b_platform 不可用时，其他项目应能继续处理已有会话；身份/授权变更可能延迟生效。

---

## 3. 领域模型

### 3.1 三层边界

```text
Platform（控制面）
   │
   ├── Platform User（全局身份）
   ├── Platform Role / Permission
   ├── Platform Param / Extension / Service Account
   │
   └── Tenant（数据隔离边界）
          │
          ├── Tenant Membership
          ├── Tenant Role / Permission
          │
          └── Organization（租户内业务组织，可树形）
                 │
                 ├── Organization Membership
                 └── Organization Role / Permission
```

### 3.2 核心实体

| 实体 | 作用 | 隔离级别 |
|---|---|---|
| `platform_user` | 全局用户身份 | 平台级 |
| `tenant` | 数据隔离边界 | 平台级 + 租户可读 |
| `tenant_membership` | 用户与租户关系 | 租户 |
| `organization` | 租户内组织 | 租户 |
| `organization_membership` | 用户与组织关系 | 租户/组织 |
| `role` | 平台/租户/组织角色 | 按 scope |
| `permission` | 权限点定义 | 平台级 |
| `role_permission` | 角色权限映射 | 按角色 scope |
| `platform_role_grant` | 平台角色授予 | 平台级 |
| `audit_log` | 审计 | 平台级 + 租户可读 |
| `extension_registry` | 扩展模块注册 | 平台级 |
| `service_account` | 服务账号 | 平台级/租户 |
| `outbox_event` | 事务性事件 | 平台级/租户 |

### 3.3 Tenant 与 Organization

- Tenant 是数据隔离边界，所有租户数据表包含 `tenant_id`。
- Organization 属于某个 Tenant，支持 `parent_id` 树形结构。
- 父子组织必须属于同一 Tenant。
- 组织树只在租户内，不存在跨租户父子关系。
- 组织审批、冻结、所有权转让都在租户内完成。
- 平台运营人员不是租户成员；平台跨租户访问走独立控制面路径。

---

## 4. 模块架构

```text
cmd/
├── platform/            # API 服务
└── worker/              # Outbox / 清理任务

internal/
├── core/
│   ├── tenant/          # 租户生命周期、配置
│   ├── identity/        # 用户、认证、会话、密码、验证
│   ├── organization/    # 组织树、审批、冻结、所有权
│   ├── membership/      # 租户成员、组织成员、邀请
│   ├── authz/           # 权限点、角色、授权、判定
│   ├── audit/           # 审计写入/查询/导出
│   ├── config/          # 平台参数、租户配置
│   ├── extension/       # 扩展注册表、SPI
│   ├── serviceaccount/  # 服务账号、API Key
│   └── outbox/          # 事件、Webhook
├── platform/            # HTTP、中间件、组合根
└── ext/                 # 可选扩展模块（编译期加载）
```

### 4.1 依赖规则

```text
platform/http
   ↓
core/* application services
   ↓
core/* domain + repository interfaces
   ↓
PostgreSQL (pgx/sqlc)
```

- `core/*` 之间只通过接口或领域事件协作。
- `core/audit` 不被业务模块反向依赖。
- `core/authz` 可以依赖 `identity`/`tenant`/`organization` 的只读接口。
- 扩展模块只能依赖 `extension` 包暴露的 SPI，不直接依赖核心 Repository。
- 禁止跨模块直接 JOIN 表。

### 4.2 事务边界

- 单个模块内的强一致操作使用本地事务。
- 跨模块强一致操作（如创建租户 + 初始 owner 成员）由应用服务编排，在一个数据库事务内完成。
- 跨模块最终一致操作使用 Outbox 事件。
- 不使用分布式事务。

---

## 5. 安全架构

### 5.1 身份与认证

- 用户密码使用 Argon2id。
- Access Token：JWT，RS256，15 分钟。
- Refresh Token：随机字符串，数据库存哈希，旋转 + 重用检测。
- JWT 包含 `iss`、`sub`、`aud`、`jti`、`iat`、`exp`、`tid`、`oid`、`mid`、`roles`、`scopes`、`pv`。
- 平台管理员与普通用户使用不同 `aud`。
- 服务账号使用 OAuth2 Client Credentials 或 API Key。

### 5.2 授权

- 三层权限：Platform / Tenant / Organization。
- 权限判定统一走 `authz.Authorizer`。
- 禁止在 Handler/Service 中写 `if role == "admin"`。
- 权限点编码不可变，只能废弃后新增。
- 扩展模块权限使用 `ext.<module>.*` 命名空间。

### 5.3 数据库隔离

- 所有租户数据表启用 `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`。
- 策略基于 `current_setting('app.tenant_id', true)::uuid`。
- 运行时角色不拥有 `BYPASSRLS`。
- 平台跨租户访问使用 `platform_control`，设置目标租户上下文，并写审计。
- 不使用自定义 GUC 表示“平台访问”或“平台写”。

### 5.4 审计

- 关键安全事件与业务事务同事务写入 `audit_log`。
- 审计表只追加，不更新、不删除。
- 租户审计按 `tenant_id` 隔离；平台审计通过 `platform_audit_reader`。
- 审计按时间分区，支持归档/SIEM 导出。
- 审计写入失败时，关键业务失败并回滚。

---

## 6. API 与事件

### 6.1 API

| 前缀 | 用途 |
|---|---|
| `/api/v1` | 用户/租户 API |
| `/api/platform/v1` | 平台控制面 API |
| `/api/v1/ext/<module>` | 扩展模块 API |

- OpenAPI 3.1 为唯一契约。
- 错误响应使用 Problem Details 风格。
- 分页使用 cursor。
- 关键写操作使用 `Idempotency-Key`。
- 资源更新可使用 `ETag` / `If-Match`。

### 6.2 事件

- Outbox 与业务同事务写入。
- Worker 异步投递 Webhook / 消息。
- 事件格式：

```json
{
  "id": "uuid",
  "type": "tenant.membership.created",
  "version": 1,
  "occurred_at": "2026-10-31T12:00:00Z",
  "tenant_id": "uuid",
  "aggregate_type": "membership",
  "aggregate_id": "uuid",
  "data": {}
}
```

- 消费者必须幂等。
- Webhook 使用 HMAC 签名、重试、死信和延迟告警。

---

## 7. 扩展模块

扩展模块通过 Manifest 注册：

```go
type Manifest struct {
    Name         string
    Version      string
    APIVersion   string
    Permissions  []PermissionDefinition
    Routes       []RouteDefinition
    Migrations   []MigrationDefinition
    Events       []EventDefinition
    ConfigSchema json.RawMessage
    UIExtensions []UIExtension
}
```

扩展模块可以是：

1. 编译期加载的 Go 包（一期推荐）；
2. 独立服务（后续），通过 API/事件集成。

约束：

- 扩展表放在独立 schema：`ext_<module>`。
- 扩展迁移不能修改核心表。
- 扩展权限只能注册 `ext.<module>.*`，不能注册 `platform.*`。
- 扩展路由挂载在 `/api/v1/ext/<module>`。
- 扩展模块不能直接访问核心表。

详见 [`extension-spi-v2.0.md`](extension-spi-v2.0.md)。

---

## 8. 部署形态

### 8.1 一期

```text
Docker Compose
├── platform-api        # Go API
├── platform-worker     # Outbox / 清理
├── postgres            # PostgreSQL 16+
└── redis               # 可选：限流/缓存/队列
```

- 迁移作为独立 Job 运行，使用 `platform_migrator`。
- API/Worker 使用受限角色。
- 健康检查：`/healthz`、`/readyz`。
- 优雅关闭：等待正在处理请求/事务完成。

### 8.2 后续

- Kubernetes / Helm。
- PostgreSQL 主从 + PITR。
- Redis 集群 / 队列。
- 多区域部署。
- 按模块拆分服务。

---

## 9. 非功能目标

| 指标 | 一期目标 |
|---|---|
| 租户规模 | 10,000+ |
| 组织规模 | 100,000+（单租户 10,000+） |
| 用户规模 | 1,000,000+ |
| 认证/授权 P95 | ≤ 50ms（不含网络） |
| 组织树查询 P95 | ≤ 300ms |
| 可用性 | 99.9%（一期） |
| RPO | ≤ 15 分钟（生产） |
| RTO | ≤ 1 小时（生产） |

具体验收以需求文档为准。

---

## 10. 关键风险

| 风险 | 缓解 |
|---|---|
| RLS 策略遗漏导致跨租户泄露 | 所有租户表强制 RLS；集成测试 + pgTAP + 渗透测试 |
| 平台跨租户访问权限过大 | 不用 `BYPASSRLS`；目标租户上下文 + 审计 |
| 扩展模块破坏核心边界 | SPI + 代码审查 + 独立 schema + 禁止跨表访问 |
| 权限缓存导致变更延迟 | `pv` + 安全敏感路径不过缓存 |
| 平台成为单点故障 | JWT 本地校验；短 TTL；降级策略；HA |
| 文档与实现不一致 | OpenAPI/迁移/测试同源；CI 检查 |

---

## 11. 相关文档

- [需求规格 V2.0](../10-requirements/requirements-v2.0.md)
- [技术设计 V2.0](../20-design/tech-design-v2.0.md)
- [数据库设计 V2.0](../20-design/database-design-v2.0.md)
- [权限模型 V2.0](../20-design/permission-model-v2.0.md)
- [状态机 V2.0](../20-design/state-machines-v2.0.md)
- [扩展 SPI V2.0](extension-spi-v2.0.md)
- [OpenAPI V2.0](../30-api/openapi-v2.0.yaml)
- [运维与测试 V2.0](../40-operations/operations-v2.0.md)
