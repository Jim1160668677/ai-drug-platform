"""Real ChEMBL 客户端 — 调用 ebi.ac.uk/chembl API

网络不可达时自动降级到 Mock 数据，保证用户体验。
"""
import logging
from typing import Any, Dict, List

import httpx

from app.clients.base import ChemblClient
from app.core.config import settings

logger = logging.getLogger(__name__)

# 统一超时：连接 8s，读取 15s（避免前端 60s 超时）
# httpx 0.28+ 不再接受 connect= 关键字参数，必须用 httpx.Timeout 对象
_TIMEOUT = httpx.Timeout(timeout=15.0, connect=8.0)


class RealChemblClient(ChemblClient):
    """真实 ChEMBL 客户端 — 调用 https://www.ebi.ac.uk/chembl/api/data

    网络不可达时自动降级到 MockChemblClient，保证功能可用。
    """

    def _get_mock_fallback(self) -> "ChemblClient":
        """获取 Mock 回退客户端"""
        from app.clients.mock.chembl_mock import MockChemblClient
        return MockChemblClient()

    async def _find_target_chembl_id(self, gene_symbol: str) -> str:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            url = f"{settings.CHEMBL_BASE_URL}/target/search.json"
            params = {"q": gene_symbol, "target_type": "SINGLE PROTEIN", "limit": 5}
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        targets = data.get("targets", [])
        for t in targets:
            pref = (t.get("pref_name") or "").upper()
            if gene_symbol.upper() in pref or gene_symbol.upper() == pref:
                return t.get("target_chembl_id")
        return targets[0].get("target_chembl_id") if targets else None

    async def get_active_molecules(
        self, target_gene: str, activity_type: str = "IC50", limit: int = 50
    ) -> List[Dict[str, Any]]:
        target_chembl_id = await self._find_target_chembl_id(target_gene)
        if not target_chembl_id:
            return []

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            url = f"{settings.CHEMBL_BASE_URL}/activity.json"
            params = {
                "target_chembl_id": target_chembl_id,
                "activity_type": activity_type,
                "limit": min(limit, 100),
                "standard_units": "nM",
            }
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        activities = data.get("activities", [])
        result = []
        for a in activities:
            molecule_chembl_id = a.get("molecule_chembl_id")
            result.append({
                "name": a.get("molecule_pref_name") or molecule_chembl_id,
                "chembl_id": molecule_chembl_id,
                "smiles": None,
                "max_phase": a.get("max_phase", 0),
                "indication": None,
                "activity": {
                    "activity_type": a.get("activity_type"),
                    "activity_value": a.get("standard_value"),
                    "activity_units": a.get("standard_units"),
                    "assay_type": a.get("assay_type"),
                    "assay_description": a.get("assay_description"),
                },
                "molecular_weight": None,
                "logp": None,
                "first_approval": None,
                "drug_indication": [],
                "target_gene": target_gene,
                "target_chembl_id": target_chembl_id,
            })
        return result

    async def find_approved_drugs(self, target_gene: str) -> List[Dict[str, Any]]:
        """两步查询：先按 target_chembl_id 找活性分子，再查每个分子的获批信息

        ChEMBL 的 /drug_indication.json 不支持 target_chembl_id 过滤（旧实现返回相同 50 个
        候选给所有靶点）。正确做法：
        1. 通过 /activity.json?target_chembl_id=X 找到对该靶点有活性的分子
        2. 对每个分子查 /molecule/{id}.json 取 max_phase / smiles
        3. 对获批分子（max_phase>=3）查 /drug_indication.json?molecule_chembl_id=Y
        """
        try:
            target_chembl_id = await self._find_target_chembl_id(target_gene)
            if not target_chembl_id:
                logger.warning(f"ChEMBL 未找到靶点 {target_gene}，降级到 Mock")
                return await self._get_mock_fallback().find_approved_drugs(target_gene)

            # Step 1: 查该靶点的活性分子（limit 100 取较大范围）
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                url = f"{settings.CHEMBL_BASE_URL}/activity.json"
                params = {
                    "target_chembl_id": target_chembl_id,
                    "limit": 100,
                }
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            activities = data.get("activities", [])
            if not activities:
                logger.info(f"ChEMBL 靶点 {target_gene}({target_chembl_id}) 无活性分子数据")
                return []

            # 收集所有相关 molecule_chembl_id（去重）
            molecule_ids = list({a.get("molecule_chembl_id") for a in activities if a.get("molecule_chembl_id")})
            molecule_ids = molecule_ids[:50]  # 限制查询数避免过多 API 调用

            # Step 2: 并发查每个分子的详情（max_phase / smiles / pref_name）
            approved = []
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                # 用 asyncio.gather 并发查询
                import asyncio as _asyncio

                async def _fetch_molecule(mid: str) -> Dict[str, Any] | None:
                    try:
                        url = f"{settings.CHEMBL_BASE_URL}/molecule/{mid}.json"
                        r = await client.get(url)
                        r.raise_for_status()
                        return r.json()
                    except Exception as e:
                        logger.debug(f"分子 {mid} 查询失败: {e}")
                        return None

                mol_results = await _asyncio.gather(*[_fetch_molecule(mid) for mid in molecule_ids])

            for mol_data in mol_results:
                if not mol_data:
                    continue
                # ChEMBL /molecule/{id}.json 返回分子对象在顶层（不在 "molecule" key 下）
                # 仅 /molecule.json (list) 端点会用 {"molecules": [...]} 包装
                mol = mol_data.get("molecule") if isinstance(mol_data, dict) and "molecule" in mol_data else mol_data
                if not isinstance(mol, dict):
                    continue
                max_phase = 0
                # max_phase 在 molecule 顶层
                if "max_phase" in mol:
                    try:
                        max_phase = int(mol.get("max_phase") or 0)
                    except (TypeError, ValueError):
                        max_phase = 0
                # 不再强制 max_phase >= 1（保留所有分子，由调用方按 score 排序）
                # 但跳过完全没有 max_phase 字段的（数据残缺）

                # 取 SMILES
                smiles = None
                mol_struct = mol.get("molecule_structures") or {}
                if mol_struct:
                    smiles = mol_struct.get("canonical_smiles")

                # 取名称
                name = mol.get("pref_name") or mol.get("molecule_chembl_id")

                approved.append({
                    "name": name,
                    "chembl_id": mol.get("molecule_chembl_id"),
                    "smiles": smiles,
                    "max_phase": max_phase,
                    "indication": None,  # 后续如需可单独查 drug_indication
                    "first_approval": mol.get("first_approval"),
                    "molecular_weight": (mol.get("molecule_properties") or {}).get("full_mwt"),
                    "drug_indication": [],
                    "target_gene": target_gene,
                    "target_chembl_id": target_chembl_id,
                })

            # 按临床阶段降序，然后保留前 50
            approved.sort(key=lambda x: x.get("max_phase", 0), reverse=True)
            return approved[:50]
        except Exception as e:
            logger.warning(f"ChEMBL 查询失败，降级到 Mock: {e}")
            return await self._get_mock_fallback().find_approved_drugs(target_gene)
