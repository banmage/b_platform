# Implementation Plan: b_platform V2.0 控制面基线

**Branch**: `001-control-plane-baseline` | **Date**: 2026-11-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-control-plane-baseline/spec.md`

## Summary

实现 b_platform V2.0 控制面：以 Go 模块化单体承载租户、身份认证、组织目录、成员关系、三层
权限、审计、平台配置、扩展注册、服务账号与事件出口；PostgreSQL 16+ 通过 RLS 承担租户隔离，
OpenAPI 3.1 契约先行，四份编码目录（权限/审计/事件/错误码）为机器校验锚点。

技术方案直接沿用 V2.0 设计基线（`docs/`），本计划只负责把基线拆成可执行阶段与门禁，不重新
做技术选型。契约与数据模型以基线为权威，本目录只保留索引与验证入口，避免双份维护。

## Technical Context

**Language/Version**: Go 1.23+（ADR-002）

**Primary Dependencies**: `chi/v5`（路由）+ `oapi-codegen`（契约 → 服务端类型，spec-first，
research R-01）+ `huma/v2`（仅请求校验与序列化，**关闭**从 Go 类型反向生成 OpenAPI）、
`pgx/v5` + `sqlc`（数据访问）、`goose`（迁移）、`golang-jwt/jwt/v5` 或 `go-jose`（RS256/JWKS）、
`argon2id`（密码）、`river`（Postgres 队列，research R-02 已定稿）

**Storage**: PostgreSQL 16+（RLS、部分唯一索引、JSONB、`SECURITY DEFINER`、`FOR UPDATE`）

**Testing**: `go test` + `testify`（单元）、`testcontainers-go`（集成）、`pgTAP`（RLS 矩阵）、
OpenAPI 契约校验、`k6`（负载）、`gosec`/`govulncheck`（安全）

**Target Platform**: Linux 服务器；一期 Docker Compose，后续 Kubernetes

**Project Type**: 单体 Web 服务（API + Worker + 迁移 Job 三个入口）

**Performance Goals**: 认证/授权 P95 ≤ 50ms；组织树查询 P95 ≤ 300ms（单租户万级组织）；
列表分页 P95 ≤ 500ms；审计写入 500 TPS

**Constraints**: 运行时角色不得拥有 `BYPASSRLS`；不得用自定义 GUC 表达平台身份；核心不得
硬编码业务域；扩展不得访问核心表；UUIDv7 主键；`/api/v1` 与 `/api/platform/v1` 双前缀

**Scale/Scope**: 10,000+ 租户、1,000,000+ 用户、61 条 FR、119 个 API 操作、64 个权限点、
83 个审计动作、15 个核心事件、41 个错误码

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁问题 | 结论 |
|---|---|---|
| I. 控制面最小化 | 本计划是否引入资源/预订/论坛/计费等业务域？ | PASS — 全部能力在控制面清单内，业务域留给扩展 |
| II. 契约先行 | 是否有未先落契约的接口变更？ | PASS — 119 个操作已全部在基线契约中 |
| III. 租户隔离不可绕过 | 是否依赖 `BYPASSRLS` 或自定义 GUC？ | PASS — 采用独立角色 + 租户上下文 + 同事务审计 |
| IV. 授权统一 | 是否存在 Handler/Service 硬编码角色判断？ | PASS — 统一 `authz.Authorizer`，权限点不可变 |
| V. 审计同事务只追加 | 是否允许异步/事后补写审计？ | PASS — 同事务写入，应用角色无 UPDATE/DELETE |
| VI. 可追溯与机器校验 | 是否有可复跑的一致性校验？ | 需在实现阶段补齐 — 基线只声明"已机器验证"，脚本未入库（见 tasks Phase 1） |
| VII. 扩展隔离 | 扩展是否触碰核心表？ | PASS — 独立 schema + SPI，迁移 Job 拒绝改核心表 |

**Gate 结论**：通过（VI 项以实现阶段补脚本为前置任务，不构成阻塞）。

## Project Structure

### Documentation (this feature)

```text
specs/001-control-plane-baseline/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出：待定项与决策记录
├── data-model.md        # Phase 1 输出：实体与约束索引
├── quickstart.md        # Phase 1 输出：端到端验证入口
├── contracts/           # Phase 1 输出：契约索引（权威契约在 docs/30-api）
├── checklists/          # /speckit.checklist 输出
└── tasks.md             # /speckit.tasks 输出
```

### Source Code (repository root)

```text
cmd/
├── platform/main.go          # API 进程
├── worker/main.go            # Outbox / Webhook / 清理
└── migrate/main.go           # 迁移 Job

internal/
├── core/
│   ├── tenant/               # 租户生命周期与配置
│   ├── identity/             # 用户、认证、会话、密码、验证
│   ├── organization/         # 组织树、审批、冻结、所有权转让
│   ├── membership/           # 租户/组织成员、邀请、加入
│   ├── authz/                # 权限点、角色、授权、判定
│   ├── audit/                # 审计写入、查询、导出
│   ├── config/               # 平台参数、租户配置
│   ├── extension/            # 扩展注册表、SPI
│   ├── serviceaccount/       # 服务账号、API Key
│   └── outbox/               # 事务性事件、Webhook 投递
├── platform/                 # 组合根：http / db / auth / config
├── ext/                      # 编译期扩展模块（示例）
└── worker/

db/
├── migrations/               # goose
├── queries/                  # sqlc 输入
├── sqlc.yaml
└── seeds/

api/openapi/openapi-v2.0.yaml # 发布产物：由构建脚本从 docs/30-api 复制，禁止手改

deploy/                       # Docker Compose 等
test/
├── integration/
├── rls/
└── contract/
```

**Structure Decision**: 单仓库单体，按 `core/<domain>` 分模块（接口 + sqlc 实现分离），
`platform/` 作组合根；扩展放在 `internal/ext/` 编译期加载。模块依赖规则见基线
`docs/20-design/tech-design-v2.0.md` §3.1（R1–R6），CI 用 `go list -deps`/`depguard` 校验。

## Phase Plan

- **Phase 0（研究）**：确认基线中的待定项（契约方向、队列选型、迁移工具、幂等豁免）与外部依赖
  约束；已定稿于 [research.md](./research.md)（R-01~R-07）。
- **Phase 1（设计落地）**：实体/约束索引（[data-model.md](./data-model.md)）、契约索引
  （[contracts/README.md](./contracts/README.md)）、验证入口（[quickstart.md](./quickstart.md)）。
- **Phase 2（任务拆解）**：`/speckit.tasks` 按用户故事优先级拆任务。
- **Phase 3（实现）**：按 tasks 顺序实现，逐故事独立验证。

## Complexity Tracking

> 无宪法违规项需要辩护。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Post-Design Constitution Re-Check

Phase 1 产物仍不引入业务域、不引入契约副本（`contracts/` 仅索引基线契约）、不绕过统一授权与
同事务审计，因此门禁结论保持 PASS；VI（机器校验脚本入库）转为 tasks 中的显式前置任务。
