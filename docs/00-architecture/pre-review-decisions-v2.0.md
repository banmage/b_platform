# b_platform 设计预评审决议记录 V2.0

**日期：** 2026-10-31
**评审方式：** 四份权威清单（审计/事件/错误码/权限点）全库对齐修复 + 独立对抗性复核（预评审）+ 项目负责人逐项追认
**状态：** 预评审通过（GO conditionally→已闭环）；正式评审仅须对本文逐条核对
**验证快照：** OpenAPI 3.1 解析通过；119 operations；Problem.code enum 41 码与错误码目录双向 diff 零差异；事件白名单 14 项边界用例全过；非公开受保护操作权限/主体声明覆盖率 100%；悬空 `$ref` 0

---

## 1. 追认决议（D-01 ~ D-08）

以下为预评审过程中产出的代裁决与语义定稿，评审负责人已于 2026-10-31 逐项确认为最终口径。

| 编号 | 决议 | 落点 |
|---|---|---|
| D-01 | `ACCOUNT_LOCKED` HTTP 状态定为 **423 Locked**（与 OpenAPI 契约对齐；`detail` 携带剩余时间） | 错误码目录 §3.1、openapi login |
| D-02 | `PERMISSION_VERSION_STALE`：客户端刷新 Token **并携带新 Token 重试原请求一次** | 错误码目录 §3.1/§5、权限模型 §7.3 |
| D-03 | 高危权限（`is_dangerous`）语义 = **审计增强标记 + 授权不受影响**：一期仅审计增强（成功 `SUCCESS`、高危路径拒绝 `DENIED`），二期 step-up（`403 STEP_UP_REQUIRED`） | 权限模型 §3.2/§7.1/§8.2、DB §6.6、tech §4.3、审计目录 §4 规则 4 |
| D-04 | 预留/无单点接口权限点清单与 **58/64 直接映射** 口径 | 权限模型 §3.4、traceability §12 |
| D-05 | 组织归档以新增 **`archiveOrganization`**（`POST /organizations/{id}/archive`）承载，复用 `tenant.organization.freeze` 权限；不删除 ARCHIVED 状态 | openapi、审计目录 §3.3、traceability FR-O-06 |
| D-06 | 一次性令牌撤销**不设独立 REVOKED 状态**：撤销同样写 `consumed_at`（派生 CONSUMED），消费/撤销语义由审计动作区分 | 状态机 §4.2、审计目录 §3.1 |
| D-07 | 扩展编码段数定稿：权限 `ext.<module>.<resource>.<action>`、事件 `ext.<module>.<entity>.<action>`（ext 后两段），`action` 允许**一个**点分限定符 | 权限模型 §3.1、事件目录 §6、SPI §3、ADR-006 |
| D-08 | 主体式授权（subject-scoped）以 OpenAPI 注解 **`x-subject-authz`** 声明，13 个操作清单与归属判定见权限模型 §7.6；契约测试按 §12.3 双轨规则 | 权限模型 §7.6/§12.3、openapi 13 处 |

## 2. 本轮新决策（D-09 ~ D-10）

| 编号 | 决议 | 落点 |
|---|---|---|
| D-09 | 多租户/组织上下文切换（`switchContext`）**一期不写审计**：已认证级读取行为，由应用日志与指标承载；**二期工程补审计** | 审计目录 §2.1 规则 6、traceability FR-I-10 |
| D-10 | **版本控制由评审负责人在开发启动前建立远程 Git 仓库**：将本次文档状态提交为设计基线（建议 tag `v2.0-design-baseline`），正式评审通过后再打 `v2.0-review-passed` | README §8 |

## 3. 二期清单（本记录内无阻塞，顺手登记）

- `switchContext` 审计（D-09）。
- 高危权限 step-up（MFA/重新验证，参数 `security.require_mfa_for_dangerous`）。
- one_time_token 独立 `revoked_at` 列（如运维需要区分撤销/消费落库差异时评估）。
- Webhook 事件订阅中段通配（`tenant.membership.*` 类），按消费反馈再放行。
- OpenAPI `x-audit` 注解（可选增强：把审计目录"接口锚点"列变机器可校验）。
- 权限模型 §10 映射表收敛为引用 §7.6/§12.3（避免同义两处维护）。

## 4. 正式评审接口说明

正式评审**不再重新审查全库一致性**（已机器验证并固化于本记录），仅需：

1. 对 §1 ~ §2 的 10 条决议逐条确认（或变更并注明理由）；
2. 对 README §8 状态页打勾"设计基线评审通过"；
3. 由评审负责人执行 D-10 建 git 基线。

## 5. 相关文档

- [审计动作目录 V2.0](../20-design/audit-catalog-v2.0.md)
- [事件目录 V2.0](../20-design/event-catalog-v2.0.md)
- [错误码目录 V2.0](../20-design/error-codes-v2.0.md)
- [权限模型 V2.0](../20-design/permission-model-v2.0.md)
- [状态机 V2.0](../20-design/state-machines-v2.0.md)
- [追溯矩阵 V2.0](../10-requirements/traceability-v2.0.md)
- [OpenAPI 契约 V2.0](../30-api/openapi-v2.0.yaml)
