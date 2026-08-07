"""OMIM API 客户端

端点：https://api.omim.org/api
需要 API Key，从环境变量 OMIM_API_KEY 读取。
按关键词搜索基因-疾病关联条目。
"""
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from app.services.knowledge.data_cache import get_cached, set_cached

logger = logging.getLogger(__name__)

OMIM_BASE = "https://api.omim.org/api"
DEFAULT_TIMEOUT = 30


class OmimClient:
    """OMIM API 客户端

    使用方法：
        client = OmimClient()
        entries = await client.search_by_keyword(db, "allergic rhinitis")
    """

    def __init__(self, base_url: str = OMIM_BASE, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = os.environ.get("OMIM_API_KEY", "")

    def is_configured(self) -> bool:
        """是否配置了 API Key"""
        return bool(self.api_key)

    async def search_by_keyword(
        self,
        db: Optional[Any],
        keyword: str,
    ) -> List[Dict]:
        """按关键词搜索 OMIM 条目

        Args:
            db: 数据库会话（用于缓存）
            keyword: 搜索关键词（如 "allergic rhinitis"）

        Returns:
            条目列表，每条含 mim_number/title/gene/phenotype 等
        """
        if not self.is_configured():
            logger.warning("OMIM API Key 未配置（环境变量 OMIM_API_KEY），跳过 OMIM 查询")
            return []

        # 1. 缓存查询
        if db is not None:
            cached = await get_cached(db, "omim", keyword)
            if cached is not None:
                logger.info(f"OMIM 缓存命中: {keyword}")
                return cached

        # 2. 调 API
        try:
            entries = await self._search(keyword)
        except Exception as e:
            logger.error(f"OMIM 查询失败: {e}")
            return []

        # 3. 写入缓存（30 天 TTL — OMIM 信息变化慢）
        if db is not None and entries:
            await set_cached(db, "omim", keyword, entries, ttl_days=30)

        return entries

    async def _search(self, keyword: str) -> List[Dict]:
        """调用 OMIM /api/entry/search"""
        url = f"{self.base_url}/entry/search"
        params = {
            "apiKey": self.api_key,
            "search": keyword,
            "searchIn": "titles",
            "start": 0,
            "limit": 20,
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params=params)
        if resp.status_code != 200:
            logger.warning(f"OMIM HTTP {resp.status_code}: {resp.text[:200]}")
            return []
        data = resp.json()
        omim_list = data.get("omim", {}).get("entryList", []) or []
        return [self._parse_entry(e) for e in omim_list]

    def _parse_entry(self, entry_wrapper: Dict) -> Dict:
        """解析 OMIM entry"""
        entry = entry_wrapper.get("entry", {})
        mim_number = entry.get("mimNumber", "")
        titles = entry.get("titles", {}) or {}

        # 提取基因列表
        gene_symbols = []
        for item in entry.get("phenotypeMapList", []) or []:
            gene_map = item.get("phenotypeMap", {}) or {}
            gene = gene_map.get("geneSymbols", "")
            if gene:
                gene_symbols.extend([g.strip() for g in gene.split(",")])

        return {
            "mim_number": str(mim_number),
            "title": titles.get("preferredTitle", ""),
            "alternative_titles": titles.get("alternativeTitles", ""),
            "gene_symbols": list(set(gene_symbols)),
            "evidence_source": "omim",
            "evidence_level": "II",
        }


__all__ = ["OmimClient", "OMIM_BASE"]
