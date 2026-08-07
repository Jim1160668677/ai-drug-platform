"""用户级 LLM 路由器 — BYO Key 模式

设计来源：参照 Trae 论坛方案，用户可在个人中心绑定自有 API Key
选择不同 LLM（豆包/DeepSeek/OpenAI 等），用于个人基因组解读。

设计原则：
1. 用户激活配置优先；调用失败自动降级到系统激活配置（Agnes）
2. 复用现有 LLMRouter 的护栏/缓存/成本追踪能力
3. SSRF 防护：复用 _is_ssrf_risky_url 检查 base_url
4. 不污染系统级 LLM 配置；用户配置仅作用于用户自己的请求
"""
import logging
import time
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.encryption import decrypt, encrypt
from app.models.user_llm_config import UserLLMConfig
from app.services.llm.router import LLMRouter
from app.services.llm.cost_tracker import get_cost_tracker
from app.services.llm.guardrail import get_guardrail
from app.services.llm.cache import get_cache

logger = logging.getLogger(__name__)


def _is_ssrf_risky_url(url: str) -> bool:
    """检查 URL 是否存在 SSRF 风险（与 llm_config 端点一致）"""
    import ipaddress
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return True
        host = host.lower()
        if host in ("localhost",):
            return True
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return True
        except ValueError:
            pass
        return False
    except Exception:
        return True


def _mask_key(key: str) -> str:
    """API key 脱敏：保留前6位和后4位"""
    if not key or len(key) < 12:
        return "***"
    return f"{key[:6]}...{key[-4:]}"


def _build_real_llm_client_from_user(user_config: UserLLMConfig):
    """根据用户 LLM 配置构造 RealLLMClient"""
    from app.clients.real.llm_real import RealLLMClient
    return RealLLMClient(
        base_url=user_config.base_url,
        api_key=decrypt(user_config.api_key),
        upstream_protocol="chat_completions",
        default_model=user_config.model_name,
        temperature=user_config.temperature,
        max_tokens=user_config.max_tokens,
        timeout_sec=user_config.timeout_sec,
    )


def _build_system_llm_client():
    """回退到系统激活配置（或 settings 默认）"""
    from app.clients.real.llm_real import RealLLMClient
    return RealLLMClient()


class UserLLMRouter:
    """用户级 LLM 路由器

    优先使用用户激活配置；调用失败降级到系统激活配置。
    复用 LLMRouter 的护栏/缓存/成本追踪能力。

    Usage:
        user_router = await UserLLMRouter.create(db, current_user, user_llm_config_id)
        result = await user_router.complete(prompt, tier="fast_screen", system=...)
    """

    def __init__(
        self,
        user_llm_client,
        system_llm_client,
        user_config: Optional[UserLLMConfig],
        cost_tracker=None,
        guardrail=None,
        cache=None,
    ):
        self.user_llm_client = user_llm_client
        self.system_llm_client = system_llm_client
        self.user_config = user_config
        self.cost_tracker = cost_tracker or get_cost_tracker()
        self.guardrail = guardrail or get_guardrail()
        self.cache = cache or get_cache()

    @classmethod
    async def create(
        cls,
        db,
        user,
        user_llm_config_id: Optional[str] = None,
    ):
        """构造 UserLLMRouter

        Args:
            db: 数据库会话
            user: 当前用户
            user_llm_config_id: 指定的用户 LLM 配置 ID（不传则用激活的）

        Returns:
            UserLLMRouter 实例
        """
        from sqlalchemy import select
        from app.models.user_llm_config import UserLLMConfig

        user_config = None
        if user_llm_config_id:
            # 统一转为 UUID，兼容 str / UUID 两种入参
            # Uuid(as_uuid=True) 列直接传 str 会导致 'str' object has no attribute 'hex'
            if isinstance(user_llm_config_id, str):
                try:
                    from uuid import UUID
                    user_llm_config_id = UUID(user_llm_config_id)
                except (ValueError, AttributeError):
                    from app.core.exceptions import NotFoundError
                    raise NotFoundError(
                        f"用户 LLM 配置 ID 格式无效: {user_llm_config_id}"
                    )
            result = await db.execute(
                select(UserLLMConfig)
                .where(UserLLMConfig.id == user_llm_config_id)
                .where(UserLLMConfig.owner_id == user.id)
                .limit(1)
            )
            user_config = result.scalar_one_or_none()
            if not user_config:
                from app.core.exceptions import NotFoundError
                raise NotFoundError(f"用户 LLM 配置不存在: {user_llm_config_id}")
        else:
            # 取用户激活配置
            result = await db.execute(
                select(UserLLMConfig)
                .where(UserLLMConfig.owner_id == user.id)
                .where(UserLLMConfig.is_active == True)  # noqa: E712
                .limit(1)
            )
            user_config = result.scalar_one_or_none()

        # 构造客户端
        user_llm_client = None
        if user_config:
            try:
                user_llm_client = _build_real_llm_client_from_user(user_config)
            except Exception as e:
                logger.warning(f"用户 LLM 客户端构造失败，降级到系统配置: {e}")
                user_config = None

        # 系统级回退
        if settings.is_mock:
            from app.clients.mock.llm_mock import MockLLMClient
            system_llm_client = MockLLMClient()
        else:
            try:
                system_llm_client = _build_system_llm_client()
            except Exception as e:
                logger.error(f"系统 LLM 客户端构造失败: {e}")
                system_llm_client = None

        return cls(
            user_llm_client=user_llm_client,
            system_llm_client=system_llm_client,
            user_config=user_config,
        )

    @property
    def active_model_name(self) -> str:
        """当前使用的模型名（供上层记录）"""
        if self.user_config:
            return self.user_config.model_name
        return settings.LLM_MODEL_FAST or "mock"

    @property
    def active_provider(self) -> str:
        """当前使用的 provider"""
        if self.user_config:
            return self.user_config.provider
        return "system_default"

    async def complete(
        self,
        prompt: str,
        tier: str = "fast_screen",
        system: Optional[str] = None,
        bypass_guardrail: bool = False,
    ) -> Dict[str, Any]:
        """路由主入口

        Args:
            prompt: 用户提示
            tier: fast_screen / deep_insight（用户级不分 tier，仅记录）
            system: 系统提示词
            bypass_guardrail: 是否跳过护栏（仅内部调用）

        Returns:
            {content, model, usage, cost_usd, guardrail, references, code, provider}
        """
        start = time.time()

        # 1. 输入护栏
        guardrail_result = None
        if not bypass_guardrail:
            guardrail_result = self.guardrail.check_input(prompt)
            if guardrail_result.blocked:
                logger.warning(f"UserLLMRouter 输入被护栏拦截: {guardrail_result.reasons}")
                return {
                    "content": f"输入被安全护栏拦截：{', '.join(guardrail_result.reasons)}",
                    "model": self.active_model_name,
                    "usage": {},
                    "cost_usd": 0.0,
                    "provider": self.active_provider,
                    "blocked": True,
                }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # 2. 优先用用户配置
        response = None
        used_provider = "system_default"
        used_model = self.active_model_name

        if self.user_llm_client is not None:
            try:
                response = await self.user_llm_client.chat(messages, model=self.user_config.model_name)
                used_provider = self.user_config.provider
                used_model = self.user_config.model_name
            except Exception as e:
                logger.warning(f"用户 LLM 调用失败，降级到系统配置: {e}")
                response = None

        # 3. 降级到系统
        if response is None:
            if self.system_llm_client is None:
                return {
                    "content": "LLM 客户端未就绪（用户与系统均不可用）",
                    "model": "none",
                    "usage": {},
                    "cost_usd": 0.0,
                    "provider": "none",
                    "error": "no_llm_client",
                }
            try:
                sys_model = settings.LLM_MODEL_FAST if tier == "fast_screen" else settings.LLM_MODEL_DEEP
                response = await self.system_llm_client.chat(messages, model=sys_model)
                used_provider = "system_default"
                used_model = sys_model
            except Exception as e:
                logger.error(f"系统 LLM 调用也失败: {e}")
                return {
                    "content": f"LLM 调用失败: {e}",
                    "model": used_model,
                    "usage": {},
                    "cost_usd": 0.0,
                    "provider": used_provider,
                    "error": str(e),
                }

        # 4. 输出护栏
        content = response.get("content", "")
        if not bypass_guardrail:
            output_check = self.guardrail.check_output(content)
            if output_check.blocked:
                logger.warning(f"UserLLMRouter 输出被护栏拦截: {output_check.reasons}")
                return {
                    "content": f"输出被安全护栏拦截：{', '.join(output_check.reasons)}",
                    "model": used_model,
                    "usage": response.get("usage", {}),
                    "cost_usd": 0.0,
                    "provider": used_provider,
                    "blocked": True,
                }

        # 5. 成本追踪
        usage = response.get("usage", {}) or {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost_usd = 0.0
        if self.cost_tracker.can_spend(0.01):
            cost_usd = self.cost_tracker.record(used_model, prompt_tokens, completion_tokens)

        duration_sec = round(time.time() - start, 3)

        return {
            "content": content,
            "model": used_model,
            "usage": usage,
            "cost_usd": cost_usd,
            "provider": used_provider,
            "references": response.get("references", []),
            "code": response.get("code"),
            "duration_sec": duration_sec,
        }


async def test_user_llm_connectivity(user_config: UserLLMConfig, message: str = "ping") -> dict:
    """测试用户 LLM 配置连通性

    复用 SSRF 防护逻辑，返回结构化结果。
    """
    start = time.time()
    api_key = decrypt(user_config.api_key)

    # SSRF 防护
    if _is_ssrf_risky_url(user_config.base_url):
        return {
            "success": False,
            "message": "拒绝测试：base_url 指向内网/回环/保留地址（SSRF 防护）",
        }

    url = user_config.base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": user_config.model_name,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": 50,
        "temperature": 0.1,
    }

    try:
        async with httpx.AsyncClient(timeout=user_config.timeout_sec) as client:
            resp = await client.post(url, json=body, headers=headers)

        duration = round(time.time() - start, 3)

        if resp.status_code != 200:
            status_hint = {
                401: "认证失败（检查 API Key）",
                403: "授权拒绝",
                404: "端点不存在（检查 base_url）",
                429: "请求过多（限流）",
                500: "上游服务内部错误",
                502: "网关错误",
                503: "服务不可用",
            }.get(resp.status_code, "上游服务错误")
            return {
                "success": False,
                "message": f"HTTP {resp.status_code}: {status_hint}",
                "duration_sec": duration,
            }

        data = resp.json()
        response_text = ""
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            response_text = choice.get("message", {}).get("content", "") or choice.get("text", "")
        model_used = data.get("model", user_config.model_name)

        return {
            "success": True,
            "message": f"连接成功（{duration}s）",
            "model": model_used,
            "response_text": response_text[:500],
            "duration_sec": duration,
        }

    except httpx.TimeoutException:
        return {
            "success": False,
            "message": f"连接超时（{user_config.timeout_sec}s）",
            "duration_sec": round(time.time() - start, 3),
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "连接失败（检查 base_url 与网络）",
            "duration_sec": round(time.time() - start, 3),
        }
    except Exception as e:
        logger.error(f"用户 LLM 测试未预期异常: {e}", exc_info=True)
        return {
            "success": False,
            "message": "测试失败（内部错误，详见日志）",
            "duration_sec": round(time.time() - start, 3),
        }


__all__ = [
    "UserLLMRouter",
    "test_user_llm_connectivity",
    "_mask_key",
    "_is_ssrf_risky_url",
]
