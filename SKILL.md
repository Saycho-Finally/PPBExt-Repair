---
name: ppb-repair
description: "工具调用修复四 pass 流水线：拍平、捞取、截断修复、风暴抑制。适用于「模型输出的工具调用格式坏掉」「JSON 被截断」「同一工具反复空转」的场景，三态输出（ok/repaired/rejected）。"
---

# ppb-repair

## 能力

- pass 1 flatten：嵌套参数拍平（可逆）
- pass 2 scavenge：从自由文本捞取调用 JSON
- pass 3 truncation：括号/引号平衡扫描 + 补全
- pass 4 storm：同工具滑窗抑制
- 三态输出 + RepairRecord 审计

## 何时使用

- 工具调用参数结构不对 / 调用混在自然语言里 / JSON 截断 / 调用风暴

## 接口

`from repaircore import RepairPipeline`

## 边界

只做结构层修复；语义问题（参数缺字段/值不符 schema）交上层重试决策，不猜测。

---

*本技能为 PPBExt-Repair 仓库的 agent 可加载形态（SKILL.md 标准）。完整文档与数据见仓库 README。*
