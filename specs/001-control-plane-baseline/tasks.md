# Tasks: b_platform V2.0 控制面基线

**Input**: Design documents from `/specs/001-control-plane-baseline/`

**Prerequisites**: [plan.md](./plan.md)、[spec.md](./spec.md)、[research.md](./research.md)、
[data-model.md](./data-model.md)、[contracts/README.md](./contracts/README.md)

**Tests**: 规格未显式要求测试，但宪法「开发工作流与质量门禁」强制单元/集成/RLS/契约测试与
覆盖率门槛，因此测试任务作为必做项纳入，并标注所属用户故事。

**Organization**: 任务按用户故事分组，保证每个故事可独立实现、独立验证、独立交付。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 所属用户故事（US1–US6）
- 描述中包含确切文件路径

## Path Conventions

单仓库单体：`cmd/`、`internal/`、`db/`、`test/`、`scripts/`、`deploy/`（见 plan.md 结构）。

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 建立可编译、可校验、可运行的项目骨架

- [ ] T001 创建目录骨架与 `go.mod`（Go 1.23），落 `cmd/{platform,worker,migrate}/main.go` 占位
- [ ] T002 [P] 配置 `golangci-lint`、`staticcheck`、`govulncheck`（`.golangci.yml`、`Makefile` 目标）
- [ ] T003 [P] 建立 `deploy/docker-compose.yml`（postgres + api + worker + migrate）与多阶段 Dockerfile
- [ ] T004 [P] 建立契约流水线：从 `docs/30-api/openapi-v2.0.yaml` 复制到 `api/openapi/` 并 `oapi-codegen` 生成类型（research R-01）
- [x] T005 [P] 实现 `scripts/spec-check/` 一致性校验（operationId/`$ref`/授权覆盖/错误码/事件/权限/FR 追溯），接入 CI（research R-06，宪法 VI）——17 项校验 + 17 个变异自测，`.github/workflows/spec-check.yml`
- [ ] T006 [P] 建立 `Makefile` 目标：`lint`、`test-unit`、`test-integration`、`test-rls`、`test-contract`、`spec-check`、`migrate-up`、`seed`

**Checkpoint**: `make lint && make spec-check` 可在空实现上通过

---

## Phase 2: Foundational（阻塞所有用户故事）

**Purpose**: 数据库角色、租户上下文、统一授权、审计与事件通道——任一缺失都无法交付故事

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事

- [ ] T007 编写数据库角色与 schema 迁移（`db/migrations/0001_init.sql`）：`platform_migrator`/`platform_auth`/`platform_core`/`platform_control`/`platform_audit_reader`（DB §5）
- [ ] T008 [P] 落地公共表与约束：UUIDv7 主键、`created_at/updated_at`、`permission_version`（DB §4、§6）
- [ ] T009 [P] 实现 RLS 策略与 `app.tenant_id` 上下文（DB §7、tech §5.2），含连接池按角色分池 `internal/platform/db/pools.go`
- [ ] T010 [P] 实现租户事务封装 `internal/platform/db/tx.go`：设置/清除上下文、异常回滚（tech §5.2）
- [ ] T011 实现中间件链 `internal/platform/http/middleware/`：请求 ID → 认证 → 租户上下文 → 授权 → 幂等 → 审计（tech §4.1）
- [ ] T012 [P] 实现统一错误模型与 `Problem` 输出（tech §8、错误码目录）
- [ ] T013 [P] 实现 `authz.Authorizer` 判定与缓存（权限模型 §7），含权限版本校验（tech §6.4）
- [ ] T014 [P] 实现 `audit.Writer`（同事务写入，tech §7.6）与只追加授权（DB §8.2）
- [ ] T015 [P] 实现 `outbox` 写入与 `river` Worker 投递骨架（tech §7.10、research R-02）
- [ ] T016 [P] 实现幂等键存储与重放（tech §9.1），豁免清单按 research R-04
- [ ] T017 [P] 实现配置加载与平台参数/租户配置读取（`internal/core/config`），含公开/私有参数可见性（公开参数视图仅暴露 `is_public=true`，FR-C-03）
- [ ] T018 建立集成测试基座：`test/integration/` testcontainers 启动 + 全量迁移（tech §10）
- [ ] T019 建立 RLS 测试基座：`test/rls/` pgTAP 用例模板（tech §10、OPS §8.2）
- [ ] T073 实现权限点编码不可变：`permission.code` 禁止 UPDATE（触发器/约束），迁移守卫拒绝改写既有编码（FR-P-03、DB §10），并加单测

**Checkpoint**: 空表 + 中间件 + 授权 + 审计 + Outbox 可运行，RLS 矩阵基线通过

---

## Phase 3: User Story 1 — 租户开通与生命周期 (Priority: P1) 🎯 MVP

**Goal**: 平台可创建租户并交付初始所有者；冻结/解冻/关闭语义正确

**Independent Test**: 创建租户 → 初始所有者可用 → 冻结拒绝写入 → 关闭拒绝登录且数据保留

### Implementation

- [ ] T020 [P] [US1] 实现租户模型与 sqlc 查询（`internal/core/tenant/`、`db/queries/tenant.sql`）
- [ ] T021 [US1] 实现租户服务：创建（同事务建 owner 成员+角色）、更新、冻结/解冻、关闭（`internal/core/tenant/service.go`，SM §5）
- [ ] T022 [US1] 实现平台侧 Handler：`platformCreateTenant`/`platformGetTenant`/`platformListTenants`/`platformFreezeTenant`/`platformUnfreezeTenant`/`platformCloseTenant`（`internal/platform/http/handler/platform_tenant.go`）
- [ ] T023 [US1] 实现租户侧 Handler：`getTenant`/`updateTenant`（`internal/platform/http/handler/tenant.go`）
- [ ] T024 [US1] 冻结态写操作拦截与 `409 STATE_CONFLICT` 语义（SM §5.2）
- [ ] T025 [US1] 审计与事件接线：`platform.tenant.created/activated/frozen/unfrozen/closed`、`tenant.created/frozen/unfrozen/closed`（审计/事件目录）
- [ ] T026 [P] [US1] 集成测试：租户创建含 owner 初始化、冻结拒绝写、关闭拒绝登录（`test/integration/tenant_test.go`）
- [ ] T027 [P] [US1] RLS 测试：租户成员读不到其他租户（`test/rls/tenant_isolation_test.go`）

**Checkpoint**: US1 可独立演示，MVP 成立

---

## Phase 4: User Story 2 — 注册、登录与上下文切换 (Priority: P1)

**Goal**: 身份闭环 + 双入口凭证 + 上下文切换 + 会话管理

**Independent Test**: 注册→验证→登录→刷新→切换→登出；重置密码后旧会话失效

### Implementation

- [ ] T028 [P] [US2] 实现用户/会话/一次性令牌模型与查询（`internal/core/identity/`、`db/queries/identity.sql`）
- [ ] T029 [US2] 实现密码哈希（Argon2id）与凭证签发/校验（RS256 + JWKS，tech §6.1/§6.2）
- [ ] T030 [US2] 实现注册、验证、登录、刷新（旋转 + 重用检测）、登出（SM §3.1/§4.1）
- [ ] T031 [US2] 实现密码找回/重置与会话批量失效（SM §3.1）
- [ ] T032 [US2] 实现登录失败锁定与限流（FR-I-07、DB §11.3）
- [ ] T033 [US2] 实现上下文切换与成员关系查询（`switchContext`、`listMyMemberships`，tech §4.2）
- [ ] T034 [US2] 实现会话查看/撤销与平台撤销用户会话（FR-I-09）
- [ ] T035 [US2] 实现 JWKS 端点与密钥轮换（OPS §6.1）
- [ ] T036 [US2] 审计接线：`auth.registered/login_succeeded/login_failed/password_reset*`、`session.revoked`、`platform.user.locked`
- [ ] T037 [P] [US2] 集成测试：完整身份闭环与重置后旧会话 401（`test/integration/identity_test.go`）
- [ ] T038 [P] [US2] 契约测试：登录 423/401、`PERMISSION_VERSION_STALE` 重试语义（`test/contract/auth_test.go`）

**Checkpoint**: US1 + US2 独立可用，平台可交付真实租户

---

## Phase 5: User Story 3 — 组织、成员与三层授权 (Priority: P2)

**Goal**: 组织树、审批、冻结、转让；成员邀请与多角色；三层授权与提权防护

**Independent Test**: 建树→邀请→授权→按角色访问；越权授予与所有者改派被拒绝

### Implementation

- [ ] T039 [P] [US3] 实现组织与闭包表模型/查询（`internal/core/organization/`、`db/queries/organization.sql`）
- [ ] T040 [US3] 实现组织创建（含审批分支）、深度校验、父子同租户校验（SM §7.2/§7.4）
- [ ] T041 [US3] 实现组织冻结/解冻/归档与级联拒绝配置（SM §7.2、`organization.freeze_cascade`）
- [ ] T042 [US3] 实现所有权转让请求/接受/拒绝/取消/过期与平台强制转让（SM §8）
- [ ] T043 [P] [US3] 实现成员模型与邀请/加入/移除/暂停/恢复（租户与组织两侧，SM §6）
- [ ] T044 [US3] 实现角色 CRUD、权限集合子集校验、所有者角色硬保护（权限模型 §5.5、SM §9）
- [ ] T045 [US3] 实现平台角色授予与四类范围（`ALL`/`TENANT`/`ORGANIZATION`/`ORG_TYPE`，DB §6.6）
- [ ] T046 [US3] 实现 `permission_version` 递增与旧凭证即时失效（tech §6.4）
- [ ] T047 [US3] 实现主体式授权 13 个操作（`x-subject-authz`，权限模型 §7.6）
- [ ] T048 [US3] 审计与事件接线：组织/成员/角色/转让全部动作与 `organization.*`、`ownership.transfer.*`
- [ ] T049 [P] [US3] 集成测试：审批分支、跨租户父子拒绝、提权拒绝、所有者改派拒绝（`test/integration/organization_test.go`）
- [ ] T050 [P] [US3] 授权矩阵测试：祖先继承、兄弟不继承、平台范围并集（`test/integration/authz_test.go`）

**Checkpoint**: 业务系统可在租户内自组织

---

## Phase 6: User Story 4 — 审计可查、可导出、不可篡改 (Priority: P2)

**Goal**: 分级查询、查询留痕、导出与归档、只追加保障

**Independent Test**: 关键操作有审计；应用角色无法改删；导出产生导出审计

### Implementation

- [ ] T051 [US4] 实现审计查询（租户/平台）与游标分页（`internal/core/audit/`）
- [ ] T052 [US4] 实现查询本身留痕（`tenant.audit.queried`、`platform.audit.queried`，审计目录 §2.1）
- [ ] T053 [US4] 实现审计导出任务与下载链接过期（FR-A-05、DB §9.5）
- [ ] T054 [US4] 实现审计月分区维护函数（含新建分区 RLS，research R-05）
- [ ] T055 [P] [US4] RLS/权限测试：租户审计员跨租户查询返回空、应用角色改删被拒（`test/rls/audit_test.go`）

**Checkpoint**: 合规可用

---

## Phase 7: User Story 5 — 扩展模块按 SPI 接入与启停 (Priority: P3)

**Goal**: Manifest 注册、启停、独立 schema、权限/路由/迁移/事件/配置接入

**Independent Test**: 注册示例扩展→启用可用→禁用路由消失且数据保留；违规 Manifest 启动失败

### Implementation

- [ ] T056 [P] [US5] 实现扩展注册表与 Manifest 校验（`internal/core/extension/`，SPI §3/§9）
- [ ] T057 [US5] 实现启用/禁用与路由挂载/卸载（SM §11.1）
- [ ] T058 [US5] 实现扩展权限注册（`namespace='EXT'`，拒绝 `platform.*`）与事件命名校验
- [ ] T059 [US5] 实现扩展迁移隔离与核心表保护（迁移 Job 拒绝改核心表）
- [ ] T060 [US5] 实现 `internal/ext/` 示例扩展（最小 Manifest + 一个受保护路由 + 一个事件）
- [ ] T061 [P] [US5] 集成测试：启停、违规注册、禁用后路由 404（`test/integration/extension_test.go`）
- [ ] T074 [US5] 实现扩展 API 版本兼容校验：Manifest `api_version` 与核心支持范围比对，不兼容的注册/升级被拒绝（FR-E-05、SPI §8）

**Checkpoint**: 平台具备可扩展性

---

## Phase 8: User Story 6 — 服务账号、API Key 与事件出口 (Priority: P3)

**Goal**: 机器身份认证、Key 生命周期、Webhook 投递与死信

**Independent Test**: 服务账号按 scope 调用；Webhook 签名可验证、失败重试进死信

### Implementation

- [ ] T062 [P] [US6] 实现服务账号与 API Key 模型/查询（`internal/core/serviceaccount/`）
- [ ] T063 [US6] 实现 Client Credentials 与 API Key 认证（`/oauth/token`、统一无效凭证码）
- [ ] T064 [US6] 实现 Webhook 端点管理、HMAC 签名、重试/死信/告警（`internal/core/outbox`，SM §11.3）
- [ ] T065 [US6] 实现投递状态查询与重投（`listWebhookDeliveries`、`redeliverWebhook`）
- [ ] T066 [US6] 审计接线：`service_account.*`、`api_key.*`、`security.api_key_anomaly`、`webhook.*`
- [ ] T067 [P] [US6] 集成测试：scope 越权拒绝、Key 撤销、Webhook 签名与死信（`test/integration/serviceaccount_test.go`）
- [ ] T075 [US6] 投递 SLO 与死信断言：消费者可用时 99% 事件 ≤1 分钟送达；失败投递 100% 进入死信并触发告警（SC-009，`test/integration/outbox_slo_test.go`）

**Checkpoint**: 与 Bufaa/Tufaa/MuPlan 可集成

---

## Phase 9: Polish & Cross-Cutting

- [ ] T068 [P] 性能验证：认证/授权 P95 ≤ 50ms、组织树 P95 ≤ 300ms、列表 P95 ≤ 500ms（`k6` 脚本入 `test/load/`）
- [ ] T069 [P] 安全验证：租户逃逸、IDOR、权限提升、SQL 注入、Token 重放（OPS §8.2-1..18）
- [ ] T070 回写基线：README 技术栈与 §4 校验脚本入口（R-01、R-06）、DB §9.5/§15 分区 RLS（R-05）、OpenAPI 幂等豁免注解（R-04，tech §9.1 已于 2026-11-01 回写）
- [ ] T071 覆盖率门禁：`core/*` ≥ 70%、`authz` ≥ 85%（CI 配置）
- [ ] T072 运行 quickstart.md 全流程验证并记录结果
- [ ] T076 [P] 契约测试专项：核心↔扩展、核心↔消费方的请求/响应/错误码契约用例集（`test/contract/`，FR-X-05）

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup（Phase 1）：无依赖，立即开始
- Foundational（Phase 2）：依赖 Setup，**阻塞所有用户故事**
- US1/US2（P1）：Foundational 完成后可并行
- US3/US4（P2）：依赖 US1+US2（需要租户与身份实体）
- US5/US6（P3）：依赖 Foundational；US6 依赖 US2（凭证签发）
- Polish：依赖目标故事完成

### 故事内部顺序

模型 → 服务 → Handler → 审计/事件接线 → 测试；测试须先失败再实现（宪法门禁）。

### Parallel Opportunities

- T002–T006（Setup 文档/工具类）可并行
- T008–T017（Foundational 各组件）大部分可并行，T011 需等待 T009/T010/T013
- US1 与 US2 可由两名开发者并行；US3 与 US4 在 US1/US2 完成后并行

---

## Implementation Strategy

### MVP First

1. Phase 1 + Phase 2
2. Phase 3（US1）+ Phase 4（US2）
3. **STOP & VALIDATE**：按 quickstart 验证 US1/US2
4. 再进入 P2、P3

### 增量交付

每个故事完成后按 quickstart 对应用例独立验证，通过后提交；`make spec-check` 每次 CI 必跑，
防止契约与目录漂移。

## Notes

- [P] 表示不同文件、无依赖，可并行
- T001–T072 为初次拆解；T073–T076 为 `/speckit.analyze` 第 2 轮补充（权限点不可变、扩展版本兼容、
  投递 SLO、契约测试专项），按所属阶段插入，编号因此非严格顺序
- 每个检查点都是可演示状态，避免长时间不可验证的大提交
