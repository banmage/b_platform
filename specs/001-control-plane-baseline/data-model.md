# Phase 1 Data Model: b_platform V2.0 控制面基线

**Feature**: `001-control-plane-baseline` | **Date**: 2026-11-01

本文件是**索引**，不是权威定义：表结构、约束、索引、RLS 策略与角色授权以
`docs/20-design/database-design-v2.0.md` 为准，状态迁移以
`docs/20-design/state-machines-v2.0.md` 为准。此处只记录实体、关键约束与实现时的落点。

## 实体与约束

| 实体 | 关键属性 | 硬约束 | 状态机 | DB 落点 |
|---|---|---|---|---|
| Platform User | 账号、状态、凭证哈希、权限版本 | 账号全局唯一；不参与租户 RLS | `ACTIVE`/`DISABLED`/`LOCKED` | DB §6.2 |
| Tenant | 标识、名称、状态、配置、所有者 | 标识唯一且不可变 | `PROVISIONING`→`ACTIVE`→`FROZEN`→`CLOSED` | DB §6.3、SM §5 |
| Tenant Membership | 租户、用户、状态、权限版本 | 同一用户同一租户有效记录唯一 | `INVITED`/`ACTIVE`/`SUSPENDED`/`INACTIVE` | DB §6.4、SM §6 |
| Organization | 租户、父组织、类型、名称、状态、所有者 | 父子同租户；深度受限 | `PENDING_APPROVAL`→`ACTIVE`→`FROZEN`→`ARCHIVED` | DB §6.4、SM §7 |
| Organization Closure | 祖先、后代、深度 | `(tenant_id, ancestor, descendant)` 唯一 | 随组织创建/归档维护 | DB §6.4 |
| Organization Membership | 租户、组织、用户、状态、权限版本 | 必须是该租户成员 | 同 Tenant Membership | DB §6.4、SM §6 |
| Role | 作用域、租户、组织、名称、类型 | 作用域与租户/组织字段一致；所有者角色唯一 | `ACTIVE`/`DISABLED` | DB §6.5、SM §9 |
| Permission | 编码、命名空间、作用域、状态 | 编码全局唯一且不可变 | `ACTIVE`/`DEPRECATED` | DB §6.5 |
| Role Permission | 角色、权限编码 | 联合唯一 | — | DB §6.5 |
| Platform Role Grant / Scope | 用户、角色、状态、范围 | `(用户, 角色)` 有效授予唯一 | `ACTIVE`/`REVOKED` | DB §6.6 |
| Audit Log | 租户、操作者、目标、动作、结果、来源 | 只追加；租户 RLS；月分区 | 无（不可变） | DB §6.7、§9 |
| Service Account | 租户、名称、client_id、secret 哈希、状态 | 租户/平台作用域二选一 | `ACTIVE`/`DISABLED` | DB §6.8 |
| API Key | 租户、服务账号、key 哈希、前缀、状态 | 只存哈希；明文仅返回一次 | `ACTIVE`/`REVOKED`/`EXPIRED` | DB §6.8 |
| Extension Registry | 名称、版本、API 版本、状态、Manifest | 名称唯一 | `REGISTERED`/`ENABLED`/`DISABLED` | DB §6.9、SM §11 |
| Outbox Event | 租户、聚合、事件类型、payload、状态 | 与业务同事务 | `PENDING`→`SENT`/`FAILED` | DB §6.10、SM §11.2 |
| Idempotency Key | 租户、主体、端点、键、请求哈希、响应 | 联合唯一；默认 24h 过期 | `IN_PROGRESS`→`COMPLETED` | DB §6.10 |

## 跨实体规则

1. 所有租户数据表含 `tenant_id` 且启用 RLS（平台级表除外，见 DB §7）。
2. 主键一律 UUIDv7；对外不暴露自增序列。
3. 成员/角色/用户状态变更必须递增 `permission_version`（宪法 IV、FR-M-09）。
4. 所有者唯一性由部分唯一索引 + 状态机共同保证，禁止直接改派（FR-M-07）。
5. 审计与 Outbox 写入必须与业务事务同事务（宪法 V、FR-A-02、FR-X-01）。
6. 扩展表位于 `ext_<module>` schema，不进入核心实体图（宪法 VII）。

## 权限点与实体关系

- 权限点 → 角色：多对多（`role_permission`），扩展权限带 `namespace='EXT'` 与 `module`。
- 平台角色授予 → 范围：一对多（`platform_role_grant_scope`），范围类型与字段必须一致。
- 授权判定顺序与缓存规则见 `docs/20-design/permission-model-v2.0.md` §7。
