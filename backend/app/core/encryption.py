"""敏感数据加密工具 — 使用 Fernet 对称加密

安全策略：
- 生产环境（APP_ENV 不是 development/testing）：无密钥时 encrypt() 抛异常，拒绝明文存储
- 开发/测试环境：无密钥时记录警告并返回明文（向后兼容）
- decrypt() 始终容错：无密钥或解密失败时返回原文（避免阻断业务）
"""
import logging
import os

from app.core.config import settings

logger = logging.getLogger(__name__)

_fernet = None


def _is_production() -> bool:
    """判断是否为生产环境"""
    return os.environ.get("APP_ENV", "development") in ("production", "staging", "prod")


def _get_fernet():
    """懒加载 Fernet 实例

    无密钥时返回 None（开发环境明文模式）。
    """
    global _fernet
    if _fernet is not None:
        return _fernet

    key = settings.API_KEY_ENCRYPTION_KEY
    if not key:
        return None

    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception as e:
        logger.error(f"Fernet 初始化失败: {e}")
        if _is_production():
            raise RuntimeError(f"Fernet 加密初始化失败，生产环境不可降级: {e}") from e
        return None


def encrypt(plaintext: str) -> str:
    """加密字符串

    生产环境无密钥时抛 RuntimeError，拒绝明文存储。
    开发环境无密钥时记录警告并返回明文（向后兼容）。
    密文以 "enc:" 前缀标识，便于 decrypt 识别。
    """
    if not plaintext:
        return plaintext

    # 已经加密的不再重复加密
    if plaintext.startswith("enc:"):
        return plaintext

    f = _get_fernet()
    if f is None:
        if _is_production():
            raise RuntimeError(
                "生产环境未配置 API_KEY_ENCRYPTION_KEY，拒绝明文存储敏感数据"
            )
        logger.warning("未配置加密密钥，敏感数据将以明文存储（仅开发环境）")
        return plaintext

    try:
        token = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"enc:{token}"
    except Exception as e:
        logger.error(f"加密失败: {e}")
        if _is_production():
            raise RuntimeError(f"加密失败，生产环境不可降级: {e}") from e
        return plaintext


def decrypt(ciphertext: str) -> str:
    """解密字符串

    容错策略：无 "enc:" 前缀或无密钥时返回原文（向后兼容明文存储）。
    解密失败时记录错误并返回原文，避免阻断业务（如密钥轮换期间）。
    """
    if not ciphertext:
        return ciphertext

    if not ciphertext.startswith("enc:"):
        return ciphertext

    f = _get_fernet()
    if f is None:
        logger.warning("数据已加密但未配置密钥，返回密文（无法解密）")
        return ciphertext

    try:
        token = ciphertext[4:]  # 去掉 "enc:" 前缀
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except Exception as e:
        logger.error(f"解密失败: {e}")
        return ciphertext


__all__ = ["encrypt", "decrypt"]
