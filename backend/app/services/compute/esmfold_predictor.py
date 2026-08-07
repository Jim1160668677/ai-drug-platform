"""ESMFold 蛋白结构预测引擎 — 集成 facebookresearch/esm

GitHub: https://github.com/facebookresearch/esm
论文: "Evolutionary-scale prediction of atomic-level protein structure with a language model" (Science 2023)

统一遵循 settings.ESMFOLD_USE_MOCK 开关：
- 真实模式：调用 ESMFold 模型（需 GPU + torch + esm 包）
- Mock 模式：返回伪造的 PDB 文本（测试环境默认）
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ESMFoldPredictor:
    """ESMFold 蛋白结构预测器

    将氨基酸序列折叠为 3D 结构，输出 PDB 文本 + pLDDT 置信度。
    Mock/Real 双模式，通过 settings.ESMFOLD_USE_MOCK 切换。
    """

    def __init__(self, db: AsyncSession = None):
        """初始化 ESMFold 预测器

        Args:
            db: 异步数据库会话（可选，用于结果持久化）
        """
        self.db = db
        self._model = None  # 懒加载 ESMFold 模型

    async def predict_structure(
        self,
        sequence: str,
        target_id: str = "",
    ) -> Dict[str, Any]:
        """预测蛋白质 3D 结构

        Args:
            sequence: 氨基酸序列（单字母编码，如 "MVLSEGEWQLVLHVWAKVEA"）
            target_id: 靶点/蛋白标识符（用于日志和存储路径）
        Returns:
            {pdb_text, plddt_mean, storage_path, source, model_name, duration_sec}
            source 为 "esmfold" 或 "mock"
        """
        if not sequence:
            return {
                "pdb_text": "",
                "plddt_mean": 0.0,
                "storage_path": "",
                "source": "error",
                "model_name": "",
                "duration_sec": 0.0,
                "error": "序列不能为空",
            }

        from app.core.config import settings

        use_mock = getattr(settings, "ESMFOLD_USE_MOCK", True)
        start_time = time.time()

        if not use_mock:
            try:
                # CPU/GPU 密集工作用 asyncio.to_thread 包装，避免阻塞事件循环
                result = await asyncio.to_thread(self._predict_sync, sequence)
                duration = round(time.time() - start_time, 2)
                result["duration_sec"] = duration
                result["storage_path"] = result.get("storage_path", "")
                logger.info(
                    f"ESMFold 真实预测完成: target={target_id}, "
                    f"len={len(sequence)}, plddt={result.get('plddt_mean', 0)}, "
                    f"耗时={duration}s"
                )
                return result
            except ImportError as e:
                logger.warning(
                    f"esm 包未安装，降级 Mock 模式: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"ESMFold 真实预测失败，降级 Mock 模式: {e}"
                )

        # Mock 模式
        result = self._mock_predict(sequence)
        duration = round(time.time() - start_time, 2)
        result["duration_sec"] = duration
        logger.info(
            f"ESMFold Mock 预测完成: target={target_id}, "
            f"len={len(sequence)}, 耗时={duration}s"
        )
        return result

    def _predict_sync(self, sequence: str) -> Dict[str, Any]:
        """同步调用 ESMFold 模型（在 asyncio.to_thread 中执行）

        Args:
            sequence: 氨基酸序列
        Returns:
            预测结果字典
        """
        import torch  # noqa: F401 — ESMFold 依赖
        import esm

        from app.core.config import settings
        model_name = getattr(settings, "ESMFOLD_MODEL_NAME", "esmfold_v1")

        # 懒加载模型（首次调用时加载，后续复用）
        if self._model is None:
            logger.info(f"加载 ESMFold 模型: {model_name} ...")
            self._model = esm.pretrained.esmfold_v1()
            self._model = self._model.eval()

        # 调用模型推断，生成 PDB 文本
        with torch.no_grad():
            output = self._model.infer_pdb(sequence)

        # 提取 pLDDT 置信度（从模型输出中获取）
        plddt_mean = 0.85  # 默认值
        try:
            # ESMFold 输出中包含 plddt 信息
            with torch.no_grad():
                inner_output = self._model.infer(sequence)
                if "plddt" in inner_output:
                    plddt_tensor = inner_output["plddt"]
                    plddt_mean = float(plddt_tensor.mean().cpu().numpy())
                    plddt_mean = round(plddt_mean, 4)
        except Exception as e:
            logger.debug(f"pLDDT 提取失败，使用默认值: {e}")

        return {
            "pdb_text": output,
            "plddt_mean": plddt_mean,
            "storage_path": "",  # 由调用方负责持久化
            "source": "esmfold",
            "model_name": model_name,
        }

    def _mock_predict(self, sequence: str) -> Dict[str, Any]:
        """Mock 预测 — 生成伪造但格式合法的 PDB 文本

        生成简化的 ATOM 记录（每个残基一个 CA 原子），
        坐标基于序列索引线性排列，模拟 alpha 螺旋。

        Args:
            sequence: 氨基酸序列
        Returns:
            伪造的预测结果
        """
        # 三字母氨基酸代码映射
        three_letter = {
            "A": "ALA", "R": "ARG", "N": "ASN", "D": "ASP", "C": "CYS",
            "E": "GLU", "Q": "GLN", "G": "GLY", "H": "HIS", "I": "ILE",
            "L": "LEU", "K": "LYS", "M": "MET", "F": "PHE", "P": "PRO",
            "S": "SER", "T": "THR", "W": "TRP", "Y": "TYR", "V": "VAL",
        }

        pdb_lines = [
            "HEADER    MOCK STRUCTURE",
            "TITLE     ESMFOLD MOCK PREDICTION",
            f"REMARK   1 SEQUENCE LENGTH: {len(sequence)}",
            "REMARK   2 THIS IS A MOCK STRUCTURE FOR TESTING ONLY",
        ]

        # 生成 ATOM 记录（每残基一个 CA 原子，模拟 alpha 螺旋坐标）
        # alpha 螺旋: 每残基上升 1.5 Å，每残基旋转 100°
        import math
        for i, aa in enumerate(sequence):
            res_name = three_letter.get(aa, "GLY")
            res_seq = i + 1
            # alpha 螺旋坐标参数
            x = round(2.3 * math.cos(math.radians(100 * i)), 3)
            y = round(2.3 * math.sin(math.radians(100 * i)), 3)
            z = round(1.5 * i, 3)
            # PDB ATOM 记录格式（简化版）
            atom_line = (
                f"ATOM  {res_seq:5d}  CA  {res_name} A{res_seq:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 85.00           C"
            )
            pdb_lines.append(atom_line)

        # 添加 pLDDT 占位（Mock 模式固定 0.85）
        pdb_lines.append("TER")
        pdb_lines.append("END")
        pdb_text = "\n".join(pdb_lines) + "\n"

        return {
            "pdb_text": pdb_text,
            "plddt_mean": 0.85,
            "storage_path": "",
            "source": "mock",
            "model_name": "esmfold_v1_mock",
        }
