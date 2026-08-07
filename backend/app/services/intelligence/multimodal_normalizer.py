"""MultimodalNormalizer — 多模态数据标准化组件

设计来源：方向 C（多模态+规则引擎）。
将异构输入（文本/图像/文件/结构化数据）标准化为统一的 MultimodalContent 表示，
支持两种消费路径：
1. textualize：将多模态内容 flatten 为纯文本（供纯文本 LLM / 追溯展示）
2. build_messages：构建原生多模态 LLM 消息（content 为 text/image_url 列表，
   供 agnes-2.0-vision 等视觉模型直接消费）

标准化流程：
- 输入校验 → 类型识别 → 内容归一化（base64/URL）→ 元数据标注 → 输出 MultimodalContent
"""
import base64
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class ModalityType(str, Enum):
    """模态类型枚举"""
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    STRUCTURED = "structured"


@dataclass
class ModalityItem:
    """单个模态条目"""
    type: ModalityType
    content: str               # 文本内容 / 图像 base64(data URI) / 文件路径 / 结构化 JSON 字符串
    mime_type: str = "text/plain"
    name: str = ""             # 文件名 / 图像描述
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "content": self.content,
            "mime_type": self.mime_type,
            "name": self.name,
            "metadata": self.metadata,
        }


@dataclass
class MultimodalContent:
    """标准化多模态内容 — 统一表示"""
    items: List[ModalityItem] = field(default_factory=list)
    primary_text: str = ""     # 主文本（用于路由/摘要）

    @property
    def has_image(self) -> bool:
        return any(i.type == ModalityType.IMAGE for i in self.items)

    @property
    def modalities(self) -> List[str]:
        return list({i.type.value for i in self.items})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [i.to_dict() for i in self.items],
            "primary_text": self.primary_text,
            "has_image": self.has_image,
            "modalities": self.modalities,
        }


# 支持的图像 MIME 类型
_IMAGE_MIME_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".tiff": "image/tiff", ".tif": "image/tiff",
}


class MultimodalNormalizer:
    """多模态数据标准化器

    用法：
        normalizer = MultimodalNormalizer()
        # 从多种输入归一化
        content = await normalizer.normalize(
            text="分析这张病理图像",
            image_paths=["/tmp/pathology.png"],
        )
        # 文本化（供纯文本 LLM）
        text = normalizer.textualize(content)
        # 构建多模态消息（供视觉 LLM）
        messages = normalizer.build_messages(content, system="你是病理分析专家")
    """

    # 最大图像大小（10MB，避免 base64 过大）
    MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024

    def normalize(
        self,
        text: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        image_urls: Optional[List[str]] = None,
        image_base64: Optional[List[str]] = None,
        file_paths: Optional[List[str]] = None,
        structured_data: Optional[Dict[str, Any]] = None,
    ) -> MultimodalContent:
        """归一化多种输入为统一的 MultimodalContent

        Args:
            text: 文本输入
            image_paths: 本地图像文件路径列表
            image_urls: 图像 URL 列表
            image_base64: 图像 base64 编码字符串列表（不含 data: 前缀）
            file_paths: 文件路径列表（非图像）
            structured_data: 结构化数据（JSON 序列化为文本）

        Returns:
            MultimodalContent 标准化内容
        """
        import json as _json

        items: List[ModalityItem] = []
        primary_text = text or ""

        # 文本
        if text:
            items.append(ModalityItem(
                type=ModalityType.TEXT, content=text, mime_type="text/plain", name="user_text",
            ))

        # 本地图像文件
        if image_paths:
            for path in image_paths:
                item = self._normalize_image_path(path)
                if item:
                    items.append(item)

        # 图像 URL
        if image_urls:
            for url in image_urls:
                items.append(ModalityItem(
                    type=ModalityType.IMAGE, content=url, mime_type="image/url",
                    name=f"image_url_{url[-12:]}", metadata={"source": "url"},
                ))

        # base64 图像
        if image_base64:
            for idx, b64 in enumerate(image_base64):
                data_uri = b64 if b64.startswith("data:") else f"data:image/png;base64,{b64}"
                items.append(ModalityItem(
                    type=ModalityType.IMAGE, content=data_uri, mime_type="image/base64",
                    name=f"image_base64_{idx}", metadata={"source": "base64"},
                ))

        # 文件
        if file_paths:
            for path in file_paths:
                item = self._normalize_file_path(path)
                if item:
                    items.append(item)

        # 结构化数据
        if structured_data:
            try:
                json_str = _json.dumps(structured_data, ensure_ascii=False, default=str)
            except Exception:
                json_str = str(structured_data)
            items.append(ModalityItem(
                type=ModalityType.STRUCTURED, content=json_str, mime_type="application/json",
                name="structured_data",
            ))

        if not primary_text and items:
            # 无显式文本时，用第一个条目作为主文本
            primary_text = items[0].content[:200]

        return MultimodalContent(items=items, primary_text=primary_text)

    def normalize_from_request(self, payload: Dict[str, Any]) -> MultimodalContent:
        """从 API 请求体归一化（便捷方法）"""
        return self.normalize(
            text=payload.get("text") or payload.get("message"),
            image_paths=payload.get("image_paths"),
            image_urls=payload.get("image_urls"),
            image_base64=payload.get("image_base64"),
            file_paths=payload.get("file_paths"),
            structured_data=payload.get("structured_data"),
        )

    def _normalize_image_path(self, path: str) -> Optional[ModalityItem]:
        """归一化本地图像文件为 base64 data URI"""
        if not os.path.isfile(path):
            logger.warning("[MultimodalNormalizer] 图像文件不存在: %s", path)
            return None
        size = os.path.getsize(path)
        if size > self.MAX_IMAGE_SIZE_BYTES:
            logger.warning("[MultimodalNormalizer] 图像过大(%d bytes)，跳过: %s", size, path)
            return None
        ext = os.path.splitext(path)[1].lower()
        mime = _IMAGE_MIME_TYPES.get(ext, mimetypes.guess_type(path)[0] or "image/png")
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            data_uri = f"data:{mime};base64,{b64}"
            return ModalityItem(
                type=ModalityType.IMAGE, content=data_uri, mime_type=mime,
                name=os.path.basename(path), metadata={"source": "file", "size": size},
            )
        except Exception as e:
            logger.warning("[MultimodalNormalizer] 读取图像失败 %s: %s", path, e)
            return None

    def _normalize_file_path(self, path: str) -> Optional[ModalityItem]:
        """归一化非图像文件（仅记录元数据，内容为路径）"""
        if not os.path.isfile(path):
            logger.warning("[MultimodalNormalizer] 文件不存在: %s", path)
            return None
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        size = os.path.getsize(path)
        return ModalityItem(
            type=ModalityType.FILE, content=path, mime_type=mime,
            name=os.path.basename(path), metadata={"size": size},
        )

    # ========== 文本化（供纯文本 LLM） ==========

    def textualize(self, content: MultimodalContent, max_length: int = 8000) -> str:
        """将多模态内容 flatten 为纯文本

        图像/文件用占位符描述（实际内容由 VisionLLMClient 处理）。
        """
        parts: List[str] = []
        for item in content.items:
            if item.type == ModalityType.TEXT:
                parts.append(item.content)
            elif item.type == ModalityType.IMAGE:
                parts.append(f"[图像: {item.name}（{item.mime_type}）]")
            elif item.type == ModalityType.FILE:
                parts.append(f"[文件: {item.name}（{item.mime_type}, {item.metadata.get('size', '?')} bytes）]")
            elif item.type == ModalityType.STRUCTURED:
                parts.append(f"[结构化数据]\n{item.content[:2000]}")
        text = "\n\n".join(parts)
        return text[:max_length]

    # ========== 构建多模态 LLM 消息 ==========

    def build_messages(
        self,
        content: MultimodalContent,
        system: Optional[str] = None,
        user_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """构建原生多模态 LLM 消息（OpenAI 兼容格式）

        输出格式：
            [{"role": "system", "content": "..."},
             {"role": "user", "content": [
                {"type": "text", "text": "..."},
                {"type": "image_url", "image_url": {"url": "data:..."}},
             ]}]

        供 agnes-2.0-vision 等视觉模型直接消费。
        """
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})

        # 构建多模态 user content
        user_content: List[Dict[str, Any]] = []
        if user_prompt:
            user_content.append({"type": "text", "text": user_prompt})

        for item in content.items:
            if item.type == ModalityType.TEXT:
                if item.content != user_prompt:
                    user_content.append({"type": "text", "text": item.content})
            elif item.type == ModalityType.IMAGE:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": item.content, "detail": "auto"},
                })
            elif item.type == ModalityType.STRUCTURED:
                user_content.append({"type": "text", "text": f"[结构化数据]\n{item.content[:2000]}"})
            elif item.type == ModalityType.FILE:
                user_content.append({
                    "type": "text",
                    "text": f"[附件: {item.name}（{item.mime_type}）]",
                })

        if not user_content:
            user_content.append({"type": "text", "text": content.primary_text or "（空内容）"})

        messages.append({"role": "user", "content": user_content})
        return messages


__all__ = [
    "MultimodalNormalizer",
    "MultimodalContent",
    "ModalityItem",
    "ModalityType",
]
