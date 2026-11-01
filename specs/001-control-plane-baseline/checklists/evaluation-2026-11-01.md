# 清单初评：security.md / api.md（2026-11-01）

**性质**：`/speckit.checklist` 生成的清单为评审人所有；本文件仅为**初评建议**，不修改任何
`[ ]` 勾选状态。勾选由评审人确认后自行完成。

**判定口径**

- **PASS**：`spec.md` 或 `docs/` 基线已有明确、可验证的表述。
- **PARTIAL**：基线（`docs/`）有答案，但 `spec.md` 未表述或未指向；按 D1 派生关系，补一句
  指向即可，不需要复制内容。
- **GAP**：规格与基线均无表述，需要新增需求。

**结论**：51 条中 **PASS 20 / PARTIAL 31 / GAP 0**。没有真正的需求缺失，问题集中在
“`spec.md` 未指向基线细节”。因此不需要 31 次改写，只需在 `spec.md` 增加一节
「需求细节索引」+ 3 处精确指向（幂等豁免、服务账号 scope、Webhook 参数）。

---

## security.md（27 条）

| ID | 判定 | 证据 | 回写建议 |
|---|---|---|---|
| CHK001 | PASS | `spec.md:183-184`（双 aud 入口）、`:194`（服务账号）；契约 `bearerAuth`/`apiKeyAuth` | — |
| CHK002 | PARTIAL | `spec.md:189` 未给阈值；`DB §11.3`：`auth.max_failed_logins=5`、`lock_duration_seconds=900` | 指向 DB §11.3 |
| CHK003 | PARTIAL | `spec.md:185` 仅“检测重用”；处置见 `SM §4.1`、审计 `security.token_reuse_detected` | 指向 SM §4.1 |
| CHK004 | PASS | `spec.md:185`（重置/禁用）、`:220`（pv 递增） | — |
| CHK005 | PARTIAL | `spec.md:188` 未给有效窗口；`DB §6.2 one_time_token.expires_at`、`SM §4.2` | 指向 SM §4.2 |
| CHK006 | PARTIAL | `spec.md:189` 未量化；`DB §11.3` 已有 4 个 `ratelimit.*` 参数（登录 IP/账号、注册、API Key） | 指向 DB §11.3 |
| CHK007 | PASS | `spec.md:178` + `SC-002`（`:294`）可度量 | — |
| CHK008 | PARTIAL | 规格未提；`tech §5.2`（后台任务显式传 tenantID）、`DB §7.3` | 指向 tech §5.2 |
| CHK009 | PARTIAL | `spec.md:176` 仅“经审计的强制管理”；权限点 `platform.tenant.force_manage`、审计 `platform.tenant.force_managed` | 补范围限制表述 |
| CHK010 | PARTIAL | `spec.md:178` 未定返回形态；`OPS §8.2-2`（伪造头不改变上下文） | 明确“拒绝或空结果” |
| CHK011 | PARTIAL | `spec.md:215` 仅“授予/修改”；撤销路径未提（`FR-M-05` 隐含） | 补撤销对称性 |
| CHK012 | PASS | `spec.md:216`（租户/组织所有者）、`:205`（强制转让） | — |
| CHK013 | PASS | `spec.md:218`（四范围、并集、含后代） | — |
| CHK014 | PASS | `spec.md:224`（`ext.<module>.*`）、`:229`（作用域限制） | — |
| CHK015 | PASS | `spec.md:214`（下一请求失效）、`:220`（pv） | — |
| CHK016 | PARTIAL | `spec.md:233-234` 未含拒绝路径；审计目录 §4（高危拒绝必审计） | 指向审计目录 §4 |
| CHK017 | PARTIAL | `spec.md:235` “关键安全事件”未枚举；审计目录 §3 为完整枚举 | 指向审计目录 §3 |
| CHK018 | PASS | `spec.md:236`（只持插入权限）+ `DB §8.2` 授权矩阵 | — |
| CHK019 | PARTIAL | `spec.md:237-238` 未定义留痕内容；审计目录 §2.1 | 指向审计目录 §2.1 |
| CHK020 | PARTIAL | `spec.md:239` “可配置”；`DB §11.3`：`audit.retention_days=180` | 指向 DB §11.3 |
| CHK021 | PARTIAL | `spec.md:261`（只存哈希）；日志禁出见 `OPS §5.1:272`、`tech §7.6` | 指向 OPS §5.1 |
| CHK022 | PARTIAL | 规格未提；`OPS §6.1`（90 天轮换表）、`§6.2`（泄露响应） | 指向 OPS §6 |
| CHK023 | PARTIAL | `spec.md:261` 只写“只显示一次/可撤销”，未定轮换；`OPS §6.1` API Key 90 天 | 补轮换语义 |
| CHK024 | PARTIAL | `spec.md:235` 覆盖审计失败；密钥服务不可达未定义 | 补失败模式 |
| CHK025 | PARTIAL | `SC-008`（`:297`）可度量；响应统一性见错误码 `INVALID_CREDENTIALS` 反枚举 | 指向错误码目录 §3.1 |
| CHK026 | PARTIAL | `spec.md:303-311` 有假设，无责任方标注 | 补责任方列 |
| CHK027 | PARTIAL | `SC-008` + `OPS §8.2-1..18`，无独立威胁模型文档 | 建威胁模型或标注为基线缺口 |

## api.md（24 条）

| ID | 判定 | 证据 | 回写建议 |
|---|---|---|---|
| CHK001 | PASS | `spec.md:269` + 错误码目录 41 码（`Problem`） | — |
| CHK002 | PASS | 错误码目录 §1 规则 1（新增不改变既有语义）；`spec.md:227`（同类不可变原则） | — |
| CHK003 | PARTIAL | 错误码目录 §2（`errors[].code` 子码：REQUIRED/TOO_LONG/PATTERN/FOREIGN_KEY） | 指向错误码目录 §2 |
| CHK004 | PASS | `spec.md:206`；契约描述 405 `NOT_SUPPORTED` / 409 `STATE_CONFLICT` | — |
| CHK005 | PARTIAL | 同 CHK025（security） | 同 CHK025 |
| CHK006 | PARTIAL | `spec.md:152-162` 仅 Edge Case 提及；豁免清单在 `research.md` R-04 | 指向 R-04 并回写 tech §9.1 |
| CHK007 | PASS | `tech §9.1`（同键同体/异体/409）+ `DB §11.3 idempotency.ttl_seconds=86400` | — |
| CHK008 | PASS | `tech §9.2`（乐观锁）、`§9.3`（悲观锁、`409 CONCURRENT_MODIFICATION`） | — |
| CHK009 | PASS | 契约 `Pagination`（`next_cursor`/`has_more`，`:3122`） | — |
| CHK010 | PARTIAL | `tech §5.4`（排序白名单）；过滤白名单未提 | 补过滤白名单 |
| CHK011 | PASS | `spec.md:269` + README §7（URL 主版本、事件 `event_version`） | — |
| CHK012 | PARTIAL | README §7“保留至少一个主版本周期”，未定时长 | 量化周期 |
| CHK013 | PASS | `spec.md:250`（Manifest）+ 契约 `/api/v1/ext/<module>` | — |
| CHK014 | PASS | `spec.md:11-19`（来源与权威性）+ 宪法原则 II | — |
| CHK015 | PARTIAL | 规格未写；`research.md` R-06 + `tasks.md` T005 已有落点 | 指向 R-06 |
| CHK016 | PARTIAL | `spec.md:270` 未定义覆盖范围；`tasks.md` T076 已拆 | 补“核心↔扩展/消费方” |
| CHK017 | PARTIAL | `spec.md:267` 未量化；`SM §11.3:531`（指数退避）、`DB §11.3 webhook.max_attempts=10` | 指向 SM §11.3 |
| CHK018 | PASS | 契约 `WebhookEventType` 正则（`:4055`）+ 事件目录 §6（ext 段数规则） | — |
| CHK019 | PARTIAL | `spec.md:266` 未写“至少一次”；需求基线 §5.4 有 | 指向需求 §5.4 |
| CHK020 | PARTIAL | `spec.md:260` 未定义 scope 词汇；`tech §7.9:443`（一期显式 scopes、API Key 继承） | 指向 tech §7.9 |
| CHK021 | PARTIAL | `spec.md:260-261` 未区分二者权限来源；`tech §7.9` 有 | 同上 |
| CHK022 | PASS | `SC-004`（`:293`） | — |
| CHK023 | PASS | `SC-005/006`（`:294-295`）按接口类别给阈值 | — |
| CHK024 | PARTIAL | `spec.md:303-311` 有假设，无责任方标注 | 补责任方 |

---

## 建议的最小回写（3 处精确指向 + 1 节索引）

1. `spec.md` 新增「需求细节索引」：把上表 PARTIAL 项映射到 `docs/` 章节（一次性解决 31 条，
   不复制内容，保持 D1 派生关系）。
2. 幂等豁免清单：`spec.md` → `research.md` R-04，并回写 `tech §9.1`（tasks T070 已含）。
3. 服务账号 scope 语义：`spec.md` → `tech §7.9`，明确“API Key 继承所属服务账号权限”。
4. Webhook 参数：`spec.md` → `SM §11.3` + `DB §11.3`（重试 10 次、指数退避、10s 超时）。

## 评审人操作提示

- 逐条勾选 `[x]` 表示“该需求质量维度已评审通过”，与实现完成无关。
- `/speckit.implement` 读取勾选状态作为门禁，且不修改标记。
