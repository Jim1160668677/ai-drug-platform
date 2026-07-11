"""Mock DiffDock 客户端 — 生成模拟分子对接构象"""
import asyncio
import hashlib
import math
import struct
from typing import List

from app.clients.base import DiffdockClient


def _seeded_random(seed_str: str) -> float:
    """基于种子字符串生成 0-1 伪随机数（确保可复现）"""
    h = hashlib.sha256(seed_str.encode("utf-8")).digest()
    return struct.unpack("I", h[:4])[0] / 4294967295.0


def _generate_pose(protein_pdb: str, ligand_smiles: str, rank: int, num_poses: int) -> dict:
    """生成单个模拟对接构象"""
    seed = f"{ligand_smiles}|{rank}|{len(protein_pdb)}"
    base_confidence = _seeded_random(seed)
    confidence = max(0.05, min(0.98, base_confidence - (rank - 1) * 0.08))

    # 模拟原子坐标（20 个原子，围绕中心扩散）
    positions = []
    num_atoms = 20
    for i in range(num_atoms):
        angle = 2 * math.pi * i / num_atoms
        radius = 2.5 + _seeded_random(f"{seed}-r{i}") * 3.5
        x = radius * math.cos(angle) + (_seeded_random(f"{seed}-x{i}") - 0.5) * 2
        y = radius * math.sin(angle) + (_seeded_random(f"{seed}-y{i}") - 0.5) * 2
        z = (_seeded_random(f"{seed}-z{i}") - 0.5) * 4
        positions.append([round(x, 3), round(y, 3), round(z, 3)])

    scores = [
        round(confidence * 10 - (_seeded_random(f"{seed}-s{i}") - 0.5) * 2, 3)
        for i in range(3)
    ]

    return {
        "rank": rank,
        "confidence": round(confidence, 4),
        "positions": positions,
        "scores": scores,
        "smiles": ligand_smiles,
        "num_atoms": num_atoms,
        "binding_affinity_pred_kd": round(10 ** (-confidence * 6 - 3), 2),  # 模拟 Kd (μM)
    }


class MockDiffdockClient(DiffdockClient):
    """Mock DiffDock 客户端 — 生成确定性可复现的模拟构象"""

    async def dock(self, protein_pdb: str, ligand_smiles: str, num_poses: int = 10) -> dict:
        await asyncio.sleep(0.8)

        actual_poses = min(max(num_poses, 1), 20)
        poses = [
            _generate_pose(protein_pdb, ligand_smiles, rank, actual_poses)
            for rank in range(1, actual_poses + 1)
        ]

        poses.sort(key=lambda p: p["confidence"], reverse=True)
        for idx, p in enumerate(poses, start=1):
            p["rank"] = idx

        return {
            "poses": poses,
            "status": "completed",
            "num_poses": len(poses),
            "protein_pdb_size": len(protein_pdb),
            "ligand_smiles": ligand_smiles,
            "best_confidence": poses[0]["confidence"] if poses else 0.0,
            "mock": True,
        }
