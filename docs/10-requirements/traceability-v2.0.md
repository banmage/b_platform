# b_platform 需求追溯矩阵 V2.0

**版本：** V2.0
**日期：** 2026-10-31
**对应：** 需求规格 V2.0（61 条 FR）、OpenAPI V2.0、数据库设计 V2.0、权限模型 V2.0、状态机 V2.0、审计/事件/错误码目录
**状态：** 设计基线（待评审）

---

## 1. 目的与使用方式

- 每条 `FR-*` 都必须能在 OpenAPI、权限点、数据库表、审计动作/Outbox 事件中找到落点，否则视为**需求丢失**。
- 本文以表格给出四向映射：

```text
FR ──> operationId ──> 权限点（x-permission）──> 审计动作 ──> Outbox 事件 ──> 必测场景
```

- 权限点目录见权限模型 §3.4；审计编码以 [审计动作目录](../20-design/audit-catalog-v2.0.md) 为准；事件编码以 [事件目录](../20-design/event-catalog-v2.0.md) 为准。
- 测试锚点缩写：`SM §x` = 状态机章节；`OPS 8.2-n` = 必测场景编号；`DB §x` = 数据库设计章节；`SPI §x` = 扩展 SPI 章节。
- 一行内接口/权限为空表示该款需求由模块内规则或基础设施承载，原因在“落点”列说明。

---

## 2. 租户管理（FR-T）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-T-01 | 创建租户，含 owner 初始化 | `platformCreateTenant` | `platform.tenant.create` | `platform.tenant.created`、`platform.tenant.activated` | `tenant.created` | SM §5.1/§5.3、DB §6.3 |
| FR-T-02 | 租户查询（平台/租户两侧） | `platformListTenants`、`platformGetTenant`、`getTenant` | `platform.tenant.read`、`tenant.read` | — | — | DB §7.2 租户策略 |
| FR-T-03 | 租户更新；slug 不可改 | `updateTenant` | `tenant.update` | `tenant.updated` | — | SM §5.1 规则 1 |
| FR-T-04 | 冻结/解冻 | `platformFreezeTenant`、`platformUnfreezeTenant` | `platform.tenant.freeze` | `platform.tenant.frozen/unfrozen` | `tenant.frozen/unfrozen` | SM §5.2、OPS 8.2-9 |
| FR-T-05 | 关闭，不物理删除 | `platformCloseTenant` | `platform.tenant.close` | `platform.tenant.closed` | `tenant.closed` | SM §5.2 |
| FR-T-06 | 完全隔离 | 所有 `/api/v1/**` | — | 高危拒绝按审计目录 §4 | — | OPS 8.2-1/2/6、DB §7.3 |

---

## 3. 身份与认证（FR-I）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-I-01 | 注册 + 联系方式验证 | `register`、`verifyEmail`、`verifyPhone` | 公开 | `auth.registered`、`platform.user.verified` | — | SM §3.1/3.2、DB §6.2 |
| FR-I-02 | 登录、双 aud 入口 | `login` | 公开 | `auth.login_succeeded`、`auth.login_failed` | — | DB §6.2、OPS §8.5 登录 |
| FR-I-03 | Refresh 旋转 + 重用检测 | `refresh` | 公开 | `security.token_reuse_detected` | — | SM §4.1 |
| FR-I-04 | 登出 | `logout` | 已认证 | `session.revoked` | — | SM §4.1 |
| FR-I-05 | 忘记/重置密码 | `forgotPassword`、`resetPassword` | 公开 | `auth.password_reset_requested`、`auth.password_reset` | — | SM §3.1、DB §6.2 |
| FR-I-06 | 一次性验证令牌 | `verifyEmail`、`verifyPhone` | 公开 | `platform.user.verified` | — | SM §4.2 |
| FR-I-07 | 失败阈值 + 限流 | `login`（服务端） | 公开 | `platform.user.locked`、`auth.login_failed` | — | DB §11.3 参数、OPS §8.5（限流不写审计，见审计目录 §4 规则 3） |
| FR-I-08 | 平台禁用/启用 | `platformDisableUser`、`platformEnableUser` | `platform.user.disable`、`platform.user.enable` | `platform.user.disabled` / `enabled` | — | SM §3.2、DB §6.3 |
| FR-I-09 | 会话查看/撤销（双端） | `listSessions`、`revokeSession`、`platformRevokeUserSessions` | `platform.user.session.revoke`（平台侧） | `session.revoked` | — | SM §4.1 |
| FR-I-10 | 多租户/组织上下文切换 | `switchContext`、`listMyMemberships` | 已认证 + 有效成员关系 | —（一期不写，二期工程补，决议 D-09） | — | tech §4.2、权限模型 §7.3 |
| FR-I-11 | 服务账号认证（OAuth2/API Key） | `clientCredentialsToken`、`createTenantApiKey` 等 | `tenant.service_account.manage` 等 | `service_account.authenticated`、`api_key.created/revoked` | — | 权限模型 §7.2、SPI §5 |

- 附：`getMe`、`updateMe`、`changePassword`、`getMyPermissions` 属于 `Me` 自助接口（已认证），对应审计 `auth.password_changed`。

---

## 4. 组织管理（FR-O）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-O-01 | 创建组织（同租户） | `createOrganization` | `tenant.organization.create` | `tenant.organization.created` | `organization.created` | SM §7.4、DB §6.4 |
| FR-O-02 | 创建可审批 + 审批通过 | `decideOrganizationApproval`、`withdrawOrganization` | `tenant.organization.approve`、`tenant.organization.create` | `tenant.organization.approved/rejected/withdrawn` | `organization.created`（`via_approval`） | SM §7.2、SM 14.2 |
| FR-O-03 | 层级树 + 深度限制 | `createOrganization`、闭包查询 | `tenant.organization.create` | — | — | DB §6.4 闭包表、SM §7.3 |
| FR-O-04 | 组织查询 + 子树过滤 | `listTenantOrganizations`、`getOrganization` | `tenant.organization.read`、`organization.read` | — | — | DB §6.4、OPS 8.2-14 |
| FR-O-05 | 组织信息/可见性更新 | `updateOrganization` | `organization.update` | `organization.updated` | — | SM §7.1 |
| FR-O-06 | 组织冻结/解冻 + 级联拒绝 | `freezeOrganization`、`unfreezeOrganization`、`archiveOrganization` | `tenant.organization.freeze` | `tenant.organization.frozen/unfrozen/archived` | `organization.frozen/unfrozen/archived` | SM §7.2、租户配置 `organization.freeze_cascade` |
| FR-O-07 | 所有者转让 + 平台强制 | `requestOrganizationTransfer`、`accept/decline/cancelOwnershipTransfer` | `organization.transfer`、`tenant.organization.transfer` | `ownership.transfer.requested/accepted/declined/cancelled`、`ownership.transfer.forced` | `ownership.transfer.requested/accepted/forced` | SM §8 |
| FR-O-08 | 不支持删除/迁移 | — | — | — | — | OpenAPI 返回 `405 NOT_SUPPORTED`；SM §7.2 规则 5 |

---

## 5. 成员与角色（FR-M）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-M-01 | 租户成员邀请/移除；多角色 | `inviteTenantMember`、`removeTenantMember`、`setTenantMemberRoles` | `tenant.member.invite`、`tenant.member.remove`、`tenant.role.assign` | `tenant.member.invited/joined/removed`、`tenant.role.assigned/revoked` | `tenant.membership.created/removed` | SM §6、OPS 8.2-7 |
| FR-M-02 | 组织成员邀请/移除；须为租户成员 | `inviteOrganizationMember`、`removeOrganizationMember` | `organization.member.invite`、`organization.member.remove` | `organization.member.invited/removed` | —（无独立事件） | SM §6、DB §6.4 外键 |
| FR-M-03 | 成员状态 INVITED/ACTIVE/SUSPENDED/INACTIVE | `suspendTenantMember` 等 | `tenant.member.suspend`、`organization.member.suspend` | `tenant.member.suspended/activated`、`organization.member.suspended/activated` | — | SM §6.1 |
| FR-M-04 | 自定义角色 + 子集校验 | `createTenantRole`、`createOrganizationRole`、`set*RolePermissions` | `tenant.role.manage`、`organization.role.manage` | `role.created`、`role.permissions_changed` | — | 权限模型 §5.5、tech §7.5 |
| FR-M-05 | 一个成员多角色；停用即时失效 | `setTenantMemberRoles` 等、`updateTenantRole` | `tenant.role.manage`、`assign` | `role.disabled/enabled`、分配/撤销 | — | SM §9.1、SM §13 |
| FR-M-06 | 提权防护（子集校验） | 所有分配/授权接口 | — | 拒绝 → `PERMISSION_DENIED` + 审计 `DENIED` | — | OPS 8.2-7、权限模型 §4 |
| FR-M-07 | 所有者硬保护 | `setTenantMemberRoles`（拒绝路径） | — | `DENIED` 记录 | — | OPS 8.2-8、SM §8 规则 3 |
| FR-M-08 | 平台授权范围四类 + 后代 | `platformGrantUserRole`、`platformRevokeUserRole` | `platform.role.grant` | `platform.role.granted/revoked` | — | DB §6.6、权限模型 §5.1、OPS 8.2-13 |
| FR-M-09 | 权限即时生效（pv） | 所有变更写接口 | — | — | — | tech §6.4、权限模型 §7.3、OPS 8.2-9 |

---

## 6. 权限点（FR-P）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-P-01 | 权限点注册（核心/扩展） | 平台：`platformCreateRole` 等；扩展：SPI | `platform.role.manage`、`platform.extension.manage` | `role.created`、`platform.extension.registered` | `extension.enabled/disabled` | DB §6.5、§11.4、SPI §4 |
| FR-P-02 | 三作用域 | —（校验层） | — | — | — | DB §6.5 约束、权限模型 §2 |
| FR-P-03 | 编码不可变 | — | — | — | — | DB §10 迁移约束、权限模型 §3.4 |
| FR-P-04 | 统一 `authz.Authorizer` | 所有受保护接口 | — | — | — | tech §4.1、§7.5（AI 约束 7） |
| FR-P-05 | 扩展权限命名/作用域限制 | 扩展启动校验 | — | 拒绝注册 → 启动失败 | — | SPI §9、OPS 8.2-10 |

---

## 7. 审计（FR-A）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-A-01 | 事件覆盖面 | — | — | [审计动作目录](../20-design/audit-catalog-v2.0.md) §3 全表 | — | 审计目录 §3/§4 |
| FR-A-02 | 同事务写入 | 所有写接口 | — | — | 同事务 | DB §6.7、tech §7.6、OPS 8.2-5 |
| FR-A-03 | 只追加 | — | — | — | — | DB §6.7、§8.2 矩阵 |
| FR-A-04 | 分级查询 + 查询本身审计 | `listTenantAudit`、`platformListAudit` | `tenant.audit.read`、`platform.audit.read` | `tenant.audit.queried`、`platform.audit.queried` | — | DB §7.2 策略、审计目录 §2.1 |
| FR-A-05 | 分区/归档/导出 | `exportTenantAudit`、`platformExportAudit`、`get*AuditExport` | `tenant.audit.export`、`platform.audit.export` | `tenant.audit.exported`、`platform.audit.exported` | — | DB §9.5、§13、OPS 8.2-17 |

---

## 8. 平台配置（FR-C）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-C-01 | 平台参数管理 | `platformListParams`、`platformGetParam`、`platformUpdateParam` | `platform.param.read`、`platform.param.manage` | `platform.param.updated` | — | DB §6.10、§11.3 |
| FR-C-02 | 租户配置 + JSON Schema 校验 | `getTenantConfig`、`updateTenantConfig` | `tenant.config.read`、`tenant.config.update` | `tenant.config.updated` | — | DB §6.10 |
| FR-C-03 | 参数公开性 | `getTenantConfig` | `tenant.config.read` | — | — | DB §9.2 公开参数视图 |

- 预留权限 `organization.config.read/update` 当前无接口（组织配置一期由 `organization.update` 承载），不给 `role` 种子外授予。

---

## 9. 扩展模块（FR-E）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-E-01 | Manifest 注册（权限/路由/迁移/事件/schema/UI） | `platformListExtensions`、`platformGetExtension` | `platform.extension.read` | `platform.extension.registered` | — | SPI §3、DB §6.9 |
| FR-E-02 | 启用/禁用 | `platformEnableExtension`、`platformDisableExtension` | `platform.extension.manage` | `platform.extension.enabled/disabled` | `extension.enabled/disabled` | SM §11.1 |
| FR-E-03 | 独立 schema，禁入核心 | — | — | 违规启动失败 | — | SPI §7、OPS 8.2-11 |
| FR-E-04 | 扩展权限点进 `permission` 表 | 扩展注册校验 | — | 拒绝注册场景 | — | DB §6.5、§11.4、OPS 8.2-10 |
| FR-E-05 | API 版本兼容 + 迁移分离 | `platformGetExtension` | `platform.extension.read` | `platform.extension.upgraded` | — | SPI §8、DB §10.5 |

---

## 10. 服务账号与 API Key（FR-S）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-S-01 | 创建/更新服务账号 | `createTenantServiceAccount`、`updateTenantServiceAccount` 及平台侧同形接口 | `tenant.service_account.manage`、`platform.service_account.manage` | `service_account.created/updated/disabled/enabled` | — | DB §6.8、权限模型 §7.2 |
| FR-S-02 | Client Credentials | `clientCredentialsToken` | 公开 | `service_account.authenticated` | — | OpenAPI `/oauth/token`、仅 `ACTIVE` scopes |
| FR-S-03 | API Key 只存哈希/过期/撤销 | `createTenantApiKey`、`revokeTenantApiKey` 及平台侧同形接口 | `tenant.service_account.manage` 等 | `api_key.created/revoked` | — | DB §6.8、OPS 8.2-15 |
| FR-S-04 | 生命周期 + 使用异常审计 | — | — | `service_account.*`、`api_key.*`、`security.api_key_anomaly` | — | 审计目录 §3.5 |

---

## 11. 事件与集成（FR-X）

| FR | 需求摘要 | 接口（`operationId`） | 权限点 | 审计动作 | Outbox | 落点 / 测试锚点 |
|---|---|---|---|---|---|---|
| FR-X-01 | Outbox 同事务 + Worker 投递 | `listTenantEvents`、`platformListEvents` | `tenant.event.read`、`platform.event.read` | — | [事件目录](../20-design/event-catalog-v2.0.md) §4 | SM §11.2、DB §6.10 |
| FR-X-02 | Webhook 端点 + HMAC + 重试/死信 | `createTenantWebhook` 等、`redeliverWebhook` | `tenant.webhook.manage`、`tenant.webhook.read` | `webhook.created/updated/disabled/redelivered`、`webhook.delivery_failed` | 投递映射见事件目录 §5 | SM §11.3、OPS 8.2-16 |
| FR-X-03 | JWKS 端点 | `getJwks` | 公开 | — | — | OpenAPI `/.well-known/jwks.json`、OPS §6.1 |
| FR-X-04 | OpenAPI 3.1 契约 + 扩展合并 | — | — | — | — | tech §3、SPI §6 |
| FR-X-05 | 契约测试 | — | — | — | — | OPS §8.1 contract、CI 门禁 |

---

## 12. 交叉检查结果

- 61 条 FR **全部**有落点；无“文档提及但无实现位置”的 FR。
- OpenAPI 119 个 operationId 全部至少被一条 FR 或自助/主体式流程引用；`Health`/`JWKS` 除外（基础设施）。
- 权限点 64 个中，58 个直接映射接口；`platform.cross_tenant.access`、`platform.tenant.force_manage`、`tenant.organization.transfer` 由强制作业/内部调用承载；`tenant.organization.update`、`organization.config.read/update` 预留（见 §8 注与权限模型 §3.4）。
- 审计动作、Outbox 事件所有编码均收录在各自目录，未出现游离编码。
- 非功能需求（§5）由运维与测试文档（SLO、连接池、限流、告警）与数据库交付检查清单（DB §15）承载。

## 13. 相关文档

- [需求规格 V2.0](requirements-v2.0.md)
- [OpenAPI 契约 V2.0](../30-api/openapi-v2.0.yaml)
- [权限模型 V2.0](../20-design/permission-model-v2.0.md)
- [状态机 V2.0](../20-design/state-machines-v2.0.md)
- [数据库设计 V2.0](../20-design/database-design-v2.0.md)
- [审计动作目录 V2.0](../20-design/audit-catalog-v2.0.md)
- [事件目录 V2.0](../20-design/event-catalog-v2.0.md)
- [错误码目录 V2.0](../20-design/error-codes-v2.0.md)
- [运维与测试 V2.0](../40-operations/operations-v2.0.md)
