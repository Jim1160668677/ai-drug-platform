"""LLM Prompt 模板 — 系统提示词与上下文构建"""
from typing import Any, Dict, List


SYSTEM_PROMPTS: Dict[str, str] = {
    "fast_screen": (
        "你是精准医学快速筛查助手。你的职责是基于规则和已知数据库快速回答用户问题。\n\n"
        "约束：\n"
        "- 回答简洁，直击要点\n"
        "- 优先引用已获批药物和临床试验数据\n"
        "- 不确定时明确说明，不编造\n"
        "- 回答控制在 500 字以内\n"
    ),
    "deep_insight": (
        "你是精准医学深度分析专家。你的职责是综合文献、变异注释、通路信息、PPI 网络、"
        "临床试验数据进行机制级深度分析。\n\n"
        "要求：\n"
        "- 给出致病机制解释（变异如何影响蛋白功能）\n"
        "- 分析通路角色（在信号通路中的位置）\n"
        "- 评估治疗策略（已有/在研/潜在疗法）\n"
        "- 讨论耐药风险\n"
        "- 给出推荐方案（含剂量与证据来源）\n"
        "- 标注证据等级（I-IV）\n"
    ),
}


TARGET_DISCOVERY_PROMPT = (
    "基于以下多组学数据，请识别并排序候选靶点：\n\n"
    "## 数据集摘要\n{datasets_summary}\n\n"
    "## 已知变异\n{variants}\n\n"
    "## 差异表达基因\n{diff_genes}\n\n"
    "请从以下维度评估每个候选靶点：\n"
    "1. 致病性（变异是否致病）\n"
    "2. 可成药性（是否有已知药物或小分子）\n"
    "3. 通路重要性（是否为 hub 基因）\n"
    "4. 临床证据（是否有临床试验支持）\n"
)

MOLECULE_DESIGN_PROMPT = (
    "基于靶点 {target_gene} 的结构信息，请设计候选分子：\n\n"
    "## 靶点信息\n{target_info}\n\n"
    "## 约束条件\n{constraints}\n\n"
    "## 已知活性分子（参考骨架）\n{known_molecules}\n\n"
    "请生成分子的 SMILES、预测活性、类药性评估。"
)

EVIDENCE_CHAIN_PROMPT = (
    "请为靶点 {gene_symbol} 构建完整证据链：\n\n"
    "## 已知信息\n{target_data}\n\n"
    "请从以下来源汇总证据：\n"
    "1. ClinVar 变异致病性注释\n"
    "2. COSMIC 肿瘤突变记录\n"
    "3. ChEMBL 活性数据\n"
    "4. ClinicalTrials.gov 试验\n"
    "5. PPI 网络邻居\n"
    "每条证据标注来源、证据类型、等级、摘要。"
)

REPURPOSING_PROMPT = (
    "针对靶点 {target_gene}，请评估老药新用候选：\n\n"
    "## 已获批药物\n{approved_drugs}\n\n"
    "## 适应症信息\n{indications}\n\n"
    "请评分并排序，考虑：批准状态、适应症匹配度、类药性、安全性。"
)


def build_context_prompt(context: Dict[str, Any]) -> str:
    """将基因/变异/药物/通路等上下文拼装为结构化 prompt

    Args:
        context: {
            gene: str,
            variants: List[dict],
            drugs: List[dict],
            pathway: dict,
            ppi_neighbors: List[dict],
            clinical_trials: List[dict],
            extra: str
        }
    Returns:
        结构化的上下文字符串
    """
    parts: List[str] = []

    gene = context.get("gene", "")
    if gene:
        parts.append(f"## 目标基因：{gene}")

    variants = context.get("variants") or []
    if variants:
        v_lines = []
        for v in variants[:10]:
            query = v.get("query", "?")
            hgvs_p = v.get("hgvs_p", "?")
            clnsig = (v.get("clinvar") or {}).get("clnsig", "unknown")
            v_lines.append(f"- {query} ({hgvs_p}) — ClinVar: {clnsig}")
        parts.append("## 已知变异\n" + "\n".join(v_lines))

    drugs = context.get("drugs") or []
    if drugs:
        d_lines = [f"- {d.get('name', '?')} (max_phase={d.get('max_phase', '?')})" for d in drugs[:10]]
        parts.append("## 已知药物\n" + "\n".join(d_lines))

    pathway = context.get("pathway") or {}
    if pathway:
        pw_names = pathway.get("pathways") or []
        if pw_names:
            parts.append("## 相关通路\n" + ", ".join(str(p) for p in pw_names[:10]))

    neighbors = context.get("ppi_neighbors") or []
    if neighbors:
        n_lines = [f"- {n.get('gene', '?')} ({n.get('interaction', '?')})" for n in neighbors[:15]]
        parts.append("## PPI 邻居\n" + "\n".join(n_lines))

    trials = context.get("clinical_trials") or []
    if trials:
        t_lines = [f"- {t.get('nct_id', '?')}: {t.get('title', '?')[:60]}" for t in trials[:5]]
        parts.append("## 临床试验\n" + "\n".join(t_lines))

    extra = context.get("extra")
    if extra:
        parts.append("## 补充信息\n" + extra)

    return "\n\n".join(parts) if parts else "无可用上下文"
