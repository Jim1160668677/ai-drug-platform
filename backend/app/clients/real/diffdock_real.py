"""Real DiffDock 客户端 — 调用 NVIDIA NIM DiffDock API"""
import asyncio
import time
from typing import Any, Dict

from app.clients.base import DiffdockClient
from app.core.config import settings


class RealDiffdockClient(DiffdockClient):
    """真实 DiffDock 客户端 — 通过 NVIDIA NIM 调用"""

    async def dock(self, protein_pdb: str, ligand_smiles: str, num_poses: int = 10) -> Dict[str, Any]:
        import httpx

        if not settings.NVIDIA_NIM_API_KEY:
            raise RuntimeError(
                "NVIDIA_NIM_API_KEY 未配置。请在 .env 设置 NVIDIA_NIM_API_KEY 并 USE_MOCK=false"
            )

        url = settings.DIFFDOCK_NIM_URL
        headers = {
            "Authorization": f"Bearer {settings.NVIDIA_NIM_API_KEY}",
            "Accept": "application/json",
        }
        payload = {
            "protein": protein_pdb,
            "ligand": ligand_smiles,
            "num_poses": num_poses,
        }

        async with httpx.AsyncClient(timeout=600.0) as client:
            # 提交任务
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            job = resp.json()
            job_id = job.get("id") or job.get("job_id")

            if not job_id:
                # 同步响应直接返回结果
                return self._parse_response(job, protein_pdb, ligand_smiles, num_poses)

            # 轮询状态
            status_url = f"{url}/{job_id}"
            for _ in range(120):  # 最多等待 10 分钟
                await asyncio.sleep(5.0)
                poll = await client.get(status_url, headers=headers)
                poll.raise_for_status()
                poll_data = poll.json()
                status = poll_data.get("status", "").lower()
                if status in ("completed", "succeeded", "success"):
                    return self._parse_response(poll_data, protein_pdb, ligand_smiles, num_poses)
                if status in ("failed", "error"):
                    return {
                        "poses": [],
                        "status": "failed",
                        "error": poll_data.get("error", "DiffDock 任务失败"),
                        "job_id": job_id,
                    }

            return {
                "poses": [],
                "status": "timeout",
                "error": "DiffDock 任务超时（>10 分钟）",
                "job_id": job_id,
            }

    def _parse_response(self, data: Dict, protein_pdb: str, ligand_smiles: str, num_poses: int) -> Dict[str, Any]:
        poses_raw = data.get("poses") or data.get("results") or []
        poses = []
        for i, p in enumerate(poses_raw, start=1):
            poses.append({
                "rank": p.get("rank", i),
                "confidence": p.get("confidence") or p.get("score"),
                "positions": p.get("positions") or p.get("coords") or [],
                "scores": p.get("scores") or [],
                "smiles": p.get("ligand_smiles", ligand_smiles),
                "num_atoms": len(p.get("positions") or p.get("coords") or []) // 3,
                "binding_affinity_pred_kd": p.get("binding_affinity"),
            })
        poses.sort(key=lambda x: x["confidence"] or 0, reverse=True)
        for idx, p in enumerate(poses, start=1):
            p["rank"] = idx

        return {
            "poses": poses,
            "status": "completed",
            "num_poses": len(poses),
            "protein_pdb_size": len(protein_pdb),
            "ligand_smiles": ligand_smiles,
            "best_confidence": poses[0]["confidence"] if poses else 0.0,
            "job_id": data.get("id") or data.get("job_id"),
            "mock": False,
        }
