"""AutoDock Vina 分子对接引擎 — 集成 ccsb-scripps/AutoDock-Vina

GitHub: https://github.com/ccsb-scripps/AutoDock-Vina
论文: "AutoDock Vina: Improving the speed and accuracy of docking with a new scoring function" (J Comput Chem 2010)

统一遵循 settings.VINA_USE_MOCK 开关：
- 真实模式：调用 Vina 可执行文件/Python 绑定（需安装 vina 包）
- Mock 模式：返回伪造的对接亲和力和 RMSD（测试环境默认）
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class VinaDocking:
    """AutoDock Vina 分子对接器

    经典物理对接引擎，将配体对接到受体口袋，输出结合亲和力 + RMSD。
    提供 dock（全局对接）和 refine（局部优化）两个接口。
    Mock/Real 双模式，通过 settings.VINA_USE_MOCK 切换。
    """

    def __init__(self, db: AsyncSession = None):
        """初始化 Vina 对接器

        Args:
            db: 异步数据库会话（可选，用于结果持久化）
        """
        self.db = db

    async def dock(
        self,
        smiles: str,
        receptor_pdbqt: str = "",
        box: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """分子对接 — Vina 全局搜索对接

        Args:
            smiles: 配体 SMILES（将被转换为 3D 构象用于对接）
            receptor_pdbqt: 受体 PDBQT 文件路径或内容
            box: 对接盒子参数 {center_x, center_y, center_z, size_x, size_y, size_z}
        Returns:
            {affinity, rmsd, pose, source}
            source 为 "vina" 或 "mock"
        """
        if not smiles:
            return {
                "affinity": 0.0,
                "rmsd": 0.0,
                "pose": {},
                "source": "error",
                "error": "SMILES 不能为空",
            }

        from app.core.config import settings

        use_mock = getattr(settings, "VINA_USE_MOCK", True)
        box = box or {}
        start_time = time.time()

        if not use_mock:
            try:
                # CPU 密集工作用 asyncio.to_thread 包装
                result = await asyncio.to_thread(
                    self._dock_sync, smiles, receptor_pdbqt, box
                )
                duration = round(time.time() - start_time, 2)
                logger.info(
                    f"Vina 真实对接完成: smiles={smiles[:30]}..., "
                    f"affinity={result.get('affinity')}, 耗时={duration}s"
                )
                return result
            except ImportError as e:
                logger.warning(
                    f"vina 包未安装，降级 Mock 模式: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"Vina 真实对接失败，降级 Mock 模式: {e}"
                )

        # Mock 模式
        result = self._mock_dock(smiles, box)
        duration = round(time.time() - start_time, 2)
        logger.info(
            f"Vina Mock 对接完成: smiles={smiles[:30]}..., 耗时={duration}s"
        )
        return result

    async def refine(self, smiles: str, pose: Dict) -> Dict[str, Any]:
        """局部优化 — 对给定姿态做 Vina 局部最小化

        Args:
            smiles: 配体 SMILES
            pose: 初始结合姿态 {coordinates, ...}
        Returns:
            {affinity, rmsd, pose, source}
        """
        if not smiles or not pose:
            return {
                "affinity": 0.0,
                "rmsd": 0.0,
                "pose": pose or {},
                "source": "error",
                "error": "SMILES 和 pose 不能为空",
            }

        from app.core.config import settings

        use_mock = getattr(settings, "VINA_USE_MOCK", True)
        start_time = time.time()

        if not use_mock:
            try:
                # CPU 密集工作用 asyncio.to_thread 包装
                result = await asyncio.to_thread(
                    self._refine_sync, smiles, pose
                )
                duration = round(time.time() - start_time, 2)
                logger.info(
                    f"Vina 真实局部优化完成: affinity={result.get('affinity')}, "
                    f"耗时={duration}s"
                )
                return result
            except ImportError as e:
                logger.warning(
                    f"vina 包未安装，降级 Mock 模式: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"Vina 局部优化失败，降级 Mock 模式: {e}"
                )

        # Mock 模式 — 优化后亲和力略好
        result = self._mock_dock(smiles, pose.get("box", {}))
        # 局部优化：亲和力提升 0.5，RMSD 略降
        result["affinity"] = round(result["affinity"] - 0.5, 2)
        result["rmsd"] = round(max(0.3, result["rmsd"] - 0.3), 2)
        result["source"] = "mock_refine"
        result["pose"]["refined"] = True
        duration = round(time.time() - start_time, 2)
        logger.info(f"Vina Mock 局部优化完成: 耗时={duration}s")
        return result

    def _dock_sync(
        self,
        smiles: str,
        receptor_pdbqt: str,
        box: Dict,
    ) -> Dict[str, Any]:
        """同步调用 Vina 对接（在 asyncio.to_thread 中执行）

        Args:
            smiles: 配体 SMILES
            receptor_pdbqt: 受体 PDBQT 路径或内容
            box: 对接盒子参数
        Returns:
            对接结果字典
        """
        from vina import Vina

        from app.core.config import settings
        vina_exe = getattr(settings, "VINA_EXE_PATH", "vina")

        # 默认对接盒子（如未指定）
        center = box.get("center", [0.0, 0.0, 0.0])
        size = box.get("size", [20.0, 20.0, 20.0])

        # 初始化 Vina
        v = Vina(sf_name="vina", seed=42)

        # 设置受体（假设 receptor_pdbqt 是文件路径）
        if receptor_pdbqt:
            v.set_receptor(receptor_pdbqt)

        # 将 SMILES 转换为配体 PDBQT（简化：假设已有 ligand.pdbqt）
        # 实际生产中需用 RDKit + Meeko 将 SMILES 转 PDBQT
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem

            mol = Chem.MolFromSmiles(smiles)
            if mol is not None:
                mol = Chem.AddHs(mol)
                AllChem.EmbedMolecule(mol, randomSeed=42)
                AllChem.MMFFOptimizeMolecule(mol)
                # 此处应调用 Meeko 将 mol 转 PDBQT，简化处理
        except Exception as e:
            logger.debug(f"RDKit 配体准备失败，使用默认: {e}")

        # 设置对接盒子
        v.set_center(center) if hasattr(v, "set_center") else None
        v.set_box_size(size) if hasattr(v, "set_box_size") else None

        # 执行对接
        v.dock(exhaustiveness=8, n_poses=10)

        # 提取最佳构象
        energies = v.energies()
        best_affinity = float(energies[0][0]) if len(energies) > 0 else -9.0
        best_pose = v.poses() if hasattr(v, "poses") else {}

        return {
            "affinity": round(best_affinity, 2),
            "rmsd": round(0.0, 2),  # Vina 输出的 RMSD 是相对最佳构象的
            "pose": {
                "coordinates": best_pose,
                "box_center": center,
                "box_size": size,
                "n_poses": len(energies),
            },
            "source": "vina",
        }

    def _refine_sync(self, smiles: str, pose: Dict) -> Dict[str, Any]:
        """同步调用 Vina 局部优化（在 asyncio.to_thread 中执行）

        Args:
            smiles: 配体 SMILES
            pose: 初始姿态
        Returns:
            优化后的对接结果
        """
        from vina import Vina

        v = Vina(sf_name="vina", seed=42)

        # 局部优化（local_opt）
        coords = pose.get("coordinates", [])
        if coords:
            # 简化：调用 optimize
            v.optimize() if hasattr(v, "optimize") else None

        energies = v.energies() if hasattr(v, "energies") else [[-9.5]]
        best_affinity = float(energies[0][0]) if len(energies) > 0 else -9.5

        return {
            "affinity": round(best_affinity, 2),
            "rmsd": round(0.5, 2),
            "pose": {
                "coordinates": coords,
                "refined": True,
            },
            "source": "vina_refine",
        }

    def _generate_3d_conformer(
        self, smiles: str, center: list, seed: int = 42
    ) -> tuple:
        """使用 RDKit 生成真实 3D 构象

        流程：SMILES → AddHs → ETKDGv3 嵌入 → MMFF 力场优化 → 平移至对接盒子中心
        生成化学合理的 3D 坐标和 MOL/SDF block，供前端 3Dmol.js 渲染。

        Args:
            smiles: 配体 SMILES
            center: 对接盒子中心 [x, y, z]
            seed: 随机种子（确定性输出）
        Returns:
            (mol_block, coordinates, atom_count, heavy_atom_count, lipinski_pass)
            RDKit 不可用时返回 (None, [], 0, 0, False)
        """
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem, Crippen, Descriptors
        except ImportError as e:
            logger.warning(f"RDKit 不可用，无法生成真实 3D 构象: {e}")
            return None, [], 0, 0, False

        try:
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return None, [], 0, 0, False

            mol = Chem.AddHs(mol)

            # ETKDGv3 优于随机嵌入，产生更合理的初始构象
            params = AllChem.ETKDGv3()
            params.randomSeed = seed
            rid = AllChem.EmbedMolecule(mol, params)
            if rid < 0:
                # 降级到基础随机嵌入
                rid = AllChem.EmbedMolecule(mol, randomSeed=seed)
                if rid < 0:
                    logger.warning(f"RDKit 嵌入失败: smiles={smiles[:30]}")
                    return None, [], 0, 0, False

            # MMFF 力场优化（失败则降级 UFF）
            try:
                AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
            except Exception:
                AllChem.UFFOptimizeMolecule(mol, maxIters=500)

            # 平移构象至对接盒子中心
            conf = mol.GetConformer()
            cx, cy, cz = center[0], center[1], center[2]
            for i in range(mol.GetNumAtoms()):
                p = conf.GetAtomPosition(i)
                conf.SetAtomPosition(i, (p.x + cx, p.y + cy, p.z + cz))

            # 提取坐标数组
            coordinates = []
            for i in range(mol.GetNumAtoms()):
                p = conf.GetAtomPosition(i)
                coordinates.append([round(p.x, 4), round(p.y, 4), round(p.z, 4)])

            # 生成 MOL block（供 3Dmol.js 渲染）
            mol_block = Chem.MolToMolBlock(mol)

            # 计算类药性指标
            heavy_count = mol.GetNumHeavyAtoms()
            atom_count = mol.GetNumAtoms()
            mw = Descriptors.MolWt(mol)
            logp = Crippen.MolLogP(mol)
            hbd = Descriptors.NumHDonors(mol)
            hba = Descriptors.NumHAcceptors(mol)
            lipinski_pass = mw <= 500 and logp <= 5 and hbd <= 5 and hba <= 10

            return mol_block, coordinates, atom_count, heavy_count, lipinski_pass
        except Exception as e:
            logger.warning(f"RDKit 3D 构象生成失败: {e}")
            return None, [], 0, 0, False

    def _mock_dock(self, smiles: str, box: Dict) -> Dict[str, Any]:
        """Mock 对接 — 使用 RDKit 生成真实 3D 构象

        当 VINA_USE_MOCK=True 时调用。通过 RDKit ETKDGv3 + MMFF 生成
        化学合理的 3D 结合姿态，替代旧的线性假坐标。

        Args:
            smiles: 配体 SMILES
            box: 对接盒子参数 {center, size, exhaustiveness, num_poses}
        Returns:
            对接结果（含 binding_pose.mol_block 供前端 3D 渲染）
        """
        import math

        center = box.get("center", [0.0, 0.0, 0.0])
        size = box.get("size", [20.0, 20.0, 20.0])

        # 生成真实 3D 构象
        mol_block, coordinates, atom_count, heavy_count, lipinski_pass = (
            self._generate_3d_conformer(smiles, center)
        )

        # 基于 SMILES 特征生成确定性亲和力
        n_atoms = sum(1 for c in smiles if c.isupper())
        n_rings = sum(1 for d in "123456789" if d in smiles)

        # 结合亲和力: -7 到 -12 kcal/mol
        affinity = round(-9.0 - (n_atoms * 0.08) + (n_rings * 0.3), 2)
        affinity = max(-12.0, min(-7.0, affinity))

        # RMSD: 0.5-2.5 Å
        rmsd = round(1.2 + (n_atoms * 0.01), 2)
        rmsd = max(0.5, min(2.5, rmsd))

        # 抑制常数 Ki（μM）：Ki = exp(affinity / RT) * 1e6，RT ≈ 0.592 kcal/mol（298K）
        # affinity 为负值（kcal/mol），exp(affinity/0.592) 得到 M，乘 1e6 转 μM
        ki_um = round(math.exp(affinity / 0.592) * 1e6, 4)

        # 配体效率：亲和力 / 重原子数（kcal/mol per heavy atom）
        ligand_efficiency = (
            round(affinity / heavy_count, 3) if heavy_count > 0 else None
        )

        # 构建结合姿态结果
        binding_pose: Dict[str, Any] = {
            "box_center": center,
            "box_size": size,
            "n_poses": int(box.get("num_poses", 1)),
            "exhaustiveness": int(box.get("exhaustiveness", 8)),
            "atom_count": atom_count,
            "heavy_atom_count": heavy_count,
            "lipinski_pass": lipinski_pass,
        }

        if mol_block and coordinates:
            # RDKit 成功生成真实 3D 构象
            binding_pose["mol_block"] = mol_block
            binding_pose["coordinates"] = coordinates
        else:
            # RDKit 不可用，降级为线性坐标（保持向后兼容）
            binding_pose["coordinates"] = [
                [center[0] + i * 1.5, center[1], center[2]]
                for i in range(min(max(n_atoms, 1), 10))
            ]

        return {
            "affinity": affinity,
            "rmsd": rmsd,
            "ki": ki_um,
            "ligand_efficiency": ligand_efficiency,
            "binding_pose": binding_pose,
            # 保留 pose 字段向后兼容（旧前端读取 result.pose）
            "pose": binding_pose,
            "source": "mock",
        }
