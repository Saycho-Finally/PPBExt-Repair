"""输出层修复：结构化输出的校验与本地修复（修复矩阵第 2 层）。

对 LLM 输出的 JSON 做 schema 校验，并尝试**不重试的本地修复**：
  - 类型转换（"12" → 12，可安全推断时）
  - 缺字段补默认值（schema 提供 default 时）
  - 多余字段剥离（schema 未声明且 additionalProperties=False）
  - 枚举值近似（大小写/空白规范化）
修不了的返回明确失败（三态语义：ok / repaired / rejected）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FieldSpec:
    name: str
    type: str                      # str / int / float / bool / list / dict
    required: bool = True
    default: object = None
    enum: list | None = None


@dataclass
class SchemaRepairResult:
    status: str                    # ok / repaired / rejected
    value: dict | None
    fixes: list[str] = field(default_factory=list)
    error: str = ""


_CASTERS = {
    "str": lambda v: v if isinstance(v, str) else str(v),
    "int": lambda v: v if isinstance(v, int) and not isinstance(v, bool) else int(str(v).strip()),
    "float": lambda v: v if isinstance(v, float) else float(str(v).strip()),
    "bool": lambda v: v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "是", "yes"),
    "list": lambda v: v if isinstance(v, list) else [v],
    "dict": lambda v: v if isinstance(v, dict) else {"value": v},
}


def repair_against_schema(value: dict, schema: list[FieldSpec],
                          allow_extra: bool = False) -> SchemaRepairResult:
    """按 field 规格修复字典。返回三态结果。"""
    if not isinstance(value, dict):
        return SchemaRepairResult("rejected", None, error="顶层不是对象")
    out = dict(value)
    fixes: list[str] = []
    declared = {f.name for f in schema}

    # 多余字段剥离
    if not allow_extra:
        for k in list(out):
            if k not in declared:
                out.pop(k)
                fixes.append(f"剥离多余字段 {k}")

    for spec in schema:
        if spec.name not in out:
            if spec.required and spec.default is None:
                return SchemaRepairResult("rejected", None,
                                          error=f"缺必填字段 {spec.name} 且无默认值")
            out[spec.name] = spec.default
            fixes.append(f"补默认 {spec.name}={spec.default!r}")
            continue
        v = out[spec.name]
        # 类型修复
        try:
            casted = _CASTERS[spec.type](v)
            if casted is not v and casted != v:
                out[spec.name] = casted
                fixes.append(f"类型转换 {spec.name}: {type(v).__name__} → {spec.type}")
        except (ValueError, TypeError):
            return SchemaRepairResult("rejected", None,
                                      error=f"字段 {spec.name} 无法转为 {spec.type}")
        # 枚举修复（大小写/空白规范化）
        if spec.enum:
            cur = out[spec.name]
            norm = {str(e).strip().lower(): e for e in spec.enum}
            key = str(cur).strip().lower()
            if key in norm and norm[key] != cur:
                out[spec.name] = norm[key]
                fixes.append(f"枚举规范化 {spec.name}: {cur!r} → {norm[key]!r}")
            elif key not in norm:
                return SchemaRepairResult("rejected", None,
                                          error=f"字段 {spec.name} 值不在枚举内: {cur!r}")
    return SchemaRepairResult("repaired" if fixes else "ok", out, fixes)


def strip_code_fence(text: str) -> str:
    """剥离 markdown 代码围栏（LLM 输出的常见包裹）。"""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return m.group(1).strip() if m else text.strip()
