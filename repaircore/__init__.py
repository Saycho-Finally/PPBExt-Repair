"""PPBExt-Repair：多层修复链（七层矩阵，已实现五层）。

已实现（全部纯确定性、零依赖）：
  1. 工具层  四 pass 流水线（flatten / scavenge / truncation / storm）
  2. 输出层  schema 校验与本地修复
  3. 检索层  查询重写（放宽 / 收紧）
  4. 记忆层  投毒隔离与过期折叠（append-only 兼容）
  5. 计划层  停滞/循环检测与重规划触发

待做（需模型参与，属研究位）：6 代码层（APR）／7 Harness 层（轨迹诊断）。
七层共用同一套三态语义：ok / repaired / rejected（拒绝优先，不静默放行）。
"""

from repaircore.pipeline import (RepairPipeline, RepairRecord, StormGuard,
                                 flatten_params, scavenge_call,
                                 repair_truncated, unflatten_params)
from repaircore.schema import (FieldSpec, SchemaRepairResult,
                               repair_against_schema, strip_code_fence)
from repaircore.retrieval import (RewriteResult, rewrite_auto,
                                  rewrite_for_precision, rewrite_for_recall)
from repaircore.memory import (MemoryDefect, MemoryEntry, MemoryRepairResult,
                               detect_defects, is_live, repair_memory, rollback)
from repaircore.memory import verify_repair as verify_memory_repair
from repaircore.plan import (PlanRepairResult, ProgressDefect, Step,
                             detect_stagnation, repair_plan)
from repaircore.plan import verify_directive
from repaircore.plan import verify_repair as verify_plan_repair

__version__ = "0.3.0"
__all__ = ["RepairPipeline", "RepairRecord", "StormGuard", "flatten_params",
           "unflatten_params", "scavenge_call", "repair_truncated",
           "FieldSpec", "SchemaRepairResult", "repair_against_schema",
           "strip_code_fence", "RewriteResult", "rewrite_auto",
           "rewrite_for_precision", "rewrite_for_recall",
           "MemoryEntry", "MemoryDefect", "MemoryRepairResult",
           "detect_defects", "repair_memory", "rollback", "is_live",
           "verify_memory_repair",
           "Step", "ProgressDefect", "PlanRepairResult",
           "detect_stagnation", "repair_plan", "verify_directive",
           "verify_plan_repair", "__version__"]
