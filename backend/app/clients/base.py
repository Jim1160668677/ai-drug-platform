"""客户端抽象接口 — Mock/Real 双模式的契约"""
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, Field


class LLMClient(ABC):
    """大模型客户端接口"""

    @abstractmethod
    async def chat(self, messages: List[dict], model: str = None, **kwargs) -> dict:
        """对话补全

        Args:
            messages: [{"role": "system/user/assistant", "content": "..."}]
            model: 模型名称
        Returns:
            {"content": str, "model": str, "usage": {"prompt_tokens": int, "completion_tokens": int}}
        """
        ...

    async def stream_chat(
        self,
        messages: List[dict],
        model: str = None,
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式对话补全 — 逐 token yield

        默认实现：回退到非流式 chat，将整段内容作为单个 token yield。
        子类（如 RealLLMClient）可覆盖以实现真正的流式响应。

        Yields:
            {"type": "token", "content": "..."} — 增量 token
            {"type": "done", "content": "...", "usage": {...}, "model": "..."} — 完整响应
            {"type": "error", "content": "..."} — 错误信息
        """
        result = await self.chat(messages, model=model, **kwargs)
        yield {
            "type": "token",
            "content": result.get("content", ""),
        }
        yield {
            "type": "done",
            "content": result.get("content", ""),
            "usage": result.get("usage", {}),
            "model": result.get("model", model),
        }

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """文本向量化"""
        ...


class GeneClient(ABC):
    """MyGene.info 基因查询客户端接口"""

    @abstractmethod
    async def query(self, gene_symbol: str) -> dict:
        """查询基因信息

        Returns:
            {"symbol": str, "name": str, "entrez_id": int, "ensembl_id": str,
             "uniprot_id": str, "summary": str, "pathways": [...], ...}
        """
        ...


class VariantClient(ABC):
    """MyVariant.info 变异注释客户端接口"""

    @abstractmethod
    async def query_batch(self, variants: List[str]) -> List[dict]:
        """批量变异注释

        Args:
            variants: ["chr7:55259515:T>A", ...]
        Returns:
            [{"query": str, "clinvar": {...}, "cosmic": {...}, "dbsnp": {...}, "gnomad": {...}}, ...]
        """
        ...


class ChemblClient(ABC):
    """ChEMBL 药物数据客户端接口"""

    @abstractmethod
    async def get_active_molecules(self, target_gene: str, activity_type: str = "IC50", limit: int = 50) -> List[dict]:
        """查询靶点对应的已知活性分子"""
        ...

    @abstractmethod
    async def find_approved_drugs(self, target_gene: str) -> List[dict]:
        """查询已获批药物（药物重定位）"""
        ...


class DiffdockClient(ABC):
    """DiffDock 分子对接客户端接口"""

    @abstractmethod
    async def dock(self, protein_pdb: str, ligand_smiles: str, num_poses: int = 10) -> dict:
        """分子对接

        Args:
            protein_pdb: 蛋白质 PDB 内容
            ligand_smiles: 配体 SMILES
            num_poses: 生成构象数
        Returns:
            {"poses": [{"confidence": float, "positions": [...], "scores": [...]}], "status": str}
        """
        ...


class NcbiClient(ABC):
    """NCBI E-utilities 客户端接口

    覆盖 NCBI 核心数据库：PubMed、ClinVar、Gene、SNP、Protein、Nucleotide。
    设计遵循 NCBI E-utilities 规范：https://www.ncbi.nlm.nih.gov/books/NBK25499/

    子类需实现 4 个原子方法（esearch/esummary/efetch/elink），
    高层封装方法（search_pubmed/fetch_clinvar_variants 等）由本基类提供默认实现，
    基于 4 个原子方法组合而成。
    """

    @abstractmethod
    async def esearch(
        self,
        db: str,
        term: str,
        retmax: int = 20,
        retmode: str = "json",
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """esearch — 搜索 NCBI 数据库，返回 ID 列表

        Args:
            db: 数据库（pubmed/clinvar/gene/snp/protein/nucleotide）
            term: 查询表达式，如 "EGFR[gene] AND pathogenic[clinsig]"
            retmax: 最大返回数
            retmode: 返回格式（json/xml）
            sort: 排序字段（如 "date_last_changed desc"）
        Returns:
            {"esearchresult": {"idlist": [...], "count": "...", "querytranslation": "..."}}
        """
        ...

    @abstractmethod
    async def esummary(
        self,
        db: str,
        ids: List[str],
        retmode: str = "json",
    ) -> Dict[str, Any]:
        """esummary — 获取条目摘要

        Args:
            db: 数据库
            ids: UID 列表
            retmode: 返回格式
        Returns:
            {"result": {"uids": [...], "<uid>": {...}}}
        """
        ...

    @abstractmethod
    async def efetch(
        self,
        db: str,
        ids: List[str],
        rettype: str = "abstract",
        retmode: str = "xml",
    ) -> str:
        """efetch — 获取完整记录（如 PubMed 摘要、基因 FASTA）

        Args:
            db: 数据库
            ids: UID 列表
            rettype: 返回类型（abstract/genbank/fasta/...)
            retmode: 返回格式（xml/text/...)
        Returns:
            原始响应文本（XML 或 plain text）
        """
        ...

    @abstractmethod
    async def elink(
        self,
        dbfrom: str,
        db: str,
        id: str,
    ) -> Dict[str, Any]:
        """elink — 获取跨库链接

        Args:
            dbfrom: 源数据库
            db: 目标数据库
            id: 源 UID
        Returns:
            {"linksets": [{"dbfrom": ..., "ids": [...], "linksetdbs": [...]}]}
        """
        ...

    # ========== 高层封装方法（子类共享逻辑） ==========

    async def search_pubmed(self, query: str, retmax: int = 10) -> List[Dict[str, Any]]:
        """PubMed 文献检索（esearch + esummary 组合）

        Args:
            query: 检索词，如 "EGFR inhibitor NSCLC"
            retmax: 最大返回数
        Returns:
            [{"uid", "title", "authors", "journal", "pubdate", "abstract"}, ...]
        """
        # 默认实现：子类可覆盖以提供解析逻辑
        return []

    async def fetch_gene_info(self, gene_symbol: str) -> Dict[str, Any]:
        """基因信息查询（gene db）

        Args:
            gene_symbol: 基因符号，如 EGFR
        Returns:
            {"symbol", "entrez_id", "summary", "aliases", "chromosome", ...}
        """
        return {}

    async def fetch_clinvar_variants(self, gene: str, retmax: int = 5) -> List[Dict[str, Any]]:
        """ClinVar 致病变异查询

        Args:
            gene: 基因符号
            retmax: 最大返回数
        Returns:
            [{"uid", "title", "clnsig", "gene", "hgvs_p", "hgvs_c", "variant_type"}, ...]
        """
        return []

    async def fetch_sequences(
        self,
        ids: List[str],
        db: str = "protein",
    ) -> str:
        """FASTA 序列获取（protein/nucleotide db）

        Args:
            ids: UID 列表（如 RefSeq NP_xxx / NM_xxx）
            db: protein 或 nucleotide
        Returns:
            FASTA 格式字符串
        """
        return ""


# ========== 学术资源客户端 ==========


class AcademicPaper(BaseModel):
    """学术文献统一数据模型 — 4 个学术数据源(bioRxiv/arXiv/Semantic Scholar/CrossRef)共用"""

    title: str = Field(..., description="论文标题")
    authors: List[str] = Field(default_factory=list, description="作者列表")
    source: str = Field(..., description="数据源名称: biorxiv/arxiv/semantic_scholar/crossref")
    abstract: Optional[str] = Field(None, description="摘要")
    doi: Optional[str] = Field(None, description="DOI")
    year: Optional[int] = Field(None, description="发表年份")
    url: Optional[str] = Field(None, description="原文链接")
    relevance_score: Optional[float] = Field(None, description="相关性分数 0-1")


class AcademicClientBase(ABC):
    """学术资源客户端抽象基类

    4 个学术数据源客户端(bioRxiv/arXiv/Semantic Scholar/CrossRef)的统一契约。
    每个子类需实现 search 方法,返回 AcademicPaper 列表。

    共享能力(由 Real*Client 在 __init__ 中初始化):
    - httpx.AsyncClient 单例连接池
    - asyncio.Semaphore 速率限制
    - 内存+数据库双层缓存
    - 指数退避重试
    - 网络异常降级返回空结果
    """

    # 数据源标识,子类覆盖为 biorxiv/arxiv/semantic_scholar/crossref
    source_name: str = "base"

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> List[AcademicPaper]:
        """按关键词检索学术文献

        Args:
            query: 检索词,如 "EGFR lung cancer"
            limit: 最大返回数(默认 10)
            **kwargs: 数据源特定参数(category/year_from/year_to 等)

        Returns:
            AcademicPaper 列表(按相关性排序),失败时返回空列表
        """
        ...

