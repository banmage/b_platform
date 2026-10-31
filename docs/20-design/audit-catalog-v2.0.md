# b_platform 审计动作目录 V2.0

**版本：** V2.0
**日期：** 2026-10-31
**对应：** 权限模型 V2.0、状态机 V2.0、数据库设计 V2.0 §6.7、OpenAPI V2.0
**状态：** 设计基线（待评审）

---

## 1. 文档定位

本文是 `core.audit_log.action` 字段的**唯一权威清单**。状态机文档各节末尾的“审计动作”只是概要；两处不一致时，以本文为准。

覆盖范围：

- 所有用户/服务账号可触发的关键写操作的审计动作；
- 系统触发（阈值锁定、Token 重用检测、转让过期等）的审计动作；
- 审计自身读写（满足 `FR-A-04`）的审计动作。

不在此清单内的请求不产生审计记录；登录尝试的流水记录在 `core.login_attempt`，不逐条写审计（见 §2.1）。

---

## 2. 通用规则

### 2.1 写入规则

1. 业务写操作的审计与业务**同一事务**写入（`FR-A-02`），失败即回滚。
2. 读路径例外：审计查询/导出动作（`*.audit.queried/exported`）在独立短事务写入；写入失败仅告警，不中断查询。
3. 迁移与种子写入由 `platform_migrator` 执行，**不写审计**；分区归档等运维作业按 §3.2 记录（`actor_type=SYSTEM`）。
4. `action` 一经发布**不可修改**；只允许新增，废弃时将状态标注为 `DEPRECATED` 并保留原编码至少一个主版本周期。
5. 同一动作并发触发各写一条，不合并、不采样。
6. 多租户/组织上下文切换（`switchContext`）一期**不写审计**（已认证级读取行为，由应用日志与指标承载），二期工程补（预评审决议 D-09）。

### 2.2 result 语义

| result | 语义 |
|---|---|
| `SUCCESS` | 动作完成，业务事务提交 |
| `DENIED` | 动作被权限/状态约束拒绝（高危操作拒绝必审计，见 §4） |
| `FAILURE` | 动作执行失败但已提交外侧状态（如 Webhook 投递失败、审计导出文件生成失败） |

拒绝时的 `action` 与对应成功动作**完全相同**，用 `result=DENIED` 区分，不引入 `-denied` 后缀编码。

### 2.3 命名规则

```text
action = <域>.<实体>.<过去式动词>    # 如 ownership.transfer.accepted
       | <实体>.<过去式动词>        # 如 role.disabled、service_account.created
```

- 全小写；实体名可含下划线（`service_account`、`api_key`）。
- `platform.` 前缀表示平台控制面操作；`tenant.` / `organization.` 前缀表示租户/组织内操作。
- 新增动作时必须优先复用已有动词：`created` / `updated` / `disabled` / `enabled` / `revoked` / `granted`。

### 2.4 上下文字段

审计事务内必须设置的上下文：

- `request_id`、`trace_id` 来自请求；
- `tenant_id`、`organization_id` 来自生效租户上下文；平台级操作为 `NULL`；
- 服务账号触发时 `actor_type='SERVICE_ACCOUNT'`；系统任务触发时 `actor_type='SYSTEM'`、`actor_id=NULL`。

### 2.5 运维 Feature Flag 映射

运维文档（`operations-v2.0.md §7.5`）要求的“Flag 变更必须审计”按 Flag 承载物落入现有编码，**不新增** Flag 专用编码：

- 平台参数类 Flag（如 MFA 要求）→ `platform.param.updated`；
- 租户级开关（如级联冻结、组织审批）→ `tenant.config.updated`；
- 扩展启停类 Flag → `platform.extension.enabled` / `disabled`。

---

## 3. 动作清单

列：编码 | 触发时机 | 默认 result | `target_type` | 接口锚点（`operationId`）

### 3.1 认证与会话（`auth` / `platform.user` / `security`）

| 编码 | 触发时机 | result | target_type | 接口锚点 |
|---|---|---|---|---|
| `auth.registered` | 注册成功，创建用户 | SUCCESS | `platform_user` | `register` |
| `auth.login_succeeded` | 登录成功 | SUCCESS | `platform_user` | `login` |
| `auth.login_failed` | 失败达到阈值触发锁定判定时记录；普通失败与限流拦截只写 `login_attempt`，不写审计（§4 规则 3） | DENIED | `platform_user` | `login` |
| `platform.user.locked` | 失败达阈值，系统自动锁定 | SUCCESS | `platform_user` | `login`（系统） |
| `platform.user.verified` | 邮箱/手机验证成功 | SUCCESS | `platform_user` | `verifyEmail`、`verifyPhone` |
| `auth.password_reset_requested` | 忘记密码申请，签发一次性令牌 | SUCCESS | `platform_user` | `forgotPassword` |
| `auth.password_reset` | 重置完成，撤销全部会话 | SUCCESS | `platform_user` | `resetPassword` |
| `auth.password_changed` | 已登录用户修改密码，撤销其他会话 | SUCCESS | `platform_user` | `changePassword` |
| `platform.user.disabled` | 平台禁用用户，递增 `u pv`、撤销会话 | SUCCESS | `platform_user` | `platformDisableUser` |
| `platform.user.enabled` | 平台启用用户；`LOCKED` 到期自动解锁由系统 Job 触发同一编码（`actor_type=SYSTEM`） | SUCCESS | `platform_user` | `platformEnableUser` |
| `platform.user.unlocked` | 管理员在到期前手动解锁锁定账号（与到期自动解锁用 `actor_type` 区分） | SUCCESS | `platform_user` | `platformEnableUser` |
| `session.revoked` | 撤销会话（本人/管理员共用，`actor_type` 区分） | SUCCESS | `user_session` | `revokeSession`、`platformRevokeUserSessions` |
| `security.token_reuse_detected` | Refresh Token 重用，撤销整个 family | SUCCESS | `user_session` | `refresh`（系统） |
| `security.one_time_token_revoked` | 安全清理撤销未消费一次性令牌（禁用用户/密码变更等）：撤销写 `consumed_at` 终结（不设 REVOKED 独立状态），由本审计与消费类审计区分语义 | SUCCESS | `one_time_token` | 系统（安全清理） |
| `service_account.authenticated` | Client Credentials 换发 Token（每次签发一条，频次低） | SUCCESS | `service_account` | `clientCredentialsToken` |

### 3.2 平台控制面（`platform.*`）

| 编码 | 触发时机 | result | target_type | 接口锚点 |
|---|---|---|---|---|
| `platform.tenant.created` | 创建租户（同一事务建 owner 成员/角色） | SUCCESS | `tenant` | `platformCreateTenant` |
| `platform.tenant.updated` | 更新租户基本信息 | SUCCESS | `tenant` | `platformUpdateTenant` |
| `platform.tenant.activated` | 初始化完成 / 创建事务内激活 | SUCCESS | `tenant` | `platformCreateTenant` |
| `platform.tenant.frozen` | 冻结租户 | SUCCESS | `tenant` | `platformFreezeTenant` |
| `platform.tenant.unfrozen` | 解冻租户 | SUCCESS | `tenant` | `platformUnfreezeTenant` |
| `platform.tenant.closed` | 关闭租户，撤销租户内会话 | SUCCESS | `tenant` | `platformCloseTenant` |
| `platform.tenant.force_managed` | 平台人员以 `platform.tenant.force_manage` 或 `platform.cross_tenant.access` 进入 FROZEN/CLOSED 租户上下文执行只读/导出（每次上下文进入一条；正常读权限的跨租户访问写 `platform.audit.cross_tenant_access`） | SUCCESS | `tenant` | 强制作业（`platformGetTenant`、`platformExportAudit` 等按调用） |
| `platform.role.granted` | 授予平台角色 | SUCCESS | `platform_user` | `platformGrantUserRole` |
| `platform.role.revoked` | 撤销平台角色授予 | SUCCESS | `platform_user` | `platformRevokeUserRole` |
| `platform.param.updated` | upsert 平台参数 | SUCCESS | `platform_param` | `platformUpdateParam` |
| `platform.audit.cross_tenant_access` | 以目标租户上下文执行跨租户操作（每次进入写一条；`target_type` 按目标实体取 `tenant` / `organization`） | SUCCESS | 目标实体 |`platformListTenantMembers` 等 |
| `platform.audit.queried` | 平台审计查询 | SUCCESS | `audit_log` | `platformListAudit` |
| `platform.audit.exported` | 平台审计导出任务的创建与完成各写一条（完成阶段触发也允许 `result=FAILURE`） | SUCCESS | `audit_log` | `platformExportAudit` |
| `platform.partition.archived` | 审计分区归档等运维作业完成（作业失败写同编码，`result=FAILURE`） | SUCCESS/FAILURE | `audit_log` | 运维 Job |

### 3.3 租户域（`tenant.*` / `organization.*`）

| 编码 | 触发时机 | result | target_type | 接口锚点 |
|---|---|---|---|---|
| `tenant.updated` | 租户管理员更新租户信息 | SUCCESS | `tenant` | `updateTenant` |
| `tenant.config.updated` | 更新租户配置 | SUCCESS | `tenant_config` | `updateTenantConfig` |
| `tenant.member.invited` | 邀请租户成员（`membership_invitation` 创建即记录） | SUCCESS | `membership_invitation` | `inviteTenantMember` |
| `tenant.member.joined` | 接受邀请成为有效成员 | SUCCESS | `membership_invitation` | `acceptInvitation` |
| `tenant.member.suspended` | 暂停租户成员 | SUCCESS | `tenant_membership` | `suspendTenantMember` |
| `tenant.member.activated` | 恢复租户成员 | SUCCESS | `tenant_membership` | `activateTenantMember` |
| `tenant.member.removed` | 移除租户成员（级联撤销组织成员） | SUCCESS | `tenant_membership` | `removeTenantMember` |
| `tenant.invitation.revoked` | 撤销邀请 | SUCCESS | `membership_invitation` | `revokeTenantInvitation` |
| `tenant.invitation.expired` | 邀请到期未接受，系统自动过期（`PENDING → EXPIRED`） | SUCCESS | `membership_invitation` | 系统 Job |
| `tenant.role.assigned` | 分配租户角色 | SUCCESS | `tenant_membership` | `setTenantMemberRoles` |
| `tenant.role.revoked` | 撤销租户角色（分配行物理删除） | SUCCESS | `tenant_membership` | `setTenantMemberRoles` |
| `tenant.organization.created` | 直接创建组织（无需审批） | SUCCESS | `organization` | `createOrganization` |
| `tenant.organization.approved` | 组织审批通过 | SUCCESS | `organization` | `decideOrganizationApproval` |
| `tenant.organization.rejected` | 组织审批拒绝 | SUCCESS | `organization` | `decideOrganizationApproval` |
| `tenant.organization.withdrawn` | 申请人撤回组织 | SUCCESS | `organization` | `withdrawOrganization` |
| `tenant.organization.frozen` | 冻结组织 | SUCCESS | `organization` | `freezeOrganization` |
| `tenant.organization.unfrozen` | 解冻组织 | SUCCESS | `organization` | `unfreezeOrganization` |
| `tenant.organization.archived` | 归档组织 | SUCCESS | `organization` | `archiveOrganization` |
| `organization.updated` | 更新组织基本信息 | SUCCESS | `organization` | `updateOrganization` |
| `organization.member.invited` | 邀请组织成员 | SUCCESS | `organization_membership` | `inviteOrganizationMember` |
| `organization.member.suspended` | 暂停组织成员 | SUCCESS | `organization_membership` | `suspendOrganizationMember` |
| `organization.member.activated` | 恢复组织成员 | SUCCESS | `organization_membership` | `activateOrganizationMember` |
| `organization.member.removed` | 移除组织成员 | SUCCESS | `organization_membership` | `removeOrganizationMember` |
| `organization.role.assigned` | 分配组织角色 | SUCCESS | `organization_membership` | `setOrganizationMemberRoles` |
| `organization.role.revoked` | 撤销组织角色 | SUCCESS | `organization_membership` | `setOrganizationMemberRoles` |
| `tenant.audit.queried` | 租户审计查询 | SUCCESS | `audit_log` | `listTenantAudit` |
| `tenant.audit.exported` | 租户审计导出 | SUCCESS | `audit_log` | `exportTenantAudit`（任务创建与完成各写一条） |

### 3.4 通用角色与所有权转让

| 编码 | 触发时机 | result | target_type | 接口锚点 |
|---|---|---|---|---|
| `role.created` | 创建角色（作用域按租户上下文区分平台/租户/组织） | SUCCESS | `role` | `createTenantRole`、`createOrganizationRole`、`platformCreateRole` |
| `role.updated` | 改名/改描述 | SUCCESS | `role` | `updateTenantRole`、`platformUpdateRole` 等 |
| `role.permissions_changed` | 修改角色权限集合 | SUCCESS | `role` | `setTenantRolePermissions` 等 |
| `role.disabled` | 停用角色（所有者角色禁止），递增作用域 pv | SUCCESS | `role` | `updateTenantRole` 等 |
| `role.enabled` | 启用角色 | SUCCESS | `role` | `updateTenantRole` 等 |
| `ownership.transfer.requested` | 发起租户/组织所有权转让 | SUCCESS | `ownership_transfer` | `requestTenantTransfer`、`requestOrganizationTransfer` |
| `ownership.transfer.accepted` | 目标接受，所有权转移，递增相关 pv | SUCCESS | `ownership_transfer` | `acceptOwnershipTransfer` |
| `ownership.transfer.declined` | 目标拒绝 | SUCCESS | `ownership_transfer` | `declineOwnershipTransfer` |
| `ownership.transfer.cancelled` | 发起人取消 | SUCCESS | `ownership_transfer` | `cancelOwnershipTransfer` |
| `ownership.transfer.expired` | 7 天超时未接受，系统过期 | SUCCESS | `ownership_transfer` | 系统 Job |
| `ownership.transfer.forced` | 平台强制转让（编码与事件目录 §4.4 一致） | SUCCESS | `ownership_transfer` | 平台强制作业 |

### 3.5 服务账号、API Key、Webhook、扩展

| 编码 | 触发时机 | result | target_type | 接口锚点 |
|---|---|---|---|---|
| `service_account.created` | 创建服务账号 | SUCCESS | `service_account` | `createTenantServiceAccount` 等 |
| `service_account.updated` | 更新名称/描述/有效期/`scopes` | SUCCESS | `service_account` | `updateTenantServiceAccount` 等 |
| `service_account.disabled` | 停用服务账号 | SUCCESS | `service_account` | `updateTenantServiceAccount`、`platformUpdateServiceAccount` |
| `service_account.enabled` | 启用服务账号 | SUCCESS | `service_account` | `updateTenantServiceAccount`、`platformUpdateServiceAccount` |
| `api_key.created` | 创建/轮换 API Key（只记录前缀） | SUCCESS | `api_key` | `createTenantApiKey` 等 |
| `api_key.revoked` | 撤销 API Key | SUCCESS | `api_key` | `revokeTenantApiKey` 等 |
| `security.api_key_anomaly` | API Key 使用异常指纹（新 IP/新指纹首次或高频命中） | SUCCESS | `api_key` | 系统（鉴权侧） |
| `webhook.created` | 创建 Webhook 端点 | SUCCESS | `webhook_endpoint` | `createTenantWebhook` |
| `webhook.updated` | 更新 Webhook 端点 | SUCCESS | `webhook_endpoint` | `updateTenantWebhook` |
| `webhook.disabled` | DELETE 端点 → 置 `DISABLED` | SUCCESS | `webhook_endpoint` | `deleteTenantWebhook` |
| `webhook.redelivered` | 手动重投单条投递 | SUCCESS | `webhook_delivery` | `redeliverWebhook` |
| `webhook.delivery_failed` | 投递进入 `DEAD` 或连续失败告警阈值 | FAILURE | `webhook_delivery` | Worker |
| `platform.extension.registered` | 扩展 Manifest 注册/升级登记 | SUCCESS | `extension_registry` | Worker/迁移 Job |
| `platform.extension.enabled` | 启用扩展 | SUCCESS | `extension_registry` | `platformEnableExtension` |
| `platform.extension.disabled` | 禁用扩展 | SUCCESS | `extension_registry` | `platformDisableExtension` |
| `platform.extension.upgraded` | 升级完成（schema 版本+API 版本变更） | SUCCESS | `extension_registry` | Worker/迁移 Job |

---

## 4. 高危操作拒绝必审计（`DENIED`）

以下高危权限点的判定失败必须写 `result='DENIED'` 的审计，`action` 使用对应成功动作：

| 权限前缀 | 对应动作 |
|---|---|
| `platform.user.disable` / `enable` | `platform.user.disabled` / `enabled` |
| `platform.tenant.freeze` / `close` / `force_manage` | `platform.tenant.frozen` / `closed` / `force_managed` |
| `platform.role.grant` / `manage` | `platform.role.granted` / `role.updated` / `role.permissions_changed` |
| `platform.param.manage` | `platform.param.updated` |
| `platform.extension.manage` | `platform.extension.enabled` / `disabled` / `upgraded` |
| `platform.service_account.manage` | `service_account.*` / `api_key.*` |
| `platform.cross_tenant.access` | `platform.audit.cross_tenant_access` |
| `tenant.transfer` | `ownership.transfer.requested` |
| `organization.transfer` / `tenant.organization.transfer` | `ownership.transfer.requested` |
| `tenant.role.assign` / `tenant.role.manage` | `tenant.role.assigned` / `tenant.role.revoked` / `role.created` / `role.updated` / `role.permissions_changed` |
| `organization.role.assign` / `organization.role.manage` | `organization.role.assigned` / `organization.role.revoked` / `role.created` / `role.updated` / `role.permissions_changed` |
| `tenant.member.remove` / `suspend` / `activate` | `tenant.member.removed` / `suspended` / `activated` |
| `tenant.organization.approve` / `freeze` | `tenant.organization.*` |
| `tenant.audit.export` | `tenant.audit.exported` |
| `platform.audit.export` | `platform.audit.exported` |

规则：

1. 只审计“高危且被明确判定拒绝”的请求，不审计普通 `403`（避免噪音）。
2. 冻结/关闭租户期间所有写请求的拒绝属于状态约束，优先使用对应状态动作（`DENIED`）。
3. 限流拦截不写审计，由指标（`OPS §5.2`）与 `login_attempt` 承载。
4. `is_dangerous=true` 权限对应动作**执行成功**时按 §3 正常写 `SUCCESS` 审计，不另设高危专用编码（权限模型 §8.2）。
5. 提权防护拒绝（`403 PERMISSION_ESCALATION_DENIED`）**一律写 `DENIED`**：子集校验失败是安全信号，不适用规则 1 的“普通 403”豁免；对应动作取本表所属权限前缀行。

---

## 5. `target_type` 清单

`audit_log.target_type` 允许值（varchar(64)，应用层白名单校验）：

```text
platform_user      user_session      one_time_token    tenant
tenant_membership  tenant_config     membership_invitation
organization       organization_membership  organization_closure
organization_approval  ownership_transfer  role
service_account    api_key           webhook_endpoint
webhook_delivery   outbox_event      extension_registry
platform_param     audit_log         none
```

- `none` 仅用于无法关联实体的系统事件（如分区维护失败告警由日志承载，不落审计）。
- 新增类型时必须同步权限模型与 OpenAPI（如有对外可见性）。

---

## 6. 与其他文档的对照关系

- 权限点目录：`permission-model-v2.0.md §3.4`；动作与权限点一一映射见 §3 各表“接口锚点”列经 `x-permission` 得到。
- 状态机副作用：`state-machines-v2.0.md` 各节“审计动作”，为概要，编码以本文为准。
- DDL/保留/分区：`database-design-v2.0.md §6.7`、`§9.5`、`§12.3`、`§13`。
- 拒绝语义与错误响应：`error-codes-v2.0.md §4`。

## 7. 相关文档

- [权限模型 V2.0](permission-model-v2.0.md)
- [状态机 V2.0](state-machines-v2.0.md)
- [数据库设计 V2.0](database-design-v2.0.md)
- [错误码目录 V2.0](error-codes-v2.0.md)
- [事件目录 V2.0](event-catalog-v2.0.md)
- [OpenAPI 契约 V2.0](../30-api/openapi-v2.0.yaml)
