"""网页抓取器 — 提取网页正文并转换为 Markdown

特性：
1. 支持 HTML/PDF/JSON 三种响应类型
2. HTML 用 trafilatura 提取正文（lazy import，避免依赖膨胀）
3. PDF 用 pypdf 提取文本
4. 长内容截断到 max_chars
5. 超时控制 + 错误降级

依赖：
- trafilatura（HTML 正文提取，按需安装）
- pypdf（PDF 文本提取，按需安装）
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class WebPageFetcher:
    """网页抓取器

    Usage:
        fetcher = WebPageFetcher()
        result = await fetcher.fetch("https://example.com/article", max_chars=5000)
        # result: {url, title, content, content_type, fetched_at}
    """

    def __init__(self, timeout: Optional[int] = None, use_mock: Optional[bool] = None):
        """初始化

        Args:
            timeout: 超时秒数（默认从 settings.WEB_FETCH_TIMEOUT_SEC 读取）
            use_mock: 是否 Mock 模式（默认从 settings.is_mock 读取）
        """
        from app.core.config import settings
        self.timeout = timeout or settings.WEB_FETCH_TIMEOUT_SEC
        self.use_mock = settings.is_mock if use_mock is None else use_mock

    async def fetch(self, url: str, max_chars: int = 5000) -> Dict[str, Any]:
        """抓取网页并提取正文

        Args:
            url: 网页 URL
            max_chars: 最大返回字符数
        Returns:
            {
                "url": str,
                "title": str,
                "content": str,
                "content_type": "html" | "pdf" | "json" | "text" | "unknown",
                "fetched_at": str (ISO 8601),
                "length": int,
            }
        """
        if not url or not url.strip():
            return self._empty_result(url, reason="empty_url")

        if self.use_mock:
            return self._mock_fetch(url, max_chars)

        try:
            # 限制响应体大小（1MB）
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                max_content_length=1_048_576,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"WebPageFetcher HTTP {resp.status_code}: {url}")
                    return self._empty_result(url, reason=f"http_{resp.status_code}")

                content_type = resp.headers.get("content-type", "").lower()

                # 按类型分发
                if "html" in content_type:
                    return await self._parse_html(url, resp.text, max_chars)
                elif "pdf" in content_type:
                    return await self._parse_pdf(url, resp.content, max_chars)
                elif "json" in content_type:
                    return self._parse_json(url, resp.text, max_chars)
                else:
                    return self._parse_text(url, resp.text, max_chars, content_type)

        except httpx.TimeoutException:
            logger.warning(f"WebPageFetcher 超时: {url}")
            return self._empty_result(url, reason="timeout")
        except httpx.HTTPError as e:
            logger.warning(f"WebPageFetcher HTTP 错误: {url} - {e}")
            return self._empty_result(url, reason="http_error")
        except Exception as e:
            logger.error(f"WebPageFetcher 异常: {url} - {e}", exc_info=True)
            return self._empty_result(url, reason="error")

    async def _parse_html(
        self,
        url: str,
        html: str,
        max_chars: int,
    ) -> Dict[str, Any]:
        """解析 HTML — 用 trafilatura 提取正文"""
        title = ""
        content = ""

        try:
            # trafilatura lazy import
            import trafilatura

            # 提取正文（include_links=True 保留链接，include_tables=True 保留表格）
            extracted = trafilatura.extract(
                html,
                include_links=True,
                include_tables=True,
                include_images=False,
                output_format="markdown",
            )
            if extracted:
                content = extracted

            # 提取元数据
            metadata = trafilatura.extract_metadata(html)
            if metadata:
                title = metadata.title or metadata.sitename or ""

        except ImportError:
            logger.warning("trafilatura 未安装，降级到简单 HTML 提取")
            title, content = self._simple_html_extract(html)
        except Exception as e:
            logger.warning(f"trafilatura 提取失败: {e}")
            title, content = self._simple_html_extract(html)

        if not title:
            title, _ = self._simple_html_extract(html)

        # 截断到 max_chars
        content = content[:max_chars] if content else ""

        return {
            "url": url,
            "title": title.strip()[:200],
            "content": content,
            "content_type": "html",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "length": len(content),
        }

    async def _parse_pdf(
        self,
        url: str,
        content_bytes: bytes,
        max_chars: int,
    ) -> Dict[str, Any]:
        """解析 PDF — 用 pypdf 提取文本"""
        try:
            from io import BytesIO

            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content_bytes))
            text_parts = []
            total_chars = 0

            for page in reader.pages:
                page_text = page.extract_text() or ""
                if total_chars + len(page_text) > max_chars:
                    page_text = page_text[: max_chars - total_chars]
                    text_parts.append(page_text)
                    break
                text_parts.append(page_text)
                total_chars += len(page_text)

            content = "\n".join(text_parts)
            # 提取 PDF 标题（元数据）
            title = ""
            try:
                if reader.metadata and reader.metadata.title:
                    title = str(reader.metadata.title)
            except Exception:
                pass

            return {
                "url": url,
                "title": title.strip()[:200],
                "content": content,
                "content_type": "pdf",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "length": len(content),
            }
        except ImportError:
            logger.warning("pypdf 未安装，无法解析 PDF")
            return self._empty_result(url, reason="pypdf_not_installed")
        except Exception as e:
            logger.warning(f"PDF 解析失败: {e}")
            return self._empty_result(url, reason="pdf_parse_error")

    def _parse_json(
        self,
        url: str,
        text: str,
        max_chars: int,
    ) -> Dict[str, Any]:
        """解析 JSON 响应"""
        try:
            import json
            data = json.loads(text)
            # 简单格式化为字符串
            content = json.dumps(data, ensure_ascii=False, indent=2)
            content = content[:max_chars]
            return {
                "url": url,
                "title": "JSON Response",
                "content": content,
                "content_type": "json",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "length": len(content),
            }
        except Exception as e:
            logger.warning(f"JSON 解析失败: {e}")
            return self._parse_text(url, text, max_chars, "application/json")

    def _parse_text(
        self,
        url: str,
        text: str,
        max_chars: int,
        content_type: str,
    ) -> Dict[str, Any]:
        """解析纯文本响应"""
        content = text[:max_chars] if text else ""
        return {
            "url": url,
            "title": "",
            "content": content,
            "content_type": "text",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "length": len(content),
        }

    def _simple_html_extract(self, html: str) -> tuple:
        """简单 HTML 提取（trafilatura 不可用时降级）"""
        import re

        # 提取 title
        title = ""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = title_match.group(1).strip()

        # 去除 script/style 标签
        cleaned = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<style[^>]*>.*?</style>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        # 去除所有 HTML 标签
        text = re.sub(r"<[^>]+>", "", cleaned)
        # 压缩空白
        text = re.sub(r"\s+", " ", text).strip()

        return title, text

    def _empty_result(self, url: str, reason: str = "") -> Dict[str, Any]:
        """空结果"""
        return {
            "url": url,
            "title": "",
            "content": "",
            "content_type": "unknown",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "length": 0,
            "reason": reason,
        }

    def _mock_fetch(self, url: str, max_chars: int) -> Dict[str, Any]:
        """Mock 模式预置结果"""
        # 根据 URL 域名返回不同的 mock 内容
        if "pubmed" in url.lower() or "ncbi" in url.lower():
            content = (
                "# EGFR Mutations in Non-Small Cell Lung Cancer\n\n"
                "## Abstract\n\n"
                "EGFR mutations are found in 10-15% of NSCLC patients. "
                "Exon 19 deletions and L858R point mutations account for 85% of activating mutations.\n\n"
                "## Key Findings\n\n"
                "1. Osimertinib showed superior PFS (18.9 vs 10.2 months)\n"
                "2. T790M is the most common resistance mechanism\n"
                "3. Liquid biopsy enables non-invasive monitoring\n"
            )
            title = "EGFR Mutations in NSCLC - PubMed"
        elif "wikipedia" in url.lower():
            content = (
                "# EGFR Inhibitor\n\n"
                "Epidermal growth factor receptor (EGFR) inhibitors are a class of "
                "targeted cancer therapies that block the EGFR pathway.\n\n"
                "## Examples\n\n"
                "- First generation: erlotinib, gefitinib\n"
                "- Second generation: afatinib, dacomitinib\n"
                "- Third generation: osimertinib, rociletinib\n"
            )
            title = "EGFR inhibitor - Wikipedia"
        else:
            content = f"# Mock Web Page Content\n\nURL: {url}\n\nThis is a mock response for testing purposes."
            title = f"Mock Page - {url}"

        content = content[:max_chars]
        return {
            "url": url,
            "title": title,
            "content": content,
            "content_type": "html",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "length": len(content),
        }
