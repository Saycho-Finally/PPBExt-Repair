"""PPBExt-Repair 测试：四 pass + 流水线 + 拒绝路径。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from repaircore import (RepairPipeline, StormGuard, flatten_params,  # noqa: E402
                        repair_truncated, scavenge_call, unflatten_params)

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" —— {note}" if note else ""))


def test_flatten():
    print("pass 1：参数拍平/还原")
    f = flatten_params({"user": {"name": "x", "tags": ["a"]}, "n": 1})
    check("嵌套拍平", f == {"user.name": "x", "user.tags": ["a"], "n": 1})
    r = unflatten_params(f)
    check("还原嵌套", r == {"user": {"name": "x", "tags": ["a"]}, "n": 1})


def test_scavenge():
    print("pass 2：自由文本捞调用")
    text = ('好的，我来调用工具：\n```json\n'
            '{"name": "search", "arguments": {"q": "北京"}}\n```')
    obj = scavenge_call(text)
    check("从文本捞 JSON 调用", obj is not None and obj["name"] == "search")
    check("无调用文本返回 None", scavenge_call("今天天气不错") is None)


def test_truncation():
    print("pass 3：截断 JSON 修复")
    cases = [
        ('{"name": "f", "arguments": {"x": 1', "补花括号"),
        ('{"name": "f", "arguments": {"s": "ab', "补引号+括号"),
    ]
    for raw, note in cases:
        obj = repair_truncated(raw)
        check(f"修复截断（{note}）", obj is not None and "name" in obj,
              str(obj)[:40])
    check("不可修复返回 None", repair_truncated("完全不是 JSON") is None)


def test_storm():
    print("pass 4：调用风暴抑制")
    g = StormGuard(window_seconds=10, max_repeats=3)
    results = [g.check("search", now=100 + i * 0.1) for i in range(5)]
    check("前 3 次放行", all(results[:3]))
    check("第 4-5 次抑制", not results[3] and not results[4])
    check("窗口滑过后恢复", g.check("search", now=120))


def test_pipeline():
    print("流水线：ok/repaired/rejected 三态")
    p = RepairPipeline()
    r1 = p.run('{"name": "f", "arguments": {"x": 1}}')
    check("直接可解析 → ok", r1.status == "ok")
    r2 = p.run('思考中… {"name": "g", "arguments": {"a": {"b": 2}}}')
    check("文本+嵌套 → repaired（scavenge+flatten）",
          r2.status == "repaired" and "scavenge" in r2.passes_hit
          and "flatten" in r2.passes_hit, str(r2.passes_hit))
    r3 = p.run("完全无法解析的内容")
    check("无法解析 → rejected（明确拒绝）", r3.status == "rejected"
          and r3.repaired is None)
    rep = p.report()
    check("报告三态统计", rep["n"] == 3 and rep["status"].get("rejected") == 1)


if __name__ == "__main__":
    print("=" * 60)
    print("PPBExt-Repair 测试")
    print("=" * 60)
    test_flatten()
    test_scavenge()
    test_truncation()
    test_storm()
    test_pipeline()
    print("=" * 60)
    n = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n}/{len(RESULTS)} PASS")
    print("REPAIR_OK" if n == len(RESULTS) else "REPAIR_FAIL")
