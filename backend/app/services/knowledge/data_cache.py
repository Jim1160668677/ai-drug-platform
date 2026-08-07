"""本地缓存层 — 外部数据源查询结果缓存

设计来源：避免每次解读都打外部 API；缓存 5 天 TTL（变异信息变化慢）
表结构：external_loci_cache {source, rsid, payload_json, fetched_at, expires_at}
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import String, Text, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base, TimestampMixin, UUIDMixin

logger = logging.getLogger(__name__)


class ExternalLociCache(Base, UUIDMixin, TimestampMixin):
    """外部数据源本地缓存表"""

    __tablename__ = "external_loci_cache"

    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="数据源 gwas_catalog/clinvar/omim/ncbi")
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="缓存键（query 哈希）")
    query_text: Mapped[Optional[str]] = mapped_column(Text, comment="原始查询文本")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, comment="缓存载荷")
    ttl_days: Mapped[int] = mapped_column(Integer, default=5, nullable=False, comment="缓存有效期天数")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="过期时间")

    def __repr__(self) -> str:
        return f"<ExternalLociCache {self.source}:{self.cache_key} expires={self.expires_at}>"


def make_cache_key(source: str, query: str) -> str:
    """生成缓存键 — SHA256(source + query) 前 32 字符"""
    raw = f"{source}|{query.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


async def get_cached(db: AsyncSession, source: str, query: str) -> Optional[dict]:
    """查询缓存

    Returns:
        缓存的 payload，未命中或已过期返回 None
    """
    cache_key = make_cache_key(source, query)
    from sqlalchemy import select
    result = await db.execute(
        select(ExternalLociCache)
        .where(ExternalLociCache.source == source)
        .where(ExternalLociCache.cache_key == cache_key)
        .limit(1)
    )
    cached = result.scalar_one_or_none()
    if not cached:
        return None
    # 检查过期
    if cached.expires_at < datetime.now(timezone.utc):
        await db.delete(cached)
        return None
    return cached.payload


async def set_cached(
    db: AsyncSession,
    source: str,
    query: str,
    payload: dict,
    ttl_days: int = 5,
) -> None:
    """写入缓存（覆盖同 source + cache_key 的旧记录）"""
    cache_key = make_cache_key(source, query)
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

    from sqlalchemy import select, delete
    # 删除旧记录
    await db.execute(
        delete(ExternalLociCache)
        .where(ExternalLociCache.source == source)
        .where(ExternalLociCache.cache_key == cache_key)
    )
    # 插入新记录
    cached = ExternalLociCache(
        source=source,
        cache_key=cache_key,
        query_text=query[:500] if query else None,
        payload=payload,
        ttl_days=ttl_days,
        expires_at=expires_at,
    )
    db.add(cached)
    await db.flush()


async def get_cache_stats(db: AsyncSession) -> dict:
    """缓存统计"""
    from sqlalchemy import select, func
    total = (await db.execute(select(func.count()).select_from(ExternalLociCache))).scalar() or 0
    by_source = (await db.execute(
        select(ExternalLociCache.source, func.count())
        .group_by(ExternalLociCache.source)
    )).all()
    return {
        "total": total,
        "by_source": {row[0]: row[1] for row in by_source},
    }


async def invalidate_cache(db: AsyncSession, source: Optional[str] = None) -> int:
    """清空缓存（可指定 source）"""
    from sqlalchemy import delete
    stmt = delete(ExternalLociCache)
    if source:
        stmt = stmt.where(ExternalLociCache.source == source)
    result = await db.execute(stmt)
    return result.rowcount or 0


__all__ = [
    "ExternalLociCache",
    "make_cache_key",
    "get_cached",
    "set_cached",
    "get_cache_stats",
    "invalidate_cache",
]
