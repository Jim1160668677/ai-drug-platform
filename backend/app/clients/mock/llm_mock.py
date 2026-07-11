"""Mock LLM 客户端 — 模拟大模型对话"""
import asyncio
import time
from typing import List

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
    """Mock LLM 客户端 — 根据关键词匹配返回预置答案"""

    async def chat(self, messages: List[dict], model: str = None, **kwargs) -> dict:
        await asyncio.sleep(0.5)  # 模拟网络延迟

        user_msg = ""
        for m in reversed(messages):
            if m["role"] == "user":
                user_msg = m["content"]
                break

        # 关键词匹配
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
