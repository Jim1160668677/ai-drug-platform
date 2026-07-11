"""老药新用引擎 — ChEMBL 查询 + RDKit 类药性评估"""
import logging
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_chembl_client

logger = logging.getLogger(__name__)


class DrugRepurposer:
    """老药新用扫描 — 已获批药物重定位"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def repurpose(self, target) -> Dict[str, Any]:
        """对靶点执行老药新用扫描

        Args:
            target: Target ORM 对象（含 gene_symbol）
        Returns:
            {candidates: [...], count, target_gene}
        """
        gene = target.gene_symbol

        try:
            client = get_chembl_client()
            approved_drugs = await client.find_approved_drugs(gene)
        except Exception as e:
            logger.warning(f"ChEMBL 查询失败: {e}")
            approved_drugs = []

        candidates = []
        for drug in approved_drugs:
            # RDKit 计算类药性
            properties = self._compute_properties(drug.get("smiles")) if drug.get("smiles") else {}

            score = self._score_candidate(drug, properties)

            candidates.append({
                "name": drug.get("name"),
                "chembl_id": drug.get("chembl_id"),
                "smiles": drug.get("smiles"),
                "max_phase": drug.get("max_phase", 0),
                "indication": drug.get("indication"),
                "first_approval": drug.get("first_approval"),
                "molecular_weight": properties.get("mw") or drug.get("molecular_weight"),
                "logp": properties.get("logp"),
                "druglikeness_score": score,
                "passes_rule_of_five": properties.get("passes_rule_of_five", True),
                "drug_indication": drug.get("drug_indication", []),
            })

        candidates.sort(key=lambda x: x["druglikeness_score"], reverse=True)

        return {
            "candidates": candidates,
            "count": len(candidates),
            "target_gene": gene,
            "source": "chembl",
        }

    def _compute_properties(self, smiles: str) -> Dict[str, Any]:
        """用 RDKit 计算分子性质"""
        if not smiles:
            return {}
        try:
            from rdkit import Chem
            from rdkit.Chem import Descriptors, Crippen, Lipinski

            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return {"error": "无效 SMILES"}

            mw = Descriptors.MolWt(mol)
            logp = Crippen.MolLogP(mol)
            hbd = Descriptors.NumHDonors(mol)
            hba = Descriptors.NumHAcceptors(mol)
            rotatable = Descriptors.NumRotatableBonds(mol)
            tpsa = Descriptors.TPSA(mol)

            violations = []
            if mw > 500: violations.append("MW>500")
            if logp > 5: violations.append("LogP>5")
            if hbd > 5: violations.append("HBD>5")
            if hba > 10: violations.append("HBA>10")

            return {
                "mw": round(mw, 2),
                "logp": round(logp, 2),
                "hbd": hbd,
                "hba": hba,
                "rotatable_bonds": rotatable,
                "tpsa": round(tpsa, 2),
                "passes_rule_of_five": len(violations) == 0,
                "violations": violations,
            }
        except ImportError:
            return {"note": "RDKit 未安装，跳过性质计算"}
        except Exception as e:
            return {"error": str(e)}

    def _score_candidate(self, drug: Dict, properties: Dict) -> float:
        """候选药物评分（0-100）"""
        score = 0.0

        # 已获批（max_phase=4）加 40 分
        max_phase = drug.get("max_phase", 0) or 0
        score += min(40, max_phase * 10)

        # 类药性（通过 Lipinski 加 30 分）
        if properties.get("passes_rule_of_five", True):
            score += 30
        elif properties.get("violations"):
            score += max(0, 30 - 10 * len(properties.get("violations", [])))

        # 适应症匹配（含 cancer 关键词加 20 分）
        indication = (drug.get("indication") or "").lower()
        if "cancer" in indication or "tumor" in indication or "carcinoma" in indication:
            score += 20

        # 分子量合理范围加 10 分
        mw = properties.get("mw") or drug.get("molecular_weight") or 0
        if 200 <= mw <= 600:
            score += 10

        return round(min(score, 100), 2)
