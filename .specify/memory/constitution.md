<!--
Sync Impact Report
==================
Version change: (none, template scaffold) → 1.0.0
Modified principles: n/a (initial ratification)
Added sections:
  - Core Principles (I–VII)
  - 技术约束 (Technical Constraints)
  - 开发工作流与质量门禁 (Development Workflow & Quality Gates)
  - Governance
Removed sections: none
Templates requiring updates: none (templates read constitution at runtime)
Follow-up TODOs: none
-->

# b_platform Constitution

## Core Principles

### I. 控制面最小化（Control Plane Only）

核心只提供控制面能力：租户、身份认证、组织目录、成员关系、角色与权限、审计、平台配置、
扩展注册、服务账号/API Key、事件出口。资源目录、预订、论坛、计费、行业业务数据 MUST NOT
进入核心，只能作为扩展模块或独立业务系统实现。

Rationale: 核心一旦吸收业务域，就无法被 Bufaa、Tufaa、MuPlan 等多个系统复用，模块边界
也会被业务变更持续侵蚀。

### II. 契约先行（Contract First）

`docs/30-api/openapi-v2.0.yaml` 是 API 的唯一权威来源。任何接口变更 MUST 先改契约，再改实现；
实现与契约不一致时以契约为准。错误码、审计动作、事件编码、权限点四份目录
（`docs/20-design/`）是各自编码的唯一权威清单，目录与契约冲突时以目录为准，且目录升版
MUST 同步契约快照。

Rationale: 平台被多个系统消费，契约漂移会直接变成跨项目故障；四份目录是机器可校验的一致性
锚点。

### III. 租户隔离不可绕过（Non-Bypassable Tenant Isolation）

所有租户数据表 MUST 含 `tenant_id` 并启用 RLS；策略默认拒绝。运行时数据库角色 MUST NOT
拥有 `BYPASSRLS`，MUST NOT 使用自定义 GUC（如 `app.is_platform_access`）表达平台身份或写
权限。跨租户访问 MUST 通过独立数据库角色 + 显式租户上下文 + 同事务审计完成。

Rationale: 应用层漏洞可以修，数据库层的隔离缺口会一次性泄露全平台数据。

### IV. 授权统一且不可提权（Unified, Non-Escalating Authorization）

所有授权判定 MUST 走 `authz.Authorizer`；Handler/Service MUST NOT 硬编码角色判断。权限点编码
一经发布不可修改，只能废弃后新增。授予或修改角色时，目标权限集合 MUST 是操作者权限集合的
子集；所有者角色 MUST 只经专用转让流程变更。扩展只能注册 `TENANT`/`ORGANIZATION` 作用域权限。

Rationale: 分散的判定逻辑与可变的权限编码是权限提升漏洞的主要来源。

### V. 审计同事务、只追加（Same-Transaction, Append-Only Audit）

关键安全事件 MUST 与业务事务同事务写入；审计写入失败 MUST 导致业务失败并回滚。审计记录
MUST NOT 被更新或删除；应用角色只持有 `INSERT`（必要时 `SELECT`），MUST NOT 持有
`UPDATE`/`DELETE`/`TRUNCATE`。

Rationale: 事后补写的审计无法用于追责，可篡改的审计等于没有审计。

### VI. 可追溯与可机器校验（Traceability & Machine Verification）

每条 FR MUST 能在契约、权限点、审计动作、Outbox 事件、测试锚点中找到落点。需求、契约、
目录、数据库设计之间的一致性 MUST 通过可复跑的脚本校验（而非一次性人工声明），并作为
CI 门禁的一部分。

Rationale: 61 条 FR 与 119 个操作的人工核对不可持续，基线漂移必须由机器发现。

### VII. 扩展隔离（Extension Isolation）

扩展 MUST 通过 SPI 注册（Manifest：权限、路由、迁移、事件、配置 schema、UI 扩展点），使用
独立 schema `ext_<module>`，MUST NOT 修改核心表结构或直接访问核心表。核心 MUST NOT 依赖任何
扩展模块。

Rationale: 扩展是平台演进的主要变更来源，隔离是保证核心稳定的前提。

## 技术约束（Technical Constraints）

- 语言与运行时：Go 1.23+，模块化单体，单二进制部署（ADR-002、ADR-003）。
- 数据库：PostgreSQL 16+，使用 RLS、部分唯一索引、JSONB、`SECURITY DEFINER`、`FOR UPDATE`
  （ADR-001）。
- 标识：对外主键 MUST 使用 UUIDv7，MUST NOT 使用自增 ID 或雪花 ID（ADR-007）。
- 数据访问：`pgx/v5` + `sqlc`；复杂 SQL MUST 经审查。
- 认证：JWT RS256 + JWKS + Refresh Token 轮换；密码 Argon2id；服务账号支持 OAuth2 Client
  Credentials 与 API Key（API Key 只存哈希）。
- 部署：一期 Docker Compose，后续 Kubernetes；迁移 MUST 可重复执行且支持 expand/contract。
- 模块规则：模块间通过接口/事件协作，MUST NOT 直接访问对方表；核心模块 MUST NOT 依赖扩展。

## 开发工作流与质量门禁（Development Workflow & Quality Gates）

- 变更流程：spec（需求/场景）→ plan（技术方案）→ tasks（可执行任务）→ implement（编码）；
  每个阶段 MUST 通过评审门禁后再进入下一阶段。
- 设计基线：`docs/` 为 V2.0 设计基线；基线变更 MUST 记录于 ADR 或预评审决议
  （`docs/00-architecture/`），并同步受影响目录与契约。
- 编码门禁：设计基线评审通过前 MUST NOT 开始编码（README §8）。
- 测试门禁：单元/集成/RLS/契约测试 MUST 通过；核心覆盖率 ≥ 70%，`authz` ≥ 85%；迁移文件
  成对且通过空库/升级库测试；OpenAPI 变更 MUST 附带实现与测试。
- 安全门禁：MUST 覆盖租户逃逸、IDOR、权限提升、SQL 注入、Token 重放；镜像扫描无
  Critical/High。

## Governance

本宪法优先于其他开发实践。与之冲突的代码、文档或流程 MUST 被修正，而不是被解释性绕过。

- 修订程序：宪法修订 MUST 以显式变更提出，说明动机、影响范围与迁移方案，经项目负责人批准
  后生效；修订 MUST 同步更新版本号与日期。
- 版本策略：MAJOR 为原则删除或重定义；MINOR 为新增原则或实质性扩展；PATCH 为措辞澄清。
- 合规审查：每个功能的 plan 阶段 MUST 通过 Constitution Check；实现与评审 MUST 验证合规性，
  违反项 MUST 在 Complexity Tracking 中说明理由或被拒绝。
- 权威顺序：宪法 → `docs/` 设计基线 → 四份编码目录 → OpenAPI 契约 → 实现代码。

**Version**: 1.0.0 | **Ratified**: 2026-11-01 | **Last Amended**: 2026-11-01
