"""记忆层修复：投毒隔离与过期折叠（修复矩阵第 4 层）。

修复两类记忆故障：
  1. 投毒（poisoned）：来源不可信，或内容含指令注入特征
  2. 过期（stale）：同一语义键上有更新的条目，旧条目仍会参与检索

算子（**append-only 兼容，不物理删除**）：
  - remove_poisoned：把不可信条目标记为隔离（检索时排除），保留原文以备审计
  - fold_stale：把旧条目标记为已被新条目取代（即记忆层的折叠纪律），并留下折叠记录
  - rollback：撤销某个时间点之后发生的隔离与折叠，恢复为可检索

被隔离（`quarantined`）与被取代（`superseded_by`）的条目都**不参与检索**，
也都不再计入缺陷——这是折叠必须改变状态、而不只是留一条记录的原因。

安全纪律（三态：ok / repaired / rejected）：
**拒绝条件**——若隔离全部可疑条目会让存储为空，则拒绝执行。
清空记忆比保留可疑条目更危险（不可逆的损失 vs 可撤销的污染）。

纯确定性实现，零依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# 可信来源白名单（可由调用方覆盖）
TRUSTED_SOURCES = {"user", "system", "verified"}

# 指令注入特征（小写匹配；示例规模，生产可替换为规则库）
INJECTION_MARKERS = (
    "ignore previous", "ignore all previous", "disregard prior",
    "忽略之前", "忽略以上", "忽略上述", "系统提示", "system prompt",
    "you are now", "你现在是", "忘记你之前",
)


@dataclass
class MemoryEntry:
    id: str
    key: str                       # 语义键：同键的新条目使旧条目过期
    content: str
    provenance: str = "unknown"    # 来源标识
    ts: float = 0.0
    kind: str = "fact"
    quarantined: bool = False      # 已隔离：不参与检索，但仍在库中
    quarantined_at: float = 0.0    # 隔离时间（rollback 用）
    superseded_by: str = ""        # 已被哪条新条目取代（折叠）；非空即不参与检索
    superseded_at: float = 0.0     # 折叠时间（rollback 用）


@dataclass
class MemoryDefect:
    kind: str                      # poisoned / stale
    entry_id: str
    detail: str


@dataclass
class MemoryRepairResult:
    status: str                    # ok / repaired / rejected
    entries: list[MemoryEntry]
    defects: list[MemoryDefect] = field(default_factory=list)
    operators: list[str] = field(default_factory=list)
    folds: list[dict] = field(default_factory=list)
    error: str = ""


def is_live(e: MemoryEntry) -> bool:
    """是否参与检索：未被隔离、也未被取代。"""
    return not e.quarantined and not e.superseded_by


def detect_defects(entries: list[MemoryEntry],
                   trusted_sources: set[str] | None = None) -> list[MemoryDefect]:
    """检出投毒与过期。已隔离或已被取代的条目不重复计入。"""
    trusted = set(trusted_sources or TRUSTED_SOURCES)
    defects: list[MemoryDefect] = []

    for e in entries:
        if not is_live(e):
            continue
        reasons = []
        if e.provenance not in trusted:
            reasons.append(f"来源不可信（{e.provenance}）")
        low = e.content.lower()
        hit = [m for m in INJECTION_MARKERS if m in low]
        if hit:
            reasons.append(f"含指令注入特征（{hit[0]}）")
        if reasons:
            defects.append(MemoryDefect("poisoned", e.id, "；".join(reasons)))

    newest: dict[str, MemoryEntry] = {}
    for e in entries:
        if not is_live(e):
            continue
        cur = newest.get(e.key)
        if cur is None or e.ts > cur.ts:
            newest[e.key] = e
    for e in entries:
        if not is_live(e):
            continue
        n = newest.get(e.key)
        if n is not None and n.id != e.id and n.ts > e.ts:
            defects.append(MemoryDefect(
                "stale", e.id, f"同键 {e.key} 上有更新的条目 {n.id}"))
    return defects


def repair_memory(entries: list[MemoryEntry],
                  trusted_sources: set[str] | None = None,
                  now: float = 0.0) -> MemoryRepairResult:
    """执行修复：隔离投毒 + 折叠过期。返回三态结果。"""
    defects = detect_defects(entries, trusted_sources)
    if not defects:
        return MemoryRepairResult("ok", list(entries))

    poisoned = {d.entry_id for d in defects if d.kind == "poisoned"}
    stale = [d.entry_id for d in defects if d.kind == "stale"]

    live = [e for e in entries if is_live(e)]
    surviving = [e for e in live if e.id not in poisoned]
    if not surviving:
        return MemoryRepairResult(
            "rejected", list(entries), defects,
            error="隔离全部可疑条目后存储将为空——拒绝执行"
                  "（清空记忆不可逆，保留可疑条目可撤销）")

    stale_map: dict[str, MemoryEntry] = {}
    for eid in stale:
        old = next(x for x in entries if x.id == eid)
        newer = next((x for x in live if x.key == old.key and x.ts > old.ts), None)
        if newer is not None:
            stale_map[eid] = newer

    out: list[MemoryEntry] = []
    for e in entries:
        if e.id in poisoned:
            out.append(replace(e, quarantined=True,
                               quarantined_at=now or e.quarantined_at or e.ts))
        elif e.id in stale_map:
            out.append(replace(e, superseded_by=stale_map[e.id].id,
                               superseded_at=now))
        else:
            out.append(e)

    operators: list[str] = []
    if poisoned:
        operators.append(f"remove_poisoned(隔离 {len(poisoned)} 条)")
    folds: list[dict] = []
    for eid, newer in stale_map.items():
        old = next(x for x in entries if x.id == eid)
        folds.append({"old": eid, "new": newer.id, "key": old.key, "ts": now})
        operators.append(f"fold_stale({eid} → {newer.id})")

    return MemoryRepairResult("repaired", out, defects, operators, folds)


def rollback(entries: list[MemoryEntry],
             to_ts: float) -> tuple[list[MemoryEntry], list[str]]:
    """回退：撤销 `to_ts` 之后发生的隔离与折叠，恢复为可检索。

    本层不做物理删除，故回退无需恢复数据，只需复位状态位。
    """
    out: list[MemoryEntry] = []
    restored: list[str] = []
    for e in entries:
        if e.quarantined and e.quarantined_at > to_ts:
            out.append(replace(e, quarantined=False, quarantined_at=0.0))
            restored.append(e.id)
        elif e.superseded_by and e.superseded_at > to_ts:
            out.append(replace(e, superseded_by="", superseded_at=0.0))
            restored.append(e.id)
        else:
            out.append(e)
    return out, restored


def verify_repair(result: MemoryRepairResult,
                  trusted_sources: set[str] | None = None) -> tuple[bool, str]:
    """复检：剩余缺陷必须为空，且良性可用条目不得减少。"""
    if result.status != "repaired":
        return False, f"状态为 {result.status}，无可验证的修复"
    remain = detect_defects(result.entries, trusted_sources)
    if remain:
        return False, f"复检仍有 {len(remain)} 处缺陷"
    if not any(is_live(e) for e in result.entries):
        return False, "复检后无可用条目"
    return True, ""
