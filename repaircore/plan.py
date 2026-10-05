"""计划层修复：停滞检测与重规划触发（修复矩阵第 5 层）。

修复两类计划故障：
  1. 停滞（stalled）：连续若干步无成功（重复失败）
  2. 循环（loop）：相同（动作, 观察）对反复出现
  3. 预算耗尽（budget_exhausted）：步数用尽且全程无成功

算子（检测到信号 → 升级决策；**不改写任务定义**，只改执行路径）：
  - replan：从最近成功步恢复，替换当前子目标（需提供备选动作）
  - backtrack：回退到最近成功步（无需备选，回退本身可执行）
  - escalate：循环或预算耗尽必须换策略 / 升档 / 转人工（原路重规划无效）

安全纪律（三态：ok / repaired / rejected）：
**拒绝条件**——指令不可执行时明确拒绝。典型情形：既没有成功步可恢复，
又没有备选动作，此时"重规划"必然产生与失败时相同的动作，是空操作，
不能假装修好了。

纯确定性实现，零依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field

ALLOWED_ACTIONS = ("replan", "backtrack", "escalate")

# 严重度优先序：循环比停滞更硬（原路重规划对循环无效）
PRIORITY = {"loop": 0, "budget_exhausted": 1, "stalled": 2}


@dataclass
class Step:
    idx: int
    action: str
    observation: str
    ok: bool = True


@dataclass
class ProgressDefect:
    kind: str            # stalled / loop / budget_exhausted
    at_step: int
    detail: str


@dataclass
class PlanRepairResult:
    status: str          # ok / repaired / rejected
    defects: list[ProgressDefect] = field(default_factory=list)
    directive: dict | None = None
    notes: list[str] = field(default_factory=list)
    error: str = ""


def detect_stagnation(steps: list[Step], stall_window: int = 3,
                      loop_repeats: int = 2) -> list[ProgressDefect]:
    """检出停滞与循环。返回按出现顺序的缺陷清单。"""
    defects: list[ProgressDefect] = []
    run = 0
    for s in steps:
        run = run + 1 if not s.ok else 0
        if run == stall_window:
            defects.append(ProgressDefect(
                "stalled", s.idx, f"连续 {stall_window} 步无成功（至第 {s.idx} 步）"))

    seen: dict[tuple[str, str], int] = {}
    for s in steps:
        k = (s.action, s.observation)
        seen[k] = seen.get(k, 0) + 1
        if seen[k] == loop_repeats + 1:
            defects.append(ProgressDefect(
                "loop", s.idx,
                f"动作 {s.action!r} 与同一观察重复 {seen[k]} 次"))
    return defects


def verify_directive(steps: list[Step], directive: dict) -> tuple[bool, str]:
    """指令可执行性检查（修复后复检的判据）。"""
    act = directive.get("action")
    if act not in ALLOWED_ACTIONS:
        return False, f"未知指令 {act!r}"
    resume = directive.get("resume_from")
    if act in ("replan", "backtrack"):
        if resume is None:
            return False, "无成功步可恢复，回退/重规划不可执行"
        if not any(s.idx == resume and s.ok for s in steps):
            return False, f"恢复点 {resume} 不是成功步"
    if act == "replan" and not directive.get("alternatives"):
        return False, "无备选动作，重规划会给出与失败时相同的动作（空操作）"
    return True, ""


def repair_plan(steps: list[Step], alternatives: list[str] | None = None,
                budget: int | None = None,
                stall_window: int = 3, loop_repeats: int = 2) -> PlanRepairResult:
    """执行修复：按严重度最高的信号给出升级指令。返回三态结果。"""
    defects = detect_stagnation(steps, stall_window, loop_repeats)
    if budget is not None and steps and len(steps) >= budget \
            and not any(s.ok for s in steps):
        defects.append(ProgressDefect(
            "budget_exhausted", steps[-1].idx,
            f"步数已达预算 {budget} 且无成功步"))
    if not defects:
        return PlanRepairResult("ok")

    last_ok = max((s.idx for s in steps if s.ok), default=None)
    kind = sorted(defects, key=lambda d: PRIORITY.get(d.kind, 9))[0].kind
    alts = list(alternatives or [])

    if kind == "loop":
        directive = {
            "action": "escalate", "signal": "loop", "resume_from": last_ok,
            "alternatives": alts,
            "reason": "相同动作与观察反复出现，原路重规划无效，需换策略或升档",
        }
    elif kind == "budget_exhausted":
        directive = {
            "action": "escalate", "signal": "budget_exhausted",
            "resume_from": last_ok, "alternatives": alts,
            "reason": "步数用尽且无成功步，需提高预算或转人工介入",
        }
    else:
        if last_ok is None:
            directive = {
                "action": "escalate", "signal": "stalled_no_progress",
                "resume_from": None, "alternatives": alts,
                "reason": "连续失败且全程无成功步，无可靠恢复点，需升档或转人工介入",
            }
        else:
            directive = {
                "action": "replan", "signal": "stalled",
                "resume_from": last_ok, "alternatives": alts,
                "reason": f"连续失败，从第 {last_ok} 步（最近成功）恢复并替换当前子目标",
            }

    ok, why = verify_directive(steps, directive)
    if not ok:
        return PlanRepairResult("rejected", defects, directive, error=why)
    return PlanRepairResult("repaired", defects, directive,
                            notes=[directive["reason"]])


def verify_repair(result: PlanRepairResult,
                  steps: list[Step] | None = None) -> tuple[bool, str]:
    """复检：repaired 时指令必须可执行。"""
    if result.status != "repaired":
        return False, f"状态为 {result.status}，无可验证的修复"
    if result.directive is None:
        return False, "repaired 但无指令"
    if steps is None:
        return True, ""
    return verify_directive(steps, result.directive)
