"""隐私保护层 — 已迁移至 app.services.privacy.privacy_layer

本文件保留为 re-export，便于已有导入路径（如
`from app.services.knowledge.privacy_layer import PrivacyLayer`）继续工作。
新代码请直接 `from app.services.privacy import PrivacyLayer`。
"""
from app.services.privacy.privacy_layer import *  # noqa: F401,F403
from app.services.privacy.privacy_layer import PrivacyLayer  # noqa: F401

# 显式导出 PrivacyLayer（覆盖 * 的行为）
__all__ = ["PrivacyLayer"]
