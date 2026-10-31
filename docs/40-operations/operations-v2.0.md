# b_platform 运维与测试 V2.0

**项目：** b_platform（通用业务底座平台·控制面）  
**版本：** V2.0  
**状态：** 设计基线（待评审）  
**对应架构：** `docs/00-architecture/architecture-v2.0.md`  
**对应技术设计：** `docs/20-design/tech-design-v2.0.md`

---

## 1. 文档定位

本文档定义 b_platform 的部署、配置、数据库运维、可观测性、安全运维、发布流程、测试策略、SLO 和故障处理手册。它是环境搭建、CI/CD、值班和验收的直接依据。

---

## 2. 环境与配置

### 2.1 环境分层

| 环境 | 用途 | 数据 | 部署 |
|---|---|---|---|
| `local` | 开发 | 本地容器，可重置 | Docker Compose |
| `ci` | 自动化测试 | 每次全新容器 | Testcontainers / CI service |
| `staging` | 预发/验收 | 脱敏数据 | 与生产同构 |
| `production` | 生产 | 真实数据 | Docker Compose（一期）/ K8s（后续） |

规则：

- 环境之间不共享数据库、密钥、对象存储。
- `staging` 必须开启与生产相同的 RLS、角色、审计、限流配置。
- 生产配置只能通过 Secret Manager / 环境变量注入，不写入镜像或仓库。

### 2.2 应用配置

| 变量 | 必填 | 说明 |
|---|---|---|
| `PLATFORM_ENV` | 是 | `local` / `ci` / `staging` / `production` |
| `HTTP_ADDR` | 是 | 例如 `:8080` |
| `HTTP_PUBLIC_BASE_URL` | 是 | 对外基址，用于 JWT `iss` / 链接 |
| `DATABASE_URL_AUTH` | 是 | `platform_auth` 连接串 |
| `DATABASE_URL_CORE` | 是 | `platform_core` 连接串 |
| `DATABASE_URL_CONTROL` | 是 | `platform_control` 连接串 |
| `DATABASE_URL_AUDIT` | 是 | `platform_audit_reader` 连接串（只读） |
| `DATABASE_URL_MIGRATE` | 仅迁移 Job | `platform_migrator` 连接串 |
| `DB_POOL_MAX_CONNS_*` | 否 | 各池最大连接数 |
| `JWT_ISSUER` | 是 | 必须等于 `HTTP_PUBLIC_BASE_URL` |
| `JWT_ACTIVE_KID` | 是 | 当前签名密钥 ID |
| `JWT_PRIVATE_KEY_PATH` | 是 | RS256 私钥（挂载/Secret） |
| `JWT_PUBLIC_KEYS_PATH` | 是 | JWKS 公钥集合 |
| `ARGON2_MEMORY_KIB` | 否 | 默认 65536 |
| `ARGON2_ITERATIONS` | 否 | 默认 3 |
| `ARGON2_PARALLELISM` | 否 | 默认 2 |
| `WEBHOOK_SECRET_KEK` | 是 | Webhook 密钥信封加密 KEK |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 否 | OTLP 端点 |
| `LOG_LEVEL` | 否 | `debug` / `info` / `warn` / `error` |
| `RATE_LIMIT_ENABLED` | 否 | 默认 `true` |

规则：

1. 启动时校验必填项、URL 格式、TTL 范围、密钥是否存在；失败立即退出。
2. 不同数据库角色使用不同连接串；禁止一个连接串复用多个角色。
3. 日志启动时打印配置摘要，必须脱敏（只显示 host/db/role，不显示密码）。
4. 配置变更需要重启（一期）；热更新配置只限 `tenant_config` / `platform_param`。

### 2.3 连接池

| 池 | 角色 | 默认 `MaxConns` | 说明 |
|---|---|---|---|
| Auth | `platform_auth` | 10 | 登录/注册/会话 |
| Core | `platform_core` | 20 | 租户业务 |
| Control | `platform_control` | 10 | 平台控制面 |
| Audit | `platform_audit_reader` | 5 | 只读审计 |

- 总连接数必须小于 PostgreSQL `max_connections` 的 70%。
- 每个池设置 `MaxConnLifetime=30m`、`MaxConnIdleTime=5m`、`HealthCheckPeriod=1m`。
- 禁止跨池事务；禁止在事务中从另一个池取连接。

---

## 3. 部署

### 3.1 一期拓扑

```text
                    ┌──────────────┐
                    │ Reverse Proxy│  TLS / 限流 / 访问日志
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       platform-api  platform-api  platform-worker
              │            │            │
              └────────────┼────────────┘
                           ▼
                    PostgreSQL 16+
                    （主 + 备份/PITR）
```

- `platform-api` 至少 2 副本，无状态。
- `platform-worker` 至少 1 副本；River 使用数据库锁，允许多副本。
- `platform-migrate` 作为一次性 Job 运行，成功后才启动新版本 API。
- Redis 可选，仅用于限流/缓存；一期默认使用进程内缓存 + PostgreSQL。

### 3.2 Docker Compose 服务

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: b_platform
      POSTGRES_USER: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d b_platform"]
      interval: 5s
      timeout: 3s
      retries: 20

  migrate:
    image: b_platform:${VERSION}
    command: ["/platform-migrate", "up"]
    environment:
      DATABASE_URL_MIGRATE: ${DATABASE_URL_MIGRATE}
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

  api:
    image: b_platform:${VERSION}
    command: ["/platform-api"]
    env_file: [.env]
    depends_on:
      migrate:
        condition: service_completed_successfully
    ports: ["8080:8080"]
    healthcheck:
      test: ["CMD", "/platform-api", "healthcheck"]
      interval: 10s
      timeout: 3s
      retries: 5

  worker:
    image: b_platform:${VERSION}
    command: ["/platform-worker"]
    env_file: [.env]
    depends_on:
      migrate:
        condition: service_completed_successfully

volumes:
  pgdata:
```

### 3.3 启动顺序

1. PostgreSQL 就绪。
2. `platform-migrate` 执行迁移与分区维护，校验 schema 版本。
3. 启动 `platform-worker`。
4. 启动 `platform-api`（至少 2 副本）。
5. 反向代理健康检查通过后接入流量。

### 3.4 优雅关闭

1. 收到 `SIGTERM` 后停止接收新请求。
2. 等待在途 HTTP 请求完成（默认 30s）。
3. 停止 Worker 领取新任务，等待当前任务完成（默认 60s）。
4. 关闭连接池。
5. 超时强制退出并记录未完成任务。

### 3.5 健康检查

| 端点 | 检查 | 失败处理 |
|---|---|---|
| `/healthz` | 进程存活，不查数据库 | 重启容器 |
| `/readyz` | 数据库可用、迁移版本匹配、扩展加载完成 | 从负载均衡摘除 |

- 健康检查不返回内部版本、连接串、迁移明细。
- 就绪检查失败时 API 仍可返回 `503`，便于排查。

---

## 4. 数据库运维

### 4.1 角色初始化

- `deploy/bootstrap/roles.sql` 由 DBA 执行一次，创建 5 个角色并设置 `search_path` / 超时。
- 角色密码由 Secret Manager 注入，禁止写入 SQL 文件。
- `platform_migrator` 仅用于迁移 Job 与分区维护，不进入 API/Worker 环境变量。
- 定期检查运行时角色是否被误授予 `BYPASSRLS` 或表 owner。

### 4.2 迁移

```bash
platform-migrate up
platform-migrate status
platform-migrate version
```

规则：

- 迁移 Job 获取 advisory lock，失败立即退出并阻止新版本启动。
- 生产禁止自动 `down`；回滚使用补偿迁移或快照恢复。
- 大表变更遵循 expand/contract，详见数据库设计 §10。
- 迁移完成后执行 RLS / 授权验收查询，失败视为发布失败。

### 4.3 分区

- 每次发布前执行 `SELECT core.fn_ensure_audit_partitions(3);`。
- 每日检查默认分区 `audit_log_default` 是否有数据；有则立即建对应月分区并迁移。
- 归档流程：`DETACH PARTITION` → 导出 → 校验 → `DROP TABLE`。
- 归档操作必须记录运维审计（谁、何时、哪个分区、目标位置）。

### 4.4 备份与恢复

| 项 | 目标 |
|---|---|
| 全量备份 | 每日一次 |
| WAL 归档 | 持续 |
| RPO | ≤ 15 分钟 |
| RTO | ≤ 1 小时 |
| 恢复演练 | 每季度一次 |

恢复步骤：

1. 停止 API/Worker 写入。
2. 从基础备份 + WAL 恢复到目标时间点。
3. 校验 `goose_db_version`、角色、RLS、审计约束。
4. 执行授权/RLS 验收查询。
5. 启动 Worker 与 API，观察错误率与 Outbox。

### 4.5 清理

| 任务 | 频率 | 执行者 |
|---|---|---|
| 过期会话/令牌 | 每小时 | `platform_auth` |
| `login_attempt` 90 天 | 每日 | `platform_auth` |
| 幂等键过期 | 每小时 | Worker（`platform_core`） |
| Outbox/Webhook 已投递 30 天 | 每日 | Worker |
| 审计归档 | 每月 | 迁移 Job |
| `VACUUM (ANALYZE)` | 自动 + 每周手动检查 | DBA |

清理必须分批（≤ 5000 行/批），避免长事务和锁等待。

---

## 5. 可观测性

### 5.1 日志

统一 JSON，字段稳定：

```json
{
  "time": "2026-10-31T12:00:00.123Z",
  "level": "info",
  "service": "platform-api",
  "version": "2.0.0",
  "request_id": "0192...",
  "trace_id": "4bf92f...",
  "tenant_id": "0192...",
  "principal_id": "0192...",
  "route": "POST /api/v1/tenant/members/invitations",
  "status": 201,
  "latency_ms": 42
}
```

禁止输出：密码、Token、API Key、完整邮箱/手机号、完整身份证/银行卡、SQL 参数值。

### 5.2 指标

| 类别 | 指标 |
|---|---|
| HTTP | 请求量、P50/P95/P99 延迟、错误率、状态码分布 |
| 数据库 | 连接池使用率、等待时间、慢查询、死锁、复制延迟 |
| 认证 | 登录成功/失败、锁定、刷新失败、Token 过期 |
| 授权 | 拒绝次数、`PERMISSION_VERSION_STALE` 次数、缓存命中率 |
| 审计 | 写入失败、跨租户访问次数 |
| Outbox | 积压数、投递延迟、失败/死信数 |
| Webhook | 成功率、重试次数、死信数、平均延迟 |
| 扩展 | 加载失败、路由数、注册冲突 |

### 5.3 Trace

- HTTP → 中间件 → Service → SQL span。
- SQL span 记录语句名与耗时，不记录参数值。
- 跨服务调用传播 `traceparent`。
- 采样：生产 10%，错误请求 100%。

### 5.4 审计

- 审计独立于日志，只追加，不可篡改。
- 关键事件与业务同事务写入。
- 审计查询本身写审计。
- 审计导出走异步任务，下载链接短期有效。

### 5.5 告警

| 告警 | 条件 | 级别 | 处理 |
|---|---|---|---|
| API 5xx 高 | 5 分钟 > 1% | P1 | 查看错误日志/trace |
| API P95 高 | 10 分钟 > 500ms | P2 | 检查数据库/下游 |
| 数据库连接耗尽 | 使用率 > 85% | P1 | 扩容/排查长事务 |
| 迁移失败 | Job 失败 | P1 | 阻止发布，回滚 |
| Outbox 积压 | > 10000 或最老 > 10m | P2 | 检查 Worker/消费者 |
| Webhook 死信 | 5 分钟新增 > 100 | P2 | 检查端点/告警租户 |
| 登录失败激增 | 5 分钟 > 1000 | P2 | 检查攻击/限流 |
| 审计写入失败 | 任意 | P1 | 业务应已回滚，立即排查 |
| 默认分区有数据 | 任意 | P2 | 创建月分区 |
| 备份失败 | 任意 | P1 | 立即重试/人工备份 |

### 5.6 SLO

| 指标 | 目标 |
|---|---|
| 可用性 | 99.9%（月度） |
| 认证/授权 P95 | ≤ 50ms（不含网络） |
| 组织树查询 P95 | ≤ 300ms |
| 列表接口 P95 | ≤ 500ms |
| 5xx 比例 | < 0.5% |
| Outbox 投递延迟 P95 | ≤ 30s |
| RPO | ≤ 15 分钟 |
| RTO | ≤ 1 小时 |

---

## 6. 安全运维

### 6.1 密钥轮换

| 密钥 | 周期 | 步骤 |
|---|---|---|
| JWT 签名密钥 | 90 天 | 新 `kid` 上线 → JWKS 发布旧+新 → 切换签名 → 旧公钥保留 ≥ 2×Access TTL → 移除旧密钥 |
| Refresh Token | 无需轮换（随机） | 泄露时撤销全部会话 |
| API Key | 90 天或泄露时 | 创建新 Key → 更新调用方 → 撤销旧 Key |
| Webhook Secret | 90 天或泄露时 | 轮换并通知租户 |
| 数据库密码 | 90 天 | 创建新密码 → 更新 Secret → 滚动重启 → 旧密码失效 |
| 加密 KEK | 按 KMS 策略 | 信封加密重包裹，不重加密全部数据 |

### 6.2 密钥泄露响应

1. 立即撤销相关密钥/会话/API Key。
2. 轮换 JWT 密钥并缩短 Access TTL。
3. 检查审计中的异常访问、跨租户访问。
4. 通知受影响租户（如涉及数据）。
5. 复盘并更新检测规则。

### 6.3 网络安全

- 全站 TLS 1.2+；HSTS。
- 反向代理限流、请求体大小限制、超时。
- 数据库不暴露公网；仅应用网段可访问。
- 管理入口（平台 API）可限制来源 IP / VPN。
- 出站 Webhook 允许列表可选，防止 SSRF。
- 禁止在 URL 中传递 Token/API Key。

### 6.4 应用安全

- 依赖扫描：`govulncheck`、镜像扫描，阻断高危漏洞。
- 静态检查：`golangci-lint`、`staticcheck`。
- 密码：Argon2id，登录成功时按参数版本 rehash。
- 限流：登录、注册、密码重置、API Key、导出。
- 审计：敏感操作全覆盖；审计失败即业务失败。
- 渗透测试：每年至少一次，覆盖 IDOR、租户逃逸、提权、注入、Token 重放。
- 漏洞修复 SLA：Critical 24h、High 7d、Medium 30d。

---

## 7. 发布与变更

### 7.1 版本

- API 主版本在 URL：`/api/v1`、`/api/platform/v1`。
- 镜像版本使用 SemVer + git SHA。
- 事件版本：`event_type` + `event_version`。
- 扩展声明 `api_version`，核心按兼容策略加载。

### 7.2 发布流程

```text
1. 契约变更（OpenAPI）合并
2. 迁移脚本 + sqlc + 测试合并
3. CI：lint / unit / integration / RLS / contract / build
4. 构建镜像并签名
5. staging 部署 + 冒烟 + 迁移演练
6. production 迁移 Job
7. production API 滚动发布（先 1 副本，再全量）
8. 观察 30 分钟指标/告警
9. 记录发布与回滚点
```

### 7.3 数据库变更门禁

- 迁移必须在 staging 全量数据副本上演练。
- 破坏性变更必须分两个版本：expand → contract。
- 迁移执行前自动备份/快照。
- 迁移失败自动阻止 API 新版本启动。
- 迁移后执行 RLS/授权/关键约束检查。

### 7.4 回滚

| 场景 | 动作 |
|---|---|
| 应用缺陷 | 回滚镜像到上一版本 |
| 迁移失败 | 停止发布，恢复快照或执行补偿迁移 |
| 数据错误 | 停止写入，按审计/备份修复 |
| 安全事件 | 撤销密钥/会话，回滚可疑版本 |

- 回滚不自动回滚数据库结构。
- 每个版本必须保留上一版本镜像与配置。
- 回滚后重新执行健康检查与关键路径冒烟。

### 7.5 Feature Flag

- 扩展启用/禁用、组织审批、级联冻结、MFA 等通过配置控制。
- Flag 变更必须审计。
- 删除 Flag 前确认无存量依赖。

---

## 8. 测试策略

### 8.1 测试层次

| 层次 | 工具 | 真实 PostgreSQL | 覆盖 |
|---|---|---|---|
| 单元 | `go test` + `testify` | 否 | 领域逻辑、权限算法、状态机 |
| 集成 | `testcontainers-go` | 是 | Repository、事务、RLS、迁移 |
| RLS 矩阵 | `pgTAP` + Go | 是 | 租户隔离、角色授权 |
| 契约 | OpenAPI 校验 + `huma` | 否 | 请求/响应/错误码 |
| 端到端 | `httptest` + Testcontainers | 是 | 关键用户旅程 |
| 负载 | `k6` | 是（预发） | 登录/授权/组织树 |
| 安全 | `gosec` / `govulncheck` / 渗透 | 是 | 注入、越权、逃逸 |

### 8.2 必测场景

1. 租户 A 成员读取租户 B 资源 → `404` / 空。
2. 伪造 `X-Tenant-Id` → 不改变 RLS 上下文。
3. 连接池复用：A 事务结束，B 复用连接，不残留 `app.tenant_id`。
4. `platform_core` 执行 `SET ROLE platform_control` → 拒绝。
5. `platform_core` 更新/删除 `audit_log` → 拒绝。
6. 未设置上下文查询 RLS 表 → 0 行。
7. 提权：授予自身没有的权限 → 拒绝。
8. 所有者角色直接改派 → 拒绝，只能走转让。
9. 过期 `pv` Token → `401`。
10. 扩展注册 `platform.*` 权限 → 启动失败。
11. 扩展迁移修改核心表 → 迁移 Job 拒绝。
12. 幂等重放 / 冲突 → 原响应 / `409`。
13. 平台授权范围：`TENANT` / `ORGANIZATION` / `ORG_TYPE` / `include_descendants`。
14. 组织角色祖先继承、兄弟不继承。
15. 服务账号 scopes 越权 → 创建失败/调用失败。
16. Webhook 签名、重放、重试、死信。
17. 审计导出权限与下载链接过期。
18. 迁移 expand/contract 期间新旧代码共存。

### 8.3 测试数据

- 使用独立测试库，每次运行全新迁移。
- Fixture 使用固定 UUID，避免随机失败。
- 测试数据包含：3 个租户、2 棵组织树、平台/租户/组织角色、服务账号、Webhook。
- 禁止使用生产数据；staging 使用脱敏数据。

### 8.4 CI 流水线

```text
lint → unit → build → integration(postgres) → rls(pgTAP) → contract → e2e → image scan
```

门禁：

- `golangci-lint` 0 error。
- 单元/集成/RLS/契约测试全部通过。
- 覆盖率：核心 `core/*` ≥ 70%，`authz` ≥ 85%。
- OpenAPI 变更必须附带实现与测试。
- 迁移文件必须成对（up/down）且通过空库/升级库测试。
- 镜像扫描无 Critical/High。

### 8.5 负载测试

| 场景 | 目标 |
|---|---|
| 登录 | 100 RPS，P95 ≤ 200ms |
| Token 校验 + 权限判定 | 1000 RPS，P95 ≤ 50ms |
| 成员列表 | 200 RPS，P95 ≤ 500ms |
| 组织树查询（万级组织） | 50 RPS，P95 ≤ 300ms |
| 审计写入 | 500 TPS，P95 ≤ 100ms |

- 压测环境与生产同规格数据库。
- 观察连接池、CPU、IO、锁等待、慢查询。
- 压测后清理数据并执行 `VACUUM (ANALYZE)`。

---

## 9. 运行手册

### 9.1 API 不可用

1. 检查负载均衡/反向代理与副本状态。
2. 检查 `/healthz`、`/readyz`。
3. 检查数据库连接、迁移版本、扩展加载。
4. 查看 5xx 日志与 trace。
5. 必要时回滚上一版本。

### 9.2 数据库连接耗尽

1. 查看 `pg_stat_activity` 长事务/空闲事务。
2. 检查连接池指标与慢查询。
3. 终止空闲事务（谨慎，先确认）。
4. 临时扩容连接或重启异常副本。
5. 修复泄漏连接/长事务代码。

### 9.3 迁移失败

1. 不要启动新版本 API。
2. 查看迁移日志与 `goose_db_version`。
3. 判断是否部分执行；必要时恢复快照。
4. 修复迁移或使用补偿迁移。
5. 重新执行并验证 RLS/授权检查。

### 9.4 Outbox 积压

1. 检查 Worker 是否运行、是否有锁竞争。
2. 检查 `outbox_event` 状态分布与最老事件。
3. 检查下游/Webhook 错误。
4. 临时扩容 Worker。
5. 处理死信并告警。

### 9.5 Webhook 大量失败

1. 按端点聚合失败原因。
2. 检查租户端点可用性、TLS、签名。
3. 4xx 不重试；5xx/网络错误退避重试。
4. 死信通知租户并保留记录。
5. 防 SSRF：禁止内网地址（可配置允许列表）。

### 9.6 登录失败激增

1. 区分攻击与故障。
2. 检查限流、账号锁定、IP 分布。
3. 启用更严格限流/封禁。
4. 通知安全值班。
5. 检查是否有撞库/密码喷洒。

### 9.7 权限异常

1. 检查 Token `pv` 与实体 `permission_version`。
2. 检查角色/授权/成员状态。
3. 检查缓存键与 TTL。
4. 检查 RLS 上下文是否设置。
5. 必要时清理缓存并刷新 Token。

### 9.8 审计写入失败

1. 关键业务应已回滚；确认无部分提交。
2. 检查磁盘、权限、分区是否存在。
3. 创建缺失分区。
4. 修复后重试业务请求（使用幂等键）。

### 9.9 密钥泄露

见 §6.2。

---

## 10. 容量与性能

### 10.1 初始规格（一期）

| 组件 | 规格 |
|---|---|
| API | 2 × 2 vCPU / 2 GiB |
| Worker | 1 × 2 vCPU / 2 GiB |
| PostgreSQL | 4 vCPU / 16 GiB / SSD 200 GiB |
| 反向代理 | 2 × 1 vCPU / 1 GiB |

### 10.2 扩容信号

- API CPU > 70% 持续 10 分钟 → 加副本。
- 数据库连接使用率 > 80% → 优化/扩容。
- 慢查询 P95 > 100ms → 加索引/优化 SQL。
- Outbox 积压持续增长 → 加 Worker。
- 审计分区过大 → 归档/分区维护。

### 10.3 性能原则

- 认证/授权不查大表；权限集合缓存 + `pv`。
- 列表强制分页，禁止全表扫描。
- 组织树使用闭包表，禁止递归查询作为主路径。
- 审计查询必须带时间范围/租户条件。
- 批量写入使用 `pgx.Batch` / `CopyFrom`。
- 长事务禁止；单事务 < 2s。

---

## 11. 数据保留与合规

| 数据 | 保留 | 说明 |
|---|---|---|
| 租户/组织/成员 | 长期 | 关闭/移除保留历史 |
| 用户 | 长期 | 禁用不删除 |
| 会话 | 30 天 | 过期清理 |
| 登录尝试 | 90 天 | 安全分析 |
| 审计 | 180 天（可配置） | 归档/SIEM |
| 幂等键 | 24h | TTL |
| Outbox/Webhook | 30 天 | 已投递 |
| 备份 | 35 天 | 加密存储 |

- 导出/删除请求按适用法规处理；删除前确认审计与备份策略。
- 审计归档加密，访问需审批。
- 数据跨境传输需单独评估。

---

## 12. 相关文档

- [总体架构 V2.0](../00-architecture/architecture-v2.0.md)
- [架构决策 V2.0](../00-architecture/decisions-v2.0.md)
- [扩展 SPI V2.0](../00-architecture/extension-spi-v2.0.md)
- [需求规格 V2.0](../10-requirements/requirements-v2.0.md)
- [技术设计 V2.0](../20-design/tech-design-v2.0.md)
- [数据库设计 V2.0](../20-design/database-design-v2.0.md)
- [权限模型 V2.0](../20-design/permission-model-v2.0.md)
- [状态机 V2.0](../20-design/state-machines-v2.0.md)
- [OpenAPI V2.0](../30-api/openapi-v2.0.yaml)
