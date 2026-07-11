"""Real LLM 客户端 — 支持 OpenAI 兼容协议的动态配置

通过 httpx 直接调用 Chat Completions API，避免对 litellm 的硬依赖。
支持两种初始化方式：
1. 从数据库激活的 LLMConfig 读取（推荐 — 由管理后台动态切换）
2. 从 settings 读取默认配置（OPENAI_API_KEY + LLM_MODEL_DEEP）
"""
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.clients.base import LLMClient
from app.core.config import settings

logger = logging.getLogger(__name__)


class RealLLMClient(LLMClient):
    """真实大模型客户端 — 支持动态配置

    通过构造参数接收数据库 LLMConfig 字段；若未提供则回退到 settings 默认值。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        upstream_protocol: str = "chat_completions",
        default_model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        timeout_sec: int = 60,
    ) -> None:
        # 回退到 settings 默认值（兼容旧调用方式）
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.upstream_protocol = upstream_protocol or "chat_completions"
        self.default_model = default_model or settings.LLM_MODEL_DEEP
        self.default_temperature = temperature
        self.default_max_tokens = max_tokens
        self.timeout_sec = timeout_sec

        if not self.api_key:
            raise RuntimeError(
                "LLM API key 未配置。请在管理后台配置 LLM，或在 .env 设置 OPENAI_API_KEY"
            )

    def _build_chat_url(self) -> str:
        """根据协议构造 chat 端点 URL"""
        if self.upstream_protocol == "chat_completions":
            return f"{self.base_url}/chat/completions"
        if self.upstream_protocol == "completions":
            return f"{self.base_url}/completions"
        # 兼容 anthropic 协议（暂未实现完整支持）
        if self.upstream_protocol == "anthropic":
            return f"{self.base_url}/messages"
        return f"{self.base_url}/chat/completions"

    async def chat(self, messages: List[dict], model: str = None, **kwargs) -> dict:
        """调用 Chat Completions API"""
        use_model = model or self.default_model
        temperature = kwargs.pop("temperature", self.default_temperature)
        max_tokens = kwargs.pop("max_tokens", self.default_max_tokens)

        url = self._build_chat_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body: Dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # 透传其他 OpenAI 兼容参数（如 top_p、stream）
        body.update(kwargs)

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as e:
            logger.error(f"LLM 调用超时 ({self.timeout_sec}s): {e}")
            return {
                "content": f"[LLM 调用超时] {type(e).__name__}: {e}",
                "model": use_model,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "duration_sec": round(time.time() - start, 3),
                "references": [],
                "code": None,
            }
        except Exception as e:
            logger.error(f"LLM 调用失败: {type(e).__name__}: {e}")
            return {
                "content": f"[LLM 调用失败] {type(e).__name__}: {e}",
                "model": use_model,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "duration_sec": round(time.time() - start, 3),
                "references": [],
                "code": None,
            }

        duration = round(time.time() - start, 3)

        if resp.status_code != 200:
            error_text = resp.text[:500] if resp.text else ""
            logger.error(f"LLM 返回 HTTP {resp.status_code}: {error_text}")
            return {
                "content": f"[LLM HTTP {resp.status_code}] {error_text}",
                "model": use_model,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "duration_sec": duration,
                "references": [],
                "code": None,
            }

        data = resp.json()
        response_text = ""
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            response_text = (
                choice.get("message", {}).get("content", "")
                or choice.get("text", "")
                or ""
            )
        usage = data.get("usage", {}) or {}

        return {
            "content": response_text,
            "model": data.get("model", use_model),
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "duration_sec": duration,
            "references": [],
            "code": None,
        }

    async def embed(self, text: str) -> List[float]:
        """调用 Embeddings API（OpenAI 兼容）"""
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "text-embedding-3-small",
            "input": text,
        }
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            resp = await client.post(url, json=body, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f"Embedding 失败 HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        return data["data"][0]["embedding"]
