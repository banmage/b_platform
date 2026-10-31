# 架构决策记录（ADR）

**项目：** b_platform  
**版本：** V2.0  
**状态：** 已决策  
**日期：** 2026-10-31

本文件记录 b_platform 作为独立控制面项目的关键架构决策。后续变更必须新增 ADR，不直接修改已生效决策。

---

## ADR-001：数据库使用 PostgreSQL 16+

**状态：** 已接受

**决策：**

- 生产与测试数据库统一使用 PostgreSQL 16 或更高版本。
- 不使用 MySQL 作为主数据库。

**理由：**

1. 平台租户隔离依赖 PostgreSQL Row Level Security（RLS）。
2. 成员有效唯一、创建者唯一、平台授权有效唯一等约束依赖部分唯一索引。
3. `JSONB`、`GIN`、`TIMESTAMPTZ`、`INET`、`ARRAY`、`SECURITY DEFINER` 函数和受控视图适合审计、配置和跨租户访问。
4. 组织闭包表、递归查询、`FOR UPDATE` / `SKIP LOCKED`、逻辑复制和 CDC 生态成熟。
5. MySQL 没有等价的原生 RLS，切换到 MySQL 会使租户隔离退化为应用层过滤，不符合本平台的安全目标。

**影响：**

- 所有数据库迁移、测试、备份恢复都必须以 PostgreSQL 为准。
- 不使用内存数据库替代 PostgreSQL 做 RLS/事务集成测试。
- 字符集使用 UTF8；排序规则使用 `C.UTF-8`，中文排序通过 ICU collation 或应用层处理。

---

## ADR-002：后端语言使用 Go

**状态：** 已接受

**决策：**

- b_platform 核心服务使用 Go 1.23+。
- 数据访问使用 `pgx/v5` + `sqlc`，不使用重型 ORM。
- HTTP 层使用 `chi` + `huma` 或 `echo`，OpenAPI 契约优先。

**理由：**

1. Bufaa、Tufaa 已选择 Go，b_platform 与之对齐，可共享认证、ID、日志、迁移等基础设施经验。
2. 平台是数据库密集型服务，Go + `pgx` 对事务、连接、RLS 上下文和原生 SQL 的控制更直接。
3. 单二进制、低内存、容器部署简单，适合作为多项目共用的基础平台。
4. `context.Context` 显式传递请求上下文，减少隐式上下文泄漏。
5. `sqlc` 生成类型安全代码，避免 ORM 隐藏 SQL 和事务边界。

**影响：**

- 不引入 TypeORM/Prisma 等 ORM。
- 业务 SQL 统一放在 `queries/`，由 `sqlc` 生成。
- 复杂查询、RLS 测试、迁移脚本必须可审查。
- 前端/管理后台可以使用 TypeScript，但不作为核心服务语言。

**备选方案：**

- Node.js/NestJS：开发速度快，但 TypeORM 与 RLS 事务上下文容易出错；如团队 TypeScript 优先，可作为次选，但必须使用 Kysely/Drizzle + `pg`。
- Rust：性能和安全性强，但 CRUD/后台类平台开发成本高；Rust 保留给 MuPlan 调度内核。

---

## ADR-003：采用模块化单体

**状态：** 已接受

**决策：**

- 一期采用模块化单体（Modular Monolith）。
- 模块之间通过接口、领域事件和事务边界协作，不直接访问对方表。
- 后续根据负载和团队边界拆分服务。

**理由：**

1. 控制面核心模块（租户、身份、组织、权限、审计）共享强事务一致性，过早微服务化会增加分布式事务成本。
2. 模块化单体可以保持清晰边界，同时降低部署和运维复杂度。
3. 平台初期规模不需要微服务；拆分应以实际瓶颈为依据。

**模块边界：**

```text
tenant
identity
organization
membership
authz
audit
config
extension
serviceaccount
outbox
```

**禁止：**

- 跨模块直接 JOIN 对方表。
- 在 Controller 中直接调用其他模块 Repository。
- 扩展模块直接访问核心表。

---

## ADR-004：Platform 是独立控制面，不是根组织

**状态：** 已接受

**决策：**

- Platform 不建模为 Organization。
- Platform 不进入任何租户的组织树。
- 平台运营人员不是租户成员，不通过租户角色获得权限。
- 平台级数据（用户、平台角色、权限点、平台参数、扩展注册表、服务账号）与租户数据分离。

**理由：**

1. Platform 是全局控制面，不是某个业务组织。
2. 把 Platform 作为根组织会导致“超级租户”模型，RLS 和权限边界复杂。
3. 独立控制面可以清晰区分平台运营、租户运营和组织运营。
4. 便于平台独立部署、独立审计、独立演进。

**影响：**

- `tenant` 与 `organization` 是分离的实体。
- 平台管理员跨租户访问必须经过独立角色、目标租户上下文和审计。
- 平台级表不参与组织 RLS，但必须通过数据库角色和表级授权严格限制。

---

## ADR-005：Tenant 与 Organization 解耦

**状态：** 已接受

**决策：**

- `Tenant` 是数据隔离边界。
- `Organization` 是租户内部的业务组织，可树形层级。
- 一个 Tenant 可以包含多个 Organization。
- 子 Organization 不自动成为独立 Tenant。
- 如业务需要独立隔离，应创建独立 Tenant，而不是把子组织当作租户。

**理由：**

1. 原设计“一个组织 = 一个租户”导致组织树跨租户，父组织审批子组织、父组织查看下级数据都必须绕过 RLS，复杂且危险。
2. Tenant/Organization 解耦后，RLS 只需按 `tenant_id` 过滤，组织树在租户内，权限模型更清晰。
3. 更符合 Bufaa/Tufaa 的集团、品牌、门店、场馆等层级场景。
4. 未来支持“一个租户内多个组织”“集团多租户”更容易。

**影响：**

- 所有租户业务表包含 `tenant_id`。
- `organization` 包含 `tenant_id` 和 `parent_id`，父子必须同租户。
- `organization_closure` 包含 `tenant_id`。
- 平台跨租户访问不再需要跨租户组织树函数。

---

## ADR-006：扩展模块 SPI

**状态：** 已接受

**决策：**

- 核心只实现控制面能力。
- 资源、预订、论坛、计费等业务能力通过扩展模块接入。
- 扩展模块通过 Manifest 注册权限、路由、迁移、事件、配置和 UI 扩展点。
- 扩展模块不得直接访问核心表，只能通过核心服务接口、API 或事件。

**理由：**

1. 避免 b_platform 重新变成某个行业项目的后端。
2. 保证核心长期稳定，业务变化通过扩展实现。
3. 支持不同项目按需启用模块。
4. 为未来拆分独立服务保留边界。

**影响：**

- 一期不实现 `resource.*`、`booking.*`、`forum.*`。
- 扩展命名空间 `ext.<module>.`：权限为 `ext.<module>.<resource>.<action>`，事件为 `ext.<module>.<entity>.<action>`（`action` 允许一个点分限定符，V2.0 细化）。
- 扩展表使用独立 schema `ext_<module>`。
- 扩展迁移独立管理，不能修改核心表。

---

## ADR-007：对外 ID 使用 UUIDv7

**状态：** 已接受

**决策：**

- 所有业务实体主键使用 UUIDv7。
- 由应用层生成，不使用数据库自增。
- API 中 ID 使用字符串（`type: string, format: uuid`）。

**理由：**

1. 避免雪花 ID 的 worker ID 分配和时钟回拨问题。
2. 避免 JavaScript/Node 客户端解析 `int64` 精度丢失。
3. 跨语言、跨服务、跨数据库迁移友好。
4. UUIDv7 按时间有序，索引局部性优于 UUIDv4。

**影响：**

- 数据库主键类型为 `UUID`。
- 索引体积大于 `BIGINT`，但控制面数据量可控。
- 如需极致写入性能，可在内部使用 `BIGINT` 代理键，但对外仍暴露 UUIDv7。

---

## ADR-008：不使用 `BYPASSRLS`，不用 GUC 做授权

**状态：** 已接受

**决策：**

- 运行时不使用 `BYPASSRLS` 数据库角色。
- 不使用 `app.is_platform_access`、`app.is_platform_write` 等自定义 GUC 作为授权依据。
- 租户上下文只使用 `app.tenant_id`，由服务端在认证、授权后设置。
- 平台跨租户访问使用独立 `platform_control` 角色，设置目标租户上下文，并在同一事务内写审计。
- 受控函数只做数据访问收敛，不复制完整权限判定。

**理由：**

1. 自定义 GUC 默认不是权限边界，任何能执行 SQL 的连接都可以 `SET`。
2. `BYPASSRLS` 的连接一旦被注入利用，就是全量数据泄露。
3. 目标租户上下文 + RLS 可以满足绝大多数平台跨租户查询。
4. 减少“应用层授权 + 数据库受控函数”两套逻辑不一致的风险。

**影响：**

- 平台跨组织聚合/报表使用独立只读视图、离线 ETL 或受控服务，不开放在线 `BYPASSRLS`。
- 受控函数必须检查 `current_user`/`session_user`，不能只检查 GUC。
- 所有平台跨租户访问必须有审计记录。

---

## ADR-009：API-first 与版本化

**状态：** 已接受

**决策：**

- OpenAPI 3.1 是 API 唯一权威契约。
- 用户/租户 API 前缀：`/api/v1`。
- 平台控制面 API 前缀：`/api/platform/v1`。
- 扩展 API 前缀：`/api/v1/ext/<module>`。
- 事件使用 `event_type` + `event_version`。
- 破坏性变更必须提升主版本，并保留弃用周期。

**理由：**

1. b_platform 会被多个项目、多种语言消费，契约必须稳定。
2. 版本化 URL 简单、可缓存、易观测。
3. OpenAPI 生成客户端，减少手写 SDK。

**影响：**

- 所有新增接口先改 OpenAPI，再实现。
- 错误响应使用 RFC 9457 Problem Details 风格。
- 分页使用 cursor，不使用 offset 作为唯一分页方式。

---

## ADR-010：核心最小化

**状态：** 已接受

**决策：**

- 核心只保留控制面能力。
- 以下能力不进入核心：
  - 资源目录/资源发布
  - 预订/预约
  - 论坛
  - 计费/结算
  - 行业字典
  - 文件/对象存储
  - 通知渠道实现（只定义事件/接口）
- 需要时以扩展模块或独立服务实现。

**理由：**

1. 核心越小，越稳定，越容易被多个项目复用。
2. 业务域变化不应导致核心升级。
3. 扩展模块可以按项目启用/禁用。

**影响：**

- 旧版 `resource.*`、`booking.*`、`forum.*` 权限点从核心移除。
- 旧版 `resource_type IN ('PRODUCT','VENUE','SERVICE')` 不再作为核心枚举。
- 扩展模块通过 SPI 注册自己的权限和表。
