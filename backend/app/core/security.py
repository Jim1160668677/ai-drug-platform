"""安全模块 — JWT 认证 + RBAC 权限控制（5角色）"""
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


class UserRole(str, Enum):
    """系统角色 — 5 级权限模型"""

    FOUNDER = "founder"            # 创始人/患者：全部数据+模型干预+紧急决策
    CHIEF_RESEARCHER = "chief"     # 首席研究员：全部分析结果+部分原始数据
    RESEARCHER = "researcher"      # 研究员：分配项目内的数据
    DOCTOR = "doctor"              # 医生：clinical 数据+靶点报告只读
    DATA_ENGINEER = "engineer"     # 数据工程师：系统日志+数据质量指标


# 角色权限矩阵：定义每个角色可访问的子系统
ROLE_PERMISSIONS = {
    UserRole.FOUNDER: ["data:read", "data:write", "analysis:read", "analysis:write",
                       "model:intervene", "decision:emergency", "audit:read", "admin:all"],
    UserRole.CHIEF_RESEARCHER: ["data:read", "analysis:read", "analysis:write",
                                "model:config", "decision:advise", "audit:read"],
    UserRole.RESEARCHER: ["data:read:assigned", "analysis:run:standard", "annotation:write"],
    UserRole.DOCTOR: ["data:read:clinical", "target:read", "clinical:advise"],
    UserRole.DATA_ENGINEER: ["system:logs", "quality:read", "system:config"],
}


pwd_context = None  # 兼容引用，passlib 已移除


def hash_password(password: str) -> str:
    """密码哈希（bcrypt，最大 72 字节）"""
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, role: UserRole, extra: Optional[dict] = None) -> str:
    """创建 JWT access token（短效，默认 30 分钟）

    携带 type=access 声明，用于与 refresh token 区分。
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role.value,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str, role: UserRole, extra: Optional[dict] = None) -> str:
    """创建 JWT refresh token（长效，默认 7 天）

    携带 type=refresh 声明，仅用于 /auth/refresh 端点换取新 access token。
    不携带业务权限，不可直接用于 API 访问。
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role.value,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT，失败抛出 JWTError"""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def has_permission(role: UserRole, permission: str) -> bool:
    """检查角色是否拥有某权限"""
    return permission in ROLE_PERMISSIONS.get(role, [])


__all__ = ["UserRole", "ROLE_PERMISSIONS", "hash_password", "verify_password",
           "create_access_token", "create_refresh_token", "decode_token", "has_permission"]
