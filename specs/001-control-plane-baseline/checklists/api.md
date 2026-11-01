# API Requirements Checklist: b_platform V2.0 控制面基线

**Purpose**: 评审 API 契约域需求的质量（完整性 / 清晰度 / 一致性 / 可度量 / 覆盖），作为契约
先行门禁的评审工件
**Created**: 2026-11-01
**Feature**: [spec.md](../spec.md)

**Note**: 本清单由 `/speckit.checklist` 基于特性上下文生成，检验的是**需求写得是否合格**，
不是接口实现是否正确。
**Review Ownership**: 评审人所有的需求质量评审工件。仅在评审人确认某条需求质量标准已满足时
才勾选 `[x]`。
**Marker Semantics**: `[x]` 表示“该需求质量维度已评审通过”，**不代表**实现完成。

## 错误与失败语义

- [ ] CHK001 是否为所有失败类别（校验、认证、授权、冲突、限流、不支持、内部错误）定义了
  统一的错误响应需求？[Completeness, Spec §FR-X-04]
- [ ] CHK002 错误码的“一经发布不可修改”是否给出可验证的判定（允许新增、禁止改写）？
  [Measurability, Spec §FR-P-03]
- [ ] CHK003 字段级校验失败与业务错误的分层是否明确（哪些进 `errors[]`，哪些进主错误码）？
  [Clarity, Gap]
- [ ] CHK004 “不支持的操作”与“状态冲突”的判定边界是否无歧义？[Clarity, Spec §FR-O-08]
- [ ] CHK005 越权访问的响应是否统一为不可枚举形式，且该要求是否可度量？[Measurability, Spec §SC-008]

## 幂等与并发

- [ ] CHK006 幂等要求的适用范围是否显式（哪些操作必需、哪些豁免）？[Clarity, Gap]
- [ ] CHK007 幂等键冲突的语义是否定义完整（同键同体、同键异体、键过期）？[Completeness, Gap]
- [ ] CHK008 并发修改冲突的处理要求是否一致（乐观锁/悲观锁的适用面与返回语义）？
  [Consistency, Gap]

## 分页、过滤与排序

- [ ] CHK009 列表类接口的分页方式是否统一规定（游标 vs 偏移）并说明上限？[Consistency, Gap]
- [ ] CHK010 过滤与排序的允许字段范围是否定义（白名单），未允许字段的行为是否明确？
  [Clarity, Gap]

## 版本与兼容

- [ ] CHK011 版本策略是否同时覆盖 URL 主版本与事件 schema 版本，并说明兼容判定标准？
  [Completeness, Spec §FR-X-04、§FR-X-01]
- [ ] CHK012 废弃策略是否量化（保留周期、通知方式、响应头语义）？[Clarity, Gap]
- [ ] CHK013 扩展 API 合并到主契约时的命名空间与冲突处理需求是否明确？[Completeness, Spec §FR-E-01]

## 契约治理

- [ ] CHK014 契约变更的评审与同步需求是否定义（谁批准、目录与契约冲突时以谁为准）？
  [Gap, Spec §FR-X-05]
- [ ] CHK015 契约与实现漂移的检测需求是否可度量（机器校验范围与失败判定）？[Measurability, Gap]
- [ ] CHK016 契约测试的覆盖范围是否明确（核心↔扩展、核心↔消费方分别测什么）？
  [Coverage, Spec §FR-X-05]

## 事件与 Webhook

- [ ] CHK017 Webhook 投递需求是否量化（重试次数、退避策略、死信阈值、告警时延）？
  [Clarity, Spec §FR-X-02]
- [ ] CHK018 事件订阅白名单与通配规则是否可机械判定（允许哪一级通配）？[Measurability, Spec §FR-X-02]
- [ ] CHK019 至少一次投递与消费者幂等的责任划分是否明确？[Clarity, Spec §FR-X-01]

## 服务账号与作用域

- [ ] CHK020 服务账号的作用域词汇与收窄规则是否定义（能否超出所属主体权限）？[Clarity, Spec §FR-S-02]
- [ ] CHK021 API Key 与 Client Credentials 的权限差异是否在需求层明确？[Consistency, Spec §FR-S-02、§FR-S-03]

## 可度量性

- [ ] CHK022 API 相关成功标准是否可在不涉及实现细节的前提下验证？[Measurability, Spec §SC-004]
- [ ] CHK023 性能类成功标准是否按接口类别给出阈值，而非笼统的“快速”？[Clarity, Spec §SC-005、§SC-006]

## 依赖与假设

- [ ] CHK024 对消费方（Bufaa/Tufaa/MuPlan）的集成假设是否记录并标注验证责任方？
  [Assumption, Spec §Assumptions]

## Notes

- 仅在评审人确认需求质量标准满足后勾选 `[x]`；未勾选表示仍需澄清、修正或评审判断。
- `/speckit.implement` 会读取勾选状态作为门禁，且不得修改标记。
- `checklists/requirements.md` 是 `/speckit.specify` 维护的内置规格质量清单，与本文件生命周期独立。
- 带 `[Gap]` 标记的条目表示当前规格中**尚无对应表述**，需回写 `spec.md` 或 `docs/` 基线。
