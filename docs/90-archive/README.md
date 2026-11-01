# V1.x 历史文档归档说明

**状态：已归档 / 仅用于追溯**  
**归档日期：2026-10-31**

---

## 1. 归档目的

本目录用于说明 V1.x 历史文档的地位。V1.x 原始文件**未纳入本仓库**（归档在项目组外部存储），
本目录只保留归档清单与 V2.0 替代关系。

归档文档保留用于：

- 追溯 V2.0 设计决策的来源与变更理由；
- 对照历史方案，理解哪些问题在 V2.0 中被修正；
- 迁移旧系统或旧数据时，查询历史字段、状态和接口定义。

归档文档**不再作为开发基线**，不得作为以下工作的依据：

- 新代码实现；
- 数据库迁移；
- API 契约；
- 测试用例设计；
- 对外集成约定。

---

## 2. 归档清单

| 文件 | 原主题 | V2.0 替代文档 |
|---|---|---|
| `通用业务底座平台 需求规格说明书v1.2.txt` | 早期需求草案 | [`../10-requirements/requirements-v2.0.md`](../10-requirements/requirements-v2.0.md) |
| `通用业务底座平台 需求规格说明书v1.3.md` | 需求规格（最后一版 V1.x） | [`../10-requirements/requirements-v2.0.md`](../10-requirements/requirements-v2.0.md) |
| `通用业务底座平台 技术设计说明书.md` | 早期技术设计 | [`../20-design/tech-design-v2.0.md`](../20-design/tech-design-v2.0.md) |
| `通用业务底座平台 技术设计说明书V1.1.md` | 技术设计 V1.1 | [`../20-design/tech-design-v2.0.md`](../20-design/tech-design-v2.0.md) |
| `通用业务底座平台 数据库设计说明书v1.0.md` | 早期数据库设计 | [`../20-design/database-design-v2.0.md`](../20-design/database-design-v2.0.md) |
| `通用业务底座平台 权限模型设计说明书v1.0.txt` | 早期权限模型 | [`../20-design/permission-model-v2.0.md`](../20-design/permission-model-v2.0.md) |
| `通用业务底座平台 状态机与并发规则设计说明书v1.0.md` | 早期状态机 | [`../20-design/state-machines-v2.0.md`](../20-design/state-machines-v2.0.md) |
| `通用业务底座平台 OpenAPI 契约v1.0.md` | 早期 API 契约 | [`../30-api/openapi-v2.0.yaml`](../30-api/openapi-v2.0.yaml) |

归档原始文件不在本仓库内；上表文件名为归档时的原始文件名，需追溯时向项目组索取。

---

## 3. V1.x 与 V2.0 的关键差异

以下差异是阅读归档文档时最容易产生误解的部分：

| 主题 | V1.x | V2.0 |
|---|---|---|
| 平台与租户关系 | 平台被视为根组织，进入组织树 | 平台是独立控制面，不属于任何租户组织树（ADR-004） |
| 数据隔离 | 应用层过滤为主 | PostgreSQL RLS + 租户上下文（ADR-008） |
| 权限模型 | 以角色为主的二维模型 | Platform / Tenant / Organization 三层模型，权限点 + 范围 |
| 主键 | 自增 / 雪花 ID | UUIDv7（ADR-007） |
| 跨租户运维 | 使用高权限连接 | 独立数据库角色 + 显式租户上下文 + 审计，不使用 `BYPASSRLS` 运行时授权 |
| 扩展能力 | 核心内硬编码业务域 | 扩展模块 SPI 注册（ADR-006） |
| API 契约 | Markdown 描述 | OpenAPI 3.1 为唯一权威来源（ADR-009） |
| 服务账号 | 角色绑定 | 一期仅显式 `scopes`，API Key 继承服务账号权限 |
| 访问令牌 | 单一版本号 | `pv` 为对象 `{u,t,m,o,om}`，按权限域分别失效 |

完整决策见 [`../00-architecture/decisions-v2.0.md`](../00-architecture/decisions-v2.0.md)。

---

## 4. 使用规则

1. **新增设计不写入本目录。** 新文档一律放到对应的 V2.0 目录。
2. **不得修改归档原文。** 如需勘误，在 V2.0 文档中说明，而不是回改历史文件。
3. **引用归档内容时必须标注版本。** 例如：“V1.1 技术设计曾采用自增主键，V2.0 已改为 UUIDv7。”
4. **冲突时以 V2.0 为准。** 归档文档与 V2.0 文档冲突，一律以 V2.0 文档为准。

---

## 5. 相关文档

- [项目入口](../../README.md)
- [总体架构 V2.0](../00-architecture/architecture-v2.0.md)
- [架构决策 V2.0](../00-architecture/decisions-v2.0.md)
