# b_platform Outbox 事件目录 V2.0

**版本：** V2.0
**日期：** 2026-10-31
**对应：** 架构 V2.0 §6.2、技术设计 V2.0 §7.10、状态机 V2.0 §11.2、数据库设计 V2.0 §6.10
**状态：** 设计基线（待评审）

---

## 1. 文档定位

本文是 `core.outbox_event.event_type` 的**唯一权威清单**。

范围约束：

1. 只收录与业务**同一事务写入**的领域事件（`FR-X-01`）；
2. 状态机各处标注“审计、Outbox”的副作用必须与本文 1:1 对应；新增触发点时必须同步本文；
3. 扩展模块事件（`ext.*`）由扩展 Manifest 声明，本文收录命名规则与校验约束，具体编码由扩展注册（见 §6）。

不写 Outbox 的情况：审计读取、纯查询、由 Worker 补偿的任务（投递重试等）不产生领域事件。

---

## 2. 事件格式

Outbox 行结构与对外投递 envelope（架构 V2.0 §6.2）：

```json
{
  "id": "0192...",
  "type": "tenant.membership.created",
  "version": 1,
  "occurred_at": "2026-10-31T12:00:00Z",
  "tenant_id": "0192...",
  "aggregate_type": "membership",
  "aggregate_id": "0192...",
  "data": { }
}
```

- `version` 对应数据库 `event_version`（整数 ≥ 1）。
- `type` 最大 128 字符（`event_type varchar(128)`）。
- `headers` 只放投递元数据（`content-type`、`traceparent` 等），不参与事件语义。
- `tenant_id` 为平台级事件时为 `NULL`（见各表“作用域”列）。
- `occurred_at` 取 `outbox_event.created_at`（同事务时间戳），数据库层无独立列（DB 设计 §6.10）。

---

## 3. 版本化规则

1. 事件 schema 只**增不改删**：新增可选字段、放宽校验为非破坏性；改字段类型/含义/删除字段为破坏性。
2. 非破坏性变更：保持 `type` 与 `version`，消费者必须忽略未知字段。
3. 破坏性变更：`event_version+1`；同一 `type` 的旧版本至少投递一个发布周期后废弃。
4. `type` 一经发布不可修改，只能新增与废弃；命名规则：

```text
type = <域>.<实体>.<过去式动词>    # tenant.membership.removed
```

5. 事件必须可重放：同一事件幂等消费不产生业务副作用；消费者按 `id` 去重。

---

## 4. 核心事件清单

列：`event_type` | `version` | 触发（状态机锚点） | 作用域 | `data` 关键字段

### 4.1 租户

| `event_type` | ver | 触发 | 作用域 | `data` |
|---|---|---|---|---|
| `tenant.created` | 1 | 创建租户（§5.1/§5.3） | `NULL` | `slug`、`name`、`owner_user_id` |
| `tenant.frozen` | 1 | 冻结（§5.1） | `NULL` | `slug`、`reason` |
| `tenant.unfrozen` | 1 | 解冻（§5.1） | `NULL` | `slug` |
| `tenant.closed` | 1 | 关闭（§5.1） | `NULL` | `slug`、`closed_by` |

- `aggregate_type='tenant'`。
- 消费者：把租户状态写入缓存/索引；冻结/关闭触发下游摘除。

### 4.2 成员与邀请

| `event_type` | ver | 触发 | 作用域 | `data` |
|---|---|---|---|---|
| `tenant.membership.created` | 1 | 邀请成员产生初始成员（§6.2 INVITED） | `tenant_id` | `user_id`、`status`、`invited_by` |
| `tenant.membership.removed` | 1 | 移除成员，含组织成员级联（§6.2） | `tenant_id` | `user_id`、`was_owner`、`cascaded_memberships` |

- `aggregate_type='membership'`（与架构示例一致）。
- 租户创建同事务写入的 owner 初始成员**不产生**本事件（订阅端依赖 `tenant.created` 即可还原）。
- 消费者：通知服务（邀请邮件）；会话/凭证服务（失效上下文）。

### 4.3 组织

| `event_type` | ver | 触发 | 作用域 | `data` |
|---|---|---|---|---|
| `organization.created` | 1 | 直接创建（§7.1）或审批通过（§7.2） | `tenant_id` | `organization_id`、`parent_id`、`org_type`、`owner_user_id`、`via_approval` |
| `organization.frozen` | 1 | 冻结（§7.2） | `tenant_id` | `organization_id`、`reason` |
| `organization.unfrozen` | 1 | 解冻（§7.2） | `tenant_id` | `organization_id` |
| `organization.archived` | 1 | 归档（§7.2） | `tenant_id` | `organization_id` |

- `PENDING→REJECTED/WITHDRAWN` 不产生事件（只写审计）。
- 消费者：权限判定辅助索引；活动流。

### 4.4 所有权转让

| `event_type` | ver | 触发 | 作用域 | `data` |
|---|---|---|---|---|
| `ownership.transfer.requested` | 1 | 发起转让（§8.2） | `tenant_id` | `entity_type`（`tenant`/`organization`）、`entity_id`、`from_user_id`、`to_user_id`、`expires_at` |
| `ownership.transfer.accepted` | 1 | 目标接受（§8.2） | `tenant_id` | `entity_type`、`entity_id`、`from_user_id`、`to_user_id` |
| `ownership.transfer.forced` | 1 | 平台强制完成（§8.2 FORCED） | `tenant_id` | `entity_type`、`entity_id`、`to_user_id`、`operator` |

- Decline / cancel / expire 只写审计，不投递（对外无消费场景）。

### 4.5 扩展生命周期（平台通报）

| `event_type` | ver | 触发 | 作用域 | `data` |
|---|---|---|---|---|
| `extension.enabled` | 1 | 启用扩展（§11.1；操作 `platformEnableExtension`） | `NULL` | `name`、`version` |
| `extension.disabled` | 1 | 禁用扩展（操作 `platformDisableExtension`） | `NULL` | `name` |

- 状态机 §11.1 概要未单独标注 Outbox，触发与字段以本文为准（`extension-spi-v2.0.md` 无独立事件）。

- 扩展自身产生的业务事件属于 `ext.*`（§6）。
- 消费者：避免路由到已停用扩展；UI 下架。

### 4.6 一期不投递、写审计即可

以下状态机动作**只写审计**，不进入 Outbox（无已知消费者；一期保持最小）：

- 登录/登出/会话撤销等身份动作（§3.1 各表，均无事件）；
- 角色创建/修改/停用变更之外的单纯信息变更（`role.updated`）；
- 服务账号 / API Key 生命周期；
- Webhook 配置变更（消费方自身）;
- 平台参数变更（`platform.param.updated` 不广播，公开值由轮询读取）。

> 一期以显式最小清单为原则：**不在状态机标注 Outbox 的动作不得私自添加事件**。若评审增加场景，按 §3 流程更新本文。

---

## 5. Webhook 投递映射

1. `webhook_endpoint.events` 以 `event_type` 前缀匹配选择事件；允许值**仅限**本文 §4 / §6 已收录的完整编码，或五个顶层订阅前缀：`tenant.*`、`organization.*`、`ownership.*`、`extension.*`、`ext.<module>.*`。**中段通配**（如 `tenant.membership.*`）与审计动作编码（如 `tenant.member.invited`）一律在创建/更新时拒绝。
2. Webhook payload 与 Outbox envelope 相同；签名遵循 `state-machines-v2.0.md §11.3`（HMAC + 时间戳防重放）。
3. 失败重试与死信遵循 §11.2/§11.3；`webhook.delivery_failed` 审计见审计目录 §3.5。
4. 平台级事件（`tenant_id IS NULL`）不投递租户 Webhook，仅消息队列消费者。

---

## 6. 扩展事件（`ext.*`）

命名：`ext.<module>.<entity>.<action>`（如 `ext.booking.reservation.created`；`action` 允许一个点分限定符，编码规则见权限模型 §3.1）。

规则（与扩展 SPI 一致）：

1. 只能由扩展声明，核心注册校验：编码必须以 `ext.<module>.` 开头，禁止注册其余核心前缀（`tenant.*`、`organization.*`、`platform.*`、`ownership.*`、`extension.*`）；
2. 事件必须由扩展事务内写 outbox（复用 `outbox.Writer` SPI）；
3. `tenant_id` 取扩展事务上下文；平台级扩展事件暂不支持；
4. 扩展升级引入破坏性变更遵循 §3 版本规则。

---

## 7. 运行约束（引用）

- 投递：`FOR UPDATE SKIP LOCKED`，至少一次，指数退避，10 次进 `DEAD`（状态机 §11.2）。
- 保留：已投递 30 天清理（DB 设计 §12.3）。
- 容量/索引：DB 设计 §12.1。
- 告警阈值：OPS §5.5（积压、死信、延迟）。

## 8. 相关文档

- [架构 V2.0 §6.2](../00-architecture/architecture-v2.0.md)
- [状态机 V2.0 §11](state-machines-v2.0.md)
- [审计动作目录 V2.0](audit-catalog-v2.0.md)
- [错误码目录 V2.0](error-codes-v2.0.md)
- [扩展 SPI V2.0](../00-architecture/extension-spi-v2.0.md)
