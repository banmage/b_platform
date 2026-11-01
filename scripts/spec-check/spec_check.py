#!/usr/bin/env python3
"""b_platform 规格一致性校验（spec-check）

对应：宪法原则 VI（基线一致性可机器校验）、research.md R-06、tasks.md T005。

校验对象是 `docs/` 基线（唯一权威）与 `specs/` 派生规格之间的一致性，
不依赖任何编译产物，可在 CI 中独立运行。

用法：
    python3 scripts/spec-check/spec_check.py            # 全量校验
    python3 scripts/spec-check/spec_check.py --strict   # 警告也视为失败
    python3 scripts/spec-check/spec_check.py --json     # 机器可读输出
    python3 scripts/spec-check/spec_check.py --only SPC006 SPC014
    python3 scripts/spec-check/spec_check.py --list

退出码：0 全部通过；1 存在失败项；2 脚本自身异常（文件缺失/YAML 无法解析等）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 环境问题，非校验失败
    sys.stderr.write("缺少依赖 PyYAML：pip install pyyaml\n")
    raise SystemExit(2)

# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]

OPENAPI = "docs/30-api/openapi-v2.0.yaml"
REQUIREMENTS = "docs/10-requirements/requirements-v2.0.md"
TRACEABILITY = "docs/10-requirements/traceability-v2.0.md"
ERROR_CODES = "docs/20-design/error-codes-v2.0.md"
PERMISSIONS = "docs/20-design/permission-model-v2.0.md"
EVENTS = "docs/20-design/event-catalog-v2.0.md"
AUDIT = "docs/20-design/audit-catalog-v2.0.md"
TECH = "docs/20-design/tech-design-v2.0.md"

HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")
WRITE_METHODS = ("post", "put", "patch", "delete")

# 契约路径前缀约定（README §7 / tech §4）
PATH_PREFIXES = ("/api/v1", "/api/platform/v1", "/oauth", "/health", "/readyz", "/.well-known")

# WebhookEventType 白名单必须拒绝的边界用例（含通配位置错误、段数错误、非事件编码）
EVENT_NEGATIVE_CASES = [
    "tenant.membership.*",              # 中段通配（二期能力，一期必须拒绝）
    "tenant.*.created",
    "tenant.created.extra",
    "organization.transfer.requested",  # 组织域无 transfer 事件
    "auth.login_succeeded",             # 审计动作，不是事件编码
    "platform.tenant.created",
    "ext.booking",                      # ext 后段数不足（需 entity + action）
    "ext.booking.reservation",          # 只有 entity
    "ext.booking.reservation.create.extra.more",  # 超过 action 允许的一个限定符
    "Tenant.created",                   # 大小写
    "",
]

# 编码形如 a.b.c（审计动作/权限点/事件）；用于从追溯矩阵的叙述性单元格中挑出编码
CODE_SHAPE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_.*]+$")


class CheckError(Exception):
    """校验无法执行（文件缺失、章节缺失等），视为脚本级错误。"""


@dataclass
class Result:
    id: str
    title: str
    status: str = "PASS"  # PASS / FAIL / WARN / SKIP
    detail: str = ""
    items: list[str] = field(default_factory=list)

    def fail(self, detail: str, items: list[str] | None = None) -> "Result":
        self.status = "FAIL"
        self.detail = detail
        if items:
            self.items = items
        return self

    def warn(self, detail: str, items: list[str] | None = None) -> "Result":
        self.status = "WARN"
        self.detail = detail
        if items:
            self.items = items
        return self

    def ok(self, detail: str = "") -> "Result":
        self.status = "PASS"
        self.detail = detail
        return self


def read(path: str) -> str:
    p = ROOT / path
    if not p.is_file():
        raise CheckError(f"缺少文件：{path}")
    return p.read_text(encoding="utf-8")


def section(text: str, start: str, end: str | None = None) -> str:
    """截取 start 到 end 之间的正文；章节不存在时抛 CheckError。"""
    i = text.find(start)
    if i < 0:
        raise CheckError(f"缺少章节：{start}")
    if end is None:
        return text[i:]
    j = text.find(end, i + len(start))
    if j < 0:
        raise CheckError(f"缺少章节：{end}（在 {start} 之后）")
    return text[i:j]


def diff_lines(left, right, left_name: str, right_name: str) -> list[str]:
    out = []
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    if only_left:
        out.append(f"{left_name} 多出 {len(only_left)}：{', '.join(only_left)}")
    if only_right:
        out.append(f"{right_name} 多出 {len(only_right)}：{', '.join(only_right)}")
    return out


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------

def load_openapi() -> dict:
    try:
        doc = yaml.safe_load(read(OPENAPI))
    except yaml.YAMLError as exc:  # pragma: no cover - 契约损坏
        raise CheckError(f"OpenAPI 无法解析：{exc}") from exc
    if not isinstance(doc, dict):
        raise CheckError("OpenAPI 顶层不是映射")
    return doc


def iter_operations(doc: dict):
    """产出 (path, method, op)，展开 path 级参数。"""
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        path_params = item.get("parameters") or []
        for method in HTTP_METHODS:
            op = item.get(method)
            if isinstance(op, dict):
                yield path, method, op, path_params


def resolve_pointer(doc: dict, ref: str):
    if not ref.startswith("#/"):
        raise KeyError(ref)
    cur = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict):
            cur = cur[part]
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            raise KeyError(ref)
    return cur


def operation_ids(doc: dict) -> list[str]:
    return [op.get("operationId") for _, _, op, _ in iter_operations(doc)]


def error_catalog() -> set[str]:
    text = section(read(ERROR_CODES), "## 3. 错误码清单")
    return set(re.findall(r"^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|\s*\d{3}\s*\|", text, re.M))


def permission_catalog() -> set[str]:
    text = section(read(PERMISSIONS), "### 3.4 核心权限点目录", "### 3.5")
    return set(re.findall(r"^\|\s*`([a-z][a-z0-9_.]*)`\s*\|\s*(?:是|否)\s*\|", text, re.M))


def permission_without_endpoint() -> set[str]:
    """§3.4 末尾“预留与无接口权限点”块中声明的编码（只取权限点形状的 token）。"""
    text = section(read(PERMISSIONS), "预留与无接口权限点", "### 3.5")
    return {code for code in re.findall(r"`([a-z][a-z0-9_.]*)`", text) if "." in code}


def event_catalog() -> set[str]:
    text = section(read(EVENTS), "## 4. 核心事件清单", "## 5.")
    return set(re.findall(r"^\|\s*`([a-z][a-z0-9_.*]*)`\s*\|\s*\d+\s*\|", text, re.M))


def audit_catalog() -> set[str]:
    text = section(read(AUDIT), "## 3. 动作清单", "## 4.")
    return set(re.findall(r"^\|\s*`([a-z][a-z0-9_.]*)`\s*\|", text, re.M))


def requirement_frs() -> set[str]:
    return set(re.findall(r"\*\*(FR-[A-Z]+-\d+)", read(REQUIREMENTS)))


def spec_frs() -> set[str]:
    spec = find_spec()
    return set(re.findall(r"\*\*(FR-[A-Z]+-\d+)", spec.read_text(encoding="utf-8")))


def find_spec() -> Path:
    specs = sorted((ROOT / "specs").glob("*/spec.md"))
    if not specs:
        raise CheckError("未找到 specs/*/spec.md")
    return specs[0]


def traceability_rows() -> list[list[str]]:
    text = read(TRACEABILITY)
    rows = []
    for line in text.splitlines():
        if not line.startswith("| FR-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6:
            rows.append(cells)
    return rows


def backticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def expand_code_shorthand(token: str) -> list[str]:
    """展开 `a.b.x/y/z` 形式的简写（追溯矩阵中的常见写法）。"""
    token = token.replace(" ", "")
    if "/" not in token:
        return [token]
    parts = token.split("/")
    base = parts[0]
    prefix = base.rsplit(".", 1)[0] + "." if "." in base else ""
    return [base] + [prefix + p for p in parts[1:]]


def code_exists(code: str, catalog: set[str]) -> bool:
    if code.endswith("*"):
        return any(c.startswith(code[:-1]) for c in catalog)
    return code in catalog


def expand_operation_shorthand(token: str, known: set[str]) -> list[str]:
    """展开 `accept/decline/cancelOwnershipTransfer` 这类共享后缀的简写。"""
    token = token.replace(" ", "")
    if token in known or "/" not in token:
        return [token]
    parts = [p for p in token.split("/") if p]
    if len(parts) < 2:
        return [token]
    suffix = re.search(r"[A-Z][A-Za-z0-9]*$", parts[-1])
    suffix = suffix.group(0) if suffix else ""
    return [parts[-1]] + [p + suffix for p in parts[:-1]]


def tech_idempotency_exempt() -> set[str]:
    text = section(read(TECH), "### 9.1 幂等", "### 9.2")
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if "豁免清单" in ln), None)
    if start is None:
        raise CheckError("tech §9.1 未找到幂等豁免清单")
    # 清单可能跨行续写：收集到空行或下一个列表项为止
    bullet = [lines[start]]
    for ln in lines[start + 1:]:
        if not ln.strip() or ln.lstrip().startswith("- "):
            break
        bullet.append(ln)
    head = "\n".join(bullet).split("理由")[0]
    return set(backticked(head)) - {"Idempotency-Key"}


def openapi_idempotency_exempt(doc: dict) -> set[str]:
    """未声明 Idempotency-Key 参数的写操作。"""
    exempt = set()
    for path, method, op, path_params in iter_operations(doc):
        if method not in WRITE_METHODS:
            continue
        params = list(path_params) + list(op.get("parameters") or [])
        names = []
        for p in params:
            if not isinstance(p, dict):
                continue
            if "$ref" in p:
                try:
                    p = resolve_pointer(doc, p["$ref"])
                except KeyError:
                    continue
            names.append(p.get("name", ""))
        if not any(n.lower() == "idempotency-key" for n in names):
            exempt.add(op.get("operationId"))
    return exempt


# ---------------------------------------------------------------------------
# 校验项
# ---------------------------------------------------------------------------

def spc001_openapi_shape(doc: dict) -> Result:
    r = Result("SPC001", "OpenAPI 可解析且结构完整")
    version = str(doc.get("openapi", ""))
    if not version.startswith("3.1"):
        return r.fail(f"openapi 版本应为 3.1.x，实际 {version or '缺失'}")
    ops = list(iter_operations(doc))
    schemas = (doc.get("components") or {}).get("schemas") or {}
    if not ops:
        return r.fail("paths 中没有任何 operation")
    return r.ok(f"{len(doc.get('paths') or {})} paths / {len(ops)} operations / {len(schemas)} schemas")


def spc002_operation_ids(doc: dict) -> Result:
    r = Result("SPC002", "operationId 唯一、非空、camelCase")
    ids = operation_ids(doc)
    missing = [f"{m.upper()} {p}" for p, m, op, _ in iter_operations(doc) if not op.get("operationId")]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    bad_case = sorted({i for i in ids if i and not re.fullmatch(r"[a-z][A-Za-z0-9]*", i)})
    items = []
    if missing:
        items.append(f"缺失 operationId：{', '.join(missing)}")
    if dupes:
        items.append(f"重复 operationId：{', '.join(dupes)}")
    if bad_case:
        items.append(f"命名不符合 camelCase：{', '.join(bad_case)}")
    if items:
        return r.fail(f"{len(ids)} 个 operationId 存在问题", items)
    return r.ok(f"{len(ids)} 个 operationId 唯一且命名合规")


def spc003_refs(doc: dict) -> Result:
    r = Result("SPC003", "全部 $ref 可解析（无悬空、无外部引用）")
    refs: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "$ref" and isinstance(v, str):
                    refs.add(v)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    external = sorted(ref for ref in refs if not ref.startswith("#/"))
    dangling = []
    for ref in refs - set(external):
        try:
            resolve_pointer(doc, ref)
        except (KeyError, IndexError, ValueError):
            dangling.append(ref)
    items = []
    if external:
        items.append(f"外部 $ref（基线要求自包含）：{', '.join(external)}")
    if dangling:
        items.append(f"悬空 $ref：{', '.join(sorted(dangling))}")
    if items:
        return r.fail(f"{len(refs)} 个 $ref 中存在问题", items)
    return r.ok(f"{len(refs)} 个内部 $ref 全部可解析")


def spc004_authz_declaration(doc: dict) -> Result:
    r = Result("SPC004", "受保护 operation 100% 声明 x-permission 或 x-subject-authz")
    global_security = doc.get("security")
    public, missing, both = [], [], []
    for path, method, op, _ in iter_operations(doc):
        oid = op.get("operationId")
        security = op.get("security", global_security)
        has_perm = "x-permission" in op
        has_subject = "x-subject-authz" in op
        if has_perm and has_subject:
            both.append(oid)
        if security == [] or security is None:
            public.append(oid)
            continue
        if not has_perm and not has_subject:
            missing.append(f"{oid}（{method.upper()} {path}）")
    items = []
    if missing:
        items.append(f"受保护但未声明授权：{', '.join(missing)}")
    if both:
        items.append(f"同时声明两种授权（应二选一）：{', '.join(both)}")
    if items:
        return r.fail("授权声明不完整", items)
    protected = len(list(iter_operations(doc))) - len(public)
    return r.ok(f"受保护 {protected} 个 / 公开 {len(public)} 个（{', '.join(public)}）")


def spc005_permission_refs(doc: dict) -> Result:
    r = Result("SPC005", "契约引用的权限点均在权限目录中")
    catalog = permission_catalog()
    used = set()
    for _, _, op, _ in iter_operations(doc):
        value = op.get("x-permission")
        if value is None:
            continue
        used.update(value if isinstance(value, list) else [value])
    unknown = sorted(used - catalog)
    if unknown:
        return r.fail(f"契约引用但目录不存在：{', '.join(unknown)}")
    return r.ok(f"引用 {len(used)} 个权限点，目录共 {len(catalog)} 个")


def spc006_problem_codes(doc: dict) -> Result:
    r = Result("SPC006", "Problem.code 与错误码目录双向一致")
    try:
        enum = doc["components"]["schemas"]["Problem"]["properties"]["code"]["enum"]
    except (KeyError, TypeError):
        return r.fail("契约缺少 components.schemas.Problem.properties.code.enum")
    catalog = error_catalog()
    items = diff_lines(enum, catalog, "契约 enum", "错误码目录")
    if items:
        return r.fail("错误码集合不一致", items)
    return r.ok(f"{len(set(enum))} 个错误码双向一致")


def spc007_events_positive(doc: dict) -> Result:
    r = Result("SPC007", "事件目录全部编码被 WebhookEventType 白名单接受")
    try:
        pattern = doc["components"]["schemas"]["WebhookEventType"]["pattern"]
    except (KeyError, TypeError):
        return r.fail("契约缺少 components.schemas.WebhookEventType.pattern")
    regex = re.compile(pattern)
    catalog = event_catalog()
    rejected = sorted(c for c in catalog if not regex.fullmatch(c))
    if rejected:
        return r.fail(f"目录事件被白名单拒绝：{', '.join(rejected)}")
    return r.ok(f"{len(catalog)} 个核心事件全部匹配白名单")


def spc008_events_negative(doc: dict) -> Result:
    r = Result("SPC008", "WebhookEventType 拒绝非法边界用例")
    try:
        pattern = doc["components"]["schemas"]["WebhookEventType"]["pattern"]
    except (KeyError, TypeError):
        return r.fail("契约缺少 components.schemas.WebhookEventType.pattern")
    regex = re.compile(pattern)
    accepted = [case for case in EVENT_NEGATIVE_CASES if regex.fullmatch(case)]
    if accepted:
        return r.fail("以下非法编码被白名单接受", [f"`{c}`" for c in accepted])
    return r.ok(f"{len(EVENT_NEGATIVE_CASES)} 个负例全部被拒绝")


def spc009_permission_usage(doc: dict) -> Result:
    r = Result("SPC009", "权限目录中未被使用的编码均为已声明的预留/无接口项")
    catalog = permission_catalog()
    used = set()
    for _, _, op, _ in iter_operations(doc):
        value = op.get("x-permission")
        if value is None:
            continue
        used.update(value if isinstance(value, list) else [value])
    declared = permission_without_endpoint()
    unexplained = sorted(catalog - used - declared)
    items = []
    if unexplained:
        items.append(f"目录中存在但契约未使用、且未声明为预留：{', '.join(unexplained)}")
    stale = sorted(declared - catalog)
    if stale:
        items.append(f"预留清单中的编码不在目录：{', '.join(stale)}")
    if items:
        return r.fail("权限点使用状态与声明不符", items)
    return r.ok(f"目录 {len(catalog)} 个 = 契约使用 {len(used)} 个 + 预留/无接口 {len(catalog - used)} 个")


def spc010_fr_derivation(doc: dict) -> Result:
    r = Result("SPC010", "规格 FR 集合与需求基线一致（派生关系）")
    base = requirement_frs()
    spec = spec_frs()
    if not base:
        return r.fail("需求基线未解析到任何 FR")
    items = diff_lines(spec, base, "spec.md", "requirements")
    if items:
        return r.fail("FR 集合不一致（spec 为派生文档，编号不得增删）", items)
    return r.ok(f"{len(base)} 条 FR 与基线完全一致")


def spc011_traceability_coverage(doc: dict) -> Result:
    r = Result("SPC011", "追溯矩阵覆盖全部 FR")
    base = requirement_frs()
    traced = {row[0] for row in traceability_rows()}
    items = diff_lines(traced, base, "追溯矩阵", "需求基线")
    if items:
        return r.fail("FR 追溯不完整", items)
    return r.ok(f"{len(traced)} 条 FR 均有追溯行")


def spc012_traceability_operations(doc: dict) -> Result:
    r = Result("SPC012", "追溯矩阵引用的 operationId 均存在于契约")
    ids = set(operation_ids(doc))
    referenced, unresolved, skipped = set(), [], []
    for row in traceability_rows():
        for token in backticked(row[2]):
            token = token.strip()
            if not token or token == "—":
                continue
            if token.startswith("/"):
                skipped.append(token)  # 路径模式（如 /api/v1/**），非 operationId
                continue
            if "*" in token:
                pattern = ("^" + re.escape(token)
                           .replace(r"\*\*", ".*")
                           .replace(r"\*", "[A-Za-z0-9]*") + "$")
                if not any(re.fullmatch(pattern, i) for i in ids):
                    unresolved.append(f"`{token}`（通配未匹配到任何 operationId）")
                continue
            if not re.fullmatch(r"[a-z][A-Za-z0-9/]*", token):
                skipped.append(token)  # 叙述性文字，如“所有分配/授权接口”
                continue
            for candidate in expand_operation_shorthand(token, ids):
                if candidate in ids:
                    referenced.add(candidate)
                else:
                    unresolved.append(f"`{token}` → `{candidate}`")
    if unresolved:
        return r.fail("追溯矩阵引用了契约中不存在的 operationId", unresolved)
    detail = f"追溯矩阵引用 {len(referenced)} 个 operationId，全部存在"
    if skipped:
        detail += f"（跳过 {len(skipped)} 处路径模式/叙述文字）"
    return r.ok(detail)


def spc013_traceability_codes(doc: dict) -> Result:
    r = Result("SPC013", "追溯矩阵的权限/审计/事件编码均在各自目录")
    perms, audits, events = permission_catalog(), audit_catalog(), event_catalog()
    problems = []
    columns = ((3, perms, "权限点"), (4, audits, "审计动作"), (5, events, "事件"))
    for row in traceability_rows():
        fr = row[0]
        for index, catalog, label in columns:
            for token in backticked(row[index]):
                token = token.replace(" ", "")
                if token == "—" or not CODE_SHAPE.match(token):
                    continue  # 叙述性片段（如 DENIED、assign、via_approval）不参与编码校验
                for code in expand_code_shorthand(token):
                    if not code_exists(code, catalog):
                        problems.append(f"{fr} {label} `{code}` 不在目录")
    if problems:
        return r.fail(f"{len(problems)} 处编码不对应", problems)
    return r.ok("追溯矩阵的权限/审计/事件编码全部命中目录")


def spc014_idempotency(doc: dict) -> Result:
    r = Result("SPC014", "幂等豁免清单（tech §9.1）与契约写操作一致")
    documented = tech_idempotency_exempt()
    actual = openapi_idempotency_exempt(doc)
    items = diff_lines(actual, documented, "契约未声明 Idempotency-Key", "tech §9.1 豁免清单")
    if items:
        return r.fail("豁免清单与契约不一致", items)
    return r.ok(f"{len(actual)} 个写操作豁免，与 tech §9.1 一致")


def spc015_markdown_links(doc: dict) -> Result:
    r = Result("SPC015", "Markdown 相对链接均可解析")
    targets: list[Path] = [ROOT / "README.md"]
    for base in ("docs", "specs"):
        targets.extend(sorted((ROOT / base).rglob("*.md")))
    broken = []
    for path in targets:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)  # 忽略代码块
        for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", text):
            target = m.group(1).split("#")[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if any(ch in target for ch in "[]{}<>*"):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    if broken:
        return r.fail(f"{len(broken)} 处链接失效", broken)
    return r.ok(f"{len(targets)} 个 Markdown 文件链接全部有效")


def spc016_path_prefixes(doc: dict) -> Result:
    r = Result("SPC016", "契约路径符合前缀约定")
    bad = [p for p in (doc.get("paths") or {}) if not p.startswith(PATH_PREFIXES)]
    if bad:
        return r.fail("不符合前缀约定的路径", bad)
    return r.ok(f"{len(doc.get('paths') or {})} 个路径前缀合规")


def spc017_audit_anchors(doc: dict) -> Result:
    r = Result("SPC017", "审计目录的接口锚点 operationId 均存在于契约")
    ids = set(operation_ids(doc))
    text = section(read(AUDIT), "## 3. 动作清单", "## 4.")
    referenced = set()
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5:
            referenced.update(backticked(cells[-1]))
    unknown = sorted(x for x in referenced - ids if re.fullmatch(r"[a-z][A-Za-z0-9]*", x))
    if unknown:
        return r.warn("审计目录引用了契约中不存在的 operationId", unknown)
    return r.ok(f"审计目录引用 {len(referenced)} 个锚点，全部存在")


CHECKS = [
    spc001_openapi_shape,
    spc002_operation_ids,
    spc003_refs,
    spc004_authz_declaration,
    spc005_permission_refs,
    spc006_problem_codes,
    spc007_events_positive,
    spc008_events_negative,
    spc009_permission_usage,
    spc010_fr_derivation,
    spc011_traceability_coverage,
    spc012_traceability_operations,
    spc013_traceability_codes,
    spc014_idempotency,
    spc015_markdown_links,
    spc016_path_prefixes,
    spc017_audit_anchors,
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render(results: list[Result], as_json: bool) -> None:
    if as_json:
        print(json.dumps({
            "root": str(ROOT),
            "results": [
                {"id": r.id, "title": r.title, "status": r.status,
                 "detail": r.detail, "items": r.items}
                for r in results
            ],
            "summary": {
                "total": len(results),
                "pass": sum(r.status == "PASS" for r in results),
                "fail": sum(r.status == "FAIL" for r in results),
                "warn": sum(r.status == "WARN" for r in results),
                "skip": sum(r.status == "SKIP" for r in results),
            },
        }, ensure_ascii=False, indent=2))
        return

    for r in results:
        print(f"[{r.id}] {r.status:<4} {r.title}")
        if r.detail:
            print(f"        {r.detail}")
        for item in r.items:
            print(f"        - {item}")
    failed = [r for r in results if r.status == "FAIL"]
    warned = [r for r in results if r.status == "WARN"]
    print()
    print(f"汇总：{len(results)} 项校验，"
          f"通过 {sum(r.status == 'PASS' for r in results)}，"
          f"失败 {len(failed)}，警告 {len(warned)}")
    if failed:
        print("失败项：" + "、".join(r.id for r in failed))
    if warned:
        print("警告项：" + "、".join(r.id for r in warned))


def main(argv: list[str] | None = None) -> int:
    global ROOT
    parser = argparse.ArgumentParser(description="b_platform 规格一致性校验")
    parser.add_argument("--root", help="校验根目录（默认仓库根；用于自测/变异测试）")
    parser.add_argument("--strict", action="store_true", help="警告也视为失败")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--only", nargs="+", metavar="ID", help="只运行指定校验项")
    parser.add_argument("--list", action="store_true", help="列出全部校验项")
    args = parser.parse_args(argv)

    if args.root:
        ROOT = Path(args.root).resolve()

    if args.list:
        for fn in CHECKS:
            check_id = fn.__name__.split("_")[0].upper()
            print(f"{check_id}\t{(fn.__doc__ or '').strip()}")
        return 0

    try:
        doc = load_openapi()
        selected = CHECKS
        if args.only:
            wanted = {x.upper() for x in args.only}
            selected = [fn for fn in CHECKS if fn.__name__.split("_")[0].upper() in wanted]
            if not selected:
                sys.stderr.write(f"未匹配到校验项：{', '.join(args.only)}\n")
                return 2
        results = []
        for fn in selected:
            try:
                results.append(fn(doc))
            except CheckError as exc:
                results.append(Result(fn.__name__.split("_")[0].upper(), fn.__doc__ or "",
                                      status="FAIL", detail=str(exc)))
    except CheckError as exc:
        sys.stderr.write(f"spec-check 无法执行：{exc}\n")
        return 2

    render(results, args.json)
    has_fail = any(r.status == "FAIL" for r in results)
    has_warn = any(r.status == "WARN" for r in results)
    return 1 if has_fail or (args.strict and has_warn) else 0


if __name__ == "__main__":
    raise SystemExit(main())
