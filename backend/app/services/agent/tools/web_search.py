"""网络搜索工具组 — 占位实现（阶段 3 完整实现）

工具列表：
- web_search         网络搜索（多引擎聚合：DuckDuckGo + Serper + Brave）
- fetch_web_page     网页抓取（提取正文转换为 Markdown）
"""
import logging
from typing import Any, Dict

from app.core.security import UserRole
from app.services.agent.tools.base import (
    AgentTool,
    ToolContext,
    ToolParameter,
    ToolResult,
)

logger = logging.getLogger(__name__)


class WebSearchTool(AgentTool):
    """网络搜索 — 调用 MultiEngineAggregator

    阶段 3 将完整实现多引擎聚合逻辑。
    """

    name = "web_search"
    description = (
        "调用网络搜索引擎获取最新信息。"
        "支持多引擎聚合（DuckDuckGo + Serper + Brave），按可用性自动切换。"
        "适用于：知识库无结果、需要最新进展、查询最新临床试验/药物审批等场景。"
    )
    parameters = [
        ToolParameter("query", "string", "搜索查询词", required=True),
        ToolParameter(
            "max_results",
            "integer",
            "最大返回结果数（1-20）",
            required=False,
            default=10,
        ),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.search.aggregator import get_aggregator

        query = params["query"]
        max_results = min(max(params.get("max_results", 10), 1), 20)

        try:
            aggregator = get_aggregator()
            results = await aggregator.search(query=query, max_results=max_results)

            return ToolResult.ok(
                data={
                    "query": query,
                    "total": len(results),
                    "results": [r.to_dict() for r in results],
                },
                display={
                    "type": "search_results",
                    "payload": {
                        "query": query,
                        "results": [r.to_dict() for r in results[:max_results]],
                    },
                },
            )
        except Exception as e:
            logger.error(f"web_search 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))


class FetchWebPageTool(AgentTool):
    """网页抓取 — 调用 WebPageFetcher

    阶段 3 将完整实现 trafilatura 正文提取。
    """

    name = "fetch_web_page"
    description = (
        "抓取网页内容并提取主要正文。"
        "支持 HTML/PDF/JSON，自动去除导航、广告等噪声。"
        "返回 Markdown 格式正文，最长 5000 字符。"
    )
    parameters = [
        ToolParameter("url", "string", "网页 URL", required=True),
        ToolParameter(
            "max_chars",
            "integer",
            "最大返回字符数（默认 5000）",
            required=False,
            default=5000,
        ),
    ]
    side_effects = False
    required_role = UserRole.RESEARCHER

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        from app.services.search.fetcher import WebPageFetcher

        url = params["url"]
        max_chars = min(max(params.get("max_chars", 5000), 500), 20000)

        try:
            fetcher = WebPageFetcher()
            result = await fetcher.fetch(url=url, max_chars=max_chars)

            return ToolResult.ok(
                data=result,
                display={
                    "type": "web_page",
                    "payload": {
                        "url": url,
                        "title": result.get("title", ""),
                        "content_preview": (result.get("content") or "")[:500],
                    },
                },
            )
        except Exception as e:
            logger.error(f"fetch_web_page 失败: {e}", exc_info=True)
            return ToolResult.fail(error=str(e))
