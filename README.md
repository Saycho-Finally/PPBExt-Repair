# PPBExt-Repair ｜ 补遗：工具调用修复外挂

**一句话**：LLM 的工具调用在真实管线里会以四种方式坏掉——参数结构不对、调用混在自然语言里、
JSON 被截断、同一工具反复空转。本外挂用**四 pass 流水线**逐类修复，修不了的明确拒绝
（绝不静默传坏参数）。

> License: MIT ｜ 零依赖 ｜ Python ≥3.10

---

## 四 pass 修复链

| pass | 故障 | 修复 |
|---|---|---|
| 1 `flatten` | 模型给嵌套参数，工具要扁平 | 嵌套拍平（`{"user":{"name":"x"}}` → `{"user.name":"x"}`），可逆 |
| 2 `scavenge` | 调用被写进自然语言/代码块 | 从自由文本捞取第一个合法调用 JSON |
| 3 `truncation` | 输出被 max_tokens 截断 | 括号/引号平衡扫描 + 补全 + 去尾逗号 |
| 4 `storm` | 同一工具短窗反复调用 | 滑窗计数抑制（默认 5s 内 3 次上限）|

## 三态输出（与决策层同纪律）

- `ok`：直接可解析，无需修复
- `repaired`：修复成功（记录命中了哪些 pass）
- `rejected`：无法修复——明确拒绝，不传坏参数

每笔修复落 `RepairRecord`（原输入截取 / 修复结果 / pass 命中 / 状态），可审计。

## 快速上手

```python
from repaircore import RepairPipeline

p = RepairPipeline()
r = p.run('思考中… {"name": "search", "arguments": {"q": {"city": "北京"}}}')
print(r.status, r.passes_hit)   # repaired ['scavenge', 'flatten']
print(r.repaired)               # {'name': 'search', 'arguments': {'q.city': '北京'}}
print(p.report())               # 三态统计 + pass 命中 + 风暴抑制计数
```

## 实测（14 项测试全过）

- 拍平/还原双向一致；从文本捞调用；两种截断场景修复成功；
- 风暴抑制三态（放行 3 次 → 抑制 → 窗口滑过恢复）；
- 流水线三态与报告统计。

## 设计边界

- **不做语义修复**：参数缺字段、值与 schema 不符属于"重试"而非"修复"——本外挂只做
  结构与格式层的确定性修复，语义层交由上层决策（重试/换工具）
- **拒绝即安全**：无法解析时返回 rejected 而非猜测——坏参数进工具比报错更贵

## 引用的先行者

- Reasonix 工具调用修复的四类故障划分（flatten / scavenge / truncation / storm）
- OpenAI/Anthropic 工具调用规范的参数结构约定

---

## 贡献与引用

- 贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)；行为准则见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全问题请走 [SECURITY.md](SECURITY.md) 的私密渠道（勿开公开 Issue）
- 版本变更见 [CHANGELOG.md](CHANGELOG.md)；学术引用格式见 [CITATION.cff](CITATION.cff)
- 许可：MIT
