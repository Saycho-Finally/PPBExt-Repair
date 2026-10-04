"""检索层修复：查询重写与检索结果对齐（修复矩阵第 3 层）。

修复两类检索故障：
  1. 零结果 / 结果过少 → 查询放宽（去停用词、去引号限定、同义扩展）
  2. 结果过多 / 明显跑题 → 查询收紧（提取核心术语，去泛化词）
纯确定性实现（无模型调用），与工具层共享三态语义。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 中文停用词（检索中无区分度的高频词）
STOPWORDS = {
    "的", "了", "和", "与", "或", "是", "在", "有", "我", "你", "他", "她", "它",
    "这", "那", "什么", "怎么", "如何", "请", "帮", "一下", "一个", "可以", "能",
    "吗", "呢", "吧", "啊", "哦", "呀", "嗯", "的话", "那个", "这个",
    "the", "a", "an", "of", "to", "and", "or", "is", "are", "how", "what",
}

# 同义扩展表（检索召回增强，示例规模；生产可替换为术语库）
SYNONYMS = {
    "报错": ["错误", "异常", "error"],
    "卡死": ["挂起", "无响应", "hang"],
    "慢": ["延迟", "性能", "latency"],
    "写好": ["实现", "编写"],
    "查一下": ["查询", "检索"],
    "怎么": [""],
}


@dataclass
class RewriteResult:
    status: str                  # ok / repaired / rejected
    query: str
    strategy: str = ""           # 命中的重写策略
    notes: list[str] = field(default_factory=list)


def _terms(q: str) -> list[str]:
    """切词（零依赖的中文处理）：先以停用词表做子串删除，再按字符类切分。
    中文无空格，字符类匹配会把连续中文串当整词——故采用删除法而非分词法。"""
    s = q.lower()
    for sw in sorted(STOPWORDS, key=len, reverse=True):
        s = s.replace(sw, " ")
    return re.findall(r"[\w]+", s)


def rewrite_for_recall(query: str, n_results: int) -> RewriteResult:
    """召回不足时放宽查询（去停用词 + 同义扩展）。"""
    notes = []
    terms = _terms(query)
    kept = [t for t in terms if t not in STOPWORDS]
    if not kept:
        return RewriteResult("rejected", query,
                             notes=["查询全为停用词，无法重写"])
    expanded = list(kept)
    for t in kept:
        if t in SYNONYMS:
            exp = [e for e in SYNONYMS[t] if e]
            if exp:
                expanded.extend(exp)
                notes.append(f"同义扩展 {t} → {exp}")
    new_q = " ".join(dict.fromkeys(expanded))     # 去重保序
    if new_q != query:
        return RewriteResult("repaired", new_q,
                             strategy="relax(去停用词 + 同义扩展)", notes=notes)
    return RewriteResult("ok", query, notes=["查询已是最简形式"])


def rewrite_for_precision(query: str, n_results: int) -> RewriteResult:
    """结果过多/跑题时收紧查询（提取核心术语，去泛化词）。"""
    notes = []
    terms = [t for t in _terms(query) if t not in STOPWORDS]
    if len(terms) <= 1:
        return RewriteResult("ok", query, notes=["查询已足够具体"])
    # 保留长词（信息量代理）与专有名词（含拉丁字母/数字）
    core = [t for t in terms if len(t) >= 3 or re.search(r"[A-Za-z0-9]", t)]
    core = core or terms[:2]
    if core != terms:
        dropped = [t for t in terms if t not in core]
        notes.append(f"去泛化词 {dropped}")
        return RewriteResult("repaired", " ".join(core),
                             strategy="tighten(核心术语提取)", notes=notes)
    return RewriteResult("ok", query)


def rewrite_auto(query: str, n_results: int,
                 low_threshold: int = 1, high_threshold: int = 50) -> RewriteResult:
    """按检索结果量自动选择策略：过少 → 放宽；过多 → 收紧。"""
    if n_results <= low_threshold:
        return rewrite_for_recall(query, n_results)
    if n_results >= high_threshold:
        return rewrite_for_precision(query, n_results)
    return RewriteResult("ok", query, notes=["结果量正常，无需重写"])
