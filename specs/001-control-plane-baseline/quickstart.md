# Quickstart Validation: b_platform V2.0 控制面基线

**Feature**: `001-control-plane-baseline` | **Date**: 2026-11-01

本文件是**验证指南**：用最短路径证明每个用户故事端到端可用。命令为约定示例，具体参数以
实现时的 `deploy/docker-compose.yml` 与 `Makefile` 为准；实现细节不在此重复。

## 前置条件

- Go 1.23+、Docker / Docker Compose、PostgreSQL 16+（或使用 compose 提供的实例）
- 已执行 `specify init` 的项目骨架（`.specify/`）与本文档基线

## 启动

```bash
# 1. 启动数据库（或 compose 全套）
docker compose -f deploy/docker-compose.yml up -d postgres

# 2. 初始化角色与 schema（migrator 角色）
make db-init

# 3. 执行迁移
make migrate-up

# 4. 载入种子（权限点、内置角色模板、平台参数）
make seed

# 5. 启动 API 与 Worker
make run-api     # 默认 :8080
make run-worker
```

健康检查：

```bash
curl -s localhost:8080/healthz        # 期望 200 alive
curl -s localhost:8080/readyz         # 期望 200 ready（数据库可达）
curl -s localhost:8080/.well-known/jwks.json   # 期望含 RS256 公钥
```

## US1 — 租户开通与生命周期

```bash
# 平台管理员登录（双 aud 之一）
TOKEN=$(curl -s -X POST localhost:8080/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"account":"admin@example.com","password":"..."}' | jq -r .access_token)

# 创建租户并指定初始所有者
curl -s -X POST localhost:8080/api/platform/v1/tenants \
  -H "authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -H 'content-type: application/json' \
  -d '{"slug":"acme","name":"Acme","owner_user_id":"<uuid>"}' | jq

# 期望：201；租户 ACTIVE；owner 立即拥有租户所有者角色
curl -s localhost:8080/api/platform/v1/tenants/<tenant_id> \
  -H "authorization: Bearer $TOKEN" | jq '.status'

# 冻结后写操作被拒绝
curl -s -X POST localhost:8080/api/platform/v1/tenants/<tenant_id>/freeze \
  -H "authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" | jq
# 期望：200；随后以租户成员身份写操作返回 409 STATE_CONFLICT 或 403
```

## US2 — 注册、登录、上下文切换

```bash
curl -s -X POST localhost:8080/api/v1/auth/register -d '{"email":"u@example.com",...}'
curl -s -X POST localhost:8080/api/v1/auth/verify/email -d '{"token":"..."}'
curl -s -X POST localhost:8080/api/v1/auth/login -d '{"account":"u@example.com","password":"..."}' | jq
curl -s -X POST localhost:8080/api/v1/auth/context/switch \
  -H "authorization: Bearer $TOKEN" -H 'X-Tenant-Id: <tenant_id>' | jq
# 期望：返回携带目标租户上下文的新凭证

curl -s localhost:8080/api/v1/auth/sessions -H "authorization: Bearer $TOKEN" | jq
curl -s -X POST localhost:8080/api/v1/auth/password/forgot -d '{"account":"u@example.com"}'
# 重置后旧会话访问期望 401
```

## US3 — 组织、成员与授权

```bash
# 创建组织（可能需要审批）
curl -s -X POST localhost:8080/api/v1/tenant/organizations \
  -H "authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -d '{"name":"研发部","parent_id":null}' | jq

# 邀请成员并分配角色
curl -s -X POST localhost:8080/api/v1/tenant/members/invitations \
  -H "authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -d '{"account":"member@example.com","role_ids":["<role_id>"]}' | jq

# 越权授予期望 403 PERMISSION_DENIED 且产生 DENIED 审计
curl -s -X PUT localhost:8080/api/v1/tenant/members/<member_id>/roles \
  -H "authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -d '{"role_ids":["<higher_role_id>"]}'
```

## US4 — 审计

```bash
curl -s "localhost:8080/api/v1/tenant/audit?limit=20" \
  -H "authorization: Bearer $TOKEN" -H 'X-Tenant-Id: <tenant_id>' | jq '.items[0]'
# 期望：含 operator/target/action/result；随后存在 tenant.audit.queried 记录
curl -s -X POST localhost:8080/api/v1/tenant/audit/exports \
  -H "authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" | jq
```

## US5 — 扩展注册与启停

```bash
curl -s localhost:8080/api/platform/v1/extensions -H "authorization: Bearer $TOKEN" | jq
curl -s -X POST localhost:8080/api/platform/v1/extensions/<name>/disable \
  -H "authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" | jq
# 期望：200；扩展路由 404；数据保留
```

## US6 — 服务账号与事件出口

```bash
curl -s -X POST localhost:8080/api/v1/tenant/service-accounts \
  -H "authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -d '{"name":"reporting","scopes":["tenant.read"]}' | jq

curl -s -X POST localhost:8080/oauth/token \
  -d 'grant_type=client_credentials&client_id=<id>&client_secret=<secret>' | jq

# 配置 Webhook 后触发一个事件，验证签名与重试
curl -s -X POST localhost:8080/api/v1/tenant/webhooks \
  -H "authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -d '{"url":"https://example.test/hook","events":["tenant.created"]}' | jq
```

## 自动化验证（CI 对应）

```bash
make lint          # golangci-lint / staticcheck / govulncheck
make test-unit     # go test ./...
make test-integration   # testcontainers + 真实 PostgreSQL
make test-rls      # pgTAP 隔离矩阵
make test-contract # OpenAPI 契约校验
make spec-check    # 需求/契约/目录/数据库一致性（research R-06）
```

## 验收判定

| 用户故事 | 通过条件 |
|---|---|
| US1 | 创建租户后 owner 可用；冻结拒绝写入；关闭拒绝登录且数据保留 |
| US2 | 注册→验证→登录→刷新→切换→登出闭环；重置后旧会话 401 |
| US3 | 建树/邀请/授权可用；越权授予与所有者改派 403 且留痕 |
| US4 | 关键操作有审计；应用角色无法改删审计；查询本身留痕 |
| US5 | 扩展启停生效且数据保留；违规 Manifest 启动失败 |
| US6 | 服务账号按 scope 调用；Webhook 签名可验证、失败重试进死信 |

全部通过且 `make spec-check` 无差异，方可认为本特性达到"可开发完成"状态。
