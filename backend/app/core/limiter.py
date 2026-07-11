"""slowapi 限流器实例

登录端点强制限流以防止暴力破解，独立于通用 RATE_LIMIT_ENABLED 开关。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


# 登录限流器 — 始终启用，按客户端 IP 计数
limiter = Limiter(
    key_func=get_remote_address,
    enabled=True,
    default_limits=[],  # 不设全局默认限流，仅显式装饰的端点受限
)


def login_limit_string() -> str:
    """登录端点限流配置字符串，如 '5/minute'"""
    return f"{settings.LOGIN_RATE_LIMIT_PER_MINUTE}/minute"


__all__ = ["limiter", "login_limit_string"]
