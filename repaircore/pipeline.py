"""repaircore：工具调用修复（四 pass 流水线）。

修复链（按 Reasonix 的四类真实故障设计，零依赖实现）：
  1. flatten   嵌套参数拍平（模型给嵌套对象，工具要扁平参数）
  2. scavenge  从自由文本捞调用（模型把调用写进自然语言）
  3. truncation 截断 JSON 括号/引号补全
  4. storm     同工具短窗重复调用抑制（防御性）

设计原则：
  - 每 pass 独立可测；pipeline 顺序固定、可开关
  - 修复必留痕（RepairRecord：原输入 → 修复后 → 命中的 pass）
  - 无法修复时明确 reject（不静默传坏参数）
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class RepairRecord:
    ts: float
    original: str
    repaired: dict | None
    passes_hit: list[str] = field(default_factory=list)
    status: str = "ok"          # ok / repaired / rejected
    note: str = ""


def flatten_params(obj: dict, sep: str = ".") -> dict:
    """pass 1：嵌套参数拍平。{"user": {"name": "x"}} → {"user.name": "x"}"""
    out: dict = {}

    def walk(prefix: str, value):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(f"{prefix}{sep}{k}" if prefix else str(k), v)
        else:
            out[prefix] = value

    walk("", obj)
    return out


def unflatten_params(obj: dict, sep: str = ".") -> dict:
    """flatten 的逆：拍平参数还原嵌套（schema 需要嵌套时用）。"""
    out: dict = {}
    for k, v in obj.items():
        parts = k.split(sep)
        cur = out
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = v
    return out


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def scavenge_call(text: str) -> dict | None:
    """pass 2：从自由文本中捞取工具调用 JSON（取第一个可解析的块）。"""
    for m in _JSON_BLOCK.finditer(text):
        chunk = m.group(0)
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict) and ("name" in obj or "tool" in obj):
                return obj
        except json.JSONDecodeError:
            fixed = repair_truncated(chunk)
            if fixed is not None:
                return fixed
    return None


def repair_truncated(s: str) -> dict | None:
    """pass 3：截断 JSON 的修复——补全未闭合的引号/括号，去尾逗号。"""
    t = s.strip()
    if not t.startswith("{"):
        return None
    # 去掉尾部不完整的键值（从最后一个逗号截断）
    if not t.endswith("}") or t.count("{") != t.count("}"):
        # 逐字符补全
        in_str = False
        esc = False
        depth = 0
        last_ok = -1
        for i, c in enumerate(t):
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
            elif c == '"':
                in_str = not in_str
            elif not in_str:
                if c in "{[":
                    depth += 1
                    last_ok = i
                elif c in "}]":
                    depth -= 1
                    last_ok = i
        if in_str:
            t += '"'
        t = re.sub(r",\s*$", "", t)
        t += "}" * max(depth, 0)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


class StormGuard:
    """pass 4：调用风暴抑制（同一工具短窗内重复调用）。"""

    def __init__(self, window_seconds: float = 5.0, max_repeats: int = 3):
        self.window = window_seconds
        self.max_repeats = max_repeats
        self.history: list[tuple[float, str]] = []
        self.suppressed = Counter()

    def check(self, tool: str, now: float | None = None) -> bool:
        """True=放行；False=抑制（风暴）。"""
        now = now if now is not None else time.time()
        self.history = [(t, n) for t, n in self.history if now - t <= self.window]
        count = sum(1 for _, n in self.history if n == tool) + 1
        self.history.append((now, tool))
        if count > self.max_repeats:
            self.suppressed[tool] += 1
            return False
        return True


class RepairPipeline:
    """四 pass 流水线：修复工具调用，无法修复则 reject。"""

    def __init__(self, enable_flatten: bool = True, enable_scavenge: bool = True,
                 enable_truncation: bool = True, enable_storm: bool = True):
        self.flags = {"flatten": enable_flatten, "scavenge": enable_scavenge,
                      "truncation": enable_truncation, "storm": enable_storm}
        self.storm = StormGuard()
        self.records: list[RepairRecord] = []

    def run(self, raw: str, tool: str | None = None) -> RepairRecord:
        """输入：模型原始输出（可能含自由文本/截断 JSON/嵌套参数）。
        输出：RepairRecord（status=ok/repaired/rejected）。"""
        hits: list[str] = []
        # pass 2：先尝试直接解析，失败则 scavenge
        obj = None
        try:
            parsed = json.loads(raw)
            obj = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            if self.flags["scavenge"]:
                obj = scavenge_call(raw)
                if obj is not None:
                    hits.append("scavenge")
            if obj is None and self.flags["truncation"]:
                obj = repair_truncated(raw)
                if obj is not None:
                    hits.append("truncation")
        if obj is None:
            rec = RepairRecord(time.time(), raw[:200], None, hits, "rejected",
                               "无法解析为工具调用")
            self.records.append(rec)
            return rec

        # pass 1：参数拍平（若参数是嵌套 dict 且调用方要求扁平）
        if self.flags["flatten"]:
            args = obj.get("arguments") or obj.get("args") or {}
            if isinstance(args, dict) and any(isinstance(v, dict) for v in args.values()):
                flat = flatten_params(args)
                obj["arguments"] = flat
                hits.append("flatten")

        # pass 4：风暴抑制
        name = obj.get("name") or tool or obj.get("tool")
        if self.flags["storm"] and name and not self.storm.check(name):
            rec = RepairRecord(time.time(), raw[:200], obj, hits + ["storm"],
                               "rejected", f"调用风暴抑制：{name}")
            self.records.append(rec)
            return rec

        status = "repaired" if hits else "ok"
        rec = RepairRecord(time.time(), raw[:200], obj, hits, status,
                           "；".join(hits) if hits else "")
        self.records.append(rec)
        return rec

    def report(self) -> dict:
        c = Counter(r.status for r in self.records)
        hit = Counter(h for r in self.records for h in r.passes_hit)
        return {"n": len(self.records), "status": dict(c), "passes_hit": dict(hit),
                "storm_suppressed": dict(self.storm.suppressed)}
