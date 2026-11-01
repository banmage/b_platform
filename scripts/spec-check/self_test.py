#!/usr/bin/env python3
"""spec-check 自测（变异测试）

对仓库做一份临时副本，逐条注入“基线漂移”，确认对应的校验项确实报错。
一个永远通过的检查器没有价值；本文件用来证明它抓得住回归。

用法：python3 scripts/spec-check/self_test.py
退出码：0 全部用例符合预期；1 有用例未按预期失败。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve().parent / "spec_check.py"
COPY_DIRS = ("docs", "specs", "scripts", ".github")
COPY_FILES = ("README.md",)


@dataclass
class Case:
    name: str
    target: str          # 相对路径
    pattern: str         # 正则
    replacement: str     # 替换文本
    expect: str          # 期望失败的校验项 ID


CASES = [
    Case("OpenAPI 版本回退", "docs/30-api/openapi-v2.0.yaml",
         r"^openapi: 3\.1\.0$", "openapi: 3.0.0", "SPC001"),
    Case("operationId 重复", "docs/30-api/openapi-v2.0.yaml",
         r"^(\s*)operationId: getTenant$", r"\1operationId: platformGetTenant", "SPC002"),
    Case("$ref 悬空", "docs/30-api/openapi-v2.0.yaml",
         r"\$ref: '#/components/schemas/Tenant'",
         "$ref: '#/components/schemas/TenantMissing'", "SPC003"),
    Case("受保护操作缺授权声明", "docs/30-api/openapi-v2.0.yaml",
         r"^(\s*)x-permission: tenant\.read$", r"\1x-unused-permission: true", "SPC004"),
    Case("引用不存在的权限点", "docs/30-api/openapi-v2.0.yaml",
         r"^(\s*)x-permission: tenant\.read$",
         r"\1x-permission: tenant.read_nonexistent", "SPC005"),
    Case("错误码 enum 多出", "docs/30-api/openapi-v2.0.yaml",
         r"^(\s*)- UNAUTHENTICATED$", r"\1- UNAUTHENTICATED\n\1- FAKE_SPEC_CHECK_CODE", "SPC006"),
    Case("事件目录出现非法编码", "docs/20-design/event-catalog-v2.0.md",
         r"^\| `tenant\.created` \|", "| `tenant.membership.*` | 1 | 注入 | `NULL` | - |\n| `tenant.created` |", "SPC007"),
    Case("白名单被放宽", "docs/30-api/openapi-v2.0.yaml",
         r"^(\s*)pattern: '\^\(\?:tenant\\\..*$", r"\1pattern: '^.*$'", "SPC008"),
    Case("权限目录新增未使用项", "docs/20-design/permission-model-v2.0.md",
         r"^\| `platform\.tenant\.read` \|",
         "| `platform.tenant.injected` | 否 | 注入 |\n| `platform.tenant.read` |", "SPC009"),
    Case("规格丢失 FR", "specs/001-control-plane-baseline/spec.md",
         r"^- \*\*FR-T-01\*\*:.*\n", "", "SPC010"),
    Case("追溯矩阵丢失 FR", "docs/10-requirements/traceability-v2.0.md",
         r"^\| FR-T-06 \|.*\n", "", "SPC011"),
    Case("追溯矩阵引用不存在的 operationId", "docs/10-requirements/traceability-v2.0.md",
         r"`platformGetTenant`", "`platformGetTenantInjected`", "SPC012"),
    Case("追溯矩阵引用不存在的审计动作", "docs/10-requirements/traceability-v2.0.md",
         r"`platform\.tenant\.created`", "`platform.tenant.injected_action`", "SPC013"),
    Case("幂等豁免清单漂移", "docs/20-design/tech-design-v2.0.md",
         r"`changePassword`", "`changePasswordInjected`", "SPC014"),
    Case("Markdown 链接失效", "README.md",
         r"^$", "[broken](does-not-exist.md)\n", "SPC015"),
    Case("路径前缀违规", "docs/30-api/openapi-v2.0.yaml",
         r"^  /api/v1/auth/register:$", "  /api/v2/auth/register:", "SPC016"),
]


def prepare(dest: Path) -> None:
    for name in COPY_DIRS:
        shutil.copytree(ROOT / name, dest / name)
    for name in COPY_FILES:
        shutil.copy2(ROOT / name, dest / name)


def mutate(dest: Path, case: Case) -> None:
    path = dest / case.target
    text = path.read_text(encoding="utf-8")
    new, count = re.subn(case.pattern, case.replacement, text, count=1, flags=re.M)
    if count == 0:
        raise RuntimeError(f"变异未命中：{case.name}（{case.target} / {case.pattern}）")
    path.write_text(new, encoding="utf-8")


def run_checker(root: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--json"],
        capture_output=True, text=True,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"results": [], "summary": {}, "stderr": proc.stderr}
    return proc.returncode, payload


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="spec-check-") as tmp:
        base = Path(tmp) / "baseline"
        prepare(base)
        code, payload = run_checker(base)
        if code != 0:
            failures.append(f"基线副本本身未通过（exit={code}）："
                            f"{[r['id'] for r in payload.get('results', []) if r['status'] == 'FAIL']}")
        else:
            print(f"[基线] PASS  17 项校验全部通过")

        for case in CASES:
            work = Path(tmp) / case.expect.lower()
            prepare(work)
            mutate(work, case)
            code, payload = run_checker(work)
            failed = {r["id"] for r in payload.get("results", []) if r["status"] == "FAIL"}
            if case.expect in failed:
                print(f"[{case.expect}] PASS  {case.name} 被捕获")
            else:
                print(f"[{case.expect}] FAIL  {case.name} 未被捕获（实际失败：{sorted(failed) or '无'}）")
                failures.append(f"{case.expect} {case.name}")

    print()
    total = len(CASES) + 1
    print(f"自测：{total - len(failures)}/{total} 通过")
    if failures:
        print("未通过：")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
