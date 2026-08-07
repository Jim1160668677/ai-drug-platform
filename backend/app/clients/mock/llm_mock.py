"""Mock LLM 客户端 — 模拟大模型对话"""
import asyncio
import json
import re
import time
from typing import List, Optional

from app.clients.base import LLMClient


# 预置的问答知识库（基于 EGFR/B7H3/FAP 等靶点）
QA_KNOWLEDGE = {
    "EGFR": {
        "answer": (
            "EGFR（表皮生长因子受体）是跨膜酪氨酸激酶受体，在非小细胞肺癌（NSCLC）中常发生激活突变。\n\n"
            "## 关键变异\n"
            "- **L858R**：外显子21点突变，最常见激活突变之一\n"
            "- **T790M**：外显子20突变，一代 TKI 耐药的主要机制\n"
            "- **Exon 19 deletion**：外显子19缺失，对 TKI 敏感\n\n"
            "## 已获批靶向药\n"
            "1. **一代**：Gefitinib（吉非替尼）、Erlotinib（厄洛替尼）\n"
            "2. **二代**：Afatinib（阿法替尼）\n"
            "3. **三代**：Osimertinib（奥希替尼）— 克服 T790M 耐药\n\n"
            "## 证据分级\n"
            "- 证据等级 I：已获批靶向药\n"
            "- 推荐方案：Osimertinib 80mg qd（针对 T790M 阳性）"
        ),
        "references": [
            {"title": "FLAURA Trial", "source": "NEJM 2018", "url": "https://example.com/flaura"},
            {"title": "EGFR Mutation Guidelines", "source": "NCCN 2024", "url": "https://example.com/nccn"},
        ],
        "code": (
            "# EGFR 突变分析代码示例\n"
            "import pandas as pd\n"
            "from scipy import stats\n\n"
            "# 加载突变数据\n"
            "mutations = pd.read_csv('egfr_mutations.csv')\n"
            "# 统计突变频率\n"
            "freq = mutations['variant'].value_counts(normalize=True)\n"
            "print(freq.head(10))"
        ),
    },
    "B7H3": {
        "answer": (
            "B7-H3（CD276）是 B7 家族免疫检查点分子，在多种实体瘤中高表达。\n\n"
            "## 临床意义\n"
            "- 在 NSCLC、前列腺癌、胰腺癌中过表达\n"
            "- 与免疫抑制和不良预后相关\n"
            "- 当前无获批靶向药，多项临床试验进行中\n\n"
            "## 在研疗法\n"
            "- 抗体药物偶联物（ADC）\n"
            "- CAR-T 细胞治疗\n"
            "- 双特异性抗体\n\n"
            "## Sid 案例关联\n"
            "Sid 团队通过单细胞分析发现 B7H3 是潜在靶点，体现了 AI 模式发现新靶点的能力。"
        ),
        "references": [
            {"title": "B7-H3 in Cancer Immunotherapy", "source": "Nature Reviews 2023", "url": "https://example.com/b7h3"},
        ],
    },
    "FAP": {
        "answer": (
            "FAP（成纤维激活蛋白）是肿瘤基质中癌症相关成纤维细胞（CAF）的标志物。\n\n"
            "## 临床意义\n"
            "- 在肿瘤基质中高表达，促进肿瘤生长和转移\n"
            "- 作为基质靶向治疗的候选\n"
            "- FAP 靶向 CAR-T 和放射性核素疗法在研\n\n"
            "## Sid 案例关联\n"
            "FAP 是 Sid 个性化治疗中的关键靶点之一，通过单细胞测序发现。"
        ),
        "references": [
            {"title": "FAP-targeted therapy", "source": "Cancer Cell 2023", "url": "https://example.com/fap"},
        ],
    },
}


class MockLLMClient(LLMClient):
    """Mock LLM 客户端 — 根据关键词匹配返回预置答案

    当 system prompt 要求 JSON 输出时（如 Co-Scientist 多智能体调用），
    自动返回符合 schema 的 JSON 响应，模拟真实 LLM 遵守 system prompt 的行为。
    """

    async def chat(self, messages: List[dict], model: str = None, **kwargs) -> dict:
        await asyncio.sleep(0.5)  # 模拟网络延迟

        system_msg = ""
        user_msg = ""
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            elif m["role"] == "user":
                user_msg = m["content"]
        # 若有多轮 user，取最后一条
        for m in reversed(messages):
            if m["role"] == "user":
                user_msg = m["content"]
                break

        # 检测 system prompt 是否要求 JSON 输出（Co-Scientist agent 调用）
        json_response = self._maybe_generate_json_response(system_msg, user_msg)
        if json_response is not None:
            return {
                "content": json_response,
                "model": model or "mock-gpt-4o",
                "usage": {"prompt_tokens": len(user_msg) // 4, "completion_tokens": len(json_response) // 4},
                "references": [],
                "code": None,
            }

        # 关键词匹配（QA 知识库）
        answer = None
        references = []
        code = None
        for key, data in QA_KNOWLEDGE.items():
            if key.lower() in user_msg.lower() or key in user_msg:
                answer = data["answer"]
                references = data.get("references", [])
                code = data.get("code")
                break

        if not answer:
            answer = (
                f"已收到您的问题：「{user_msg}」\n\n"
                "这是 Mock 模式的预置响应。配置 OPENAI_API_KEY 并设置 USE_MOCK=false 后，"
                "将调用真实大模型获得深度分析。\n\n"
                "## 提示\n"
                "尝试提问包含关键词：EGFR、B7H3、FAP，可获得预置的专业解答。"
            )

        return {
            "content": answer,
            "model": model or "mock-gpt-4o",
            "usage": {"prompt_tokens": len(user_msg) // 4, "completion_tokens": len(answer) // 4},
            "references": references,
            "code": code,
        }

    def _maybe_generate_json_response(self, system_msg: str, user_msg: str) -> Optional[str]:
        """检测 system prompt 是否要求 JSON 输出，返回合规 JSON 或 None

        真实 LLM 会遵守 system prompt 中的 JSON 输出要求。Mock 模式下需模拟此行为，
        否则 Co-Scientist 多智能体的 generation/reflection/ranking 等阶段会因解析失败而中断。

        检测策略：
        1. system prompt 包含 "输出 JSON" / "输出JSON" 关键词
        2. 根据 system prompt 中的角色关键词识别 agent 类型
        3. 返回符合该 agent schema 的 mock JSON
        """
        if not system_msg:
            return None

        system_lower = system_msg.lower()
        if "输出 json" not in system_lower and "输出json" not in system_lower:
            return None

        # 从 user_msg 中提取研究目标关键词（用于生成相关性更高的假设）
        goal_keyword = self._extract_goal_keyword(user_msg)

        # 根据 system prompt 关键词识别 agent 类型
        if "生成" in system_msg and "假设" in system_msg:
            # Generation Agent
            return json.dumps({
                "hypotheses": [
                    {
                        "name": f"{goal_keyword}靶向治疗假设{i}",
                        "description": f"针对{goal_keyword}相关通路的小分子抑制剂可阻断肿瘤进展",
                        "mechanism": f"通过抑制{goal_keyword}信号传导，诱导肿瘤细胞凋亡并抑制增殖",
                        "novelty": 7 + i, "plausibility": 6 + i, "testability": 8, "safety": 9,
                        "key_evidence": [f"{goal_keyword}在肿瘤中高表达", "临床前模型有效"],
                    }
                    for i in range(1, 4)
                ]
            }, ensure_ascii=False)

        if "审查" in system_msg or "批判" in system_msg:
            # Reflection Agent
            return json.dumps({
                "flaws": [
                    {"description": "证据主要来源于体外实验，缺乏体内验证", "severity": 5, "category": "evidence", "suggestion": "增加动物模型验证"},
                    {"description": "机制通路描述不够完整", "severity": 4, "category": "mechanism", "suggestion": "补充下游信号通路"},
                ],
                "strengths": ["假设有明确的分子靶点", "可测试性强"],
                "overall_assessment": "假设有一定科学依据，但需更多实验证据支持",
                "improvement_priority": ["补充体内实验数据", "完善机制描述"],
            }, ensure_ascii=False)

        if "成对比较" in system_msg or ("比较" in system_msg and "判定" in system_msg):
            # Ranking Agent
            return json.dumps({
                "winner": "A", "confidence": 0.75, "reasoning": "A 假设机制更清晰，证据更充分",
                "winning_criteria": ["plausibility", "testability"],
                "a_advantages": ["机制描述更完整", "可测试性更高"],
                "b_advantages": ["新颖性略高"],
            }, ensure_ascii=False)

        if "相似度" in system_msg:
            # Proximity Agent
            return json.dumps({
                "semantic_similarity": 0.3, "mechanism_overlap": 0.2,
                "recommendation": "keep_separate",
                "shared_concepts": ["肿瘤治疗"],
                "unique_to_a": ["靶点A"], "unique_to_b": ["靶点B"],
                "merge_rationale": "",
            }, ensure_ascii=False)

        if "进化" in system_msg and "优化" in system_msg:
            # Evolution Agent
            return json.dumps({
                "name": f"{goal_keyword}增强假设", "description": "增强后的假设描述，补充了体内实验验证路径",
                "mechanism": "增强后的机制说明，包含下游信号通路和反馈调节",
                "change_log": "补充体内实验验证方案，完善机制通路描述",
                "parent_ids": [], "novelty": 8, "plausibility": 7, "testability": 9, "safety": 8,
                "evolution_strategy": "enhancement",
            }, ensure_ascii=False)

        if "元评审" in system_msg or "综合评审" in system_msg:
            # Meta-Review Agent
            return json.dumps({
                "top_hypotheses": [
                    {"id": "1", "rank": 1, "reason": "机制最清晰，证据最充分"},
                    {"id": "2", "rank": 2, "reason": "新颖性高但需更多验证"},
                    {"id": "3", "rank": 3, "reason": "可测试性强但机制较简单"},
                ],
                "quality_summary": "整体假设质量良好，覆盖多种机制路径",
                "diversity_assessment": "假设具有较好的多样性",
                "evolution_effectiveness": "进化提升了假设的可测试性",
                "recommended_experiments": ["体外细胞实验", "动物模型验证", "生物标志物分析"],
                "research_gaps": ["缺乏临床数据支持"],
                "final_recommendation": "优先验证排名1的假设",
                "confidence_level": 0.8,
            }, ensure_ascii=False)

        if "辩护" in system_msg:
            # Debate advocate
            return json.dumps({"argument": f"该假设基于{goal_keyword}的已知生物学功能，有充分的文献支持", "evidence": ["文献证据1", "实验数据1"]}, ensure_ascii=False)

        if "质疑" in system_msg:
            # Debate critic
            return json.dumps({"argument": "假设缺乏体内实验验证，机制通路尚不完整", "counter_evidence": ["缺乏动物模型数据"]}, ensure_ascii=False)

        if "裁判" in system_msg and "共识" in system_msg:
            # Debate judge
            return json.dumps({"consensus_score": 0.85, "agreed_points": ["靶点有效性"], "disagreed_points": ["机制完整性"], "assessment": "双方在核心靶点上达成共识"}, ensure_ascii=False)

        if "综合修正" in system_msg:
            # Debate synthesizer
            return json.dumps({"name": f"{goal_keyword}辩论修正假设", "description": "综合正反方意见后的修正假设", "mechanism": "修正后的机制说明", "consensus_score": 0.85}, ensure_ascii=False)

        # 通用 JSON 要求：返回空对象（保证可解析）
        return json.dumps({}, ensure_ascii=False)

    def _extract_goal_keyword(self, user_msg: str) -> str:
        """从 user message 中提取研究目标关键词"""
        for key in QA_KNOWLEDGE:
            if key.lower() in user_msg.lower() or key in user_msg:
                return key
        # 提取「」或 "" 内的内容
        m = re.search(r'[「「"](.+?)[」」"]', user_msg)
        if m:
            return m.group(1)[:20]
        # 提取 "研究目标:" 后的内容
        m = re.search(r'研究目标[:：]\s*(.+)', user_msg)
        if m:
            return m.group(1).strip()[:20]
        return "肿瘤"

    async def embed(self, text: str) -> List[float]:
        """模拟向量化 — 返回固定维度的伪向量"""
        await asyncio.sleep(0.1)
        import hashlib
        import struct
        h = hashlib.sha256(text.encode()).digest()
        # 生成 1536 维伪向量
        vec = []
        for i in range(0, len(h) * 30, 4):
            chunk = h[i % len(h):i % len(h) + 4].ljust(4, b'\x00')
            vec.append(struct.unpack('f', chunk)[0])
        return vec[:1536]
