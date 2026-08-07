"""Real LLM 客户端 — 支持 OpenAI 兼容协议的动态配置

通过 httpx 直接调用 Chat Completions API，避免对 litellm 的硬依赖。
支持两种初始化方式：
1. 从数据库激活的 LLMConfig 读取（推荐 — 由管理后台动态切换）
2. 从 settings 读取默认配置（OPENAI_API_KEY + LLM_MODEL_DEEP）

支持流式响应（stream_chat）— 让 Agent 能逐 token 推送给前端，
显著降低首字延迟（从 3-8s 降到 200-500ms）。
"""
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

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
        # 优先 AGNES_API_KEY（系统默认 Agnes），回退 OPENAI_API_KEY；数据库 LLMConfig 由调用方注入 api_key 覆盖
        self.base_url = (base_url or settings.LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or settings.AGNES_API_KEY or settings.OPENAI_API_KEY
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
            # 处理 content 为列表的情况（多模态或分段响应）
            if isinstance(response_text, list):
                parts = []
                for part in response_text:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        parts.append(part)
                response_text = "\n".join(parts)
            # 某些 API 返回 content 为嵌套结构
            if isinstance(response_text, dict):
                response_text = response_text.get("text", "") or str(response_text)
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

    async def stream_chat(
        self,
        messages: List[dict],
        model: str = None,
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式调用 Chat Completions API — 逐 token yield

        让 Agent 引擎能在 LLM 生成时就推送 token 到前端，无需等待整段响应。
        显著降低首字延迟（从 3-8s 降到 200-500ms）。

        Args:
            messages: [{"role": ..., "content": ...}]
            model: 模型名（None 使用 default_model）
            **kwargs: 透传给 chat_completions（如 temperature、max_tokens）

        Yields:
            每个 chunk 的 dict：
            - {"type": "token", "content": "..."}     — 增量 token
            - {"type": "done", "content": "...", "usage": {...}, "model": "..."} — 完整响应结束
            - {"type": "error", "content": "..."}     — 错误信息
        """
        use_model = model or self.default_model
        temperature = kwargs.pop("temperature", self.default_temperature)
        max_tokens = kwargs.pop("max_tokens", self.default_max_tokens)

        url = self._build_chat_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        body: Dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,  # 开启流式
        }
        body.update(kwargs)

        full_content: List[str] = []
        start = time.time()
        # 流式读取需要更长的超时：用 connect+read 各自超时，避免整体超时打断
        timeout = httpx.Timeout(
            connect=10.0,
            read=self.timeout_sec,
            write=10.0,
            pool=10.0,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", url, json=body, headers=headers
                ) as resp:
                    if resp.status_code != 200:
                        error_text = ""
                        async for chunk in resp.aiter_text():
                            error_text += chunk
                            if len(error_text) > 500:
                                break
                        logger.error(
                            f"LLM stream 返回 HTTP {resp.status_code}: {error_text[:500]}"
                        )
                        yield {
                            "type": "error",
                            "content": f"[LLM HTTP {resp.status_code}] {error_text[:500]}",
                        }
                        return

                    # 解析 SSE：每行 "data: {...}"，以空行分隔
                    buffer = ""
                    async for chunk in resp.aiter_text():
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            if not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                # 流结束
                                yield {
                                    "type": "done",
                                    "content": "".join(full_content),
                                    "usage": {},
                                    "model": use_model,
                                    "duration_sec": round(time.time() - start, 3),
                                }
                                return
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            # 提取增量 content
                            choices = data.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {}) or {}
                            token = delta.get("content") or ""
                            if token:
                                full_content.append(token)
                                yield {"type": "token", "content": token}

                    # 流正常结束但未收到 [DONE]
                    yield {
                        "type": "done",
                        "content": "".join(full_content),
                        "usage": {},
                        "model": use_model,
                        "duration_sec": round(time.time() - start, 3),
                    }

        except httpx.TimeoutException as e:
            logger.error(f"LLM stream 超时 ({self.timeout_sec}s): {e}")
            yield {
                "type": "error",
                "content": f"[LLM stream 超时] {type(e).__name__}: {e}",
            }
        except Exception as e:
            logger.error(f"LLM stream 失败: {type(e).__name__}: {e}")
            yield {
                "type": "error",
                "content": f"[LLM stream 失败] {type(e).__name__}: {e}",
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
