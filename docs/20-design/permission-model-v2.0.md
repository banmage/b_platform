# b_platform 权限模型 V2.0

**项目：** b_platform（通用业务底座平台·控制面）  
**版本：** V2.0  
**状态：** 设计基线（待评审）  
**对应需求：** `docs/10-requirements/requirements-v2.0.md`  
**对应数据库：** `docs/20-design/database-design-v2.0.md`

---

## 1. 文档定位

本文档定义 b_platform 的权限点、角色、授权范围、判定算法、提权防护和缓存规则，是 `authz` 模块、JWT 声明、OpenAPI 安全声明、种子数据和权限测试的唯一语义来源。

本文档不定义：

- 表结构与索引：见数据库设计 V2.0。
- 状态转换：见状态机 V2.0。
- API 字段：见 OpenAPI V2.0。

---

## 2. 三层权限模型

```text
Platform（控制面）
   │  平台角色 + 授权范围（ALL / TENANT / ORGANIZATION / ORG_TYPE）
   │
   └── Tenant（数据隔离边界）
          │  租户角色（授予租户成员）
          │
          └── Organization（租户内组织树）
                 │  组织角色（授予组织成员，向下继承）
                 └── 组织成员
```

| 层级 | 权限作用域 | 授予对象 | 生效范围 |
|---|---|---|---|
| Platform | `PLATFORM` | 平台用户 | 全平台，或授权范围指定的租户/组织 |
| Tenant | `TENANT` | 租户成员 | 整个租户 |
| Organization | `ORGANIZATION` | 组织成员 | 该组织及其后代组织 |

约束：

1. Platform 不是组织，不进入组织树。
2. 平台运营人员不是租户成员；其跨租户能力只来自平台角色和授权范围。
3. 租户角色不能授予平台权限；组织角色不能授予租户/平台权限。
4. 扩展只能注册 `TENANT` / `ORGANIZATION` 作用域权限。
5. 所有判定在服务端完成，Token 中的 `roles` / `scopes` 只用于展示和粗过滤。

---

## 3. 权限点

### 3.1 编码规则

```text
核心：<domain>.<resource>.<action>        tenant.member.invite
扩展：ext.<module>.<resource>.<action>    ext.booking.reservation.create
```

规则：

- 全小写，点分隔，段内使用下划线；总长度 ≤ 128。
- 扩展编码段数：`ext.<module>.` 之后权限为 `<resource>.<action>` 两段、事件为 `<entity>.<action>` 两段；`action` 允许**一个**点分限定符（如 `cancel.others`，不得再嵌套），其余段内只允许字母数字与下划线。
- `domain` 为核心模块名：`platform`、`tenant`、`organization`。
- 扩展模块名必须与 Manifest `name` 一致。
- 编码发布后不可修改；只能标记 `DEPRECATED` 并新增替代编码。
- 权限点由平台维护；扩展启动时注册，不能覆盖核心权限。

### 3.2 元数据

| 字段 | 说明 |
|---|---|
| `code` | 主键，全局唯一 |
| `namespace` | `CORE` / `EXT` |
| `module` | 扩展模块名；核心为 `NULL` |
| `scope` | `PLATFORM` / `TENANT` / `ORGANIZATION` |
| `description` | 中文说明 |
| `is_dangerous` | 高危权限标记：一期仅审计增强（审计目录 §4 规则 4）；step-up 二期（§8.2） |
| `status` | `ACTIVE` / `DEPRECATED` |

### 3.3 作用域约束

| 权限作用域 | 可授予的角色 | 可授予的服务账号 |
|---|---|---|
| `PLATFORM` | 平台角色 | 平台级服务账号 |
| `TENANT` | 平台角色、租户角色 | 租户级服务账号 |
| `ORGANIZATION` | 平台角色、租户角色、组织角色 | 租户级服务账号 |

说明：

- 平台角色可以包含 `TENANT` / `ORGANIZATION` 权限，用于平台支持人员在指定范围内协助租户。
- 租户角色可以包含 `ORGANIZATION` 权限，表示租户管理员在整个租户的组织范围内生效。
- 组织角色只能包含 `ORGANIZATION` 权限。
- 平台级服务账号只能持有 `PLATFORM` 权限；租户级服务账号不能持有 `PLATFORM` 权限。

### 3.4 核心权限点目录

#### 平台域（`PLATFORM`）

| 编码 | 高危 | 说明 |
|---|---|---|
| `platform.tenant.read` | 否 | 查看租户列表/详情 |
| `platform.tenant.create` | 否 | 创建租户 |
| `platform.tenant.update` | 否 | 更新租户基本信息 |
| `platform.tenant.freeze` | 是 | 冻结/解冻租户 |
| `platform.tenant.close` | 是 | 关闭租户 |
| `platform.tenant.force_manage` | 是 | 对冻结/关闭租户执行强制管理 |
| `platform.tenant.member.read` | 否 | 查看指定租户成员 |
| `platform.tenant.organization.read` | 否 | 查看指定租户组织 |
| `platform.user.read` | 否 | 查看平台用户 |
| `platform.user.disable` | 是 | 禁用用户 |
| `platform.user.enable` | 是 | 启用用户 |
| `platform.user.session.revoke` | 是 | 撤销指定用户会话 |
| `platform.role.read` | 否 | 查看平台角色 |
| `platform.role.manage` | 是 | 创建/修改/停用平台角色 |
| `platform.role.grant` | 是 | 授予/撤销平台角色 |
| `platform.param.read` | 否 | 查看平台参数 |
| `platform.param.manage` | 是 | 修改平台参数 |
| `platform.extension.read` | 否 | 查看扩展注册表 |
| `platform.extension.manage` | 是 | 启用/禁用/升级扩展 |
| `platform.service_account.read` | 否 | 查看平台级服务账号 |
| `platform.service_account.manage` | 是 | 管理平台级服务账号/API Key |
| `platform.audit.read` | 否 | 查询平台审计 |
| `platform.audit.export` | 是 | 导出平台审计 |
| `platform.event.read` | 否 | 查看 Outbox/Webhook 投递状态 |
| `platform.cross_tenant.access` | 是 | 以目标租户上下文执行受审计的跨租户操作 |

#### 租户域（`TENANT`）

| 编码 | 高危 | 说明 |
|---|---|---|
| `tenant.read` | 否 | 查看租户信息 |
| `tenant.update` | 否 | 更新租户名称等基本信息 |
| `tenant.transfer` | 是 | 发起租户所有权转让 |
| `tenant.config.read` | 否 | 查看租户配置 |
| `tenant.config.update` | 否 | 修改租户配置 |
| `tenant.member.read` | 否 | 查看租户成员 |
| `tenant.member.invite` | 否 | 邀请租户成员 |
| `tenant.member.remove` | 是 | 移除租户成员 |
| `tenant.member.suspend` | 是 | 暂停租户成员 |
| `tenant.member.activate` | 是 | 恢复租户成员 |
| `tenant.role.read` | 否 | 查看租户角色 |
| `tenant.role.manage` | 是 | 创建/修改/停用租户角色 |
| `tenant.role.assign` | 是 | 给成员分配/撤销租户角色 |
| `tenant.organization.read` | 否 | 查看租户内组织 |
| `tenant.organization.create` | 否 | 创建组织 |
| `tenant.organization.approve` | 是 | 审批组织创建 |
| `tenant.organization.update` | 否 | 更新组织信息 |
| `tenant.organization.freeze` | 是 | 冻结/解冻组织 |
| `tenant.organization.transfer` | 是 | 强制转让组织所有权 |
| `tenant.audit.read` | 否 | 查看租户审计 |
| `tenant.audit.export` | 是 | 导出/归档租户审计 |
| `tenant.service_account.read` | 否 | 查看租户级服务账号 |
| `tenant.service_account.manage` | 是 | 管理租户级服务账号/API Key |
| `tenant.webhook.read` | 否 | 查看 Webhook 配置 |
| `tenant.webhook.manage` | 是 | 管理 Webhook 配置 |
| `tenant.event.read` | 否 | 查看事件投递状态 |

#### 组织域（`ORGANIZATION`）

| 编码 | 高危 | 说明 |
|---|---|---|
| `organization.read` | 否 | 查看组织信息 |
| `organization.update` | 否 | 更新组织名称、可见性 |
| `organization.member.read` | 否 | 查看组织成员 |
| `organization.member.invite` | 否 | 邀请组织成员 |
| `organization.member.remove` | 是 | 移除组织成员 |
| `organization.member.suspend` | 是 | 暂停组织成员 |
| `organization.member.activate` | 是 | 恢复组织成员 |
| `organization.role.read` | 否 | 查看组织角色 |
| `organization.role.manage` | 是 | 创建/修改/停用组织角色 |
| `organization.role.assign` | 是 | 给成员分配/撤销组织角色 |
| `organization.config.read` | 否 | 查看组织配置 |
| `organization.config.update` | 否 | 修改组织配置 |
| `organization.transfer` | 是 | 发起组织所有权转让 |

> 预留与无接口权限点（一期）：
>
> - `tenant.organization.update`、`organization.config.read`、`organization.config.update` 为**预留权限点**：进目录与种子校验，但一期无 OpenAPI 锚点，仅进入内置角色模板（`org_member` 含 `organization.config.read`）。
> - `platform.cross_tenant.access`、`platform.tenant.force_manage`、`tenant.organization.transfer` 由**平台强制作业/内部判定**使用（状态机 §5.2、§8.2），不直接对应单一 `operationId`。

### 3.5 扩展权限点

```text
ext.<module>.<resource>.<action>
```

规则：

- 只能注册 `TENANT` / `ORGANIZATION` 作用域。
- 不能注册 `platform.*`、`tenant.*`、`organization.*`。
- 扩展权限点由核心写入 `core.permission`，`namespace='EXT'`，`module=<name>`。
- 扩展路由必须声明权限点，由核心 `Authorizer` 判定。
- 扩展停用后权限点保留，但不可再授予新角色；已有角色绑定保留，重新启用后生效。
- 扩展不得在自身代码中复制核心权限判定；只做业务级二次校验。

示例：

| 编码 | 作用域 | 说明 |
|---|---|---|
| `ext.resource.resource.create` | `ORGANIZATION` | 创建资源 |
| `ext.resource.resource.read` | `ORGANIZATION` | 查看资源 |
| `ext.booking.reservation.create` | `ORGANIZATION` | 创建预订 |
| `ext.booking.reservation.cancel.others` | `ORGANIZATION` | 取消他人预订 |
| `ext.forum.post.create` | `TENANT` | 发帖 |

---

## 4. 内置角色

### 4.1 平台角色

| 角色 | 说明 | 包含权限 |
|---|---|---|
| `platform_super_admin` | 平台超级管理员 | 全部 `platform.*`（含 `platform.cross_tenant.access`） |
| `platform_operator` | 平台运营 | `platform.tenant.read/create/update/freeze/close`、`platform.tenant.member.read`、`platform.tenant.organization.read`、`platform.user.read/disable/enable/session.revoke`、`platform.extension.read`、`platform.service_account.read`、`platform.param.read`、`platform.audit.read` |
| `platform_auditor` | 平台审计员 | `platform.audit.read/export`、`platform.tenant.read`、`platform.tenant.member.read`、`platform.tenant.organization.read`、`platform.user.read`、`platform.role.read`、`platform.event.read` |
| `platform_support` | 平台支持 | `platform.tenant.read`、`platform.tenant.member.read`、`platform.tenant.organization.read`、`platform.user.read`、`platform.user.session.revoke`、`platform.audit.read` |

规则：

- 平台角色 `scope='PLATFORM'`，`tenant_id` / `organization_id` 为 `NULL`。
- 平台角色不能是 `is_owner_role`。
- `platform_super_admin` 不通过角色名硬编码获得权限，而是由种子数据授予全部平台权限；新增平台权限时必须在同一迁移中补充种子。
- 平台角色可以包含 `tenant.*` / `organization.*` 权限，但必须限定授权范围（见 §5.2）。

### 4.2 租户角色

| 角色 | 所有者角色 | 包含权限 |
|---|---|---|
| `tenant_owner` | 是 | 全部 `tenant.*` 与 `organization.*`（通配） |
| `tenant_admin` | 否 | 除 `tenant.transfer`、`tenant.organization.transfer`、`tenant.audit.export` 外的全部 `tenant.*` 与 `organization.*` |
| `tenant_auditor` | 否 | `tenant.read`、`tenant.config.read`、`tenant.member.read`、`tenant.role.read`、`tenant.organization.read`、`tenant.audit.read`、`tenant.audit.export`、`tenant.event.read`、`tenant.service_account.read`、`tenant.webhook.read` |
| `tenant_member` | 否 | `tenant.read`、`tenant.config.read`、`tenant.member.read`、`tenant.role.read`、`tenant.organization.read` |

规则：

- 每个租户有且仅有一个 `tenant_owner` 角色，且同一时刻只有一个成员持有。
- `tenant_owner` 不能被删除、停用、改名或修改权限集合。
- `tenant_owner` 的权限按通配处理：自动拥有当前及未来新增的全部 `TENANT` / `ORGANIZATION` 权限，但不拥有 `PLATFORM` 权限。
- 自定义租户角色只能包含 `TENANT` / `ORGANIZATION` 权限。

### 4.3 组织角色

| 角色 | 所有者角色 | 包含权限 |
|---|---|---|
| `org_owner` | 是 | 全部 `organization.*`（通配） |
| `org_admin` | 否 | 除 `organization.transfer` 外的全部 `organization.*` |
| `org_member` | 否 | `organization.read`、`organization.member.read`、`organization.role.read`、`organization.config.read` |

规则：

- `org_owner` 按通配处理，自动拥有当前及未来新增的全部 `ORGANIZATION` 权限。
- 每个组织有且仅有一个 `org_owner` 角色和一个持有者。
- 组织角色只在该组织及其后代组织生效，不向上、不向兄弟组织生效。

---

## 5. 授权范围

### 5.1 平台角色授予

平台角色通过 `core.platform_role_grant` 授予用户，并通过 `core.platform_role_grant_scope` 指定范围。

| `scope_type` | 必填字段 | 生效范围 | `include_descendants` |
|---|---|---|---|
| `ALL` | 无 | 全平台 | 必须为 `false` |
| `TENANT` | `tenant_id` | 指定租户 | 为 `true` 时同时覆盖该租户内所有组织 |
| `ORGANIZATION` | `tenant_id` + `organization_id` | 指定组织 | 为 `true` 时覆盖该组织的后代 |
| `ORG_TYPE` | `tenant_id` + `org_type` | 指定租户内某类组织 | 为 `true` 时覆盖这些组织的后代 |

规则：

1. 一个授予至少有一条范围；多条范围取并集。
2. `ALL` 必须显式授予，不能由其他范围推导。
3. `include_descendants` 只向下扩展，不向上、不跨租户。
4. 平台权限点（`PLATFORM`）只有 `ALL` 范围拥有全局效力；`TENANT` / `ORGANIZATION` / `ORG_TYPE` 范围只对带目标租户/组织的平台操作生效。
5. 租户/组织权限点按范围生效：`TENANT` 覆盖租户本身；`include_descendants=true` 时覆盖租户内组织；`ORGANIZATION` / `ORG_TYPE` 按组织范围生效。
6. 范围引用的租户/组织必须存在且同租户，由复合外键和应用校验保证。
7. 授予/撤销/范围变更必须递增目标用户的 `permission_version` 并写审计。

### 5.2 平台权限与目标作用域

平台 API 分两类：

| 类型 | 示例 | 判定 |
|---|---|---|
| 全局操作 | 列出所有租户、创建租户、管理平台参数 | 需要 `ALL` 范围 |
| 目标操作 | 查看租户 A、冻结租户 B、查看组织 C | 授权范围必须覆盖目标租户/组织 |

判定规则：

- 全局操作只接受 `scope_type='ALL'` 的有效授予。
- 目标操作接受覆盖目标的任一有效授予。
- 平台角色包含的 `tenant.*` / `organization.*` 权限按同一范围规则生效。
- 平台用户对某租户的跨租户访问必须写 `platform.audit.cross_tenant_access` 审计。

### 5.3 租户角色授予

- 租户角色通过 `core.tenant_role_assignment` 授予 `tenant_membership`。
- 一个成员可以有多个租户角色，权限取并集。
- 租户角色在整个租户生效；其中的 `ORGANIZATION` 权限覆盖租户内全部组织。
- 分配/撤销必须递增 `tenant_membership.permission_version` 并写审计。
- 不能给非 `ACTIVE` 成员分配角色。

### 5.4 组织角色授予

- 组织角色通过 `core.organization_role_assignment` 授予 `organization_membership`。
- 组织角色在该组织及其后代组织生效（向下继承）。
- 组织成员必须先是有效租户成员，由复合外键保证。
- 分配/撤销必须递增 `organization_membership.permission_version` 并写审计。
- 不支持“只对当前组织生效、不继承给后代”的例外；如未来需要，新增范围字段并提升版本。

### 5.5 所有权

- 所有权不是普通权限点，而是“所有者角色 + 成员 `is_owner` 标记 + 实体 `owner_user_id`”三者一致。
- 所有者角色 `is_owner_role=true`，权限按通配处理。
- 所有者只能通过 `ownership_transfer` 流程变更；任何直接改派、删除所有者角色、修改所有者角色权限的请求都必须拒绝。
- 平台运营不能成为租户/组织所有者；平台强制转让需要 `platform.tenant.force_manage` 或 `platform.cross_tenant.access` 并写审计。

---

## 6. 主体与作用域

```go
type Principal struct {
    Type              PrincipalType // USER | SERVICE_ACCOUNT | SYSTEM
    ID                uuid.UUID
    Audience          Audience      // user | platform | service
    SessionID         uuid.UUID
    PermissionVersion PermissionVersion
    Scopes            []string      // 服务账号 OAuth scope
}

type Scope struct {
    TenantID       *uuid.UUID
    OrganizationID *uuid.UUID
    IsPlatform     bool
}

type PermissionVersion struct {
    User            int64 `json:"u"`
    Tenant          int64 `json:"t,omitempty"`
    Membership      int64 `json:"m,omitempty"`
    Organization    int64 `json:"o,omitempty"`
    OrgMembership   int64 `json:"om,omitempty"`
}
```

规则：

- `Principal` 只由认证中间件构造，Handler 不得从请求体/请求头构造。
- `Scope` 只由 `ScopeResolver` 根据“已认证主体 + 已验证成员关系”产生。
- `X-Tenant-Id` 只是作用域提示，必须与 Token 的 `tid` 或平台授权范围交叉校验。
- 服务账号使用 `aud=service`，`Scopes` 来自服务账号定义。
- `SYSTEM` 仅用于受控后台任务，必须携带明确任务来源，不参与用户 API。

---

## 7. 判定算法

### 7.1 总流程

```text
Authorize(ctx, principal, scope, permission):
  1. 校验 principal 类型、账号/服务账号状态
  2. 校验 permission 存在、ACTIVE、作用域匹配
  3. 校验 Token 版本与当前版本一致
  4. 校验 scope 与 Token/成员关系一致
  5. 校验租户/组织状态允许操作
  6. 计算有效权限集合
  7. 判定 permission 是否在集合内
  8. 高危权限按 §8.2 处理（一期仅审计增强；二期执行 step-up）
  9. 拒绝时写安全审计（敏感路径）
```

### 7.2 有效权限集合

#### 用户主体

```text
Effective(user, scope) =
    PlatformGrants(user, scope)
  ∪ TenantRoles(user, scope.TenantID)
  ∪ OrganizationRoles(user, scope.OrganizationID)
```

- `PlatformGrants`：按 §5.1 的范围规则匹配 `scope`。
- `TenantRoles`：该用户在目标租户的有效成员关系上的全部租户角色权限；包含 `ORGANIZATION` 权限时覆盖租户内全部组织。
- `OrganizationRoles`：目标组织及其祖先组织上的有效组织角色权限；只包含 `ORGANIZATION` 权限。
- 没有显式拒绝（deny）；权限不在集合内即拒绝。
- 所有者角色按通配展开（§7.5）。

#### 服务账号

```text
Effective(service_account, scope) = Scopes(service_account)
```

一期规则：

- `scopes` 必须是已存在的 `ACTIVE` 权限点。
- 平台级服务账号只能包含 `PLATFORM` 权限。
- 租户级服务账号只能包含 `TENANT` / `ORGANIZATION` 权限。
- 租户级服务账号仍受租户状态、目标组织状态约束。
- API Key 继承所属服务账号的 `scopes`，不额外扩大权限。
- 二期引入“服务账号绑定角色”时，有效权限改为 `Scopes ∩ BoundRolePermissions`；一期不实现绑定表。

### 7.3 版本校验

Token 中 `pv` 为对象：

```json
{
  "pv": {
    "u": 42,
    "t": 7,
    "m": 3,
    "o": 5,
    "om": 2
  }
}
```

校验规则：

| 字段 | 对应实体 | 不匹配 |
|---|---|---|
| `u` | `platform_user.permission_version` | `401 PERMISSION_VERSION_STALE` |
| `t` | `tenant.permission_version` | `401 PERMISSION_VERSION_STALE` |
| `m` | `tenant_membership.permission_version` | `401 PERMISSION_VERSION_STALE` |
| `o` | `organization.permission_version` | `401 PERMISSION_VERSION_STALE` |
| `om` | `organization_membership.permission_version` | `401 PERMISSION_VERSION_STALE` |

- Token 未包含当前作用域需要的字段 → 视为过期。
- 平台操作不需要 `t/m/o/om`；但平台用户仍有 `u`。
- 版本只增不减；任何变更在同一事务内递增。
- 客户端收到 `401 PERMISSION_VERSION_STALE` 后刷新 Token，可携带新 Token 重试原请求一次（重试语义以错误码目录 §5 为准）。

### 7.4 版本递增矩阵

| 事件 | 递增字段 |
|---|---|
| 用户禁用/启用 | `platform_user.permission_version` |
| 平台角色授予/撤销/范围变更 | 目标用户 `platform_user.permission_version` |
| 平台角色权限变更 | 该角色全部持有者的 `platform_user.permission_version` |
| 租户角色权限变更/停用 | `tenant.permission_version` |
| 租户成员角色分配/撤销 | `tenant_membership.permission_version` |
| 租户成员状态变化 | `tenant_membership.permission_version` |
| 租户冻结/解冻/关闭 | `tenant.permission_version` |
| 组织角色权限变更/停用 | `organization.permission_version` |
| 组织成员角色分配/撤销 | `organization_membership.permission_version` |
| 组织成员状态变化 | `organization_membership.permission_version` |
| 组织冻结/解冻 | `organization.permission_version` |

### 7.5 所有者通配

- `role.is_owner_role=true` 时，该角色在自身作用域内视为拥有全部权限：
  - 租户所有者角色：全部 `TENANT` / `ORGANIZATION` 权限。
  - 组织所有者角色：全部 `ORGANIZATION` 权限。
- 通配不跨越作用域：租户所有者不获得 `PLATFORM` 权限；组织所有者不获得 `TENANT` 权限。
- 通配只对 `ACTIVE` 的所有者角色和 `ACTIVE` 的所有者成员生效。
- 所有者角色不允许被修改权限；`role_permission` 中的记录仅用于展示，判定以通配为准。

### 7.6 主体式授权（subject-scoped）

以下操作**不经过权限点判定**，按 Principal 与目标资源的归属关系放行（OpenAPI 以 `x-subject-authz` 标注，契约测试规则见 §12.3）：

| 操作 | 归属判定 | 拒绝语义 |
|---|---|---|
| `logout` | 登出仅撤销当前会话（属主本人） | 404 防枚举 |
| `listSessions`、`revokeSession` | 会话属主 = `Principal.ID` | 404 防枚举 |
| `getMe`、`updateMe`、`changePassword`、`getMyPermissions`、`switchContext`、`listMyMemberships` | `Principal.ID` 即目标用户 | 401/400 |
| `acceptOwnershipTransfer`、`declineOwnershipTransfer` | 当前用户 = 转让目标（目标成员本人） | 404 防枚举 |
| `cancelOwnershipTransfer` | 当前用户 = 转让发起人 | 404 防枚举 |
| `acceptInvitation` | 当前用户 = 邀请目标（邮箱匹配 `PENDING` 邀请） | 400/404 |

规则：

1. 主体式操作不读取 `core.permission`、不参与内置角色；由归属中间件/Handler 判定。
2. 管理他人资源的动作不属于本节（如平台撤销他人会话走 `platformRevokeUserSessions` + `platform.user.session.revoke`）。
3. 主体式操作的认证失效统一 `401 UNAUTHENTICATED`；无归属统一 `404`（防枚举），邀请语义错误用 `400`。

### 7.7 组织角色继承

查询目标组织及其祖先上的组织角色：

```sql
SELECT DISTINCT rp.permission_code
FROM core.organization_role_assignment ora
JOIN core.organization_closure c
  ON c.tenant_id = ora.tenant_id
 AND c.ancestor_id = ora.organization_id
JOIN core.role r
  ON r.id = ora.role_id
 AND r.status = 'ACTIVE'
JOIN core.role_permission rp
  ON rp.role_id = r.id
WHERE c.tenant_id = core.app_current_tenant_id()
  AND c.descendant_id = $1          -- 目标组织
  AND ora.tenant_id = core.app_current_tenant_id()
  AND ora.membership_id = $2;       -- 当前用户的组织成员关系
```

- `depth=0` 是当前组织自身，`depth>0` 是祖先。
- 不查询后代：组织角色向下继承，但判定某组织时只合并该组织及祖先的授予。
- 组织角色继承与平台授予的 `include_descendants` 是两套独立机制，可叠加。

### 7.8 租户角色查询

```sql
SELECT DISTINCT rp.permission_code
FROM core.tenant_role_assignment tra
JOIN core.role r
  ON r.id = tra.role_id
 AND r.status = 'ACTIVE'
JOIN core.role_permission rp
  ON rp.role_id = r.id
WHERE tra.tenant_id = core.app_current_tenant_id()
  AND tra.membership_id = $1;
```

- 只查询 `ACTIVE` 成员关系对应的分配。
- 租户角色中的 `ORGANIZATION` 权限在整个租户生效，不再按组织过滤。

### 7.9 平台授权查询

使用 `core.fn_platform_permissions_for_user($user_id)`，按 §5.1 规则在应用层匹配作用域：

```text
match(grant_scope, target):
  ALL                                  -> true
  TENANT(t)                            -> target.tenant_id = t
  ORGANIZATION(t, o, include_desc)     -> target.tenant_id = t
                                          AND (target.org = o
                                               OR (include_desc AND target.org ∈ descendants(o)))
  ORG_TYPE(t, type, include_desc)      -> target.tenant_id = t
                                          AND (target.org.type = type
                                               OR (include_desc AND target.org ∈ descendants of any org of type))
```

- 全局平台操作（无目标租户/组织）只匹配 `ALL`。
- 目标操作匹配任一覆盖范围。
- 平台授权查询结果按 `permission_code` 去重。

---

## 8. 提权防护

### 8.1 子集规则

授予/修改角色权限时：

```text
TargetPermissionSet ⊆ ActorEffectivePermissionSet
```

- 比较权限编码集合，不比较角色名。
- 平台授权：Actor 必须在目标范围内拥有待授予的全部权限编码。
- 租户/组织角色：Actor 在目标租户/组织内必须拥有待授予的全部权限编码。
- 服务账号：创建/修改 `scopes` 时同样适用子集规则。
- 不满足时返回 `403 PERMISSION_ESCALATION_DENIED` 并写审计。

### 8.2 高危权限

`is_dangerous=true` 的权限：

- `is_dangerous` 是**审计增强标记**：对应动作执行成功正常写 `SUCCESS` 审计，高危路径被拒按审计目录 §4 写 `DENIED`；该标记本身不改变授权判定。
- 一期不要求全量高危权限 step-up；角色获得途径仍受 §8.1 提权子集规则约束（内置 `tenant_admin` / `org_admin` 等模板按 §4 定义直接持有），不允许通过自定义角色“间接发现”高危权限（分配时校验子集）。
- 二期启用 step-up（MFA/重新验证），Token 中带 `amr` / `auth_time`，未满足时返回 `403 STEP_UP_REQUIRED`（错误码目录 §3.1）。
- `platform.cross_tenant.access` 只能由平台角色持有，不能授予租户/组织角色或服务账号。

### 8.3 所有者保护

- 不得删除、停用、改名所有者角色。
- 不得修改所有者角色的权限集合。
- 不得直接给成员设置 `is_owner=true`；只能通过转让流程。
- 不得移除最后一个所有者成员。
- 转让必须由当前所有者或平台强制发起，目标必须是有效成员，且有且只有一个进行中的转让。

### 8.4 平台超级管理员

- 平台超级管理员权限来自角色权限集合，不来自硬编码角色名。
- 授予 `platform_super_admin` 需要 `platform.role.grant`，并写审计。
- 平台超级管理员不能绕过 RLS；跨租户访问仍需目标租户上下文和审计。
- 新增平台权限时必须在同一迁移中更新超级管理员角色绑定；CI 检查权限目录与超级管理员集合的差集为空。

### 8.5 扩展权限

- 扩展注册 `platform.*` → 启动失败。
- 扩展注册的权限作用域只能是 `TENANT` / `ORGANIZATION`。
- 扩展不能修改其他模块的权限点。
- 扩展停用后不能新增授予；已有绑定保留但路由不挂载。
- 扩展权限不能被平台级服务账号持有。

---

## 9. 权限缓存

### 9.1 缓存键

```text
perm:v1:{principal_type}:{principal_id}:{tenant_id}:{org_id}:
        {u}:{t}:{m}:{o}:{om}
```

- 缓存值为有效权限编码集合。
- `pv` 变化自然产生新键，旧键按 TTL 过期。
- 不使用“删除缓存”作为正确性保证；只作为性能优化。

### 9.2 TTL

| 场景 | TTL |
|---|---|
| 普通读接口 | 60s |
| 高危权限判定 | 不使用缓存 |
| 负结果（无权限） | 10s |
| 所有者通配 | 60s |

### 9.3 禁止

- 不得缓存“角色名 → 权限”而不带 `pv`。
- 不得在 JWT 中缓存完整权限集合作为最终判定依据。
- 不得因缓存未失效而放行已撤销权限；`pv` 校验优先于缓存。

---

## 10. 接口与权限映射

| 接口 | 权限 |
|---|---|
| `POST /api/v1/auth/register` | 公开（限流） |
| `POST /api/v1/auth/login` | 公开（限流） |
| `POST /api/v1/auth/refresh` | 公开（Refresh Token） |
| `POST /api/v1/auth/logout` | 已认证 |
| `GET /api/v1/me` | 已认证 |
| `GET /api/v1/me/permissions` | 已认证 |
| `POST /api/v1/auth/context/switch` | 已认证 + 有效成员关系 |
| `GET /api/v1/tenant` | `tenant.read` |
| `PATCH /api/v1/tenant` | `tenant.update` |
| `POST /api/v1/tenant/transfer` | `tenant.transfer` |
| `GET/PUT /api/v1/tenant/config` | `tenant.config.read` / `tenant.config.update` |
| `GET /api/v1/tenant/members` | `tenant.member.read` |
| `POST /api/v1/tenant/members/invitations` | `tenant.member.invite` |
| `DELETE /api/v1/tenant/members/{id}` | `tenant.member.remove` |
| `POST /api/v1/tenant/members/{id}/suspend` | `tenant.member.suspend` |
| `POST /api/v1/tenant/members/{id}/activate` | `tenant.member.activate` |
| `GET/POST /api/v1/tenant/roles` | `tenant.role.read` / `tenant.role.manage` |
| `PUT /api/v1/tenant/roles/{id}/permissions` | `tenant.role.manage` |
| `PUT /api/v1/tenant/members/{id}/roles` | `tenant.role.assign` |
| `GET /api/v1/tenant/organizations` | `tenant.organization.read` |
| `POST /api/v1/tenant/organizations` | `tenant.organization.create` |
| `POST /api/v1/tenant/organizations/{id}/approve` | `tenant.organization.approve` |
| `PATCH /api/v1/organizations/{id}` | `organization.update` |
| `POST /api/v1/organizations/{id}/freeze` | `tenant.organization.freeze` |
| `GET/POST /api/v1/organizations/{id}/members` | `organization.member.read` / `organization.member.invite` |
| `GET/POST /api/v1/organizations/{id}/roles` | `organization.role.read` / `organization.role.manage` |
| `PUT /api/v1/organizations/{id}/members/{mid}/roles` | `organization.role.assign` |
| `POST /api/v1/organizations/{id}/transfer` | `organization.transfer` |
| `GET /api/v1/tenant/audit` | `tenant.audit.read` |
| `POST /api/v1/tenant/audit/export` | `tenant.audit.export` |
| `GET/POST /api/v1/tenant/service-accounts` | `tenant.service_account.read` / `tenant.service_account.manage` |
| `GET/POST /api/v1/tenant/webhooks` | `tenant.webhook.read` / `tenant.webhook.manage` |
| `/api/platform/v1/tenants/**` | 对应 `platform.tenant.*` |
| `/api/platform/v1/users/**` | 对应 `platform.user.*` |
| `/api/platform/v1/roles/**` | 对应 `platform.role.*` |
| `/api/platform/v1/params/**` | 对应 `platform.param.*` |
| `/api/platform/v1/extensions/**` | 对应 `platform.extension.*` |
| `/api/platform/v1/service-accounts/**` | 对应 `platform.service_account.*` |
| `/api/platform/v1/audit/**` | 对应 `platform.audit.*` |
| `/api/platform/v1/events/**` | `platform.event.read` |

未列出的接口以 OpenAPI `security` / 操作描述为准；新增接口必须同时声明权限点。

---

## 11. 数据库与种子

### 11.1 表映射

| 概念 | 表 |
|---|---|
| 权限点 | `core.permission` |
| 平台角色 | `core.role` (`scope='PLATFORM'`) |
| 平台角色权限 | `core.platform_role_permission` |
| 租户/组织角色权限 | `core.role_permission` |
| 平台授予 | `core.platform_role_grant` + `core.platform_role_grant_scope` |
| 租户角色分配 | `core.tenant_role_assignment` |
| 组织角色分配 | `core.organization_role_assignment` |
| 权限版本 | 各实体 `permission_version` |

### 11.2 种子顺序

1. 插入/更新核心权限点（`0002_seed_permissions.sql`）。
2. 插入平台角色及平台角色权限（`0003_seed_platform_roles.sql`）。
3. 租户创建时按模板生成租户角色与权限。
4. 组织创建时按模板生成组织角色与权限。

### 11.3 一致性检查

CI 必须校验：

```sql
-- 权限目录中不存在未知作用域
SELECT code FROM core.permission
WHERE scope NOT IN ('PLATFORM','TENANT','ORGANIZATION');

-- 扩展权限必须使用 ext. 前缀且 module 非空
SELECT code FROM core.permission
WHERE namespace = 'EXT'
  AND (module IS NULL OR code NOT LIKE 'ext.' || module || '.%');

-- 平台角色不得包含 ORGANIZATION 以外的越权组合（按业务规则校验）
SELECT r.code, p.code
FROM core.role r
JOIN core.platform_role_permission prp ON prp.role_id = r.id
JOIN core.permission p ON p.code = prp.permission_code
WHERE r.scope <> 'PLATFORM';

-- 超级管理员必须拥有全部平台权限
SELECT p.code
FROM core.permission p
WHERE p.scope = 'PLATFORM'
  AND p.status = 'ACTIVE'
  AND NOT EXISTS (
      SELECT 1
      FROM core.platform_role_permission prp
      JOIN core.role r ON r.id = prp.role_id
      WHERE r.code = 'platform_super_admin'
        AND prp.permission_code = p.code
  );
```

---

## 12. 测试要求

### 12.1 单元测试

- 权限点编码解析与作用域校验。
- 平台授权范围匹配：`ALL` / `TENANT` / `ORGANIZATION` / `ORG_TYPE`。
- `include_descendants` 边界：当前组织、后代、祖先、兄弟、跨租户。
- 组织角色继承：当前组织、祖先生效，后代/兄弟不生效。
- 所有者通配不跨作用域。
- 服务账号 scopes 作用域校验。

### 12.2 集成测试（真实 PostgreSQL）

1. 租户 A 成员读取租户 B 资源 → `404`。
2. 伪造 `X-Tenant-Id` → 不改变 RLS 上下文。
3. 平台角色 `TENANT` 范围只能操作指定租户。
4. 平台角色 `ORGANIZATION` 范围 + `include_descendants=true` 可操作后代，不能操作祖先/兄弟。
5. 租户角色中的 `organization.*` 权限覆盖租户内全部组织。
6. 组织角色在祖先组织授予，后代组织生效。
7. 组织角色在子组织授予，父组织不生效。
8. 撤销角色后旧 Token `pv` 不匹配 → `401`。
9. 租户角色权限变更后租户内所有旧 Token → `401`。
10. 授予自身没有的权限 → `403 PERMISSION_ESCALATION_DENIED`。
11. 修改所有者角色权限 → `403`。
12. 直接设置 `is_owner=true` → `403` / 数据库约束失败。
13. 平台用户无 `ALL` 范围列出全部租户 → `403`。
14. 扩展注册 `platform.*` → 启动失败。
15. 服务账号 scopes 含 `platform.*` 但为租户级 → 创建失败。
16. 高危权限无 step-up（二期）→ `403 STEP_UP_REQUIRED`。

### 12.3 契约测试

- OpenAPI 中每个受保护操作必须声明权限点，**或**声明 `x-subject-authz`（主体式授权，规则见 §7.6）；契约测试同时校验其一，两者皆无视为缺陷。
- 权限点必须存在于 `core.permission`。
- 扩展 OpenAPI 只能引用 `ext.<module>.*`。

---

## 13. 相关文档

- [总体架构 V2.0](../00-architecture/architecture-v2.0.md)
- [架构决策 V2.0](../00-architecture/decisions-v2.0.md)
- [扩展 SPI V2.0](../00-architecture/extension-spi-v2.0.md)
- [需求规格 V2.0](../10-requirements/requirements-v2.0.md)
- [技术设计 V2.0](tech-design-v2.0.md)
- [数据库设计 V2.0](database-design-v2.0.md)
- [状态机 V2.0](state-machines-v2.0.md)
- [OpenAPI V2.0](../30-api/openapi-v2.0.yaml)
- [运维与测试 V2.0](../40-operations/operations-v2.0.md)
