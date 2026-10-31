# b_platform 错误码目录 V2.0

**版本：** V2.0
**日期：** 2026-10-31
**对应：** 技术设计 V2.0 §8、OpenAPI V2.0（`Problem` schema）、权限模型 V2.0 §7.3、状态机 V2.0 §12
**状态：** 设计基线（待评审）

---

## 1. 文档定位

本文是 Problem Details 响应 `code` 字段的**唯一权威清单**。OpenAPI 中 `Problem.code` 的取值以本文为准；技术设计与状态机提到的 `409 IDEMPOTENCY_CONFLICT`、`401 PERMISSION_VERSION_STALE` 等均已收录。

规则：

1. `code` 一经发布不可修改；新增错误不改变已有语义。
2. 同一业务场景只能有一个稳定 `code`；`HTTP` 状态码失效时改用新 `code`，不复用。
3. 错误响应不包含堆栈、SQL、内部表名（技术设计 §8）。
4. `type` URI 规范：`https://platform.example.com/problems/<slug>`，slug 为本文“type slug”列。
5. `detail` 可为本地化文案，但 `code` 与状态码不得本地化。
6. 字段级校验失败必须在 `errors[]` 中给出 `field` / `code` / `message`。

---

## 2. 响应格式

```json
{
  "type": "https://platform.example.com/problems/idempotency-conflict",
  "title": "Idempotency conflict",
  "status": 409,
  "code": "IDEMPOTENCY_CONFLICT",
  "detail": "Idempotency-Key was used with a different request body",
  "instance": "/api/v1/tenant/organizations",
  "request_id": "0192...",
  "trace_id": "4bf9...",
  "errors": [ { "field": "body.name", "code": "REQUIRED", "message": "must not be empty" } ]
}
```

- `errors[].code` 为字段级校验子码（`REQUIRED`、`TOO_LONG`、`PATTERN`、`FOREIGN_KEY`），不属于本文主清单，新增子码不需升版。
- `X-Tenant-Id`：租户上下文头；`Idempotency-Key`：幂等键头（OpenAPI `components/parameters`）。

---

## 3. 错误码清单

列：`code` | HTTP | type slug | 触发时机 | 重试语义

### 3.1 认证与令牌

| `code` | HTTP | type slug | 触发时机 | 重试 |
|---|---|---|---|---|
| `UNAUTHENTICATED` | 401 | `unauthenticated` | 缺失/无效/过期 Token；Refresh Token 无效或已重用 | 否，重新登录/刷新 |
| `INVALID_CREDENTIALS` | 401 | `invalid-credentials` | 登录账号或密码错误（反枚举：用户不存在也返回此码） | 否 |
| `ACCOUNT_LOCKED` | 423 | `account-locked` | 连续失败达阈值被临时锁定（锁定是账号状态资源，按 OpenAPI 契约返回 `423 Locked`）；`detail` 提示剩余时间 | 否（到期后再试） |
| `PERMISSION_VERSION_STALE` | 401 | `permission-version-stale` | Token `pv` 落后服务端当前值 | 是：刷新 Token 后携带新 Token 重试原请求一次 |
| `CONTACT_NOT_VERIFIED` | 403 | `contact-not-verified` | 要求已验证联系方式时未通过验证 | 否，先完成验证 |
| `STEP_UP_REQUIRED` | 403 | `step-up-required` | 高危权限需要 step-up 认证（二期，MFA/重新验证），Token 缺少 `amr`/`auth_time` | 是，完成 step-up 后重试 |
| `API_KEY_INVALID` | 401 | `api-key-invalid` | API Key 不存在/过期/已撤销（反枚举统一码） | 否 |
| `OAUTH_INVALID_CLIENT` | 401 | `oauth-invalid-client` | Client Credentials 校验失败 | 否 |

### 3.2 授权与上下文

| `code` | HTTP | type slug | 触发时机 | 重试 |
|---|---|---|---|---|
| `PERMISSION_DENIED` | 403 | `permission-denied` | 权限/范围/作用域不满足；服务账号 scope 不足 | 否 |
| `TENANT_CONTEXT_REQUIRED` | 400 | `tenant-context-required` | 缺失或非法 `X-Tenant-Id` | 否，修正请求 |
| `NO_ACTIVE_MEMBERSHIP` | 403 | `no-active-membership` | 用户对该租户/组织无有效成员关系或成员已退出 | 否 |
| `TENANT_FROZEN` | 403 | `tenant-frozen` | 冻结租户内写操作 | 否，等待解冻 |
| `TENANT_CLOSED` | 403 | `tenant-closed` | 关闭租户内任何写操作 | 否，永久 |
| `ORGANIZATION_FROZEN` | 403 | `organization-frozen` | 冻结组织内写操作（含级联拒绝） | 否，等待解冻 |
| `ORGANIZATION_ARCHIVED` | 403 | `organization-archived` | 归档组织内写操作 | 否，永久 |
| `PERMISSION_ESCALATION_DENIED` | 403 | `permission-escalation-denied` | 提权防护校验失败：授予的目标权限集合超出操作者有效权限集合（权限模型 §8.1）；拒绝同时写 `DENIED` 审计（审计目录 §4） | 否 |

### 3.3 资源、状态与并发

| `code` | HTTP | type slug | 触发时机 | 重试 |
|---|---|---|---|---|
| `RESOURCE_NOT_FOUND` | 404 | `resource-not-found` | 资源不存在或无权访问（防枚举统一 `404`） | 否 |
| `VALIDATION_FAILED` | 400 | `validation-failed` | 请求体/参数校验失败；`errors[]` 给字段明细 | 否，修正请求 |
| `IDEMPOTENCY_CONFLICT` | 409 | `idempotency-conflict` | 同一 `Idempotency-Key` 携带不同请求指纹 | 否，换键重发 |
| `IDEMPOTENCY_IN_PROGRESS` | 409 | `idempotency-in-progress` | 幂等键对应的首次请求仍在处理 | 是，短暂退避后 GET/重放 |
| `VERSION_CONFLICT` | 409 | `version-conflict` | 乐观锁 `If-Match`/`If-Unmodified-Since` 期望失败 | 是，重新读取后合并 |
| `CONCURRENT_MODIFICATION` | 409 | `concurrent-modification` | `lock_timeout` 超时（悲观锁等待命中上限） | 是，重试（带退避） |
| `PRECONDITION_FAILED` | 412 | `precondition-failed` | 请求前置条件不满足（如 `ETag` 报文头错误） | 否，先 GET |
| `STATE_CONFLICT` | 409 | `state-conflict` | 违反状态机合法迁移（如暂停 `INVITED` 成员）；状态冲突唯一编码（状态机通用规则 §2） | 否，纠正状态 |
| `OWNER_TRANSFER_PENDING` | 409 | `owner-transfer-pending` | 同一租户/组织已存在 `PENDING` 转让 | 否 |
| `OWNER_NOT_REMOVABLE` | 409 | `owner-not-removable` | 不能移除最后一个所有者/改派所有者角色 | 否，走转让 |
| `ORGANIZATION_DEPTH_EXCEEDED` | 400 | `organization-depth-exceeded` | 组织创建超过 `organization.max_depth` | 否 |
| `IDEMPOTENCY_FAILED` | 409 | `idempotency-failed` | 幂等键对应的首次请求已终态完成但结果为失败（`FAILED`）；换新键重试 | 否，换键重发 |
| `TENANT_SLUG_EXISTS` | 409 | `tenant-slug-exists` | 租户 slug 唯一约束冲突 | 否，更换 slug |
| `MEMBERSHIP_EXISTS` | 409 | `membership-exists` | 同一用户同一租户已存在有效成员关系（部分唯一索引） | 否，直接使用现有成员 |
| `ORGANIZATION_NAME_EXISTS` | 409 | `organization-name-exists` | 同一父组织下同名组织已存在 | 否，更换名称 |
| `OWNER_EXISTS` | 409 | `owner-exists` | 所有者唯一性冲突（数据库部分唯一索引兜底） | 否，走转让流程 |
| `PENDING_REQUEST_EXISTS` | 409 | `pending-request-exists` | 同一实体已存在待审批申请（组织创建审批重复）；转让场景专用码为 `OWNER_TRANSFER_PENDING` | 否 |
| `NOT_SUPPORTED` | 405 | `not-supported` | 一期不支持（父组织变更、物理删除、组织/租户迁移）；目标处于不可转换状态时按状态冲突返回 `409 STATE_CONFLICT`（状态机 §7.2 规则 5） | 否 |

### 3.4 邀请与一次性令牌

| `code` | HTTP | type slug | 触发时机 | 重试 |
|---|---|---|---|---|
| `INVITATION_INVALID` | 400 | `invitation-invalid` | 邀请令牌无效/已消费/用户邮箱不匹配/状态不合法 | 否 |
| `INVITATION_EXPIRED` | 400 | `invitation-expired` | 邀请超过 `expires_at` | 否，请管理员重发 |
| `ONE_TIME_TOKEN_INVALID` | 400 | `one-time-token-invalid` | 一次性令牌无效/已消费 | 否，重新申请 |
| `ONE_TIME_TOKEN_EXPIRED` | 400 | `one-time-token-expired` | 一次性令牌超时 | 否，重新申请 |

### 3.5 服务端

| `code` | HTTP | type slug | 触发时机 | 重试 |
|---|---|---|---|---|
| `RATE_LIMITED` | 429 | `rate-limited` | IP/账号/接口限流命中；响应带 `Retry-After` | 是，按 `Retry-After` |
| `SERVICE_UNAVAILABLE` | 503 | `service-unavailable` | 依赖不可用、迁移版本不匹配、扩展未加载（`readyz` 未就绪期间的请求） | 是，等待/读 `readyz` |
| `INTERNAL_ERROR` | 500 | `internal-error` | 未预期异常；只留 `request_id`/`trace_id` | 原样重试通常无效 |

---

## 4. 审计与错误码的关系

1. `PERMISSION_DENIED` 对应的高危操作拒绝按审计目录 §4 写 `result='DENIED'`。
2. `TENANT_FROZEN` / `ORGANIZATION_FROZEN` / `TENANT_CLOSED` / `ORGANIZATION_ARCHIVED` 的拒绝同样按状态动作审计（审计目录 §4 规则 2）。
3. `ACCOUNT_LOCKED` / `auth.login_failed` 的阈值锁定对应 `platform.user.locked` 审计与指标告警（OPS §5.5）。
4. 限流拒绝只产生指标与 `login_attempt`，不写审计（审计目录 §4 规则 3）。
5. 所有错误响应都会带 `request_id` / `trace_id`，用于审计与日志关联。

---

## 5. 重试语义汇总

| 类别 | 示例 `code` | 客户端动作 |
|---|---|---|
| 可自动重试 | `PERMISSION_VERSION_STALE`、`IDEMPOTENCY_IN_PROGRESS`、`VERSION_CONFLICT`、`CONCURRENT_MODIFICATION` | 退避后重试（PV 过期时先刷新 Token） |
| 条件重试 | `RATE_LIMITED`、`SERVICE_UNAVAILABLE`、`INTERNAL_ERROR` | 按 `Retry-After`/等待重试 |
| 不可重试 | 其余 4xx | 修正请求或联系管理员 |

---

## 6. 相关文档

- [技术设计 V2.0 §8](tech-design-v2.0.md)
- [OpenAPI 契约 V2.0](../30-api/openapi-v2.0.yaml)
- [权限模型 V2.0](permission-model-v2.0.md)
- [状态机 V2.0 §12](state-machines-v2.0.md)
- [审计动作目录 V2.0](audit-catalog-v2.0.md)
- [事件目录 V2.0](event-catalog-v2.0.md)
