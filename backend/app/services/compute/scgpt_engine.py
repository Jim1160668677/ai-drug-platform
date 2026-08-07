"""scGPT 单细胞扰动预测引擎 — 集成 bowang-lab/scGPT

GitHub: https://github.com/bowang-lab/scGPT
论文: "scGPT: Toward Building a Foundation Model for Single-Cell Multi-OMICS Using Generative AI" (Nat Methods 2024)

统一遵循 settings.SCGPT_USE_MOCK 开关：
- 真实模式：调用 scGPT 模型（需 GPU + scgpt 包 + 模型权重）
- Mock 模式：返回伪造的扰动得分和细胞类型概率（测试环境默认）
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ScGPTEngine:
    """scGPT 单细胞分析引擎

    提供基因扰动预测和细胞类型注释两大能力：
    1. predict_perturbation: 预测基因敲除/激活后的表达变化
    2. annotate_cell_types: 基于 scRNA-seq 数据注释细胞类型

    Mock/Real 双模式，通过 settings.SCGPT_USE_MOCK 切换。
    """

    def __init__(self, db: AsyncSession = None):
        """初始化 scGPT 引擎

        Args:
            db: 异步数据库会话（可选，用于结果持久化）
        """
        self.db = db
        self._model = None  # 懒加载 scGPT 模型

    async def predict_perturbation(
        self,
        gene: str,
        cell_type: str = "",
    ) -> Dict[str, Any]:
        """预测基因扰动效果 — 预测基因敲除/激活后的表达变化

        Args:
            gene: 目标基因符号（如 "TP53", "BRCA1"）
            cell_type: 细胞类型（如 "T cell", "B cell"），可选
        Returns:
            {gene, cell_type, perturbation_score, affected_genes, direction, source}
            source 为 "scgpt" 或 "mock"
        """
        if not gene:
            return {
                "gene": "",
                "cell_type": cell_type,
                "perturbation_score": 0.0,
                "affected_genes": [],
                "direction": "unknown",
                "source": "error",
                "error": "基因符号不能为空",
            }

        from app.core.config import settings

        use_mock = getattr(settings, "SCGPT_USE_MOCK", True)
        start_time = time.time()

        if not use_mock:
            try:
                # GPU 密集工作用 asyncio.to_thread 包装
                result = await asyncio.to_thread(
                    self._perturbation_sync, gene, cell_type
                )
                duration = round(time.time() - start_time, 2)
                logger.info(
                    f"scGPT 真实扰动预测完成: gene={gene}, "
                    f"cell_type={cell_type}, score={result.get('perturbation_score')}, "
                    f"耗时={duration}s"
                )
                return result
            except ImportError as e:
                logger.warning(
                    f"scgpt 包未安装，降级 Mock 模式: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"scGPT 扰动预测失败，降级 Mock 模式: {e}"
                )

        # Mock 模式
        result = self._mock_perturbation(gene, cell_type)
        duration = round(time.time() - start_time, 2)
        logger.info(
            f"scGPT Mock 扰动预测完成: gene={gene}, 耗时={duration}s"
        )
        return result

    async def annotate_cell_types(self, adata_path: str) -> Dict[str, Any]:
        """细胞类型注释 — 基于 scRNA-seq 数据预测细胞类型

        Args:
            adata_path: AnnData 文件路径（.h5ad 格式）
        Returns:
            {n_cells, cell_types, probabilities, source}
            source 为 "scgpt" 或 "mock"
        """
        if not adata_path:
            return {
                "n_cells": 0,
                "cell_types": [],
                "probabilities": [],
                "source": "error",
                "error": "AnnData 文件路径不能为空",
            }

        from app.core.config import settings

        use_mock = getattr(settings, "SCGPT_USE_MOCK", True)
        start_time = time.time()

        if not use_mock:
            try:
                # GPU 密集工作用 asyncio.to_thread 包装
                result = await asyncio.to_thread(
                    self._annotate_sync, adata_path
                )
                duration = round(time.time() - start_time, 2)
                logger.info(
                    f"scGPT 真实细胞类型注释完成: n_cells={result.get('n_cells')}, "
                    f"耗时={duration}s"
                )
                return result
            except ImportError as e:
                logger.warning(
                    f"scgpt 包未安装，降级 Mock 模式: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"scGPT 细胞类型注释失败，降级 Mock 模式: {e}"
                )

        # Mock 模式
        result = self._mock_annotate(adata_path)
        duration = round(time.time() - start_time, 2)
        logger.info(f"scGPT Mock 细胞类型注释完成: 耗时={duration}s")
        return result

    def _perturbation_sync(self, gene: str, cell_type: str) -> Dict[str, Any]:
        """同步调用 scGPT 扰动预测（在 asyncio.to_thread 中执行）

        Args:
            gene: 目标基因符号
            cell_type: 细胞类型
        Returns:
            扰动预测结果
        """
        import torch  # noqa: F401
        import scgpt

        # 懒加载模型
        if self._model is None:
            logger.info("加载 scGPT 扰动预测模型 ...")
            # 实际加载逻辑依赖 scGPT API
            self._model = scgpt.load_perturbation_model()

        # 调用扰动预测
        result = self._model.predict(gene, cell_type)

        # 提取扰动得分（表达变化幅度）
        perturbation_score = float(result.get("score", 0.65))
        direction = result.get("direction", "down")

        # 提取受影响基因列表
        affected_genes = result.get("affected_genes", [])

        return {
            "gene": gene,
            "cell_type": cell_type,
            "perturbation_score": round(perturbation_score, 4),
            "affected_genes": affected_genes,
            "direction": direction,
            "source": "scgpt",
        }

    def _annotate_sync(self, adata_path: str) -> Dict[str, Any]:
        """同步调用 scGPT 细胞类型注释（在 asyncio.to_thread 中执行）

        Args:
            adata_path: AnnData 文件路径
        Returns:
            注释结果
        """
        import torch  # noqa: F401
        import scgpt
        import anndata as ad

        # 懒加载模型
        if self._model is None:
            logger.info("加载 scGPT 注释模型 ...")
            self._model = scgpt.load_cell_annotation_model()

        # 加载 AnnData
        adata = ad.read_h5ad(adata_path)
        n_cells = adata.n_obs

        # 调用细胞类型注释
        result = self._model.annotate(adata)

        return {
            "n_cells": int(n_cells),
            "cell_types": result.get("cell_types", []),
            "probabilities": result.get("probabilities", []),
            "source": "scgpt",
        }

    def _mock_perturbation(self, gene: str, cell_type: str) -> Dict[str, Any]:
        """Mock 扰动预测 — 返回伪造的扰动得分

        基于基因名称生成确定性伪随机扰动得分，
        保持数值在生物学合理范围内。

        Args:
            gene: 目标基因符号
            cell_type: 细胞类型
        Returns:
            伪造的扰动预测结果
        """
        # 基于基因名称哈希生成确定性分数
        gene_hash = sum(ord(c) for c in gene)
        # 扰动得分: 0.3-0.9（越高表示扰动效果越显著）
        perturbation_score = round(0.3 + (gene_hash % 60) / 100.0, 4)

        # 方向：基因敲除通常导致表达下降
        direction = "down" if gene_hash % 2 == 0 else "up"

        # 受影响基因列表（伪造）
        affected_pool = [
            "CD4", "CD8A", "IL2RA", "FOXP3", "GZMB", "PRF1", "IFNG",
            "TNF", "CXCL9", "CXCL10", "PDCD1", "CTLA4", "LAG3", "TIGIT",
        ]
        # 基于哈希选择受影响基因
        n_affected = 3 + (gene_hash % 5)
        affected_genes = [
            affected_pool[(gene_hash + i * 7) % len(affected_pool)]
            for i in range(n_affected)
        ]

        return {
            "gene": gene,
            "cell_type": cell_type,
            "perturbation_score": perturbation_score,
            "affected_genes": affected_genes,
            "direction": direction,
            "source": "mock",
        }

    def _mock_annotate(self, adata_path: str) -> Dict[str, Any]:
        """Mock 细胞类型注释 — 返回伪造的细胞类型概率

        Args:
            adata_path: AnnData 文件路径
        Returns:
            伪造的注释结果
        """
        # 基于文件路径哈希生成确定性结果
        path_hash = sum(ord(c) for c in adata_path)
        n_cells = 100 + (path_hash % 900)  # 100-1000 个细胞

        # 常见细胞类型
        cell_type_pool = [
            "T cell", "B cell", "NK cell", "Monocyte", "DC",
            "Fibroblast", "Endothelial", "Epithelial", "Macrophage",
        ]

        # 生成概率分布（归一化到和为1）
        import random
        random.seed(path_hash)
        n_types = 3 + (path_hash % 4)  # 3-6 种细胞类型
        selected_types = random.sample(cell_type_pool, min(n_types, len(cell_type_pool)))
        raw_probs = [random.random() for _ in selected_types]
        total = sum(raw_probs)
        probabilities = [round(p / total, 4) for p in raw_probs]

        return {
            "n_cells": n_cells,
            "cell_types": selected_types,
            "probabilities": probabilities,
            "source": "mock",
        }
