# Phase 0 Research: b_platform V2.0 控制面基线

**Feature**: `001-control-plane-baseline` | **Date**: 2026-11-01

基线（`docs/`）已完成选型，本文件只记录**仍需在编码前定稿**的决策点，以及它们的依据。每条
包含：Decision / Rationale / Alternatives considered。

## R-01 契约生成方向（spec-first vs code-first）

- **Decision**：以 spec-first 为准——`docs/30-api/openapi-v2.0.yaml` 是唯一手写契约，
  `oapi-codegen` 从契约生成服务端类型与路由绑定；`huma` 仅用于请求校验与序列化，
  必须关闭其从 Go 类型反向生成 OpenAPI 的能力。
- **Rationale**：宪法原则 II 要求契约先行且契约是唯一权威；若由 Go 类型生成契约，实现即
  权威，契约评审失效，且与四份编码目录的机器校验无法闭环。
- **Alternatives considered**：纯 `huma`（code-first，实现与契约同步但契约失去独立评审点）；
  纯 `oapi-codegen`（无运行时校验辅助，需自写校验层）。基线 README 同时列出 `huma` 与
  `oapi-codegen`，本节视为对冲突的定稿，需回写 README 技术栈表。

## R-02 队列实现

- **Decision**：`river`（Postgres 后端）。
- **Rationale**：复用现有 PostgreSQL，避免一期引入 Redis；事务性入队与 Outbox 同事务语义一致。
- **Alternatives considered**：`asynq`（需 Redis，多一个基础设施与备份项）；自研轮询
  （重试/死信/可见性需自行实现）。

## R-03 迁移工具与执行主体

- **Decision**：`goose`，单文件 up/down；生产 expand/contract；由 `cmd/migrate` 以
  `platform_migrator` 角色执行，API/Worker 不持有 DDL 权限。
- **Rationale**：基线 DB §10 已按此设计角色与门禁；迁移 Job 独立部署便于回滚与审计。
- **Alternatives considered**：`atlas`（声明式 diff 能力强，但与 sqlc 的 SQL-first 流程重叠）。

## R-04 幂等豁免清单（编码前必须定稿）

- **Decision**：以下 13 个写操作**不要求** `Idempotency-Key`，其余写操作要求：
  `register`、`login`、`refresh`、`logout`、`forgotPassword`、`resetPassword`、`verifyEmail`、
  `verifyPhone`、`switchContext`、`revokeSession`、`updateMe`、`changePassword`、
  `clientCredentialsToken`。
- **Rationale**：这些操作要么天然幂等（登出、撤销会话），要么以一次性令牌/凭证为幂等键
  （验证、重置），要么是认证入口（重复提交无副作用累积）；对它们强制幂等头会增加客户端
  负担而不提升正确性。
- **Alternatives considered**：全量要求（实现简单但契约噪声大）；按 HTTP 方法一刀切
  （POST 认证类会被误伤）。需在 `docs/20-design/tech-design-v2.0.md` §9.1 与 OpenAPI 中以
  显式清单/注解固化。
- **Status（2026-11-01）**：已回写 `tech-design-v2.0.md` §9.1；OpenAPI 注解待 T070。按宪法
  治理要求，该基线变更需在正式评审登记为决议（建议 D-11），当前状态为“已回写、待登记”。

## R-05 审计分区与 RLS

- **Decision**：分区维护函数 `fn_ensure_audit_partitions` 在创建分区后追加
  `ALTER TABLE core.<partition> ENABLE ROW LEVEL SECURITY`；同时保持"应用角色只有父表权限"。
- **Rationale**：PostgreSQL 中直接访问分区不会套用父表策略；仅靠权限兜底在新增角色或运维
  直连时会失效，双保险成本极低。
- **Alternatives considered**：仅依赖权限（脆弱）；不分区（审计表 5 亿行量级不可行）。

## R-06 一致性校验脚本入库（宪法原则 VI 的前置）

- **Decision**：把需求/契约/目录/数据库的机器校验做成 `scripts/spec-check/`（Go 或 Python 均可），
  在 CI 中作为独立 job 运行，覆盖：operationId 唯一性与 `$ref` 可解析、受保护操作授权声明
  100%、`Problem.code` 与错误码目录双向 diff、事件白名单边界用例、FR↔operationId 追溯、
  权限点目录与契约一致。
- **Rationale**：基线只留下"2026-10-31 已机器验证"的结论，脚本未入库；基线一旦漂移无法发现。
- **Alternatives considered**：人工评审（不可持续）；只做一次性脚本（无法防回归）。
- **Status（2026-11-01）**：已入库 `scripts/spec-check/`（17 项校验 + 变异自测），
  CI 见 `.github/workflows/spec-check.yml`；`README.md` §4 入口待 T070 补。

## R-07 上下文切换审计

- **Decision**：一期不写审计（沿用预评审决议 D-09），以结构化日志 + 指标承载；二期补审计动作。
- **Rationale**：属已认证读取行为，写审计会显著放大审计表写入量而不增加追责价值。
- **Alternatives considered**：一期即写（成本高、收益低）；完全不记录（运维排障缺信号）。

## 待回写基线的条目

| 编号 | 需回写位置 | 内容 | 状态 |
|---|---|---|---|
| R-01 | `README.md` §6.1 技术栈表 | 明确 spec-first + `oapi-codegen`，`huma` 仅作校验 | 待回写（T070） |
| R-04 | `docs/20-design/tech-design-v2.0.md` §9.1、OpenAPI | 幂等豁免清单 | tech §9.1 已回写（2026-11-01，13/13 与契约一致）；OpenAPI 注解待 T070 |
| R-05 | `docs/20-design/database-design-v2.0.md` §9.5、§15 | 分区 RLS + 检查清单项 | 待回写（T070） |
| R-06 | `README.md` §4、CI 配置 | 校验脚本入口 | 脚本与 CI 已入库（2026-11-01）；README §4 入口待 T070 |
