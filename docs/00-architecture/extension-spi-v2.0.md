# 扩展模块 SPI V2.0

**项目：** b_platform  
**版本：** V2.0  
**状态：** 设计基线

---

## 1. 目标

扩展模块 SPI 用于让 Bufaa、Tufaa、MuPlan 或类似项目在不修改 b_platform 核心的前提下接入业务能力。

核心原则：

1. 核心不依赖扩展。
2. 扩展不修改核心表。
3. 扩展不直接访问核心表。
4. 扩展通过 Manifest 注册能力。
5. 扩展可以编译期加载，也可以后续拆为独立服务。

---

## 2. 扩展 Manifest

```go
package extension

type Manifest struct {
    Name         string                 `json:"name"`
    Version      string                 `json:"version"`
    APIVersion   string                 `json:"api_version"`
    Description  string                 `json:"description,omitempty"`
    Permissions  []PermissionDefinition `json:"permissions"`
    Routes       []RouteDefinition      `json:"routes"`
    Migrations   []MigrationDefinition  `json:"migrations"`
    Events       []EventDefinition      `json:"events"`
    ConfigSchema json.RawMessage        `json:"config_schema,omitempty"`
    UIExtensions []UIExtension          `json:"ui_extensions,omitempty"`
}
```

### 2.1 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 小写、短横线，例如 `resource`、`booking`、`forum` |
| `version` | 是 | 扩展版本，SemVer |
| `api_version` | 是 | 扩展 SPI 版本，例如 `v1` |
| `permissions` | 否 | 扩展注册的权限点 |
| `routes` | 否 | 扩展 API 路由 |
| `migrations` | 否 | 扩展数据库迁移 |
| `events` | 否 | 扩展发布的事件 |
| `config_schema` | 否 | 扩展配置 JSON Schema |
| `ui_extensions` | 否 | 管理后台菜单/页面扩展点 |

---

## 3. 权限注册

扩展只能注册 `ext.<module>.*` 命名空间。

```go
type PermissionDefinition struct {
    Code        string   `json:"code"`         // ext.resource.resource.create
    Scope       Scope    `json:"scope"`        // TENANT | ORGANIZATION
    Description string   `json:"description"`
    Deprecated  bool     `json:"deprecated,omitempty"`
}
```

规则：

- `Scope` 只能是 `TENANT` 或 `ORGANIZATION`。
- 扩展不能注册 `PLATFORM` 权限。
- 权限编码发布后不可修改，只能废弃。
- 权限元数据写入 `permission` 表，`namespace='EXT'`，`module=<name>`（权限模型 V2.0 §3.2）。
- 平台/租户/组织角色可以授予扩展权限点。
- 扩展路由必须声明权限点，由核心 `Authorizer` 统一判定（权限模型 V2.0 §3.5）；扩展只做业务级二次校验，不在自身运行时重复核心权限判定。

示例：

```json
{
  "name": "booking",
  "permissions": [
    {
      "code": "ext.booking.reservation.create",
      "scope": "ORGANIZATION",
      "description": "创建预订"
    },
    {
      "code": "ext.booking.reservation.cancel.others",
      "scope": "ORGANIZATION",
      "description": "取消他人预订"
    }
  ]
}
```

---

## 4. 路由注册

```go
type RouteDefinition struct {
    Method      string
    Path        string
    Permission  string
    Handler     http.Handler
    Idempotent  bool
}
```

规则：

- 路径统一挂载在 `/api/v1/ext/<module>`。
- 扩展路由必须声明所需权限点。
- 扩展路由使用核心认证中间件，获取 `Principal` 和 `TenantContext`。
- 扩展不得注册 `/api/platform/*` 路由。
- 扩展路由的 OpenAPI 文档由扩展提供，构建时合并。

---

## 5. 数据库迁移

```go
type MigrationDefinition struct {
    Schema  string   // ext_<module>
    Version int64
    Up      string
    Down    string
}
```

规则：

- 扩展使用独立 schema：`ext_<module>`。
- 扩展表必须包含 `tenant_id`（如涉及租户数据），并启用 RLS。
- 扩展迁移不能修改 `core` schema。
- 扩展迁移不能创建跨 schema 外键到核心表；使用 ID 引用 + 应用校验。
- 扩展迁移版本独立管理，失败不影响核心迁移。
- 扩展卸载只允许禁用，不自动删除数据。

目录示例：

```text
extensions/booking/
├── manifest.go
├── migrations/
│   ├── 0001_init.sql
│   └── 0002_add_index.sql
├── handler/
├── service/
└── repository/
```

---

## 6. 事件契约

```go
type EventDefinition struct {
    Type       string // ext.booking.reservation.created
    Version    int
    Schema     json.RawMessage
    Aggregate  string
    Published  bool
}
```

规则：

- 扩展事件使用 `ext.<module>.<entity>.<action>`。
- 事件通过核心 Outbox 发布。
- 事件包含 `tenant_id`、`aggregate_id`、`occurred_at`。
- 事件 schema 版本化，破坏性变更提升 `version`。
- 消费者必须幂等。

---

## 7. 配置

扩展配置存放在 `tenant_config` 或扩展自己的 schema 中，使用 JSON Schema 校验。

```json
{
  "type": "object",
  "properties": {
    "max_advance_days": { "type": "integer", "minimum": 1 },
    "cancellation_policy": { "type": "string", "enum": ["none", "24h", "48h"] }
  }
}
```

规则：

- 配置 schema 随 Manifest 注册。
- 配置变更必须审计。
- 不允许扩展读取其他租户配置。

---

## 8. 生命周期

```text
REGISTERED ──enable──> ACTIVE ──disable──> DISABLED
     │                    │                  │
     └──────uninstall─────┴──────────────────┘
                    （仅禁用，不删除数据）
```

| 状态 | 说明 |
|---|---|
| `REGISTERED` | 已注册，未启用 |
| `ACTIVE` | 已启用，路由/权限/事件生效 |
| `DISABLED` | 已禁用，路由不挂载，数据保留 |

规则：

- 启用/禁用由平台 `platform.extension.manage` 权限控制。
- 启用前检查迁移版本、API 版本、权限冲突。
- 禁用不删除数据。
- 扩展升级必须向后兼容当前 API 版本。

---

## 9. 扩展与核心的边界

### 允许

- 调用核心公开 API。
- 使用核心 JWT/JWKS 校验身份。
- 读取核心提供的 `Principal`、`TenantContext`。
- 通过核心 Outbox 发布事件。
- 注册权限、路由、迁移、配置、UI 扩展点。

### 禁止

- 直接连接/查询 `core` schema 表。
- 修改核心表结构。
- 注册 `platform.*` 权限。
- 绕过核心认证/授权中间件。
- 在扩展中实现自己的租户隔离（必须复用核心 `tenant_id` + RLS）。
- 把业务数据写入核心表。

---

## 10. 参考模块

一期可以提供两个参考扩展（不进入核心）：

1. `resource`：资源目录/资源类型注册。
2. `booking`：预订/可用时间（未来可对接 MuPlan）。

这两个模块用于验证 SPI，但默认不启用。

---

## 11. 扩展清单示例

```json
{
  "name": "resource",
  "version": "0.1.0",
  "api_version": "v1",
  "permissions": [
    { "code": "ext.resource.resource.create", "scope": "ORGANIZATION", "description": "创建资源" },
    { "code": "ext.resource.resource.read", "scope": "ORGANIZATION", "description": "查看资源" }
  ],
  "routes": [
    { "method": "POST", "path": "/resources", "permission": "ext.resource.resource.create", "idempotent": true },
    { "method": "GET", "path": "/resources", "permission": "ext.resource.resource.read" }
  ],
  "migrations": [
    { "schema": "ext_resource", "version": 1, "up": "0001_init.sql" }
  ],
  "events": [
    { "type": "ext.resource.resource.created", "version": 1 }
  ]
}
```
