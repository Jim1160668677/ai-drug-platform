"""VisionLLMClient — 视觉内容解析客户端

设计来源：方向 C（多模态+规则引擎）。
封装 agnes-2.0-vision 视觉大模型，提供病理图像、蛋白结构图、分子结构图、
实验图表等视觉内容的语义解析能力。

核心能力：
1. analyze_image：通用图像分析 — 输入图像 + 提示词，返回结构化描述
2. analyze_pathology_image：病理图像专用 — 识别组织形态、细胞特征、染色模式
3. analyze_protein_structure：蛋白结构图 — 识别二级结构、结合口袋、配体位置
4. analyze_molecule_structure：分子结构图 — 识别官能团、骨架、立体化学
5. analyze_chart：实验图表 — 提取数据趋势、峰值、统计显著性

与 MultimodalNormalizer 协作：normalizer 构建多模态消息，本客户端调用视觉 LLM。
"""
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class VisionLLMClient:
    """视觉 LLM 客户端 — 基于 agnes-2.0-vision

    用法：
        client = VisionLLMClient(llm_client)
        result = await client.analyze_image(
            image_data_uri="data:image/png;base64,...",
            prompt="识别这张病理图像中的肿瘤区域",
        )
    """

    def __init__(
        self,
        llm_client: Any = None,
        model: Optional[str] = None,
        normalizer: Optional[Any] = None,
    ):
        """初始化视觉 LLM 客户端

        Args:
            llm_client: 底层 LLM 客户端（RealLLMClient / FallbackLLMClient），需支持 chat(messages, model)
            model: 视觉模型名（默认 settings.LLM_MODEL_VISION = agnes-2.0-vision）
            normalizer: MultimodalNormalizer 实例（可选，未传入时按需创建）
        """
        self.llm_client = llm_client
        self.model = model or settings.LLM_MODEL_VISION
        self._normalizer = normalizer

    @property
    def normalizer(self):
        if self._normalizer is None:
            from app.services.intelligence.multimodal_normalizer import MultimodalNormalizer
            self._normalizer = MultimodalNormalizer()
        return self._normalizer

    # ========== 通用图像分析 ==========

    async def analyze_image(
        self,
        image_data_uri: str,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """通用图像分析

        Args:
            image_data_uri: 图像数据 URI（data:image/...;base64,...）或 URL
            prompt: 分析提示词
            system: 系统提示词（可选）
            temperature: 温度（视觉分析建议低温，默认 0.3）
            max_tokens: 最大输出 token

        Returns:
            {description, model, usage, cost_usd, duration_sec}
        """
        start = time.time()
        default_system = "你是专业的生物医学图像分析专家。请基于视觉内容给出准确、结构化的分析。"
        messages = self.normalizer.build_messages(
            content=self.normalizer.normalize(image_base64=[image_data_uri] if image_data_uri.startswith("data:") else [],
                                               image_urls=[image_data_uri] if not image_data_uri.startswith("data:") else [],
                                               text=prompt),
            system=system or default_system,
        )

        description, usage = await self._call_vision(messages, temperature, max_tokens)
        duration_sec = round(time.time() - start, 3)
        cost_usd = self._estimate_cost(usage)

        return {
            "description": description,
            "model": self.model,
            "usage": usage,
            "cost_usd": cost_usd,
            "duration_sec": duration_sec,
        }

    # ========== 专用图像分析场景 ==========

    async def analyze_pathology_image(
        self, image_data_uri: str, focus: str = "肿瘤区域识别",
    ) -> Dict[str, Any]:
        """病理图像分析 — 识别组织形态、细胞特征、染色模式"""
        system = (
            "你是病理学专家。请分析病理切片图像，重点关注：\n"
            "1. 组织类型与形态学特征\n2. 细胞形态（大小/核质比/异型性）\n"
            "3. 染色模式（HE/IHC/特殊染色）\n4. 病变区域定位与范围\n"
            "5. 鉴别诊断要点\n请输出结构化结论。"
        )
        prompt = f"分析这张病理图像，重点关注：{focus}。"
        return await self.analyze_image(image_data_uri, prompt, system=system)

    async def analyze_protein_structure(
        self, image_data_uri: str, focus: str = "结合口袋识别",
    ) -> Dict[str, Any]:
        """蛋白结构图分析 — 识别二级结构、结合口袋、配体位置"""
        system = (
            "你是结构生物学专家。请分析蛋白结构图（ cartoon / surface / stick 表示），重点关注：\n"
            "1. 二级结构分布（α螺旋/β折叠/loop）\n2. 结构域组织\n"
            "3. 结合口袋位置与特征\n4. 配体位置与相互作用\n5. 别构位点可能性\n"
            "请输出结构化结论。"
        )
        prompt = f"分析这张蛋白结构图，重点关注：{focus}。"
        return await self.analyze_image(image_data_uri, prompt, system=system)

    async def analyze_molecule_structure(
        self, image_data_uri: str, focus: str = "官能团识别",
    ) -> Dict[str, Any]:
        """分子结构图分析 — 识别官能团、骨架、立体化学"""
        system = (
            "你是药物化学专家。请分析分子结构图，重点关注：\n"
            "1. 骨架类型（杂环/脂环/芳环）\n2. 关键官能团\n"
            "3. 立体中心与构型\n4. 氢键供体/受体\n5. 类药性相关特征\n"
            "请输出结构化结论。"
        )
        prompt = f"分析这张分子结构图，重点关注：{focus}。"
        return await self.analyze_image(image_data_uri, prompt, system=system)

    async def analyze_chart(
        self, image_data_uri: str, focus: str = "数据趋势提取",
    ) -> Dict[str, Any]:
        """实验图表分析 — 提取数据趋势、峰值、统计显著性"""
        system = (
            "你是数据分析专家。请分析实验图表（柱状图/折线图/散点图/热图等），重点关注：\n"
            "1. 图表类型与坐标轴含义\n2. 数据趋势与分布\n3. 峰值/谷值/异常点\n"
            "4. 统计显著性标注\n5. 关键数值读数\n请输出结构化结论。"
        )
        prompt = f"分析这张实验图表，重点关注：{focus}。"
        return await self.analyze_image(image_data_uri, prompt, system=system)

    # ========== 批量图像分析 ==========

    async def analyze_multi_images(
        self, image_data_uris: List[str], prompt: str, system: Optional[str] = None,
    ) -> Dict[str, Any]:
        """批量多图分析（单次调用多张图）"""
        start = time.time()
        default_system = "你是生物医学图像分析专家。请综合分析提供的多张图像，找出关联与差异。"
        content = self.normalizer.normalize(
            image_base64=[u for u in image_data_uris if u.startswith("data:")],
            image_urls=[u for u in image_data_uris if not u.startswith("data:")],
            text=prompt,
        )
        messages = self.normalizer.build_messages(content, system=system or default_system)
        description, usage = await self._call_vision(messages, 0.3, 2500)
        return {
            "description": description,
            "image_count": len(image_data_uris),
            "model": self.model,
            "usage": usage,
            "cost_usd": self._estimate_cost(usage),
            "duration_sec": round(time.time() - start, 3),
        }

    # ========== 私有方法 ==========

    async def _call_vision(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> tuple:
        """调用视觉 LLM，返回 (content, usage)"""
        if self.llm_client is None:
            logger.warning("[VisionLLMClient] LLM 客户端未注入，返回空描述")
            return "（视觉 LLM 未配置）", {}
        try:
            response = await self.llm_client.chat(
                messages, model=self.model, temperature=temperature, max_tokens=max_tokens,
            )
            if isinstance(response, dict):
                return response.get("content", ""), response.get("usage", {}) or {}
            return str(response), {}
        except Exception as e:
            logger.error("[VisionLLMClient] 视觉 LLM 调用失败: %s", e)
            return f"视觉分析失败：{str(e)}", {}

    def _estimate_cost(self, usage: Dict[str, Any]) -> float:
        """估算成本（视觉模型定价略高）"""
        if not usage:
            return 0.0
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        # 视觉模型粗略定价：输入 $1/1M，输出 $3/1M
        return round((prompt_tokens * 1.0 + completion_tokens * 3.0) / 1_000_000, 6)


__all__ = ["VisionLLMClient"]
