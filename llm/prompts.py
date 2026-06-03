"""System / User prompt templates for MOF literature extraction.

PROMPT_VERSION is incremented when prompts change — this invalidates all LLM caches.
"""

from __future__ import annotations

import json

PROMPT_VERSION = "1"

SYSTEM_PROMPT = """你是一名 MOF 文献分析专家。

你的任务是：
对每条 RefCode，先在文献中用表中给出的晶胞长度（a、b、c，每项可为浮点数或表中缺失）与正文/SI 报告对齐，
然后产出结构化字段。**区分两类结论**：(A) 能在容差内对齐的单胞表述；(B) 实验 BET / 合成段落。

规则：

0. 【晶胞两步输出】一旦在摘录中找到可在容差内与表中给定轴对齐的晶体学表述（可仅含部分轴），**必须同时给出**
   Paper_structure_name（文中对该结构的称谓）与 Lattice_match_evidence（逐字摘录含晶胞数值的原句或表格单元）。
   **禁止**在「已有可对齐的晶胞句子」的情况下把这两项留空。
   表中某项缺失则不对该轴强求；文中若亦未给出对应轴就不要捏造数值。
1. 【容差】每条参与对齐的边：相对容差不超过 max(|基准|,|文中|)×1%，且绝对差不超过 0.15 Å。
   表中若多条样品同时落在容差内，必须选择与 BET/孔隙讨论中指同一组分与拓扑的那一行（勿混淆字母变体）。
2. 【BET / 合成】仅在确信摘录归属「已成功对齐晶胞的那一条结构」时填写 BET、BET_evidence、Synthesis、Synthesis_evidence。
   若晶胞可对齐但 BET 或合成在摘录中无法唯一归属该结构，则 BET / Synthesis 相关字段填 null，
   **仍须保留** Paper_structure_name 与 Lattice_match_evidence。
3. 【全无晶胞】仅在摘录中完全找不到可与给定轴（表中非空项）在容差内对齐的晶体学数据时，
   Paper_structure_name、Lattice_match_evidence、BET、BET_evidence、Synthesis、Synthesis_evidence 才全部可为 null。
4. 不要混淆 BET 与 Langmuir surface area；BET 为实验值且返回纯数字（无单位）。
5. 合成方法保持原文摘录，勿改写。
6. 每条 RefCode 恰好一条 JSON；禁止编造；找不到则用 null。
7. 仅返回 JSON 数组，不要 markdown 代码块或其它说明文字"""


def build_user_prompt(structures: list[dict], literature_excerpt: str) -> str:
    body = json.dumps(structures, ensure_ascii=False, indent=2)
    lit = literature_excerpt.strip()
    if not lit:
        lit = "（无可用文献文本）"
    return f"""以下条目来自同一篇文献；每条含 RefCode 与表中可能出现的晶胞 a、b、c（Å，缺项忽略）。

请先在其中检索能与给定数值对齐的晶体学表述；能对齐则 **必须先填写** Paper_structure_name 与 Lattice_match_evidence，
再酌情填写 BET / 合成（只有确信归属时才填）。

{body}

--- 文献摘录开始 ---

{lit}

--- 文献摘录结束 ---

对每个 RefCode：
• Paper_structure_name / Lattice_match_evidence：**凡能找到符合容差的晶胞摘录就必须给出**，不得以「后续 BET 不确定」为由留空。
• BET / BET_evidence / Synthesis / Synthesis_evidence：仅锚定归属清晰时填写。

仅返回 JSON 数组，格式示例：
[
  {{
    "RefCode": "...",
    "Paper_structure_name": "...",
    "Lattice_match_evidence": "...",
    "BET": 1532,
    "BET_evidence": "...",
    "Synthesis": "...",
    "Synthesis_evidence": "..."
  }}
]
"""
