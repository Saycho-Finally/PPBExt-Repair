# PPBExt-Repair

**一句话**：LLM 应用在真实管线里会以多种方式坏掉——工具的调用格式、输出的结构、
检索的查询、记忆的内容、计划的推进。本项目把这些故障拆成**七个正交层位**并逐层修复，
修不了的明确拒绝（绝不静默放行）。当前已实现五层，全部纯确定性、零依赖。

> 作者：Saycho-Finally（独立研究者） ｜ AI 使用声明见 [AI_DISCLOSURE.md](AI_DISCLOSURE.md) ｜ License: MIT ｜ 零依赖 ｜ Python ≥3.10

---

## 已实现的五层

| # | 层位 | 故障形态 | 修复手段 |
|---|---|---|---|
| 1 | **工具层** | 参数结构错 / 调用混入文本 / JSON 截断 / 调用风暴 | 四 pass：`flatten` / `scavenge` / `truncation` / `storm` |
| 2 | **输出层** | 结构化输出违规（schema 不符 / 格式漂移） | schema 校验 + 本地修复（类型转换 / 补默认 / 枚举规范化 / 剥离多余字段） |
| 3 | **检索层** | 误检索（相关性低 / 覆盖不足） | 查询重写：召回不足放宽 / 结果过泛收紧 |
| 4 | **记忆层** | 记忆投毒 / 过时条目 | 投毒隔离 + 过期折叠（append-only 兼容，不物理删除） |
| 5 | **计划层** | 步骤停滞 / 循环 / 预算耗尽 | 重规划触发：`replan` / `backtrack` / `escalate` |

## 三态输出（七层共用的安全语义）

- `ok`：无需修复
- `repaired`：修复成功（记录命中的算子与证据）
- `rejected`：无法修复或修复不可信——**明确拒绝，绝不静默放行**

**每层都有明确的拒绝条件**，不是"总能修好"：

| 层 | 拒绝条件 |
|---|---|
| 工具层 | 无法解析为工具调用；或命中调用风暴 |
| 输出层 | 缺必填字段且无默认值；类型不可转换；值不在枚举内 |
| 检索层 | 查询全为停用词，无法重写 |
| 记忆层 | 隔离全部可疑条目后存储将为空（清空记忆不可逆，比保留可疑条目更危险） |
| 计划层 | 无备选动作可重规划（会产生与失败时相同的动作，属空操作） |

## 各层要点

**记忆层的折叠必须改变状态。** 初版只追加一条折叠记录而不改条目状态，
导致复检仍把旧条目判为"过期"。修正后旧条目标记为 `superseded_by`，
不再参与检索——**记录与状态一致**，折叠才成立。隔离与折叠都可按时间点回滚。

**计划层的指令必须可执行。** 检测到停滞/循环/预算耗尽后给出的升级指令要过
`verify_directive`：`resume_from` 必须指向真实成功步、`replan` 必须有备选动作。
全程无成功步时改为 `escalate`（无从恢复，升级而非空转）。

## 快速上手

```python
from repaircore import (RepairPipeline, MemoryEntry, repair_memory,
                        Step, repair_plan)

# 工具层
p = RepairPipeline()
r = p.run('思考中… {"name": "search", "arguments": {"q": {"city": "北京"}}}')
print(r.status, r.passes_hit)   # repaired ['scavenge', 'flatten']

# 记忆层：投毒隔离 + 过期折叠
entries = [MemoryEntry("m1", "pref", "喜欢 React", "user", 1.0),
           MemoryEntry("m2", "pref", "改用 Svelte", "user", 5.0)]
res = repair_memory(entries, now=100.0)
print(res.status, res.operators)   # repaired ['fold_stale(m1 → m2)']

# 计划层：停滞 → 重规划
steps = [Step(0, "a", "ok", True), Step(1, "b", "err", False),
         Step(2, "c", "err", False), Step(3, "d", "err", False)]
plan = repair_plan(steps, alternatives=["retry_with_backoff"])
print(plan.status, plan.directive["action"])   # repaired replan
```

## 实测（64 项测试全过）

41 项 v0.1/v0.2 测试（四 pass 链 / 输出层 / 检索层）+ **37 项 v0.3 测试**（记忆层 / 计划层）。
另附 32 例损坏样本的"带修复 vs 不带修复"对照（见下方实验依据）。

## 七层修复矩阵（完整路线）

| 层位 | 状态 |
|---|---|
| 工具层 / 输出层 / 检索层 | **已实现**（v0.1 / v0.2） |
| 记忆层 / 计划层 | **已实现**（v0.3） |
| 代码层（APR） | 研究位——需模型参与，成本与验证设计未定 |
| Harness 层（轨迹诊断） | 研究位——失败轨迹是诊断入口，但需离线工具链 |

**统一抽象**：`detect(evidence) → locate(layer, step) → repair(operator) → verify(ok?) → commit 或 reject`。
详见 [SPEC.md](SPEC.md)。

## 实验依据

修复链实测（**32 例损坏样本，五层对照**）见
[reports/修复链实测报告_2026-10-04.md](reports/修复链实测报告_2026-10-04.md) 与
[reports/记忆层与计划层实测_2026-10-05.md](reports/记忆层与计划层实测_2026-10-05.md)：

| 层 | 样本 | 不修复可用 | 修复后可用 |
|---|---|---|---|
| 工具层 | 9 | 0 | 9 |
| 输出层 | 8 | 1 | 8 |
| 检索层 | 4 | 3 | 4 |
| 记忆层 | 6 | 1 | 6 |
| 计划层 | 5 | 1 | 5 |
| **合计** | **32** | **6（19%）** | **32（100%）** |

## 设计边界

- **不做语义修复**：参数缺字段、值与 schema 不符属于"重试"而非"修复"——本项目只做
  结构与状态层的确定性修复，语义层交由上层决策（重试 / 换工具）
- **拒绝即安全**：无法修复或不可信时返回 rejected 而非猜测
- **记忆层不物理删除**：投毒条目只被隔离，原文保留以备审计；清空记忆不可逆，故宁可拒绝
- **计划层只改执行路径，不改任务定义**：指令是"从哪恢复、要不要升档"，不是改写目标
- **32 例为自建样本**，覆盖设计内的故障类型；不构成对真实流量的覆盖率估计

## 引用的先行者

- 工具层四类故障划分：Reasonix 的 tool-call repair（flatten / scavenge / truncation / storm）
- 工具调用规范的参数结构约定：OpenAI / Anthropic 的 tool-calling 文档
- 记忆层与计划层的故障形态参考（**仅作相关工作定位，实现为本项目独立设计**）：
  PMCoder（规划阶段与情节记忆的双向耦合）、Self-Healing Agentic Orchestrators
  （失败信号分类 + 预算内定向恢复）
- Harness 层方向：HCL / HarnessFix / Self-Harness（harness-level forgetting 与轨迹诊断）

---

## 贡献与引用

- 贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)；行为准则见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全问题请走 [SECURITY.md](SECURITY.md) 的私密渠道（勿开公开 Issue）
- 版本变更见 [CHANGELOG.md](CHANGELOG.md)；学术引用格式见 [CITATION.cff](CITATION.cff)
- 许可：MIT
