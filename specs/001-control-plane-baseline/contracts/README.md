# Contracts Index: b_platform V2.0 控制面基线

**权威契约**：`docs/30-api/openapi-v2.0.yaml`（OpenAPI 3.1，唯一手写来源）

本目录**不复制**契约内容，避免双份维护导致漂移（宪法原则 II）。发布产物
`api/openapi/openapi-v2.0.yaml` 由构建脚本从权威契约复制生成，禁止手改。

## 覆盖范围

| 范围 | 路径前缀 | 操作数 | 规格用户故事 |
|---|---|---|---|
| 认证与自助 | `/api/v1/auth`、`/api/v1/me` | 15 | US2 |
| 租户内资源 | `/api/v1/tenant`、`/api/v1/organizations` | 41 | US3、US4 |
| 平台控制面 | `/api/platform/v1` | 31 | US1、US3、US5 |
| 邀请与转让 | `/api/v1/invitations`、`/api/v1/ownership-transfers` | 4 | US3 |
| 服务账号与 Webhook | `/api/v1/tenant`（子资源） | 12 | US6 |
| 基础设施 | `/healthz`、`/readyz`、`/.well-known/jwks.json`、`/oauth/token` | 4 | US2、US6 |
| 扩展 API | `/api/v1/ext/<module>` | 由扩展 Manifest 合并 | US5 |

合计 119 个操作（`operationId` 唯一，无悬空引用）。

## 契约约束（实现时必须遵守）

1. 每个受保护操作必须声明 `x-permission` 或 `x-subject-authz`；公开操作显式 `security: []`。
2. 错误响应统一 `Problem`，`code` 取值以 `docs/20-design/error-codes-v2.0.md` 为唯一清单（41 码）。
3. Webhook 订阅 `events` 使用 `WebhookEventType` 白名单，编码以
   `docs/20-design/event-catalog-v2.0.md` 为准；中段通配与审计编码拒绝。
4. 写操作默认要求 `Idempotency-Key`；豁免清单见 [research.md](../research.md) R-04，需先回写基线。
5. 分页统一 cursor；不支持的操作返回 `405 NOT_SUPPORTED`，状态冲突返回 `409 STATE_CONFLICT`。

## 契约测试入口

- 契约与实现一致性：`test/contract/`（CI job `contract`）。
- 契约自身一致性：`scripts/spec-check/`（research R-06），校验 operationId、`$ref`、
  授权声明覆盖、错误码/事件/权限目录 diff。
