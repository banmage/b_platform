# Security Requirements Checklist: b_platform V2.0 控制面基线

**Purpose**: 评审安全域需求的质量（完整性 / 清晰度 / 一致性 / 可度量 / 覆盖），作为设计基线
安全门禁的评审工件
**Created**: 2026-11-01
**Feature**: [spec.md](../spec.md)

**Note**: 本清单由 `/speckit.checklist` 基于特性上下文生成，检验的是**需求写得是否合格**，
不是实现是否正确。
**Review Ownership**: 评审人所有的需求质量评审工件。仅在评审人确认某条需求质量标准已满足时
才勾选 `[x]`。
**Marker Semantics**: `[x]` 表示“该需求质量维度已评审通过”，**不代表**实现完成。

## 认证与凭证

- [ ] CHK001 是否为所有受保护面（平台入口 / 租户入口 / 服务账号入口）分别定义了认证需求？[Completeness, Spec §FR-I-02、§FR-I-11]
- [ ] CHK002 账号锁定阈值是否被量化，或明确声明为可配置并给出默认值？[Clarity, Spec §FR-I-07]
- [ ] CHK003 刷新凭证重用的检测与处置需求是否完整（检测时机、处置动作、通知对象）？[Completeness, Spec §FR-I-03]
- [ ] CHK004 会话失效触发条件是否穷举（密码重置、账号禁用、成员移除、角色变更）？[Completeness, Spec §FR-I-03、§FR-I-08、§FR-M-09]
- [ ] CHK005 一次性令牌的“一次性”与“有时效”是否给出可验证判定标准（有效窗口、重复使用结果）？[Measurability, Spec §FR-I-06]
- [ ] CHK006 限流需求是否按端点类别量化（登录、注册、重置、API Key 使用）？[Clarity, Gap, Spec §FR-I-07]

## 租户隔离

- [ ] CHK007 “租户隔离”是否以可观察结果表述（返回空/404/拒绝），而非依赖实现机制描述？[Measurability, Spec §FR-T-06]
- [ ] CHK008 隔离需求是否覆盖非请求路径（后台任务、导出、迁移、平台强制作业）？[Coverage, Gap]
- [ ] CHK009 平台跨租户强制管理是否同时定义了授权、审计与范围限制三项要求？[Consistency, Spec §FR-T-04]
- [ ] CHK010 伪造上下文的处置需求是否明确（拒绝还是降级为无上下文）？[Clarity, Spec §FR-T-06]

## 授权与提权防护

- [ ] CHK011 提权防护规则是否对“授予”和“撤销”两条路径对称表述？[Consistency, Spec §FR-M-06]
- [ ] CHK012 所有者角色保护是否同时覆盖租户与组织作用域，并说明平台强制转让的边界？[Completeness, Spec §FR-M-07、§FR-O-07]
- [ ] CHK013 平台角色四类授权范围的并集语义与“是否含后代”是否有无歧义定义？[Clarity, Spec §FR-M-08]
- [ ] CHK014 扩展权限的命名空间与作用域限制是否可机械校验（而非仅原则性描述）？[Measurability, Spec §FR-P-05、§FR-E-04]
- [ ] CHK015 权限变更的生效时延是否被量化（“下一请求即失效”是否可验证）？[Measurability, Spec §FR-M-05、§FR-M-09]

## 审计与不可篡改

- [ ] CHK016 审计覆盖清单是否与关键安全事件一一对应且无遗漏（含拒绝路径）？[Completeness, Spec §FR-A-01]
- [ ] CHK017 “关键安全事件”的范围是否有明确枚举，以便判定同事务写入的适用范围？[Ambiguity, Spec §FR-A-02]
- [ ] CHK018 “审计不可更新/删除”是否给出可验证的判定方式（角色权限矩阵或约束）？[Measurability, Spec §FR-A-03]
- [ ] CHK019 审计查询本身留痕的需求是否定义了留痕内容与最小保留期？[Completeness, Spec §FR-A-04]
- [ ] CHK020 审计导出/归档的保留周期是否量化并给出默认值？[Clarity, Spec §FR-A-05]

## 敏感数据与密钥

- [ ] CHK021 密钥/令牌/密码在存储与日志中的处理要求是否完整（只存哈希、禁止落日志）？[Completeness, Gap]
- [ ] CHK022 密钥轮换与泄露响应是否定义了触发条件、时限与影响面？[Gap, Exception Flow]
- [ ] CHK023 API Key 的“只显示一次”是否有明确的后续找回策略（不可找回 vs 可轮换）？[Clarity, Spec §FR-S-03]

## 异常与恢复

- [ ] CHK024 是否定义了安全组件不可用时的失败模式（审计不可写、密钥服务不可达）？[Coverage, Exception Flow, Gap]
- [ ] CHK025 是否定义了越权尝试的响应策略（统一错误 vs 显式拒绝）及其反枚举要求？[Clarity, Spec §SC-008]

## 依赖与假设

- [ ] CHK026 安全相关的假设是否被显式记录并标注验证责任方（如外部渠道、消费方校验）？[Assumption, Spec §Assumptions]
- [ ] CHK027 威胁模型范围（IDOR、租户逃逸、提权、注入、令牌重放）是否与需求条目建立追溯？[Traceability, Spec §SC-008]

## Notes

- 仅在评审人确认需求质量标准满足后勾选 `[x]`；未勾选表示仍需澄清、修正或评审判断。
- `/speckit.implement` 会读取勾选状态作为门禁，且不得修改标记。
- `checklists/requirements.md` 是 `/speckit.specify` 维护的内置规格质量清单，与本文件生命周期独立。
