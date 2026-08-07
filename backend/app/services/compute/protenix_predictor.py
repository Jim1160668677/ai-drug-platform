"""Protenix 蛋白结构预测引擎 — 集成字节跳动 bytedance/Protenix

GitHub: https://github.com/bytedance/Protenix
论文: Protenix — 字节跳动开源的蛋白-配体复合物结构预测模型

Protenix 的核心优势（相对于 ESMFold）：
1. 支持蛋白-配体复合物结构预测（蛋白 + 小分子药物 + 离子 + 修饰残基）
2. 输出结合位点信息和配体坐标（可用于药物-靶点结合可视化）
3. 集成 AlphaFold3 同等能力，开源可商用

集成方式（HTTP API 模式）：
- 通过环境变量 PROTENIX_API_URL 配置 Protenix 服务地址
- Protenix 服务独立部署（推荐 Docker 容器化运行）
- 主应用通过 HTTP 调用 Protenix 推断接口

部署 Protenix 服务（用户自行）：
    # 1. 克隆仓库
    git clone https://github.com/bytedance/Protenix
    cd Protenix

    # 2. 拉取模型权重（按 README 操作）
    # 3. 启动推断服务（示例 HTTP 接口）
    python -m protenix.serve --port 8001

    # 4. 在 .env 配置：PROTENIX_API_URL=http://localhost:8001

Mock 模式（未配置 PROTENIX_API_URL 时）：
- 生成伪造的 PDB 文本（沿用 ESMFoldPredictor 的 Mock 策略）
- 附加假想的配体坐标（用于前端结合位点可视化演示）
"""
import asyncio
import logging
import math
import time
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ProtenixPredictor:
    """Protenix 蛋白结构预测器（HTTP API 模式）

    通过 HTTP 调用独立的 Protenix 服务，支持：
    - 蛋白结构预测（输出 PDB + pLDDT）
    - 蛋白-配体复合物结构预测（输出 PDB + 配体坐标 + 结合位点）
    """

    def __init__(self, db: AsyncSession = None):
        """初始化

        Args:
            db: 异步数据库会话（可选）
        """
        self.db = db
        self._api_url: Optional[str] = None
        self._timeout: float = 300.0  # 默认 5 分钟，会被 settings 覆盖

    def _get_api_url(self) -> Optional[str]:
        """获取 Protenix 服务地址（懒加载）

        当 PROTENIX_USE_MOCK=False 且配置了 PROTENIX_API_URL 时返回真实地址。
        """
        if self._api_url is not None:
            return self._api_url if self._api_url else None
        from app.core.config import settings
        # 同步超时配置
        self._timeout = float(getattr(settings, "PROTENIX_TIMEOUT_SEC", 300))
        use_mock = getattr(settings, "PROTENIX_USE_MOCK", True)
        url = getattr(settings, "PROTENIX_API_URL", "") or ""
        # use_mock=True 时强制走 Mock；否则按 API_URL 是否配置决定
        if use_mock:
            url = ""
        # 缓存结果（即使为空也缓存，避免每次都读 settings）
        self._api_url = url
        return url or None

    async def predict_structure(
        self,
        sequence: str,
        target_id: str = "",
        ligand_smiles: Optional[str] = None,
    ) -> Dict[str, Any]:
        """预测蛋白质结构（可选含配体）

        Args:
            sequence: 氨基酸序列
            target_id: 靶点 ID（用于日志）
            ligand_smiles: 配体 SMILES（可选，传入后预测复合物）
        Returns:
            {
                pdb_text, plddt_mean, storage_path, source, model_name,
                ligand_coordinates: List[[x, y, z]],   # 配体原子坐标（若有）
                binding_site_residues: List[int],       # 结合位点残基索引（若有）
                duration_sec
            }
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

        api_url = self._get_api_url()
        start_time = time.time()

        if api_url:
            # 真实模式：调用 Protenix HTTP 服务
            try:
                result = await self._predict_via_api(api_url, sequence, ligand_smiles)
                duration = round(time.time() - start_time, 2)
                result["duration_sec"] = duration
                logger.info(
                    f"Protenix 真实预测完成: target={target_id}, len={len(sequence)}, "
                    f"plddt={result.get('plddt_mean', 0)}, 耗时={duration}s"
                )
                return result
            except Exception as e:
                logger.warning(
                    f"Protenix HTTP 调用失败，降级 Mock 模式: {e}"
                )

        # Mock 模式
        result = self._mock_predict(sequence, ligand_smiles)
        duration = round(time.time() - start_time, 2)
        result["duration_sec"] = duration
        logger.info(
            f"Protenix Mock 预测完成: target={target_id}, len={len(sequence)}, "
            f"耗时={duration}s"
        )
        return result

    async def _predict_via_api(
        self,
        api_url: str,
        sequence: str,
        ligand_smiles: Optional[str],
    ) -> Dict[str, Any]:
        """通过 HTTP API 调用 Protenix 服务

        Args:
            api_url: Protenix 服务地址（如 http://localhost:8001）
            sequence: 氨基酸序列
            ligand_smiles: 配体 SMILES（可选）
        Returns:
            Protenix 推断结果
        """
        payload = {
            "sequence": sequence,
            "ligand_smiles": ligand_smiles,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{api_url.rstrip('/')}/v1/predict",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

        return {
            "pdb_text": data.get("pdb_text", ""),
            "plddt_mean": float(data.get("plddt_mean", 0.0)),
            "storage_path": "",
            "source": "protenix",
            "model_name": "protenix_v1",
            "ligand_coordinates": data.get("ligand_coordinates", []),
            "binding_site_residues": data.get("binding_site_residues", []),
            "confidence_per_residue": data.get("confidence_per_residue", []),
        }

    def _mock_predict(
        self,
        sequence: str,
        ligand_smiles: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Mock 预测 — 生成伪造但格式合法的 PDB 文本

        生成 alpha 螺旋结构的 PDB 文本，并附加假想的配体坐标（若提供 SMILES）。

        Args:
            sequence: 氨基酸序列
            ligand_smiles: 配体 SMILES（可选）
        Returns:
            伪造的预测结果
        """
        three_letter = {
            "A": "ALA", "R": "ARG", "N": "ASN", "D": "ASP", "C": "CYS",
            "E": "GLU", "Q": "GLN", "G": "GLY", "H": "HIS", "I": "ILE",
            "L": "LEU", "K": "LYS", "M": "MET", "F": "PHE", "P": "PRO",
            "S": "SER", "T": "THR", "W": "TRP", "Y": "TYR", "V": "VAL",
        }

        pdb_lines = [
            "HEADER    MOCK STRUCTURE (PROTENIX)",
            "TITLE     PROTENIX MOCK PREDICTION",
            f"REMARK   1 SEQUENCE LENGTH: {len(sequence)}",
            "REMARK   2 ENGINE: protenix (mock)",
            "REMARK   3 PROOF-OF-CONCEPT — INSTALL PROTENIX FOR REAL PREDICTIONS",
        ]

        # 生成蛋白原子坐标（alpha 螺旋）
        binding_site_residues: List[int] = []
        for i, aa in enumerate(sequence):
            res_name = three_letter.get(aa, "GLY")
            res_seq = i + 1
            # 蛋白坐标：alpha 螺旋
            x = round(2.3 * math.cos(math.radians(100 * i)), 3)
            y = round(2.3 * math.sin(math.radians(100 * i)), 3)
            z = round(1.5 * i, 3)
            # Mock pLDDT 0.5-0.95 之间随机
            plddt = round(0.5 + 0.45 * ((i * 7) % 100) / 100.0, 2)
            atom_line = (
                f"ATOM  {res_seq:5d}  CA  {res_name} A{res_seq:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 {plddt * 100:5.2f}           C"
            )
            pdb_lines.append(atom_line)
            # 中间 30% 的残基作为结合位点（演示用）
            if int(len(sequence) * 0.35) <= i <= int(len(sequence) * 0.65):
                binding_site_residues.append(res_seq)

        # 配体坐标（如果提供了 SMILES）
        ligand_coordinates: List[List[float]] = []
        if ligand_smiles:
            # 模拟配体原子坐标：摆放在结合口袋中央（约在蛋白序列中间）
            center_residue = len(sequence) // 2
            center_x = 0.0
            center_y = 0.0
            center_z = 1.5 * center_residue
            # 基于 SMILES 长度生成假想原子数
            n_ligand_atoms = max(5, min(30, sum(1 for c in ligand_smiles if c.isupper())))
            for i in range(n_ligand_atoms):
                # 围绕结合口袋中心散布
                lx = round(center_x + 1.5 * math.cos(math.radians(60 * i)), 3)
                ly = round(center_y + 1.5 * math.sin(math.radians(60 * i)), 3)
                lz = round(center_z + 0.5 * i, 3)
                ligand_coordinates.append([lx, ly, lz])

            # 在 PDB 中加入 HETATM 记录（配体原子）
            pdb_lines.append("TER")
            pdb_lines.append(f"REMARK   4 LIGAND: {ligand_smiles[:60]}")
            pdb_lines.append(f"REMARK   5 LIGAND ATOMS: {n_ligand_atoms}")
            for i, (lx, ly, lz) in enumerate(ligand_coordinates):
                atom_idx = len(sequence) + i + 1
                het_line = (
                    f"HETATM{atom_idx:5d}  C   LIG A   1     "
                    f"{lx:8.3f}{ly:8.3f}{lz:8.3f}  1.00 50.00           C"
                )
                pdb_lines.append(het_line)

        pdb_lines.append("TER")
        pdb_lines.append("END")
        pdb_text = "\n".join(pdb_lines) + "\n"

        return {
            "pdb_text": pdb_text,
            "plddt_mean": 0.82,
            "storage_path": "",
            "source": "protenix_mock",
            "model_name": "protenix_v1_mock",
            "ligand_coordinates": ligand_coordinates,
            "binding_site_residues": binding_site_residues,
        }

    async def predict_complex(
        self,
        sequence: str,
        ligand_smiles: str,
        target_id: str = "",
    ) -> Dict[str, Any]:
        """预测蛋白-配体复合物结构

        Args:
            sequence: 蛋白氨基酸序列
            ligand_smiles: 配体 SMILES
            target_id: 靶点 ID
        Returns:
            {pdb_text, plddt_mean, ligand_coordinates, binding_site_residues, ...}
        """
        return await self.predict_structure(sequence, target_id, ligand_smiles)
