"""分子设计引擎 — DeepChem 性质预测 + RDKit 类药性评估"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MoleculeDesigner:
    """分子设计器 — P2 阶段使用 DeepChem，P0 提供框架"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def design(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """分子设计

        Args:
            payload: {target_id, smiles(种子), constraints}
        Returns:
            {designed_molecules, model_info}
        """
        target_id = payload.get("target_id")
        seed_smiles = payload.get("smiles")
        constraints = payload.get("constraints") or {}

        # 尝试加载 DeepChem（P2）
        try:
            import deepchem as dc
            return await self._design_with_deepchem(seed_smiles, constraints, dc)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"DeepChem 设计失败，降级: {e}")

        # DeepChem 不可用 — 降级到片段组合 + RDKit 类药性评估
        strategy = "optimization" if seed_smiles else "fragment"
        gen_result = await self.generate_molecules(
            target_id=target_id or "unknown",
            strategy=strategy,
            n=10,
            seed_smiles=seed_smiles,
            constraints=constraints,
        )

        molecules = gen_result.get("molecules", [])
        # 为每个分子附加类药性评估结果
        designed = []
        for mol in molecules:
            smiles = mol.get("smiles", "")
            props = assess_druglikeness(smiles)
            designed.append({
                "smiles": smiles,
                "source": mol.get("source", strategy),
                "properties": props,
                "predicted_toxicity": max(0.0, 1.0 - props.get("druglikeness_score", 50) / 100),
            })

        # 按类药性评分排序，取前 5 个
        designed.sort(key=lambda m: m.get("properties", {}).get("druglikeness_score", 0), reverse=True)
        designed = designed[:5]

        return {
            "designed_molecules": designed,
            "model_info": {
                "status": "rdkit_fallback",
                "message": "DeepChem 未安装，已降级为 RDKit 片段组合 + 类药性评估",
                "strategy": strategy,
                "target_id": target_id,
                "seed_smiles": seed_smiles,
                "constraints": constraints,
            },
        }

    async def _design_with_deepchem(
        self,
        seed_smiles: str,
        constraints: Dict,
        dc,
    ) -> Dict[str, Any]:
        """P2 实现 — DeepChem GraphConvModel 性质预测"""
        import numpy as np

        # 1. 加载预训练模型（毒性/活性预测）
        try:
            tasks, datasets, transformers = dc.molnet.load_tox21()
            model = dc.models.GraphConvModel(len(tasks), mode="classification")
            model.restore()  # 假设已有 checkpoint
        except Exception as e:
            logger.warning(f"DeepChem 模型加载失败: {e}")
            return {
                "designed_molecules": [],
                "model_info": {"status": "model_load_failed", "error": str(e)},
            }

        # 2. 基于种子 SMILES 生成类似分子（简化：仅评估种子）
        if seed_smiles:
            from rdkit import Chem
            mol = Chem.MolFromSmiles(seed_smiles)
            if mol:
                feats = dc.feat.ConvMolFeaturizer().featurize([mol])
                preds = model.predict(feats)
                return {
                    "designed_molecules": [{
                        "smiles": seed_smiles,
                        "predicted_toxicity": float(np.mean(preds[0])),
                        "properties": assess_druglikeness(seed_smiles),
                    }],
                    "model_info": {
                        "status": "deepchem_predicted",
                        "model": "GraphConvModel(tox21)",
                        "n_tasks": len(tasks),
                    },
                }

        return {
            "designed_molecules": [],
            "model_info": {"status": "no_seed_smiles"},
        }

    async def generate_molecules(
        self,
        target_id: str,
        strategy: str = "fragment",
        n: int = 10,
        seed_smiles: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成新分子

        三种生成策略：
        - fragment: 基于片段组合（优先）
        - optimization: 基于种子分子优化
        - random: 随机生成（骨架 + 取代基）

        Args:
            target_id: 靶点 ID
            strategy: 生成策略（fragment / optimization / random）
            n: 生成数量
            seed_smiles: 种子分子（optimization 策略必需）
            constraints: 约束条件（mw, logp 等范围）
        Returns:
            {"molecules": [...], "strategy": ..., "count": n}
        """
        constraints = constraints or {}
        try:
            if strategy == "fragment":
                molecules = self._generate_by_fragments(n, constraints)
            elif strategy == "optimization":
                if not seed_smiles:
                    return {"error": "optimization 策略需要 seed_smiles", "molecules": []}
                molecules = self._generate_by_optimization(seed_smiles, n, constraints)
            elif strategy == "random":
                molecules = self._generate_random(n, constraints)
            else:
                return {"error": f"未知策略: {strategy}", "molecules": []}
        except Exception as e:
            logger.warning(f"分子生成失败: {e}")
            return {"error": str(e), "molecules": [], "strategy": strategy}

        # 评估每个分子的类药性
        for mol in molecules:
            mol["druglikeness"] = assess_druglikeness(mol.get("smiles", ""))

        return {
            "molecules": molecules,
            "strategy": strategy,
            "count": len(molecules),
            "target_id": target_id,
            "seed_smiles": seed_smiles,
            "constraints": constraints,
        }

    def _generate_by_fragments(
        self,
        n: int,
        constraints: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """片段组合策略 — 从预定义片段库组合"""
        fragments = [
            "c1ccccc1",  # 苯环
            "C(=O)N",    # 酰胺
            "NC(=O)",    # 氨基
            "C(F)(F)F",  # 三氟甲基
            "c1cnccc1",  # 吡啶
            "C1CCNCC1",  # 哌啶
            "OC(=O)",    # 羧酸
            "N",         # 氨基
        ]
        molecules = []
        import random

        for _ in range(n):
            n_frags = random.randint(2, 4)
            selected = random.sample(fragments, min(n_frags, len(fragments)))
            smiles = "".join(selected)
            molecules.append({
                "smiles": smiles,
                "source": "fragment_combination",
                "fragments": selected,
            })
        return molecules

    def _generate_by_optimization(
        self,
        seed_smiles: str,
        n: int,
        constraints: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """优化策略 — 基于种子分子做取代基替换"""
        # 简化实现：在种子 SMILES 上添加常见取代基
        substituents = ["F", "Cl", "Br", "CH3", "OCH3", "OH", "NH2", "CN", "CF3"]
        molecules = []
        import random

        for _ in range(n):
            sub = random.choice(substituents)
            # 简化：在种子 SMILES 末尾添加取代基
            new_smiles = seed_smiles + sub
            molecules.append({
                "smiles": new_smiles,
                "source": "seed_optimization",
                "seed": seed_smiles,
                "substituent": sub,
            })
        return molecules

    def _generate_random(
        self,
        n: int,
        constraints: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """随机生成策略 — 骨架 + 取代基"""
        scaffolds = ["C1CCCCC1", "c1ccccc1", "C1CCNCC1", "c1cnccc1"]
        substituents = ["F", "Cl", "CH3", "OCH3", "OH", "NH2", "CN", "C(=O)N"]
        molecules = []
        import random

        for _ in range(n):
            scaffold = random.choice(scaffolds)
            n_subs = random.randint(1, 3)
            subs = random.sample(substituents, min(n_subs, len(substituents)))
            smiles = scaffold + "".join(subs)
            molecules.append({
                "smiles": smiles,
                "source": "random_generation",
                "scaffold": scaffold,
                "substituents": subs,
            })
        return molecules

    @staticmethod
    def calculate_similarity(smiles1: str, smiles2: str) -> float:
        """计算两个分子的 Tanimoto 相似度

        Args:
            smiles1: 第一个分子的 SMILES
            smiles2: 第二个分子的 SMILES
        Returns:
            Tanimoto 相似度（0-1）
        """
        if not smiles1 or not smiles2:
            return 0.0

        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem, DataStructs

            mol1 = Chem.MolFromSmiles(smiles1)
            mol2 = Chem.MolFromSmiles(smiles2)
            if mol1 is None or mol2 is None:
                return 0.0

            fp1 = AllChem.GetMorganFingerprintAsBitVect(mol1, 2, 1024)
            fp2 = AllChem.GetMorganFingerprintAsBitVect(mol2, 2, 1024)
            return DataStructs.TanimotoSimilarity(fp1, fp2)
        except ImportError:
            # 降级：基于字符的 Jaccard 相似度
            set1 = set(smiles1)
            set2 = set(smiles2)
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            return intersection / union if union else 0.0
        except Exception as e:
            logger.warning(f"相似度计算失败: {e}")
            return 0.0


def assess_druglikeness(smiles: str) -> Dict[str, Any]:
    """类药性评估 — Lipinski 五规则（同步函数，被 endpoints 直接调用）

    Args:
        smiles: 分子 SMILES 字符串
    Returns:
        {mw, logp, hbd, hba, rotatable_bonds, tpsa, passes_rule_of_five, violations}
    """
    if not smiles:
        return {"error": "SMILES 不能为空"}

    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Crippen
    except ImportError:
        # Mock 模式回退：基于 SMILES 字符串的简单规则估算
        return _mock_assess_druglikeness(smiles)
    # （rdkit 可用时继续走下面的真实计算路径）

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"smiles": smiles, "error": "无效 SMILES"}

    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    hbd = Descriptors.NumHDonors(mol)
    hba = Descriptors.NumHAcceptors(mol)
    rotatable = Descriptors.NumRotatableBonds(mol)
    tpsa = Descriptors.TPSA(mol)
    n_rings = Descriptors.RingCount(mol)
    n_aromatic = sum(1 for r in mol.GetRingInfo().AtomRings() if all(mol.GetAtomWithIdx(i).GetIsAromatic() for i in r))

    violations = []
    if mw > 500:
        violations.append("MW>500 (Lipinski)")
    if logp > 5:
        violations.append("LogP>5 (Lipinski)")
    if hbd > 5:
        violations.append("HBD>5 (Lipinski)")
    if hba > 10:
        violations.append("HBA>10 (Lipinski)")

    # Veber 规则
    veber_passes = rotatable <= 10 and tpsa <= 140

    # 类药性综合评分（0-100）
    score = 100
    score -= 15 * len(violations)
    if not veber_passes:
        score -= 20
    if mw < 200 or mw > 600:
        score -= 10
    score = max(0, score)

    return {
        "smiles": smiles,
        "mw": round(mw, 2),
        "logp": round(logp, 2),
        "hbd": hbd,
        "hba": hba,
        "rotatable_bonds": rotatable,
        "tpsa": round(tpsa, 2),
        "n_rings": n_rings,
        "n_aromatic_rings": n_aromatic,
        "passes_rule_of_five": len(violations) == 0,
        "passes_veber_rule": veber_passes,
        "violations": violations,
        "druglikeness_score": round(score, 2),
    }


def _mock_assess_druglikeness(smiles: str) -> Dict[str, Any]:
    """Mock 类药性评估 — RDKit 未安装时的回退方案

    基于 SMILES 字符串的简单规则估算分子量、LogP、氢键供体/受体数等。
    仅用于 P0 框架演示，实际评估需安装 rdkit。
    """
    if not smiles:
        return {"error": "SMILES 不能为空"}

    # 基于 SMILES 字符串特征估算
    n_atoms = sum(1 for c in smiles if c.isupper())
    n_carbon = smiles.count("C") + smiles.count("c")
    n_nitrogen = smiles.count("N") + smiles.count("n")
    n_oxygen = smiles.count("O") + smiles.count("o")
    n_rings = smiles.count("c") > 0 or "1" in smiles  # 芳香环或环编号
    n_branches = smiles.count("(")

    # 简单估算分子量（C≈12, N≈14, O≈16, H≈1）
    est_mw = n_carbon * 12 + n_nitrogen * 14 + n_oxygen * 16 + n_atoms * 1.5
    # 简单估算 LogP（碳越多越疏水）
    est_logp = round(max(-2.0, min(6.0, n_carbon * 0.4 - n_nitrogen * 0.5 - n_oxygen * 0.4)), 2)
    est_hbd = n_nitrogen + n_oxygen // 2
    est_hba = n_nitrogen + n_oxygen
    est_rotatable = max(0, n_branches + n_atoms // 4)
    est_tpsa = round(n_nitrogen * 12 + n_oxygen * 20, 2)

    violations = []
    if est_mw > 500:
        violations.append("MW>500 (Lipinski, 估算)")
    if est_logp > 5:
        violations.append("LogP>5 (Lipinski, 估算)")
    if est_hbd > 5:
        violations.append("HBD>5 (Lipinski, 估算)")
    if est_hba > 10:
        violations.append("HBA>10 (Lipinski, 估算)")

    veber_passes = est_rotatable <= 10 and est_tpsa <= 140

    score = 100
    score -= 15 * len(violations)
    if not veber_passes:
        score -= 20
    if est_mw < 200 or est_mw > 600:
        score -= 10
    score = max(0, score)

    return {
        "smiles": smiles,
        "mw": round(est_mw, 2),
        "logp": est_logp,
        "hbd": est_hbd,
        "hba": est_hba,
        "rotatable_bonds": est_rotatable,
        "tpsa": est_tpsa,
        "n_rings": 1 if n_rings else 0,
        "n_aromatic_rings": 1 if "c" in smiles else 0,
        "passes_rule_of_five": len(violations) == 0,
        "passes_veber_rule": veber_passes,
        "violations": violations,
        "druglikeness_score": round(score, 2),
        "_note": "Mock 模式估算（rdkit 未安装），数值仅供演示",
    }


# ========== ADMET 预测与分子可解释性 ==========

PAINS_PATTERNS = {
    "rhodanine": "C1=NC(=O)NC(=O)C1",
    "toxoflavin": "c1nc2n(sc2c(=O)[nH]1)",
    "isothiazolone": "C1=CC(=O)NS1",
    "hydroquinone": "c1cc(O)cc(O)1",
    "furan_reactive": "c1ccoc1C(=O)",
    "ene_one_michael": "C=CC(=O)",
    "azo_dye": "NN=N",
}

TOXICOPHORE_PATTERNS = {
    "nitro": "[N+](=O)[O-]",
    "azo": "N=N",
    "alkyl_halide": "[CX4][F,Cl,Br,I]",
    "aldehyde": "C(=O)[H]",
    "isocyanate": "N=C=O",
    "thiol": "[SH]",
    "epoxide": "C1OC1",
    "anhydride": "C(=O)OC(=O)",
    "peroxide": "OO",
    "heavy_metal_organic": "[Hg,Pb,Sn]",
}

FUNCTIONAL_GROUP_PATTERNS = {
    "hydroxyl": "[#8X2H]",
    "carbonyl": "[#6X3]=[#8X1]",
    "carboxyl": "[#6X3](=[#8X1])[#8X1H0-,X2H1]",
    "primary_amine": "[#7X3;H2]",
    "secondary_amine": "[#7X3;H1]",
    "tertiary_amine": "[#7X3;H0]",
    "amide": "[#7X3][#6X3](=[#8X1])",
    "ester": "[#6X3](=[#8X1])[#8X2H0]",
    "ether": "[#8X2]([#6])[#6]",
    "aromatic_ring": "c1ccccc1",
    "halogen": "[F,Cl,Br,I]",
    "nitrile": "[#6]#[#7]",
    "sulfonamide": "[#16X4]([#8X2])([#8X2])[#7X3]",
}


def predict_admet(smiles: str) -> Dict[str, Any]:
    """ADMET 性质预测 — RDKit 计算（同步函数）

    预测 8 项 ADMET 指标：LogS、BBB 渗透性、生物利用度评分、
    PAINS 警告、毒性警示结构、hERG 风险、Caco-2 渗透性、血浆蛋白结合。

    Args:
        smiles: 分子 SMILES 字符串
    Returns:
        ADMET 预测结果字典
    """
    if not smiles:
        return {"error": "SMILES 不能为空"}

    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors
    except ImportError:
        return _mock_predict_admet(smiles)

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"smiles": smiles, "error": "无效 SMILES"}

    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = Descriptors.TPSA(mol)
    hbd = Descriptors.NumHDonors(mol)
    hba = Descriptors.NumHAcceptors(mol)
    rotatable = Descriptors.NumRotatableBonds(mol)

    # LogS — General Solubility Equation
    log_s = round(0.5 - 0.01 * (mw - 20) - logp, 3)

    # BBB 渗透性
    if tpsa < 90 and 1 <= logp <= 3:
        bbb = "high"
    elif tpsa < 140 and 0 <= logp <= 4:
        bbb = "medium"
    else:
        bbb = "low"

    # 生物利用度评分
    lipinski_violations = 0
    if mw > 500:
        lipinski_violations += 1
    if logp > 5:
        lipinski_violations += 1
    if hbd > 5:
        lipinski_violations += 1
    if hba > 10:
        lipinski_violations += 1
    veber_passes = rotatable <= 10 and tpsa <= 140
    bio_score = 1.0
    bio_score -= 0.25 * lipinski_violations
    if veber_passes:
        bio_score += 0.25
    if 200 <= mw <= 500:
        bio_score += 0.25
    if 1 <= logp <= 3:
        bio_score += 0.25
    bio_score = round(max(0.0, min(1.0, bio_score)), 3)

    # PAINS 警告
    pains_alerts = []
    for name, smarts in PAINS_PATTERNS.items():
        patt = Chem.MolFromSmarts(smarts)
        if patt and mol.HasSubstructMatch(patt):
            pains_alerts.append({"name": name, "smarts": smarts})

    # 毒性警示结构
    toxicophore_alerts = []
    for name, smarts in TOXICOPHORE_PATTERNS.items():
        patt = Chem.MolFromSmarts(smarts)
        if patt and mol.HasSubstructMatch(patt):
            toxicophore_alerts.append({"name": name, "smarts": smarts})

    # hERG 风险
    if mw > 400 and logp > 3 and tpsa < 80:
        herg_risk = "high"
    elif mw > 300 and logp > 2:
        herg_risk = "medium"
    else:
        herg_risk = "low"

    # Caco-2 渗透性
    if tpsa < 60 and 1 <= logp <= 3:
        caco2 = "high"
    elif tpsa < 140 and 0 <= logp <= 4:
        caco2 = "medium"
    else:
        caco2 = "low"

    # 血浆蛋白结合
    if logp > 3:
        ppb = "high"
    elif 1 <= logp <= 3:
        ppb = "medium"
    else:
        ppb = "low"

    risk_count = len(pains_alerts) + len(toxicophore_alerts)
    if risk_count >= 3 or herg_risk == "high":
        toxicity = "high"
    elif risk_count >= 1 or herg_risk == "medium":
        toxicity = "medium"
    else:
        toxicity = "low"

    return {
        "smiles": smiles,
        "logS": log_s,
        "bbb_permeability": bbb,
        "bioavailability_score": bio_score,
        "pains_alerts": pains_alerts,
        "toxicophore_alerts": toxicophore_alerts,
        "herg_risk": herg_risk,
        "caco2_permeability": caco2,
        "plasma_protein_binding": ppb,
        "summary": {"toxicity": toxicity, "risk_count": risk_count},
    }


def _mock_predict_admet(smiles: str) -> Dict[str, Any]:
    """Mock ADMET 预测 — RDKit 未安装时的回退方案"""
    if not smiles:
        return {"error": "SMILES 不能为空"}

    n_carbon = smiles.count("C") + smiles.count("c")
    n_nitrogen = smiles.count("N") + smiles.count("n")
    n_oxygen = smiles.count("O") + smiles.count("o")
    n_atoms = sum(1 for c in smiles if c.isupper())

    est_mw = n_carbon * 12 + n_nitrogen * 14 + n_oxygen * 16 + n_atoms * 1.5
    est_logp = round(max(-2.0, min(6.0, n_carbon * 0.4 - n_nitrogen * 0.5 - n_oxygen * 0.4)), 2)
    est_tpsa = round(n_nitrogen * 12 + n_oxygen * 20, 2)

    log_s = round(0.5 - 0.01 * (est_mw - 20) - est_logp, 3)

    if est_tpsa < 90 and 1 <= est_logp <= 3:
        bbb = "high"
    elif est_tpsa < 140 and 0 <= est_logp <= 4:
        bbb = "medium"
    else:
        bbb = "low"

    bio_score = round(max(0.0, min(1.0, 0.5 + n_carbon * 0.03 - n_oxygen * 0.05)), 3)

    pains_alerts = []
    for name, pattern in PAINS_PATTERNS.items():
        if pattern in smiles or name == "azo_dye" and "N=N" in smiles:
            pains_alerts.append({"name": name, "smarts": pattern})

    toxicophore_alerts = []
    for name, pattern in TOXICOPHORE_PATTERNS.items():
        simple = pattern.replace("[", "").replace("]", "").replace("+", "").replace("-", "")
        if simple in smiles:
            toxicophore_alerts.append({"name": name, "smarts": pattern})

    if est_mw > 400 and est_logp > 3:
        herg_risk = "high"
    elif est_mw > 300 and est_logp > 2:
        herg_risk = "medium"
    else:
        herg_risk = "low"

    if est_tpsa < 60 and 1 <= est_logp <= 3:
        caco2 = "high"
    elif est_tpsa < 140 and 0 <= est_logp <= 4:
        caco2 = "medium"
    else:
        caco2 = "low"

    if est_logp > 3:
        ppb = "high"
    elif 1 <= est_logp <= 3:
        ppb = "medium"
    else:
        ppb = "low"

    risk_count = len(pains_alerts) + len(toxicophore_alerts)
    if risk_count >= 3 or herg_risk == "high":
        toxicity = "high"
    elif risk_count >= 1 or herg_risk == "medium":
        toxicity = "medium"
    else:
        toxicity = "low"

    return {
        "smiles": smiles,
        "logS": log_s,
        "bbb_permeability": bbb,
        "bioavailability_score": bio_score,
        "pains_alerts": pains_alerts,
        "toxicophore_alerts": toxicophore_alerts,
        "herg_risk": herg_risk,
        "caco2_permeability": caco2,
        "plasma_protein_binding": ppb,
        "summary": {"toxicity": toxicity, "risk_count": risk_count},
        "_note": "Mock 模式估算（rdkit 未安装），数值仅供演示",
    }


def explain_molecule(smiles: str) -> Dict[str, Any]:
    """分子可解释性分析 — RDKit SMARTS 匹配（同步函数）

    识别功能团、环系统、立体化学特征和原子组成。

    Args:
        smiles: 分子 SMILES 字符串
    Returns:
        分子可解释性分析结果字典
    """
    if not smiles:
        return {"error": "SMILES 不能为空"}

    try:
        from rdkit import Chem
        from rdkit.Chem import FindMolChiralCenters
    except ImportError:
        return _mock_explain_molecule(smiles)

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"smiles": smiles, "error": "无效 SMILES"}

    # 功能团识别
    functional_groups = []
    for name, smarts in FUNCTIONAL_GROUP_PATTERNS.items():
        patt = Chem.MolFromSmarts(smarts)
        if patt:
            matches = mol.GetSubstructMatches(patt)
            if matches:
                functional_groups.append({
                    "name": name,
                    "count": len(matches),
                    "smarts": smarts,
                })

    # 环分析
    ring_info = mol.GetRingInfo()
    atom_rings = ring_info.AtomRings()
    aromatic_count = 0
    aliphatic_count = 0
    for ring in atom_rings:
        if all(mol.GetAtomWithIdx(idx).GetIsAromatic() for idx in ring):
            aromatic_count += 1
        else:
            aliphatic_count += 1

    # 立体化学
    chiral_centers = FindMolChiralCenters(mol)
    stereo_bonds = 0
    for bond in mol.GetBonds():
        stereo = bond.GetStereo()
        if stereo != Chem.BondStereo.STEREONONE:
            stereo_bonds += 1

    # 原子计数
    atom_counts: Dict[str, int] = {}
    for atom in mol.GetAtoms():
        symbol = atom.GetSymbol()
        atom_counts[symbol] = atom_counts.get(symbol, 0) + 1

    return {
        "smiles": smiles,
        "functional_groups": functional_groups,
        "rings": {
            "aromatic": aromatic_count,
            "aliphatic": aliphatic_count,
            "total": len(atom_rings),
        },
        "stereochemistry": {
            "chiral_centers": len(chiral_centers),
            "stereo_bonds": stereo_bonds,
        },
        "atom_counts": atom_counts,
    }


def _mock_explain_molecule(smiles: str) -> Dict[str, Any]:
    """Mock 分子可解释性分析 — RDKit 未安装时的回退方案"""
    if not smiles:
        return {"error": "SMILES 不能为空"}

    functional_groups = []
    fg_simple = {
        "hydroxyl": "OH",
        "carbonyl": "C(=O)",
        "carboxyl": "C(=O)O",
        "primary_amine": "N",
        "amide": "NC(=O)",
        "ester": "C(=O)OC",
        "aromatic_ring": "c1ccccc1",
        "halogen": ["F", "Cl", "Br", "I"],
        "nitrile": "C#N",
    }
    for name, pattern in fg_simple.items():
        if isinstance(pattern, list):
            count = sum(smiles.count(p) for p in pattern)
            if count:
                functional_groups.append({"name": name, "count": count, "smarts": "|".join(pattern)})
        else:
            count = smiles.count(pattern)
            if count:
                functional_groups.append({"name": name, "count": count, "smarts": pattern})

    has_aromatic = "c" in smiles
    ring_count = 1 if (has_aromatic or any(d in smiles for d in "123456789")) else 0

    atom_counts: Dict[str, int] = {}
    atom_counts["C"] = smiles.count("C") + smiles.count("c")
    atom_counts["N"] = smiles.count("N") + smiles.count("n")
    atom_counts["O"] = smiles.count("O") + smiles.count("o")
    atom_counts["S"] = smiles.count("S") + smiles.count("s")
    for hal in ["F", "Cl", "Br", "I"]:
        cnt = smiles.count(hal)
        if cnt:
            atom_counts[hal] = cnt
    atom_counts = {k: v for k, v in atom_counts.items() if v > 0}

    chiral_count = smiles.count("@")
    stereo_bond_count = smiles.count("/") + smiles.count("\\")

    return {
        "smiles": smiles,
        "functional_groups": functional_groups,
        "rings": {
            "aromatic": 1 if has_aromatic else 0,
            "aliphatic": max(0, ring_count - (1 if has_aromatic else 0)),
            "total": ring_count,
        },
        "stereochemistry": {
            "chiral_centers": chiral_count,
            "stereo_bonds": stereo_bond_count,
        },
        "atom_counts": atom_counts,
        "_note": "Mock 模式估算（rdkit 未安装），数值仅供演示",
    }
