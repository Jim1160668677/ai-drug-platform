"""搜索引擎抽象接口 — 多引擎聚合的契约

设计来源：阶段 3 网络搜索集成

支持引擎：
- DuckDuckGo（免费，无 API Key）
- Serper.dev（Google 代理，免费 2500 次/月）
- Brave Search（免费 2000 次/月）

所有引擎实现统一接口，由 MultiEngineAggregator 并发调用并聚合结果。
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果数据类

    Attributes:
        title: 结果标题
        url: 结果 URL（归一化后）
        snippet: 结果摘要
        source: 来源引擎（duckduckgo/serper/brave）
        score: 综合评分（0-1，由 Aggregator 计算）
        published_at: 发布时间（ISO 8601，可选）
        position: 原始排名（从 1 开始）
    """
    title: str
    url: str
    snippet: str
    source: str
    score: Optional[float] = None
    published_at: Optional[str] = None
    position: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_url(url: str) -> str:
    """URL 归一化 — 去除追踪参数

    去除 utm_*、gclid、fbclid、mc_cid、mc_eid 等追踪参数，
    保留语义参数（如文章 ID、查询关键字等）。
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url

        # 追踪参数黑名单
        tracking_prefixes = ("utm_", "fb_", "mc_")
        tracking_keys = {"gclid", "gbraid", "wbraid", "msclkid", "yclid",
                         "fbclid", "igshid", "_hsenc", "_hsmi", "hsCtaTracking"}

        query = parse_qs(parsed.query, keep_blank_values=True)
        cleaned = {
            k: v for k, v in query.items()
            if not any(k.startswith(p) for p in tracking_prefixes)
            and k not in tracking_keys
        }

        new_query = urlencode(cleaned, doseq=True)
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            "",  # 去除 fragment
        ))
    except Exception:
        return url


def get_domain_authority(url: str) -> int:
    """域名权威性评分

    Returns:
        0-10 的整数分（10 分最高）
        - .gov/.edu/.nih.gov/.who.int → 10
        - arxiv.org/pubmed.ncbi.nlm.nih.gov → 8
        - nature.com/science.org/cell.com → 7
        - nejm.org/jamanetwork.com/ascopubs.org → 6
        - wikipedia.org → 5
        - 其他 → 0
    """
    if not url:
        return 0
    try:
        netloc = urlparse(url).netloc.lower()
        # 去除 www. 前缀
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # 顶级权威
        if netloc.endswith(".gov") or netloc.endswith(".edu"):
            return 10
        if "nih.gov" in netloc or "who.int" in netloc:
            return 10
        # 学术论文
        if "arxiv.org" in netloc or "pubmed" in netloc:
            return 8
        if "nature.com" in netloc or "science.org" in netloc or "cell.com" in netloc:
            return 7
        if "nejm.org" in netloc or "jamanetwork" in netloc or "ascopubs" in netloc:
            return 6
        if "wikipedia.org" in netloc:
            return 5
        return 0
    except Exception:
        return 0


class SearchEngine(ABC):
    """搜索引擎抽象基类

    子类需实现：
    - search(query, max_results) -> List[SearchResult]
    - is_available 属性
    - name 类属性
    """

    name: str = "base"

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> List[SearchResult]:
        """执行搜索

        Args:
            query: 搜索查询词
            max_results: 最大返回数
        Returns:
            搜索结果列表
        """
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """引擎是否可用（API Key 已配置且未禁用）"""
        ...
