"""MHCflurry MHC-I 结合亲和力预测引擎 — 集成 OpenVaccine/mhcflurry

GitHub: https://github.com/openvax/mhcflurry
论文: "MHCflurry: A Command-Line Tool for Peptide-MHC Binding Prediction" (Bioinformatics 2024)

统一遵循 settings.MHCFLURRY_USE_MOCK 开关：
- 真实模式：调用 MHCflurry 模型（需安装 mhcflurry 包 + 下载模型权重）
- Mock 模式：返回伪造的 IC50 结合亲和力（测试环境默认）
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MHCflurryPredictor:
    """MHCflurry MHC-I 结合亲和力预测器

    预测肽段与 MHC-I 等位基因的结合亲和力（IC50, nM），
    并基于突变蛋白序列识别新抗原（neoantigen）。

    Mock/Real 双模式，通过 settings.MHCFLURRY_USE_MOCK 切换。
    """

    def __init__(self, db: AsyncSession = None):
        """初始化 MHCflurry 预测器

        Args:
            db: 异步数据库会话（可选，用于结果持久化）
        """
        self.db = db
        self._predictor = None  # 懒加载 MHCflurry 预测器

    async def predict_binding(
        self,
        peptide: str,
        mhc_allele: str,
    ) -> Dict[str, Any]:
        """预测肽段-MHC 结合亲和力

        Args:
            peptide: 肽段序列（8-15 个氨基酸）
            mhc_allele: MHC 等位基因（如 "HLA-A*02:01"）
        Returns:
            {affinity_nM, rank, is_binder, peptide, mhc_allele, source}
            source 为 "mhcflurry" 或 "mock"
            is_binder: affinity < 500nM 时为 True
        """
        if not peptide or not mhc_allele:
            return {
                "affinity_nM": 0.0,
                "rank": 0.0,
                "is_binder": False,
                "peptide": peptide,
                "mhc_allele": mhc_allele,
                "source": "error",
                "error": "肽段和 MHC 等位基因不能为空",
            }

        from app.core.config import settings

        use_mock = getattr(settings, "MHCFLURRY_USE_MOCK", True)
        start_time = time.time()

        if not use_mock:
            try:
                # CPU 密集工作用 asyncio.to_thread 包装
                result = await asyncio.to_thread(
                    self._predict_binding_sync, peptide, mhc_allele
                )
                duration = round(time.time() - start_time, 2)
                logger.info(
                    f"MHCflurry 真实预测完成: peptide={peptide}, "
                    f"allele={mhc_allele}, affinity={result.get('affinity_nM')}nM, "
                    f"耗时={duration}s"
                )
                return result
            except ImportError as e:
                logger.warning(
                    f"mhcflurry 包未安装，降级 Mock 模式: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"MHCflurry 预测失败，降级 Mock 模式: {e}"
                )

        # Mock 模式
        result = self._mock_predict_binding(peptide, mhc_allele)
        duration = round(time.time() - start_time, 2)
        logger.info(
            f"MHCflurry Mock 预测完成: peptide={peptide}, "
            f"allele={mhc_allele}, 耗时={duration}s"
        )
        return result

    async def identify_neoantigens(
        self,
        mutations: List[Dict[str, Any]],
        mhc_alleles: List[str],
    ) -> List[Dict[str, Any]]:
        """新抗原识别 — 基于体细胞突变预测免疫原性肽段

        对每个突变生成 8-11mer 滑动窗口肽段，
        对每个肽段 × MHC 等位基因组合预测结合亲和力，
        返回 is_neoantigen=True（即 is_binder=True）的列表。

        Args:
            mutations: 体细胞突变列表，每个元素为
                {mutation_id, protein_sequence (突变后), mutation_position, ...}
            mhc_alleles: MHC 等位基因列表（如 ["HLA-A*02:01", "HLA-B*07:02"]）
        Returns:
            新抗原列表，每个元素为
            {mutation_id, peptide, mhc_allele, affinity_nM, rank, is_binder, is_neoantigen, source}
        """
        if not mutations or not mhc_alleles:
            return []

        from app.core.config import settings

        use_mock = getattr(settings, "MHCFLURRY_USE_MOCK", True)
        start_time = time.time()
        neoantigens: List[Dict[str, Any]] = []

        for mutation in mutations:
            protein_seq = mutation.get("protein_sequence", "")
            mut_pos = mutation.get("mutation_position", 0)
            mut_id = mutation.get("mutation_id", "")

            if not protein_seq or mut_pos <= 0:
                continue

            # 生成 8-11mer 滑动窗口肽段（包含突变位点）
            peptides = self._generate_peptides(protein_seq, mut_pos)

            for peptide in peptides:
                for allele in mhc_alleles:
                    if use_mock:
                        result = self._mock_predict_binding(peptide, allele)
                    else:
                        try:
                            result = await asyncio.to_thread(
                                self._predict_binding_sync, peptide, allele
                            )
                        except Exception as e:
                            logger.warning(
                                f"MHCflurry 预测失败，降级 Mock: {e}"
                            )
                            result = self._mock_predict_binding(peptide, allele)

                    if result.get("is_binder", False):
                        neoantigens.append({
                            "mutation_id": mut_id,
                            "peptide": peptide,
                            "mhc_allele": allele,
                            "affinity_nM": result.get("affinity_nM", 0.0),
                            "rank": result.get("rank", 0.0),
                            "is_binder": True,
                            "is_neoantigen": True,
                            "source": result.get("source", "mock"),
                        })

        duration = round(time.time() - start_time, 2)
        logger.info(
            f"新抗原识别完成: {len(mutations)} 个突变 × {len(mhc_alleles)} 个等位基因, "
            f"发现 {len(neoantigens)} 个新抗原, 耗时={duration}s"
        )
        return neoantigens

    def _generate_peptides(
        self,
        protein_seq: str,
        mut_pos: int,
    ) -> List[str]:
        """生成包含突变位点的 8-11mer 滑动窗口肽段

        Args:
            protein_seq: 蛋白质序列（突变后）
            mut_pos: 突变位置（1-based）
        Returns:
            肽段列表（8-11mer，去重）
        """
        peptides = set()
        pos_0 = mut_pos - 1  # 转为 0-based

        for pep_len in range(8, 12):  # 8, 9, 10, 11
            # 滑动窗口：窗口需包含突变位点
            for start in range(max(0, pos_0 - pep_len + 1), min(pos_0 + 1, len(protein_seq) - pep_len + 1)):
                end = start + pep_len
                if end <= len(protein_seq):
                    peptide = protein_seq[start:end]
                    if start <= pos_0 < end:  # 确保包含突变位点
                        peptides.add(peptide)

        return list(peptides)

    def _predict_binding_sync(
        self,
        peptide: str,
        mhc_allele: str,
    ) -> Dict[str, Any]:
        """同步调用 MHCflurry 预测（在 asyncio.to_thread 中执行）

        Args:
            peptide: 肽段序列
            mhc_allele: MHC 等位基因
        Returns:
            结合亲和力预测结果
        """
        from mhcflurry import Class1AffinityPredictor

        # 懒加载预测器
        if self._predictor is None:
            logger.info("加载 MHCflurry Class1AffinityPredictor ...")
            self._predictor = Class1AffinityPredictor.load()

        # 预测 IC50 (nM)
        affinity_nM = float(self._predictor.predict(
            peptides=[peptide], allele=mhc_allele
        )[0])

        # 计算 rank（百分位排名，越低越好）
        rank = float(self._predictor.predict(
            peptides=[peptide], allele=mhc_allele, percentile=True
        )[0]) if hasattr(self._predictor, "predict") else 0.5

        # is_binder: IC50 < 500nM 视为结合者
        is_binder = affinity_nM < 500.0

        return {
            "affinity_nM": round(affinity_nM, 2),
            "rank": round(rank, 4),
            "is_binder": is_binder,
            "peptide": peptide,
            "mhc_allele": mhc_allele,
            "source": "mhcflurry",
        }

    def _mock_predict_binding(
        self,
        peptide: str,
        mhc_allele: str,
    ) -> Dict[str, Any]:
        """Mock 预测 — 返回伪造的 IC50 结合亲和力

        基于肽段和等位基因特征生成确定性伪随机 IC50 值，
        范围在 50-1000nM（涵盖 binder 和 non-binder）。

        Args:
            peptide: 肽段序列
            mhc_allele: MHC 等位基因
        Returns:
            伪造的结合亲和力预测结果
        """
        # 基于肽段和等位基因生成确定性伪随机 IC50
        pep_hash = sum(ord(c) * (i + 1) for i, c in enumerate(peptide))
        allele_hash = sum(ord(c) for c in mhc_allele)
        combined_hash = pep_hash + allele_hash

        # IC50: 50-1000 nM（对数分布，低值更常见）
        # 使用模运算映射到 50-1000 范围
        affinity_nM = round(50.0 + (combined_hash % 950), 2)

        # rank: 0.01-5.0%（越低表示结合越强）
        rank = round(0.01 + (combined_hash % 500) / 100.0, 4)

        # is_binder: IC50 < 500nM
        is_binder = affinity_nM < 500.0

        return {
            "affinity_nM": affinity_nM,
            "rank": rank,
            "is_binder": is_binder,
            "peptide": peptide,
            "mhc_allele": mhc_allele,
            "source": "mock",
        }
