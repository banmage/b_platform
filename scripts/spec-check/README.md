# spec-check：基线一致性校验

`docs/` 是唯一权威，`specs/` 是派生规格。本工具把“两者是否仍然一致”变成可执行门禁，
对应宪法原则 VI、[research.md R-06](../../specs/001-control-plane-baseline/research.md) 与
[tasks.md T005](../../specs/001-control-plane-baseline/tasks.md)。

基线此前只在评审记录里留下“2026-10-31 已机器验证”的结论，脚本未入库；基线一旦漂移无法发现。
本目录把那次一次性验证固化为可重复运行的检查。

## 用法

```bash
python3 scripts/spec-check/spec_check.py            # 全量校验
python3 scripts/spec-check/spec_check.py --strict   # 警告也视为失败（CI 使用）
python3 scripts/spec-check/spec_check.py --json     # 机器可读输出
python3 scripts/spec-check/spec_check.py --only SPC006 SPC014
python3 scripts/spec-check/spec_check.py --list     # 列出校验项
python3 scripts/spec-check/self_test.py             # 变异自测（证明检查器抓得住漂移）
```

依赖：Python ≥ 3.10 + PyYAML（`pip install pyyaml`）。

退出码：`0` 全部通过；`1` 存在失败项；`2` 脚本无法执行（文件缺失、YAML 损坏等）。

## 校验项

| ID | 检查内容 | 权威来源 |
|---|---|---|
| SPC001 | OpenAPI 可解析、版本为 3.1.x、存在 operation | `docs/30-api/openapi-v2.0.yaml` |
| SPC002 | `operationId` 唯一、非空、camelCase | 同上 |
| SPC003 | 全部 `$ref` 可解析，且无外部引用（基线自包含） | 同上 |
| SPC004 | 受保护 operation 100% 声明 `x-permission` 或 `x-subject-authz`，且不重复声明 | 同上、权限模型 §7.6 |
| SPC005 | 契约引用的权限点均在权限目录中 | 权限模型 §3.4 |
| SPC006 | `Problem.code` enum 与错误码目录双向一致 | 错误码目录 §3 |
| SPC007 | 事件目录全部编码被 `WebhookEventType` 白名单接受 | 事件目录 §4 |
| SPC008 | 白名单拒绝非法边界用例（中段通配、段数错误、大小写、审计编码） | 事件目录 §6、D-07 |
| SPC009 | 权限目录中未被契约使用的编码，必须是已声明的预留/无接口项 | 权限模型 §3.4 尾注 |
| SPC010 | `spec.md` 的 FR 集合与需求基线完全一致（派生关系，禁止增删） | 需求规格、spec.md |
| SPC011 | 追溯矩阵覆盖全部 FR | 追溯矩阵 |
| SPC012 | 追溯矩阵引用的 `operationId` 均存在（支持 `a/b/c` 与 `get*X` 简写） | 追溯矩阵、契约 |
| SPC013 | 追溯矩阵的权限/审计/事件编码均在各自目录 | 四份权威清单 |
| SPC014 | 幂等豁免清单与契约写操作一致（D-11） | tech §9.1 |
| SPC015 | README / docs / specs 的相对链接可解析 | 全库 |
| SPC016 | 契约路径符合前缀约定 | README §7、tech §4 |
| SPC017 | 审计目录的接口锚点 `operationId` 均存在（警告级） | 审计目录 §3 |

## 设计约定

- **只读**：校验器不修改任何文件，也不生成中间产物。
- **单一事实源**：只解析 `docs/` 与 `specs/` 的文本，不引入数据库或代码依赖，可在任何环境运行。
- **失败要可定位**：每条失败都给出具体编码或文件路径，不输出“检查未通过”这类空结论。
- **简写要显式**：追溯矩阵里的 `a.b.x/y`、`get*X`、`/api/v1/**` 会被展开或显式跳过并计数，
  不做模糊匹配（避免用宽松解析掩盖真实漂移）。
- **自测即证据**：`self_test.py` 对每个校验项注入一次漂移，确认其确实报错。新增校验项时应
  同步新增一个变异用例。

## 新增校验项

1. 在 `spec_check.py` 中实现 `def spcNNN_xxx(doc: dict) -> Result`，返回 `Result(...)`。
2. 加入 `CHECKS` 列表（顺序即输出顺序）。
3. 在 `self_test.py` 的 `CASES` 中加一个能触发该检查的变异。
4. 更新本文件表格。

## CI

`.github/workflows/spec-check.yml` 在 push / PR 上运行 `--strict` 与自测。基线漂移会直接让流水线失败，
而不是等到实现阶段才暴露。
