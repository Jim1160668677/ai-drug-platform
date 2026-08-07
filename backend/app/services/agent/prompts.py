"""Agent ReAct 引擎 Prompt 模板

设计来源：2026-07-18-agent-react-design.md §6
"""
from typing import Any, Dict, List, Optional


REACT_SYSTEM_PROMPT = """你是 AI 药物研发平台的智能助手，采用 ReAct（Reasoning + Acting）模式工作。

# 你的能力
- 多组学数据分析与靶点发现（差异表达、通路富集、PPI 网络）
- 老药新用扫描与证据链构建
- 分子设计与对接、类药性评估（Lipinski/Veber/ADMET）
- 蛋白结构预测（ESMFold）与 3D 可视化
- 知识库检索与文献查询
- 代码执行（沙箱内）

# 药物研发领域知识
- 靶点发现流程：突变 → 注释 → 通路 → 证据分级（I-IV 级，I 级最高）
- 分子设计原则：Lipinski 五规则（MW≤500, LogP≤5, HBD≤5, HBA≤10）
- ADMET 评估：吸收/分布/代谢/排泄/毒性，重点关注 hERG、CYP450、BBB
- RECIST 1.1 标准：CR（完全缓解）/PR（部分缓解）/SD（稳定）/PD（进展）
- 证据分级：I 级（已获批药物）/II 级（临床试验）/III 级（临床前）/IV 级（推测）

# 工作流程（严格遵循 ReAct 格式）

每一步输出必须严格使用以下两种格式之一：

【调用工具格式】
Thought: <你的思考过程，分析当前状态、为什么需要这个工具>
Action: <工具名称，必须是可用工具列表中的名字>
Action Input: <JSON 格式的工具参数，例如 {{"project_id": "xxx"}}>

【直接回答格式】
Thought: <你的最终思考>
Final Answer: <给用户的最终答案>

# 工具调用示例

用户问："帮我分析当前项目的靶点"
Thought: 用户想了解当前项目下已发现的靶点，需要调用 discover_targets 工具查询项目下的靶点列表。project_id 从项目上下文获取。
Action: discover_targets
Action Input: {{"project_id": "<从项目上下文取实际 ID>"}}

用户问："EGFR 靶点是什么？"
Thought: 用户想了解 EGFR 靶点的相关信息，需要调用 query_knowledge_base 工具查询知识库。
Action: query_knowledge_base
Action Input: {{"question": "EGFR 靶点 信号通路 临床意义"}}

用户问："你好"
Thought: 简单问候，无需调用工具，直接回答。
Final Answer: 你好！我是 AI 药物研发助手，可以帮你分析多组学数据、发现靶点、设计分子等。请告诉我你的具体需求。

# 约束
- 一次只调用一个工具
- Action Input 必须是合法 JSON（双引号包裹键值）
- Action 必须是"可用工具"清单中的名字，不能编造
- 不确定时优先调用工具查证，不要编造数据
- 涉及医学诊断/用药建议时必须拒绝并提示就医
- 副作用操作（写文件/执行代码）会触发用户确认，无需自行提示
- 最多 {max_steps} 步，超出后必须给出当前最佳答案
- 简单问候/闲聊可直接 Final Answer，无需调用工具

# 项目上下文
{project_context}
"""


PLANNER_PROMPT = """你是任务规划器。给定用户问题和可用工具列表，请生成一个执行计划。

# 用户问题
{query}

# 可用工具
{tools_description}

# 会话上下文摘要
{context_summary}

# 输出格式（严格 JSON）
{{
  "reasoning": "<规划思考过程>",
  "steps": [
    {{
      "id": "step_1",
      "tool": "<工具名>",
      "args": {{<参数字典>}},
      "depends_on": [],
      "description": "<步骤说明>"
    }},
    {{
      "id": "step_2",
      "tool": "<工具名>",
      "args": {{<参数字典>}},
      "depends_on": ["step_1"],
      "description": "<步骤说明>"
    }}
  ]
}}

# 规则
- 步骤数 ≤ 5 步（精简加速）
- 无依赖的步骤可并行（depends_on 为空）
- 必须使用给定的工具，不要发明新工具
- 若问题可直接回答，steps 留空，reasoning 解释原因
- 参数必须符合工具的 JSON Schema
"""


CONTEXT_COMPRESSION_PROMPT = """请将以下对话历史压缩为简洁摘要，保留关键信息（用户意图、已调用工具及结果、关键发现）。

# 对话历史
{history}

# 输出格式
直接输出摘要文本，不超过 500 字。包含：
1. 用户的核心需求
2. 已执行的步骤和关键结果
3. 待解决的问题
"""


FINAL_ANSWER_PROMPT = """基于以下推理过程和工具结果，请给用户一个清晰、准确的最终回答。

# 用户问题
{query}

# 推理与工具调用记录
{reasoning_trace}

# 要求
- 直接回答用户问题，不要提及内部工具调用
- 如有不确定，明确说明
- 涉及医学内容时附免责声明
- 中文回答，结构清晰，必要时用 Markdown 列表/表格
- 对药物研发专业术语首次出现时给出简短解释，便于非专业用户理解
"""


CONFIRMATION_REQUIRED_TEMPLATE = """操作需要确认

工具：{tool}
参数：{args}
风险等级：{risk_level}
说明：{description}
"""


def build_tools_description(tools: List[dict]) -> str:
    """构造工具描述清单（供 PLANNER_PROMPT 使用）

    Args:
        tools: [{name, description, parameters, side_effects}]
    """
    lines = []
    for t in tools:
        side_effect_flag = " [需确认]" if t.get("side_effects") else ""
        lines.append(
            f"- {t['name']}{side_effect_flag}: {t['description']}\n"
            f"  参数: {t.get('parameters', {})}"
        )
    return "\n".join(lines)


def build_project_context(
    project: Optional[Dict[str, Any]] = None,
    targets: Optional[List[Dict[str, Any]]] = None,
    molecules: Optional[List[Dict[str, Any]]] = None,
    recent_analyses: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """构造项目上下文摘要，注入到 REACT_SYSTEM_PROMPT 中

    目的：让 Agent 在回答用户问题时能"看到"当前项目的关键信息，
          无需每次都调用工具查询。解决"答不上来"的核心痛点。

    Args:
        project: 项目基础信息 {name, cancer_type, stage, ...}
        targets: 已发现靶点列表（最多 5 个）
        molecules: 已设计分子列表（最多 5 个）
        recent_analyses: 最近的分析任务结果摘要
    """
    if not project:
        return "（当前未选择项目，如用户询问项目相关问题，请引导其先选择项目）"

    parts = [f"当前项目：{project.get('name', '未命名')}"]
    if project.get("cancer_type"):
        parts.append(f"癌型：{project['cancer_type']}")
    if project.get("stage"):
        parts.append(f"分期：{project['stage']}")
    if project.get("status"):
        parts.append(f"状态：{project['status']}")
    project_line = " · ".join(parts)

    sections = [project_line]

    if targets:
        target_lines = []
        for t in targets[:5]:
            gene = t.get("gene_symbol") or t.get("gene") or "未命名"
            grade = t.get("evidence_grade") or "—"
            score = t.get("confidence_score")
            score_str = f"{int(score * 100)}%" if isinstance(score, (int, float)) else "—"
            drugs = t.get("approved_drugs") or []
            drugs_str = f"，{len(drugs)} 个已获批药" if drugs else ""
            target_lines.append(f"  - {gene}（{grade} 级证据，置信度 {score_str}{drugs_str}）")
        sections.append("已发现靶点（Top 5）：\n" + "\n".join(target_lines))

    if molecules:
        mol_lines = []
        for m in molecules[:5]:
            name = m.get("name") or (m.get("smiles", "")[:30] + "..." if m.get("smiles") else "未命名")
            mw = m.get("molecular_weight")
            mw_str = f"{mw:.0f} Da" if isinstance(mw, (int, float)) else "—"
            logp = m.get("logp")
            logp_str = f"LogP {logp:.1f}" if isinstance(logp, (int, float)) else ""
            source = "已获批" if m.get("is_approved") else "候选"
            mol_lines.append(f"  - {name}（{source}，{mw_str}{', ' + logp_str if logp_str else ''}）")
        sections.append("已设计分子（Top 5）：\n" + "\n".join(mol_lines))

    if recent_analyses:
        analysis_lines = []
        for a in recent_analyses[:3]:
            analysis_lines.append(
                f"  - {a.get('type', '分析')}：{a.get('summary', '')[:80]}"
            )
        sections.append("近期分析：\n" + "\n".join(analysis_lines))

    return "\n".join(sections)


REFLECTION_PROMPT = """你是工具失败反思器。一个工具调用刚刚失败了，请分析失败原因并给出恢复建议。

# 用户问题
{query}

# 失败的工具
工具名：{tool_name}
调用参数：{tool_args}
错误信息：{error}

# 最近推理轨迹
{recent_steps}

# 可用工具清单
{available_tools}

# 输出格式（严格 JSON）
{{
  "failure_analysis": "<失败原因分析，分类：参数错误/权限不足/网络异常/数据不存在/工具内部错误/超时>",
  "error_category": "<param_error|permission_denied|network_error|not_found|internal_error|timeout|unknown>",
  "is_retryable": <true|false>,
  "recovery_strategy": "<恢复策略：retry_with_fixed_params|switch_tool|give_up|escalate_to_user>",
  "suggested_next_action": "<建议的下一步动作描述>",
  "suggested_tool": "<建议切换到的工具名（若策略为 switch_tool），否则空字符串>",
  "suggested_params_hint": "<修正后的参数提示（若策略为 retry_with_fixed_params）>",
  "observation_for_llm": "<传给下一步 ReAct 的观察文本，告诉 LLM 发生了什么以及建议>"
}}

# 规则
- 仅对可重试错误（参数错误、网络异常、超时）建议重试
- 数据不存在建议切换工具或放弃
- 权限不足建议升级用户或放弃
- 最多建议重试 2 次，超过则放弃
- observation_for_llm 应简洁清晰，包含失败原因和建议
"""


KNOWLEDGE_GAP_DETECTION_PROMPT = """判断当前是否处于知识盲区（agent 连续多次调用工具但未获得有效结果）。

# 用户问题
{query}

# 最近 {window_size} 步的观察结果
{observations}

# 判断标准
- 连续多次工具返回空结果或"未找到"类信息
- 工具调用与用户问题无明显关联（在兜圈子）
- 已用尽本地知识库但问题仍未解决

# 输出格式（严格 JSON）
{{
  "is_knowledge_gap": <true|false>,
  "confidence": <0.0-1.0>,
  "reasoning": "<判断依据>",
  "suggested_search_query": "<若判断为盲区，建议的网络搜索查询词；否则空字符串>",
  "gap_type": "<no_results|irrelevant_results|circular_reasoning|none>"
}}
"""


def is_simple_question(query: str) -> bool:
    """启发式判断：是否为简单问题，可跳过 Planner 直接进 ReAct

    简单问题的特征：
    - 短消息（< 30 字符）
    - 问候/闲聊（你好、谢谢、再见）
    - 概念解释类（什么是...、...是什么意思）
    - 流程咨询（如何...、怎么...）

    跳过 Planner 可节省一次 LLM 调用，将首字延迟降低 30-50%。
    """
    if not query or not query.strip():
        return False
    q = query.strip()
    # 长查询几乎一定需要工具
    if len(q) > 80:
        return False
    # 问候 / 闲聊
    greetings = {"你好", "您好", "hi", "hello", "嗨", "在吗", "在不在", "谢谢", "感谢", "再见", "拜拜"}
    if q.lower() in greetings:
        return True
    # 概念解释 / 流程咨询（典型的"是什么/如何"开头）
    concept_patterns = (
        "什么是", "什么叫", "是什么意思", "解释", "定义",
        "如何", "怎么", "怎样", "请问", "帮我解释", "科普",
        "区别", "差异", "对比", "有什么",
        "lipinski", "recist", "orr", "dcr", "pfs", "os", "admet",
    )
    ql = q.lower()
    if any(p in ql for p in concept_patterns):
        return True
    return False
