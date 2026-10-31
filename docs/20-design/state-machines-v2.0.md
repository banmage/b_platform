# b_platform 状态机与并发规则 V2.0

**项目：** b_platform（通用业务底座平台·控制面）  
**版本：** V2.0  
**状态：** 设计基线（待评审）  
**对应需求：** `docs/10-requirements/requirements-v2.0.md`  
**对应数据库：** `docs/20-design/database-design-v2.0.md`

---

## 1. 文档定位

本文是租户、组织、成员、角色、转让、扩展等核心状态机的权威定义。各节末尾的“审计动作”与状态图中的 Outbox 标注是**概要**：审计编码以 [审计动作目录](audit-catalog-v2.0.md) 为准，事件编码以 [事件目录](event-catalog-v2.0.md) 为准；本文清单与目录冲突时以目录为准，但新增转换必须双向同步。

**状态机间与文档间不一致时，状态与并发规则以本节为准；权限编码以权限模型为准；错误响应以 [错误码目录](error-codes-v2.0.md) 为准。**

本文档定义 b_platform 核心实体的状态、允许的转换、触发权限、并发控制、幂等语义和副作用。所有状态字段、`CHECK` 约束、Service 方法和测试用例必须与本文档一致。

覆盖实体：

- 平台用户、会话、一次性令牌
- 租户、租户成员、邀请
- 组织、组织审批、所有权转让
- 角色、角色分配
- 服务账号、API Key
- 扩展
- Outbox 事件、Webhook 投递、幂等键
- 权限点

---

## 2. 通用规则

1. 状态值使用大写蛇形字符串，只增不改；删除状态需要迁移和兼容期。
2. 终态不可逆，除非本文档明确给出回退路径。
3. 每次状态转换必须：
   - 校验当前状态（`WHERE id = $1 AND status = $expected`）；
   - 校验操作者权限；
   - 递增相关 `permission_version`；
   - 在同一事务写审计；已标注 Outbox 的转换在同一事务写领域事件（事件清单以事件目录为唯一权威）；
   - 返回最新状态。
4. 重复请求的幂等语义：
   - 已处于目标状态：返回 `200`/`204`，不重复写审计；
   - 状态冲突：返回 `409 STATE_CONFLICT`；
   - 资源不存在或不可见：统一 `404`。
5. 状态转换不得由客户端直接指定目标状态；只能调用语义化 action。
6. 后台任务不得绕过状态机；清理任务只处理终态数据。

---

## 3. 平台用户

### 3.1 状态

```text
PENDING_VERIFICATION ──verify──> ACTIVE ──disable──> DISABLED
          │                        │  ^                  │
          │                        │  └────enable────────┘
          │                        │
          │                     lock (failed logins)
          │                        ▼
          │                      LOCKED
          │                        │
          └──────verify────────────┴──unlock/timeout──> ACTIVE
```

| 状态 | 说明 |
|---|---|
| `PENDING_VERIFICATION` | 已注册，未完成邮箱/手机验证 |
| `ACTIVE` | 正常可用 |
| `LOCKED` | 连续登录失败临时锁定 |
| `DISABLED` | 平台运营禁用 |

### 3.2 转换

| From | 事件 | To | 权限/条件 | 副作用 |
|---|---|---|---|---|
| `PENDING_VERIFICATION` | 验证联系方式 | `ACTIVE` | 一次性令牌有效 | 递增 `u pv`、审计 |
| `PENDING_VERIFICATION` | 平台启用 | `ACTIVE` | `platform.user.enable` | 递增 `u pv`、审计 |
| `ACTIVE` | 登录失败达阈值 | `LOCKED` | 自动 | 设置 `locked_until`、审计 |
| `LOCKED` | 锁定到期 / 管理员解锁 | `ACTIVE` | 时间到 / `platform.user.enable` | 清空失败计数、审计 |
| `ACTIVE` / `LOCKED` | 平台禁用 | `DISABLED` | `platform.user.disable` | 递增 `u pv`、撤销全部会话、审计 |
| `DISABLED` | 平台启用 | `ACTIVE` | `platform.user.enable` | 递增 `u pv`、审计；不恢复成员关系 |
| `PENDING_VERIFICATION` | 平台禁用 | `DISABLED` | `platform.user.disable` | 递增 `u pv`、审计 |

规则：

- `LOCKED` 是临时状态，不递增 `permission_version`；但登录被拒绝。
- `DISABLED` 必须撤销所有 `ACTIVE` 会话。
- 重新启用不自动恢复租户/组织成员关系。
- 用户不物理删除。

审计动作：`auth.registered`、`auth.login_succeeded`、`auth.login_failed`、`platform.user.verified`、`platform.user.locked`、`platform.user.unlocked`、`platform.user.disabled`、`platform.user.enabled`。

---

## 4. 会话与令牌

### 4.1 用户会话

```text
ACTIVE ──refresh──> ROTATED
   │
   ├──logout / revoke / password reset / user disabled──> REVOKED
   │
   └──expires_at reached──> EXPIRED
```

| 状态 | 说明 |
|---|---|
| `ACTIVE` | 当前 Refresh Token 有效 |
| `ROTATED` | 已被刷新替换，保留用于重用检测 |
| `REVOKED` | 主动撤销/安全事件撤销 |
| `EXPIRED` | 超过 `expires_at` |

规则：

1. 刷新时旧会话置 `ROTATED`，`replaced_by` 指向新会话；新会话同 `family_id`。
2. 检测到 `ROTATED` 或 `REVOKED` 的 Refresh Token 被再次使用：撤销整个 family，写安全审计。
3. 登出只撤销当前会话；密码重置/用户禁用撤销全部会话。
4. `EXPIRED` 由清理任务批量标记，不实时阻塞读取（读取时仍校验时间）。
5. 会话表允许物理清理过期数据，保留期 30 天。

### 4.2 一次性令牌

```text
ISSUED ──consume──> CONSUMED
   │
   ├──expires_at reached──> EXPIRED（派生状态）
   └──revoke──> CONSUMED（撤销同样写 `consumed_at`，不设独立 REVOKED 状态）
```

- 数据库只存 `consumed_at` 与 `expires_at`，状态为派生值。
- 撤销与消费共用终结写 `consumed_at`；语义由审计动作区分（消费走所属业务审计，撤销写 `security.one_time_token_revoked`）。
- 同一令牌只能成功消费一次；并发消费使用 `UPDATE ... WHERE consumed_at IS NULL`，影响行数为 0 → 拒绝。
- 消费后递增 `u pv`（密码重置场景）并撤销相关会话。

审计动作：`session.revoked`、`security.token_reuse_detected`、`security.one_time_token_revoked`、`auth.password_reset_requested`、`auth.password_reset`、`auth.password_changed`。概要为汇总，编码以审计目录为准。

---

## 5. 租户

### 5.1 状态

```text
PROVISIONING ──complete──> ACTIVE ──freeze──> FROZEN
      │                       │  ^              │
      │                       │  └──unfreeze────┘
      │                       │
      └────fail───┐           ├──close──> CLOSED
                  ▼           │
               CLOSED <───────┘
```

| 状态 | 说明 |
|---|---|
| `PROVISIONING` | 创建中，尚未完成初始化 |
| `ACTIVE` | 正常 |
| `FROZEN` | 冻结，拒绝业务写操作 |
| `CLOSED` | 关闭，保留数据，拒绝登录与写入 |

### 5.2 转换

| From | 事件 | To | 权限 | 副作用 |
|---|---|---|---|---|
| — | 创建租户 | `PROVISIONING` | `platform.tenant.create` | 创建租户、owner 成员、owner 角色、审计、Outbox |
| `PROVISIONING` | 初始化完成 | `ACTIVE` | 系统 | 递增 `t pv`、审计 |
| `PROVISIONING` | 初始化失败 | `CLOSED` | 系统 | 审计；数据保留 |
| `ACTIVE` | 冻结 | `FROZEN` | `platform.tenant.freeze` | 递增 `t pv`、审计、Outbox |
| `FROZEN` | 解冻 | `ACTIVE` | `platform.tenant.freeze` | 递增 `t pv`、审计、Outbox |
| `ACTIVE` / `FROZEN` | 关闭 | `CLOSED` | `platform.tenant.close` | 递增 `t pv`、撤销租户内会话、审计、Outbox |
| `CLOSED` | 强制管理 | `CLOSED` | `platform.tenant.force_manage` | 仅允许只读/导出，写审计 |

规则：

1. `slug` 创建后不可修改。
2. 创建租户必须在同一事务内创建：`tenant`、初始 `tenant_membership`（owner）、`tenant_owner` 角色分配、审计、Outbox。
3. 冻结期间：拒绝所有业务写操作；读操作按接口策略允许或拒绝；平台仅允许解冻或经审计的强制管理。
4. 关闭后：禁止登录、禁止写入；数据保留，不物理删除。
5. 租户状态变化影响所有租户内 Token：冻结/关闭递增 `t pv`。
6. 平台跨租户强制操作必须写 `platform.audit.cross_tenant_access`。

### 5.3 创建流程（同一事务）

```text
BEGIN
  INSERT tenant (status=PROVISIONING)
  INSERT platform_user? （初始 owner 必须已存在）
  INSERT tenant_membership (owner, ACTIVE)
  INSERT role (tenant_owner, is_owner_role=true)
  INSERT role_permission（模板权限，仅展示；判定按通配）
  INSERT tenant_role_assignment
  UPDATE tenant SET status='ACTIVE', owner_user_id=...
  INSERT audit_log
  INSERT outbox_event('tenant.created')
COMMIT
```

- 初始 owner 必须是 `ACTIVE` 平台用户。
- 任一步失败回滚整个事务。
- 租户创建后发送 `tenant.created` 事件；消费者幂等。

审计动作：`platform.tenant.created`、`platform.tenant.activated`、`platform.tenant.frozen`、`platform.tenant.unfrozen`、`platform.tenant.closed`、`platform.tenant.force_managed`。

---

## 6. 租户成员与邀请

### 6.1 成员状态

```text
INVITED ──accept──> ACTIVE ──suspend──> SUSPENDED
   │                  │  ^                 │
   │                  │  └────activate─────┘
   │                  │
   └──revoke/expire──> INACTIVE <──remove──┘
```

| 状态 | 说明 |
|---|---|
| `INVITED` | 已邀请，未接受 |
| `ACTIVE` | 正常成员 |
| `SUSPENDED` | 暂停，保留成员关系 |
| `INACTIVE` | 已移除/邀请失效，保留历史 |

### 6.2 转换

| From | 事件 | To | 权限/条件 | 副作用 |
|---|---|---|---|---|
| — | 邀请已存在用户 | `INVITED` | `tenant.member.invite` | 创建成员/邀请、审计、Outbox |
| `INVITED` | 接受邀请 | `ACTIVE` | 令牌有效、用户匹配 | 递增 `m pv`、审计 |
| `INVITED` | 撤销/过期 | `INACTIVE` | `tenant.member.remove` / 时间到 | 审计 |
| `ACTIVE` | 暂停 | `SUSPENDED` | `tenant.member.suspend` | 递增 `m pv`、审计 |
| `SUSPENDED` | 恢复 | `ACTIVE` | `tenant.member.activate` | 递增 `m pv`、审计 |
| `ACTIVE` / `SUSPENDED` | 移除 | `INACTIVE` | `tenant.member.remove` | 递增 `m pv`、撤销组织成员、审计、Outbox |

规则：

1. 同一用户同一租户最多一条非 `INACTIVE` 记录（部分唯一索引）。
2. 移除使用 `INACTIVE`，不物理删除；重新加入创建新记录。
3. 移除租户成员时，其组织成员关系一并置 `INACTIVE`，组织角色分配删除（保留审计）。
4. 暂停租户成员时，是否级联暂停组织成员由租户配置 `membership.suspend_cascade` 决定，默认 `true`。
5. 不能移除最后一个所有者；所有者变更只能走转让流程。
6. 成员状态变化递增 `m pv`；角色变更也递增 `m pv`。

### 6.3 邀请状态

```text
PENDING ──accept──> ACCEPTED
   │
   ├──revoke──> REVOKED
   └──expires_at reached──> EXPIRED
```

- 邀请按 `(tenant_id, organization_id, lower(email))` 唯一，仅对 `PENDING` 生效。
- 邀请令牌只存哈希；接受时校验邮箱、租户、可选组织。
- 接受邀请时：若用户不存在，先完成注册/验证，再创建成员；整个过程同一事务。
- 邀请过期时间默认 7 天，可配置。
- 接受/撤销/过期写审计。

审计动作：`tenant.member.invited`、`tenant.member.joined`、`tenant.member.suspended`、`tenant.member.activated`、`tenant.member.removed`、`tenant.invitation.revoked`、`tenant.invitation.expired`。

---

## 7. 组织

### 7.1 状态

```text
PENDING ──approve──> ACTIVE ──freeze──> FROZEN
   │                    │  ^              │
   ├──reject──> REJECTED│  └──unfreeze────┘
   │                    │
   └──withdraw─> WITHDRAWN
                        └──archive──> ARCHIVED
```

| 状态 | 说明 |
|---|---|
| `PENDING` | 待审批（仅需审批时） |
| `ACTIVE` | 正常 |
| `REJECTED` | 审批拒绝，保留记录 |
| `WITHDRAWN` | 申请人撤回，保留记录 |
| `FROZEN` | 冻结，拒绝该组织写操作 |
| `ARCHIVED` | 归档，只读 |

### 7.2 转换

| From | 事件 | To | 权限/条件 | 副作用 |
|---|---|---|---|---|
| — | 直接创建（无需审批） | `ACTIVE` | `tenant.organization.create` | 创建组织、闭包、owner 成员/角色、审计、Outbox |
| — | 创建待审批 | `PENDING` | `tenant.organization.create` | 创建组织（不可用）、审批记录、审计 |
| `PENDING` | 审批通过 | `ACTIVE` | `tenant.organization.approve` | 审批记录更新、创建 owner 成员/角色、闭包、审计、Outbox |
| `PENDING` | 审批拒绝 | `REJECTED` | `tenant.organization.approve` | 审批记录更新、审计 |
| `PENDING` | 申请人撤回 | `WITHDRAWN` | 创建者/`tenant.organization.create` | 审批记录更新、审计 |
| `ACTIVE` | 冻结 | `FROZEN` | `tenant.organization.freeze` | 递增 `o pv`、审计、Outbox |
| `FROZEN` | 解冻 | `ACTIVE` | `tenant.organization.freeze` | 递增 `o pv`、审计、Outbox |
| `ACTIVE` / `FROZEN` | 归档 | `ARCHIVED` | `tenant.organization.freeze` | 递增 `o pv`、审计、Outbox |

规则：

1. 父子组织必须同租户，由复合外键保证。
2. 组织创建是否需要审批由租户配置 `organization.require_approval` 决定；平台参数提供默认值。
3. `PENDING` 组织不能被普通成员访问；只有申请人、审批人和平台管理员可见。
4. 组织创建/审批通过时必须在同一事务内：
   - 插入 `organization`；
   - 插入 `organization_closure`（自身 + 父节点祖先）；
   - 创建 owner 成员与 `org_owner` 角色；
   - 写审计与 Outbox。
5. 一期不支持父组织变更和物理删除；接口返回 `409` / `405`。
6. 祖先冻结是否级联拒绝由租户配置 `organization.freeze_cascade` 决定，默认 `true`；判定时通过闭包查询祖先状态。
7. 组织冻结/归档递增 `o pv`；组织内成员 Token 失效。

### 7.3 闭包表维护

```text
创建组织 C（父 P）：
  INSERT (C, C, 0)
  INSERT (ancestor, C, depth+1)
    SELECT ancestor_id, C, depth + 1
    FROM organization_closure
    WHERE descendant_id = P
```

约束：

- 闭包写入与组织写入同一事务。
- 深度上限检查：`max(depth) + 1 <= organization.max_depth`。
- 禁止跨租户父子；复合外键已保证。
- 闭包表只允许 `INSERT` / `DELETE`，不允许 `UPDATE`。
- 组织归档不删除闭包；组织不物理删除。

### 7.4 组织审批

```text
PENDING ──approve──> APPROVED
   │
   ├──reject──> REJECTED
   └──withdraw──> WITHDRAWN
```

- 审批记录与组织状态在同一事务更新，保持一致。
- 审批人必须是租户管理员或具备 `tenant.organization.approve` 的成员；不能审批自己创建的组织（可配置）。
- 一个组织同时最多一条 `PENDING` 审批（部分唯一索引）。
- 审批通过时创建 owner 成员与角色；审批拒绝/撤回不创建成员。
- 审批操作使用 `SELECT ... FOR UPDATE` 锁定审批记录和组织。

审计动作：`tenant.organization.created`、`tenant.organization.approved`、`tenant.organization.rejected`、`tenant.organization.withdrawn`、`tenant.organization.frozen`、`tenant.organization.unfrozen`、`tenant.organization.archived`。

---

## 8. 所有权转让

### 8.1 状态

```text
PENDING ──accept──> ACCEPTED
   │
   ├──decline──> DECLINED
   ├──cancel───> CANCELLED
   ├──expire───> EXPIRED
   └──force────> FORCED（平台强制）
```

| 状态 | 说明 |
|---|---|
| `PENDING` | 已发起，等待目标接受 |
| `ACCEPTED` | 目标接受，所有权已转移 |
| `DECLINED` | 目标拒绝 |
| `CANCELLED` | 发起人取消 |
| `EXPIRED` | 超时未处理 |
| `FORCED` | 平台强制完成 |

### 8.2 转换

| From | 事件 | To | 权限/条件 | 副作用 |
|---|---|---|---|---|
| — | 发起转让 | `PENDING` | 租户：`tenant.transfer`；组织：`organization.transfer` / `tenant.organization.transfer`（租户级强制） | 创建转让记录、审计、Outbox |
| `PENDING` | 目标接受 | `ACCEPTED` | 目标用户、未过期 | 更新 owner 标记、owner 角色分配、递增相关 pv、审计、Outbox |
| `PENDING` | 目标拒绝 | `DECLINED` | 目标用户 | 审计 |
| `PENDING` | 发起人取消 | `CANCELLED` | 发起人/当前所有者 | 审计 |
| `PENDING` | 超时 | `EXPIRED` | 系统 | 审计 |
| `PENDING` | 平台强制 | `FORCED` | `platform.tenant.force_manage` / `platform.cross_tenant.access` | 更新所有权、审计、Outbox |

规则：

1. 同一租户/组织同时最多一条 `PENDING` 转让（部分唯一索引）。
2. 目标必须是有效成员（租户成员或组织成员），且状态 `ACTIVE`。
3. 转让完成必须在同一事务内：
   - 旧所有者 `is_owner=false`，移除 `owner` 角色分配；
   - 新所有者 `is_owner=true`，分配 `owner` 角色；
   - 更新实体 `owner_user_id`；
   - 递增 `tenant`/`organization` 与相关成员 `permission_version`；
   - 写审计与 Outbox。
4. 转让期间对租户/组织加 `FOR UPDATE` 行锁，锁定顺序见 §12。
5. 强制转让必须写 `platform.audit.cross_tenant_access` 审计，并在同事务写事件 `ownership.transfer.forced`（事件目录 §4.4）。
6. 过期时间默认 7 天，可配置。

审计动作：`ownership.transfer.requested`、`ownership.transfer.accepted`、`ownership.transfer.declined`、`ownership.transfer.cancelled`、`ownership.transfer.expired`、`ownership.transfer.forced`。

---

## 9. 角色与分配

### 9.1 角色状态

```text
ACTIVE <──disable/enable──> DISABLED
```

| 状态 | 说明 |
|---|---|
| `ACTIVE` | 可分配、可判定 |
| `DISABLED` | 不可新分配；已有分配是否生效由配置决定，默认不生效 |

规则：

- 角色不物理删除。
- 停用角色递增对应作用域的 `permission_version`（租户角色 → `t pv`；组织角色 → `o pv`）。
- 所有者角色不能停用。
- 系统角色不能改名/改作用域；只能改描述（所有者角色连描述也不建议改）。

### 9.2 分配

- 租户角色分配：`tenant_role_assignment` 行存在即生效；撤销为物理删除 + 审计。
- 组织角色分配：`organization_role_assignment` 行存在即生效；撤销为物理删除 + 审计。
- 分配前校验：
  - 成员 `ACTIVE`；
  - 角色 `ACTIVE`；
  - 角色作用域与分配层级一致；
  - 操作者权限集合是目标角色权限集合的超集；
  - 所有者角色只能走转让。
- 分配/撤销递增成员 `permission_version`（`m pv` / `om pv`）。

审计动作：`tenant.role.assigned`、`tenant.role.revoked`、`organization.role.assigned`、`organization.role.revoked`、`role.created`、`role.updated`、`role.permissions_changed`、`role.disabled`、`role.enabled`。

---

## 10. 服务账号与 API Key

### 10.1 服务账号

```text
ACTIVE <──disable/enable──> DISABLED
```

| 状态 | 说明 |
|---|---|
| `ACTIVE` | 可签发 Token / 使用 API Key |
| `DISABLED` | 禁止认证；已有 Token 在 TTL 内仍可能有效，需撤销会话/Key |

规则：

- `expires_at` 到期由认证时校验，状态不自动变；到期后拒绝签发与调用。
- 禁用服务账号时撤销其全部 API Key，并写审计。
- 服务账号不物理删除，保留审计关联。

### 10.2 API Key

```text
ACTIVE ──revoke──> REVOKED
   │
   └──expires_at reached──> EXPIRED
```

| 状态 | 说明 |
|---|---|
| `ACTIVE` | 可用 |
| `REVOKED` | 已撤销 |
| `EXPIRED` | 已过期 |

规则：

- API Key 只在创建时显示一次明文，库中只存哈希。
- 撤销立即生效；`last_used_at` 异步更新（允许延迟）。
- 服务账号禁用时批量撤销其 Key。
- 过期清理只更新状态，不删除记录（保留审计）。

审计动作：`service_account.created`、`service_account.updated`、`service_account.disabled`、`service_account.enabled`、`api_key.created`、`api_key.revoked`、`security.api_key_anomaly`、`service_account.authenticated`。

---

## 11. 扩展、事件与幂等

### 11.1 扩展

```text
REGISTERED ──enable──> ACTIVE ──disable──> DISABLED
     ^                    │                   │
     └──────enable────────┴───────────────────┘
```

| 状态 | 说明 |
|---|---|
| `REGISTERED` | 已注册，未启用 |
| `ACTIVE` | 路由/权限/事件生效 |
| `DISABLED` | 路由不挂载，数据保留 |

规则：

- 启用前检查迁移版本、API 版本、权限命名空间冲突。
- 禁用不删除数据、不删除权限点。
- 扩展升级保持 `ACTIVE`/`DISABLED` 状态，更新版本与 Manifest。
- 卸载只允许禁用，不自动删除 schema 或数据。

审计动作：`platform.extension.registered`、`platform.extension.enabled`、`platform.extension.disabled`、`platform.extension.upgraded`。

### 11.2 Outbox 事件

```text
PENDING ──dispatch ok──> DISPATCHED
   │
   ├──retryable fail──> FAILED ──retry──> PENDING
   │                      │
   │                      └──max attempts──> DEAD
   └──non-retryable fail──> DEAD
```

| 状态 | 说明 |
|---|---|
| `PENDING` | 待投递 |
| `FAILED` | 可重试失败，等待 `available_at` |
| `DISPATCHED` | 已投递 |
| `DEAD` | 超过重试上限或不可重试 |

规则：

- Worker 使用 `FOR UPDATE SKIP LOCKED` 批量领取。
- 至少一次投递；消费者必须幂等。
- 指数退避：`min(2^attempts * 1s, 5m)` + 抖动。
- 默认最大 10 次；超过进入 `DEAD` 并告警。
- `DISPATCHED` / `DEAD` 为终态；清理任务按保留期删除。

### 11.3 Webhook 投递

```text
PENDING ──2xx──> DELIVERED
   │
   ├──retryable fail──> FAILED ──retry──> PENDING
   │                      │
   │                      └──max attempts──> DEAD
   └──non-retryable fail──> DEAD
```

- 每个 `(endpoint_id, event_id)` 唯一。
- 签名包含时间戳与 HMAC，接收方必须防重放。
- 4xx（除 408/429）视为不可重试；5xx/网络错误可重试。
- 同一端点并发投递受租户级并发限制。

### 11.4 幂等键

```text
IN_PROGRESS ──success──> COMPLETED
      │
      └──business fail──> FAILED
```

| 状态 | 说明 |
|---|---|
| `IN_PROGRESS` | 首次请求处理中 |
| `COMPLETED` | 已提交，保存响应快照 |
| `FAILED` | 业务失败，未产生副作用 |

规则：

1. 键：`(tenant_id, principal_type, principal_id, endpoint, idem_key)` 唯一。
2. 相同键 + 相同请求哈希：
   - `COMPLETED` → 返回原响应；
   - `IN_PROGRESS` → `409 IDEMPOTENCY_IN_PROGRESS`；
   - `FAILED` → `409 IDEMPOTENCY_FAILED`（客户端换新键重试）。
3. 相同键 + 不同请求哈希 → `409 IDEMPOTENCY_CONFLICT`。
4. `FAILED` 为终态，不自动重试。
5. TTL 默认 24h，过期清理。

---

## 12. 并发与锁

### 12.1 乐观锁

- 使用 `updated_at` 作为版本令牌（ETag）。
- 更新语句：

```sql
UPDATE core.organization
SET name = $1, updated_at = now()
WHERE id = $2
  AND updated_at = $3
  AND tenant_id = core.app_current_tenant_id();
```

- 影响行数为 0 → `409 VERSION_CONFLICT` 或 `412 PRECONDITION_FAILED`。
- 高风险实体（角色、授权、所有权）强制乐观锁。
- `updated_at` 精度为微秒；API 返回的 ETag 使用哈希，不直接暴露数据库时间格式。

### 12.2 悲观锁

使用 `SELECT ... FOR UPDATE` 的场景：

| 场景 | 锁定对象 |
|---|---|
| 所有权转让 | `tenant` / `organization` → owner `membership` → `ownership_transfer` |
| 组织审批 | `organization_approval` → `organization` |
| 租户冻结/关闭 | `tenant` → `tenant_membership`（owner） |
| 角色权限修改 | `role` → `role_permission` |
| 平台授权修改 | `platform_role_grant` → `platform_role_grant_scope` |
| 组织闭包写入 | `organization`（父）→ `organization_closure` |

### 12.3 锁顺序

固定顺序，禁止逆序：

```text
tenant
  → organization（按 id ASC）
  → tenant_membership
  → organization_membership
  → role
  → role_permission / assignment
  → audit_log / outbox_event（追加写，不锁读）
```

规则：

- 多行锁按主键排序。
- `lock_timeout = 3s`；超时返回 `409 CONCURRENT_MODIFICATION`。
- 事务内不调用外部服务；Outbox 异步投递。
- 单事务目标 < 2s；批量操作拆分。

### 12.4 唯一约束冲突

| 冲突 | 处理 |
|---|---|
| 租户 slug 重复 | `409 TENANT_SLUG_EXISTS` |
| 成员有效记录重复 | `409 MEMBERSHIP_EXISTS` |
| 组织同级重名 | `409 ORGANIZATION_NAME_EXISTS` |
| 所有者重复 | `409 OWNER_EXISTS`（数据库约束兜底） |
| 待审批重复（转让场景使用 `OWNER_TRANSFER_PENDING`） | `409 PENDING_REQUEST_EXISTS` |
| 幂等键重复 | 按 §11.4 处理 |
| API Key 哈希冲突 | 重新生成（概率可忽略） |

### 12.5 重试

- 只对幂等操作重试。
- 数据库序列化失败/死锁：最多重试 2 次，使用新事务。
- 网络超时：不自动重试写请求；客户端使用幂等键重试。
- 事务提交结果未知：先按幂等键查询结果，再决定是否重试。

---

## 13. 状态与权限版本对照

| 实体 | 状态字段 | 权限版本字段 | 状态变化是否递增 pv |
|---|---|---|---|
| `platform_user` | `status` | `permission_version` | 是（禁用/启用） |
| `tenant` | `status` | `permission_version` | 是（冻结/关闭/解冻） |
| `tenant_membership` | `status` | `permission_version` | 是 |
| `organization` | `status` | `permission_version` | 是（冻结/归档/解冻） |
| `organization_membership` | `status` | `permission_version` | 是 |
| `role` | `status` | 无（影响所属 scope 的 pv） | 是 |
| `service_account` | `status` | 无（Token TTL 内有效） | 撤销 Key + 审计 |
| `api_key` | `status` | 无 | 立即拒绝 |
| `extension_registry` | `status` | 无 | 启用/禁用审计 |

---

## 14. 测试要求

### 14.1 状态转换测试

每个实体至少覆盖：

1. 合法转换成功，状态与副作用正确。
2. 非法转换返回 `409`，数据不变。
3. 重复请求幂等。
4. 并发两个相同请求只有一个成功。
5. 转换失败回滚审计/Outbox。
6. 权限不足返回 `403`。
7. 跨租户访问返回 `404`。

### 14.2 重点场景

- 租户创建失败回滚，不残留 owner 成员/角色。
- 租户冻结后旧 Token 的 `t pv` 不匹配。
- 组织审批通过后闭包、owner、角色一次性完成。
- 组织角色在祖先授予、后代生效。
- 所有权转让并发：两个转让只有一个 `PENDING`。
- 所有者直接改派被拒绝。
- Outbox 投递失败重试后进入 `DEAD`。
- Webhook 4xx 不重试，5xx 重试。
- 幂等键并发：一个 `IN_PROGRESS`，另一个 `409`。
- 锁顺序错误（人为逆序）在集成测试中触发死锁并验证重试。

---

## 15. 相关文档

- [总体架构 V2.0](../00-architecture/architecture-v2.0.md)
- [架构决策 V2.0](../00-architecture/decisions-v2.0.md)
- [扩展 SPI V2.0](../00-architecture/extension-spi-v2.0.md)
- [需求规格 V2.0](../10-requirements/requirements-v2.0.md)
- [技术设计 V2.0](tech-design-v2.0.md)
- [数据库设计 V2.0](database-design-v2.0.md)
- [权限模型 V2.0](permission-model-v2.0.md)
- [OpenAPI V2.0](../30-api/openapi-v2.0.yaml)
- [运维与测试 V2.0](../40-operations/operations-v2.0.md)
