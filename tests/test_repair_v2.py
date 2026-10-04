"""PPBExt-Repair v0.2 测试：输出层 schema 修复 + 检索层查询重写。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from repaircore import (FieldSpec, repair_against_schema, rewrite_auto,  # noqa: E402
                        rewrite_for_precision, rewrite_for_recall,
                        strip_code_fence)

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" —— {note}" if note else ""))


SCHEMA = [
    FieldSpec("tool", "str", enum=["search", "fetch", "summarize"]),
    FieldSpec("count", "int", default=1),
    FieldSpec("verbose", "bool", default=False),
]


def test_schema():
    print("输出层：schema 校验与本地修复")
    # ok：完全合规
    r1 = repair_against_schema({"tool": "search", "count": 3, "verbose": True}, SCHEMA)
    check("合规输入判 ok", r1.status == "ok" and r1.value["count"] == 3)
    # repaired：类型 + 缺默认 + 多余字段 + 枚举规范化
    r2 = repair_against_schema(
        {"tool": "Search", "count": "3", "extra": 1}, SCHEMA)
    check("可修复输入判 repaired", r2.status == "repaired"
          and r2.value == {"tool": "search", "count": 3, "verbose": False},
          str(r2.value))
    check("修复项记录完整", len(r2.fixes) == 4, f"{len(r2.fixes)} 项: {r2.fixes}")
    # rejected：缺必填 / 枚举外值 / 类型不可转
    r3 = repair_against_schema({"count": 1}, SCHEMA)
    check("缺必填判 rejected", r3.status == "rejected")
    r4 = repair_against_schema({"tool": "unknown"}, SCHEMA)
    check("枚举外值判 rejected", r4.status == "rejected")
    r5 = repair_against_schema({"tool": "search", "count": "abc"}, SCHEMA)
    check("类型不可转判 rejected", r5.status == "rejected")
    # 代码围栏剥离
    check("剥离 markdown 围栏",
          strip_code_fence('```json\n{"a":1}\n```') == '{"a":1}')


def test_retrieval():
    print("检索层：查询重写")
    # 召回不足 → 放宽（去停用词 + 同义扩展）
    r1 = rewrite_for_recall("怎么查一下报错", 0)
    check("零结果时放宽查询", r1.status == "repaired" and "报错" in r1.query,
          r1.query)
    check("同义扩展生效", "错误" in r1.query, r1.query)
    # 结果过多 → 收紧（去泛化词）
    r2 = rewrite_for_precision("帮我查一下 2026 年第三季度的销售数据", 100)
    check("结果过多时收紧查询", r2.status == "repaired", r2.query)
    # 自动路由
    r3 = rewrite_auto("怎么查报错", 0)
    check("自动选择放宽策略", "relax" in r3.strategy, r3.strategy)
    r4 = rewrite_auto("查数据库", 10)
    check("正常结果量不重写", r4.status == "ok")
    # 全停用词 → rejected（明确失败）
    r5 = rewrite_for_recall("的了吗呢", 0)
    check("全停用词判 rejected", r5.status == "rejected")


if __name__ == "__main__":
    print("=" * 60)
    print("PPBExt-Repair v0.2 测试")
    print("=" * 60)
    test_schema()
    test_retrieval()
    print("=" * 60)
    n = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n}/{len(RESULTS)} PASS")
    print("REPAIR_V2_OK" if n == len(RESULTS) else "REPAIR_V2_FAIL")
