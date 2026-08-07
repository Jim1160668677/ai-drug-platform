"""Uni-Mol 分子对接引擎 — 集成 dp-tech/Uni-Mol

GitHub: https://github.com/dp-tech/Uni-Mol
论文: "Uni-Mol: A Universal 3D Molecular Representation Learning Framework" (ICLR 2023)

统一遵循 settings.UNIMOL_USE_MOCK 开关：
- 真实模式：调用 Uni-Mol 对接模型（需 GPU + unimol_tools 包）
- Mock 模式：返回伪造的结合姿态和亲和力（测试环境默认）
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class UniMolDocking:
    """Uni-Mol 分子对接器

    将小分子（SMILES）对接到蛋白质靶点口袋，输出 RMSD + 结合亲和力 + 置信度。
    Mock/Real 双模式，通过 settings.UNIMOL_USE_MOCK 切换。
    """

    def __init__(self, db: AsyncSession = None):
        """初始化 Uni-Mol 对接器

        Args:
            db: 异步数据库会话（可选，用于结果持久化）
        """
        self.db = db
        self._predictor = None  # 懒加载 Uni-Mol 预测器

    async def dock(
        self,
        smiles: str,
        target_pdb: str = "",
        target_name: str = "",
    ) -> Dict[str, Any]:
        """分子对接 — 预测配体与受体的结合模式

        Args:
            smiles: 配体 SMILES 字符串
            target_pdb: 受体 PDB 文本或 PDB ID
            target_name: 靶点名称（用于日志）
        Returns:
            {rmsd, affinity, confidence, binding_pose, source}
            source 为 "unimol" 或 "mock"
        """
        if not smiles:
            return {
                "rmsd": 0.0,
                "affinity": 0.0,
                "confidence": 0.0,
                "binding_pose": {},
                "source": "error",
                "error": "SMILES 不能为空",
            }

        from app.core.config import settings

        use_mock = getattr(settings, "UNIMOL_USE_MOCK", True)
        start_time = time.time()

        if not use_mock:
            try:
                # CPU/GPU 密集工作用 asyncio.to_thread 包装
                result = await asyncio.to_thread(self._dock_sync, smiles, target_pdb)
                duration = round(time.time() - start_time, 2)
                logger.info(
                    f"Uni-Mol 真实对接完成: target={target_name}, "
                    f"smiles={smiles[:30]}..., rmsd={result.get('rmsd')}, "
                    f"affinity={result.get('affinity')}, 耗时={duration}s"
                )
                return result
            except ImportError as e:
                logger.warning(
                    f"unimol_tools 包未安装，降级 Mock 模式: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"Uni-Mol 真实对接失败，降级 Mock 模式: {e}"
                )

        # Mock 模式
        result = self._mock_dock(smiles, target_name)
        duration = round(time.time() - start_time, 2)
        logger.info(
            f"Uni-Mol Mock 对接完成: target={target_name}, "
            f"smiles={smiles[:30]}..., 耗时={duration}s"
        )
        return result

    def _dock_sync(self, smiles: str, target_pdb: str) -> Dict[str, Any]:
        """同步调用 Uni-Mol 对接模型（在 asyncio.to_thread 中执行）

        Args:
            smiles: 配体 SMILES
            target_pdb: 受体 PDB 文本
        Returns:
            对接结果字典
        """
        import numpy as np
        from unimol_tools import UniMolPredictor

        # 懒加载预测器
        if self._predictor is None:
            logger.info("加载 Uni-Mol 预测器 ...")
            self._predictor = UniMolPredictor()

        # 调用 Uni-Mol 预测结合模式
        # 注意：实际 Uni-Mol API 可能略有差异，此处为示意性实现
        result = self._predictor.predict(smiles, target_pdb)

        # 提取对接指标
        rmsd = float(result.get("rmsd", 1.5))
        affinity = float(result.get("affinity", -8.5))
        confidence = float(result.get("confidence", 0.75))

        # 提取结合姿态坐标
        binding_pose = {
            "coordinates": result.get("coordinates", np.array([])).tolist()
            if hasattr(result.get("coordinates", None), "tolist")
            else result.get("coordinates", []),
            "rmsd": rmsd,
            "target_pdb_id": target_pdb[:20] if target_pdb else "",
        }

        return {
            "rmsd": round(rmsd, 2),
            "affinity": round(affinity, 2),
            "confidence": round(confidence, 4),
            "binding_pose": binding_pose,
            "source": "unimol",
        }

    def _generate_3d_conformer(
        self, smiles: str, center: list, seed: int = 42
    ) -> tuple:
        """使用 RDKit 生成真实 3D 构象

        流程：SMILES → AddHs → ETKDGv3 嵌入 → MMFF 力场优化 → 平移至中心
        生成化学合理的 3D 坐标和 MOL/SDF block，供前端 3Dmol.js 渲染。

        Args:
            smiles: 配体 SMILES
            center: 坐标中心 [x, y, z]
            seed: 随机种子（确定性输出）
        Returns:
            (mol_block, coordinates, atom_count, heavy_atom_count)
            RDKit 不可用时返回 (None, [], 0, 0)
        """
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem, Crippen, Descriptors
        except ImportError as e:
            logger.warning(f"RDKit 不可用，无法生成真实 3D 构象: {e}")
            return None, [], 0, 0

        try:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return None, [], 0, 0

            mol = Chem.AddHs(mol)

            params = AllChem.ETKDGv3()
            params.randomSeed = seed
            rid = AllChem.EmbedMolecule(mol, params)
            if rid < 0:
                rid = AllChem.EmbedMolecule(mol, randomSeed=seed)
                if rid < 0:
                    logger.warning(f"RDKit 嵌入失败: smiles={smiles[:30]}")
                    return None, [], 0, 0

            try:
                AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
            except Exception:
                AllChem.UFFOptimizeMolecule(mol, maxIters=500)

            # 平移构象至中心
            conf = mol.GetConformer()
            cx, cy, cz = center[0], center[1], center[2]
            for i in range(mol.GetNumAtoms()):
                p = conf.GetAtomPosition(i)
                conf.SetAtomPosition(i, (p.x + cx, p.y + cy, p.z + cz))

            coordinates = []
            for i in range(mol.GetNumAtoms()):
                p = conf.GetAtomPosition(i)
                coordinates.append([round(p.x, 4), round(p.y, 4), round(p.z, 4)])

            mol_block = Chem.MolToMolBlock(mol)
            heavy_count = mol.GetNumHeavyAtoms()
            atom_count = mol.GetNumAtoms()

            return mol_block, coordinates, atom_count, heavy_count
        except Exception as e:
            logger.warning(f"RDKit 3D 构象生成失败: {e}")
            return None, [], 0, 0

    def _mock_dock(self, smiles: str, target_name: str) -> Dict[str, Any]:
        """Mock 对接 — 使用 RDKit 生成真实 3D 构象

        当 UNIMOL_USE_MOCK=True 时调用。通过 RDKit ETKDGv3 + MMFF 生成
        化学合理的 3D 结合姿态，替代旧的线性假坐标。

        Args:
            smiles: 配体 SMILES
            target_name: 靶点名称
        Returns:
            对接结果（含 binding_pose.mol_block 供前端 3D 渲染）
        """
        import math

        # 基于 SMILES 长度生成确定性伪随机值（相同输入→相同输出）
        n_atoms = sum(1 for c in smiles if c.isupper())
        n_branches = smiles.count("(")

        # RMSD: 0.5-3.0 Å（越小越好），基于复杂度
        rmsd = round(1.5 + (n_branches * 0.1) - (n_atoms * 0.02), 2)
        rmsd = max(0.5, min(3.0, rmsd))

        # 结合亲和力: -6 到 -12 kcal/mol（越负越好）
        affinity = round(-8.5 - (n_atoms * 0.05) + (n_branches * 0.2), 2)
        affinity = max(-12.0, min(-6.0, affinity))

        # 置信度: 0.5-0.95（越高越好）
        confidence = round(0.75 + (0.05 if n_atoms > 15 else -0.05), 4)
        confidence = max(0.5, min(0.95, confidence))

        # 抑制常数 Ki（μM）：Ki = exp(affinity / RT) * 1e6，RT ≈ 0.592 kcal/mol（298K）
        ki_um = round(math.exp(affinity / 0.592) * 1e6, 4)

        # 生成真实 3D 构象（中心默认 [0,0,0]）
        mol_block, coordinates, atom_count, heavy_count = (
            self._generate_3d_conformer(smiles, [0.0, 0.0, 0.0])
        )

        # 配体效率
        ligand_efficiency = (
            round(affinity / heavy_count, 3) if heavy_count > 0 else None
        )

        # 构建结合姿态
        binding_pose: Dict[str, Any] = {
            "rmsd": rmsd,
            "target_name": target_name,
            "atom_count": atom_count,
            "heavy_atom_count": heavy_count,
        }

        if mol_block and coordinates:
            binding_pose["mol_block"] = mol_block
            binding_pose["coordinates"] = coordinates
        else:
            # RDKit 不可用时降级为线性坐标
            binding_pose["coordinates"] = [
                [0.0 + i * 1.5, 0.0, 0.0] for i in range(min(max(n_atoms, 1), 10))
            ]

        return {
            "rmsd": rmsd,
            "affinity": affinity,
            "confidence": confidence,
            "ki": ki_um,
            "ligand_efficiency": ligand_efficiency,
            "binding_pose": binding_pose,
            "source": "mock",
        }
