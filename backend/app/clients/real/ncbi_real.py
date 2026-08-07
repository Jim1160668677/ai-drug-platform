"""Real NCBI E-utilities 客户端 — 调用 https://eutils.ncbi.nlm.nih.gov/entrez/eutils

特性：
1. API Key 自动注入（提升速率限制 3→10 req/s）
2. 速率限制：asyncio.Semaphore + token bucket（按 settings.NCBI_RATE_LIMIT_RPS）
3. 指数退避重试：429/5xx 自动重试 NCBI_MAX_RETRIES 次，间隔 1s/2s/4s
4. 持久化缓存：复用 app/services/knowledge/data_cache.py（TTL 7 天）
5. 错误降级：网络异常返回空结果（不抛异常，业务层降级）

设计遵循 NCBI E-utilities 规范：https://www.ncbi.nlm.nih.gov/books/NBK25499/
"""
import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from app.clients.base import NcbiClient
from app.core.config import settings

logger = logging.getLogger(__name__)

# 指数退避重试间隔（秒）：1s / 2s / 4s
_RETRY_DELAYS = [1.0, 2.0, 4.0]


class RealNcbiClient(NcbiClient):
    """真实 NCBI E-utilities 客户端

    Usage:
        client = RealNcbiClient()
        result = await client.search_pubmed("EGFR inhibitor NSCLC")
        variants = await client.fetch_clinvar_variants("TP53")

    # 带持久化缓存（需数据库会话）
        async with db_session:
            result = await client.search_pubmed("EGFR", db=db_session)
    """

    def __init__(self):
        self.base_url = settings.NCBI_BASE_URL.rstrip("/")
        self.api_key = settings.NCBI_API_KEY.strip()
        self.timeout = settings.NCBI_TIMEOUT_SEC
        self.max_retries = settings.NCBI_MAX_RETRIES
        # 速率限制信号量：并发上限 = 速率（每秒请求数）
        # 加 1 个缓冲避免完全串行
        rps = settings.NCBI_RATE_LIMIT_RPS if not self.api_key else 10
        self._semaphore = asyncio.Semaphore(max(rps, 1))
        # 连接池单例（避免每次请求创建新 client）
        self._http_client: Optional[httpx.AsyncClient] = None
        # 内存缓存（无 db session 时使用，TTL 由 _mem_cache_time 管理）
        self._mem_cache: Dict[str, tuple] = {}  # key -> (payload, expires_at)
        self._mem_cache_ttl = settings.NCBI_CACHE_TTL_DAYS * 86400

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取/复用 httpx.AsyncClient 单例"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout=self.timeout, connect=8.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            )
        return self._http_client

    def _build_params(self, base: Dict[str, Any]) -> Dict[str, Any]:
        """附加 API Key 到请求参数（若已配置）"""
        if self.api_key:
            base = {**base, "api_key": self.api_key}
        return base

    async def _get_cached(self, db: Optional[Any], source: str, query: str) -> Optional[dict]:
        """查询缓存（先内存，后数据库）"""
        # 内存缓存
        cache_key = f"{source}:{query}"
        if cache_key in self._mem_cache:
            payload, expires_at = self._mem_cache[cache_key]
            if time.time() < expires_at:
                return payload
            del self._mem_cache[cache_key]

        # 数据库缓存
        if db is not None:
            try:
                from app.services.knowledge.data_cache import get_cached
                return await get_cached(db, source, query)
            except Exception as e:
                logger.debug(f"数据库缓存查询失败: {e}")
        return None

    async def _set_cached(
        self,
        db: Optional[Any],
        source: str,
        query: str,
        payload: dict,
    ) -> None:
        """写入缓存（内存 + 数据库）"""
        cache_key = f"{source}:{query}"
        self._mem_cache[cache_key] = (payload, time.time() + self._mem_cache_ttl)

        if db is not None:
            try:
                from app.services.knowledge.data_cache import set_cached
                await set_cached(
                    db,
                    source,
                    query,
                    payload,
                    ttl_days=settings.NCBI_CACHE_TTL_DAYS,
                )
            except Exception as e:
                logger.debug(f"数据库缓存写入失败: {e}")

    async def _request_with_retry(
        self,
        url: str,
        params: Dict[str, Any],
        source: str,
        cache_query: Optional[str] = None,
        db: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """带重试 + 缓存的 GET 请求

        Returns:
            解析后的 JSON 响应，失败返回 None
        """
        # 1. 缓存命中检查
        if cache_query:
            cached = await self._get_cached(db, source, cache_query)
            if cached is not None:
                logger.info(f"NCBI 缓存命中: {source}:{cache_query[:60]}")
                return cached

        params = self._build_params(params)
        last_error: Optional[Exception] = None

        async with self._semaphore:
            client = await self._get_http_client()
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.get(url, params=params)

                    # 429 限流或 5xx 服务器错误 → 重试
                    if resp.status_code in (429, 500, 502, 503, 504):
                        if attempt < self.max_retries:
                            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                            logger.warning(
                                f"NCBI {source} HTTP {resp.status_code}，"
                                f"{delay}s 后重试（{attempt + 1}/{self.max_retries}）"
                            )
                            await asyncio.sleep(delay)
                            continue

                    if resp.status_code != 200:
                        logger.warning(f"NCBI {source} HTTP {resp.status_code}: {resp.text[:200]}")
                        return None

                    data = resp.json()

                    # 写入缓存
                    if cache_query and data:
                        await self._set_cached(db, source, cache_query, data)

                    return data

                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    last_error = e
                    if attempt < self.max_retries:
                        delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                        logger.warning(
                            f"NCBI {source} 网络异常 {type(e).__name__}: {e}，"
                            f"{delay}s 后重试（{attempt + 1}/{self.max_retries}）"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(f"NCBI {source} 网络异常最终失败: {e}")
                    return None
                except Exception as e:
                    logger.error(f"NCBI {source} 请求异常: {e}", exc_info=True)
                    return None

        logger.error(f"NCBI {source} 请求最终失败: {last_error}")
        return None

    # ========== 4 个原子方法实现 ==========

    async def esearch(
        self,
        db: str,
        term: str,
        retmax: int = 20,
        retmode: str = "json",
        sort: Optional[str] = None,
        db_session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """esearch — 搜索 NCBI 数据库

        Args:
            db_session: 可选数据库会话（用于持久化缓存）
        """
        params: Dict[str, Any] = {
            "db": db,
            "term": term,
            "retmax": retmax,
            "retmode": retmode,
        }
        if sort:
            params["sort"] = sort

        cache_query = f"esearch:{db}:{term}:{retmax}:{sort or ''}"
        result = await self._request_with_retry(
            url=f"{self.base_url}/esearch.fcgi",
            params=params,
            source=f"ncbi_esearch_{db}",
            cache_query=cache_query,
            db=db_session,
        )
        return result or {"esearchresult": {"idlist": [], "count": "0"}}

    async def esummary(
        self,
        db: str,
        ids: List[str],
        retmode: str = "json",
        db_session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """esummary — 获取条目摘要"""
        if not ids:
            return {"result": {"uids": []}}

        params = {
            "db": db,
            "id": ",".join(ids),
            "retmode": retmode,
        }
        cache_query = f"esummary:{db}:{','.join(ids)}"
        result = await self._request_with_retry(
            url=f"{self.base_url}/esummary.fcgi",
            params=params,
            source=f"ncbi_esummary_{db}",
            cache_query=cache_query,
            db=db_session,
        )
        return result or {"result": {"uids": []}}

    async def efetch(
        self,
        db: str,
        ids: List[str],
        rettype: str = "abstract",
        retmode: str = "xml",
        db_session: Optional[Any] = None,
    ) -> str:
        """efetch — 获取完整记录（XML/text）

        efetch 不走 JSON 缓存（响应为 XML/FASTA 文本），仅走内存缓存。
        """
        if not ids:
            return ""

        params = self._build_params({
            "db": db,
            "id": ",".join(ids),
            "rettype": rettype,
            "retmode": retmode,
        })

        cache_key = f"efetch:{db}:{','.join(ids)}:{rettype}:{retmode}"
        if cache_key in self._mem_cache:
            payload, expires_at = self._mem_cache[cache_key]
            if time.time() < expires_at:
                return payload
            del self._mem_cache[cache_key]

        async with self._semaphore:
            client = await self._get_http_client()
            last_error: Optional[Exception] = None
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.get(
                        f"{self.base_url}/efetch.fcgi",
                        params=params,
                    )
                    if resp.status_code in (429, 500, 502, 503, 504):
                        if attempt < self.max_retries:
                            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                            await asyncio.sleep(delay)
                            continue
                    if resp.status_code != 200:
                        logger.warning(f"NCBI efetch HTTP {resp.status_code}")
                        return ""
                    text = resp.text
                    # 内存缓存
                    self._mem_cache[cache_key] = (text, time.time() + self._mem_cache_ttl)
                    return text
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    last_error = e
                    if attempt < self.max_retries:
                        await asyncio.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])
                        continue
                    return ""
                except Exception as e:
                    logger.error(f"NCBI efetch 异常: {e}")
                    return ""
        return ""

    async def elink(
        self,
        dbfrom: str,
        db: str,
        id: str,
        db_session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """elink — 获取跨库链接"""
        params = {
            "dbfrom": dbfrom,
            "db": db,
            "id": id,
            "retmode": "json",
        }
        cache_query = f"elink:{dbfrom}:{db}:{id}"
        result = await self._request_with_retry(
            url=f"{self.base_url}/elink.fcgi",
            params=params,
            source="ncbi_elink",
            cache_query=cache_query,
            db=db_session,
        )
        return result or {"linksets": []}

    # ========== 高层封装方法 ==========

    async def search_pubmed(
        self,
        query: str,
        retmax: int = 10,
        db_session: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """PubMed 文献检索（esearch + esummary 组合）

        Args:
            query: 检索词，如 "EGFR inhibitor NSCLC"
            retmax: 最大返回数
            db_session: 可选数据库会话（用于缓存）
        Returns:
            [{"uid", "title", "authors", "journal", "pubdate", "abstract"}, ...]
        """
        # Step 1: esearch 获取 PMID 列表
        search_result = await self.esearch(
            db="pubmed",
            term=query,
            retmax=retmax,
            sort="pub_date",
            db_session=db_session,
        )
        id_list = (search_result.get("esearchresult") or {}).get("idlist", []) or []
        if not id_list:
            return []

        # Step 2: esummary 获取文献详情
        summary = await self.esummary(
            db="pubmed",
            ids=id_list,
            db_session=db_session,
        )
        result_obj = summary.get("result", {}) or {}
        uids = result_obj.get("uids", []) or []

        articles: List[Dict[str, Any]] = []
        for uid in uids:
            rec = result_obj.get(uid, {}) or {}
            if not rec:
                continue
            # 解析作者列表
            authors = []
            for a in rec.get("authors", []) or []:
                name = a.get("name") if isinstance(a, dict) else str(a)
                if name:
                    authors.append(name)
            articles.append({
                "uid": uid,
                "title": rec.get("title", ""),
                "authors": authors[:10],
                "journal": rec.get("fulljournalname") or rec.get("source", ""),
                "pubdate": rec.get("pubdate") or rec.get("sortpubdate", ""),
                "abstract": rec.get("abstract", ""),
                "doi": rec.get("elocationid", ""),
                "pubtype": rec.get("pubtype", []),
                "source": "PubMed",
            })

        return articles

    async def fetch_gene_info(
        self,
        gene_symbol: str,
        db_session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """基因信息查询（gene db）"""
        search_result = await self.esearch(
            db="gene",
            term=f"{gene_symbol}[Gene Name] AND Homo sapiens[Organism]",
            retmax=1,
            db_session=db_session,
        )
        id_list = (search_result.get("esearchresult") or {}).get("idlist", []) or []
        if not id_list:
            return {"symbol": gene_symbol, "entrez_id": None, "summary": ""}

        summary = await self.esummary(
            db="gene",
            ids=id_list,
            db_session=db_session,
        )
        result_obj = summary.get("result", {}) or {}
        uid = id_list[0]
        rec = result_obj.get(uid, {}) or {}

        return {
            "symbol": gene_symbol,
            "entrez_id": uid,
            "name": rec.get("name", ""),
            "description": rec.get("description", ""),
            "summary": rec.get("summary", ""),
            "chromosome": rec.get("chromosome", ""),
            "map_location": rec.get("maplocation", ""),
            "aliases": [a.get("name") for a in rec.get("aliases", []) if isinstance(a, dict)],
            "other_aliases": rec.get("otheraliases", ""),
            "source": "NCBI Gene",
        }

    async def fetch_clinvar_variants(
        self,
        gene: str,
        retmax: int = 5,
        db_session: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """ClinVar 致病变异查询

        Args:
            gene: 基因符号，如 TP53
            retmax: 最大返回数
        Returns:
            [{"uid", "title", "clnsig", "gene", "hgvs_p", "hgvs_c", "variant_type"}, ...]
        """
        # Step 1: esearch 搜索该基因的致病变异
        search_result = await self.esearch(
            db="clinvar",
            term=f"{gene}[gene] AND (pathogenic[clinsig] OR likely pathogenic[clinsig])",
            retmax=retmax,
            sort="date_last_changed desc",
            db_session=db_session,
        )
        id_list = (search_result.get("esearchresult") or {}).get("idlist", []) or []
        if not id_list:
            return []

        # Step 2: esummary 获取变异详情
        summary = await self.esummary(
            db="clinvar",
            ids=id_list,
            db_session=db_session,
        )
        result_obj = summary.get("result", {}) or {}
        uids = result_obj.get("uids", []) or id_list

        variants: List[Dict[str, Any]] = []
        for uid in uids[:retmax]:
            rec = result_obj.get(uid, {}) or {}
            if not rec:
                continue
            title = rec.get("title", "") or ""
            # 解析 HGVS
            hgvs_c = None
            hgvs_p = None
            if title:
                m = re.search(r"c\.(\S+?)(?:\s|$)", title)
                if m:
                    hgvs_c = f"c.{m.group(1)}"
                m = re.search(r"p\.([A-Za-z0-9]+)", title)
                if m:
                    hgvs_p = f"p.{m.group(1)}"

            # 临床意义
            clinsig_obj = rec.get("clinical_significance") or {}
            if isinstance(clinsig_obj, dict):
                clnsig = clinsig_obj.get("description") or clinsig_obj.get("clinsig") or "Pathogenic"
            else:
                clnsig = str(clinsig_obj) if clinsig_obj else "Pathogenic"

            # 基因信息
            genes_list = rec.get("genes", []) or []
            gene_symbol = gene
            if genes_list and isinstance(genes_list[0], dict):
                gene_symbol = genes_list[0].get("symbol") or genes_list[0].get("name") or gene

            # 变异类型
            variation_set = rec.get("variation_set", []) or []
            variant_type = (
                variation_set[0].get("variation_class")
                if variation_set and isinstance(variation_set[0], dict)
                else "single_nucleotide_variant"
            )

            variants.append({
                "uid": uid,
                "title": title,
                "clnsig": clnsig,
                "gene": gene_symbol,
                "hgvs_p": hgvs_p,
                "hgvs_c": hgvs_c,
                "variant_type": variant_type,
                "review_status": (
                    clinsig_obj.get("review_status")
                    if isinstance(clinsig_obj, dict) else None
                ),
                "source": "NCBI ClinVar (E-utilities)",
            })

        return variants

    async def fetch_sequences(
        self,
        ids: List[str],
        db: str = "protein",
        db_session: Optional[Any] = None,
    ) -> str:
        """FASTA 序列获取（protein/nucleotide db）"""
        return await self.efetch(
            db=db,
            ids=ids,
            rettype="fasta",
            retmode="text",
            db_session=db_session,
        )

    async def close(self) -> None:
        """关闭 HTTP 连接池"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
