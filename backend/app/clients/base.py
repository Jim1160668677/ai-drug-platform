"""客户端抽象接口 — Mock/Real 双模式的契约"""
from abc import ABC, abstractmethod
from typing import Any, List, Optional


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
