"""药物相互作用（DDI）检查器 — 规则表 + 靶点重合度算法

设计来源：v3.0 文档第 7 章 v2.0 五大关键深化能力

实现策略：
- 内置 50+ 常见 DDI 规则表（基于 FDA/DrugBank 公开数据）
- 靶点重合度算法（两药物作用于相同靶点 → 潜在相互作用）
- 风险等级汇总：none / minor / moderate / major / contraindicated

DeepDDI 深度学习模型不可用时降级为本规则表方案，P2 阶段可升级。
"""
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ========== 风险等级 ==========
RISK_NONE = "none"
RISK_MINOR = "minor"
RISK_MODERATE = "moderate"
RISK_MAJOR = "major"
RISK_CONTRAINDICATED = "contraindicated"

# 风险等级优先级（数值越高越严重）
_RISK_PRIORITY = {
    RISK_NONE: 0,
    RISK_MINOR: 1,
    RISK_MODERATE: 2,
    RISK_MAJOR: 3,
    RISK_CONTRAINDICATED: 4,
}


def _max_risk(levels: List[str]) -> str:
    """从多个风险等级中取最高"""
    if not levels:
        return RISK_NONE
    return max(levels, key=lambda r: _RISK_PRIORITY.get(r, 0))


# ========== DDI 规则表 ==========
# 每条规则：{drug_a, drug_b, severity, mechanism, clinical_effect}
# drug_a 和 drug_b 不区分顺序（检查时双向匹配）
_DDI_RULES: List[Dict[str, str]] = [
    # ===== 抗凝药相互作用 =====
    {"drug_a": "warfarin", "drug_b": "aspirin", "severity": RISK_MAJOR,
     "mechanism": "抗凝+抗血小板协同", "clinical_effect": "出血风险显著增加"},
    {"drug_a": "warfarin", "drug_b": "ibuprofen", "severity": RISK_MAJOR,
     "mechanism": "NSAID 替换华法林蛋白结合", "clinical_effect": "出血风险增加 + INR 升高"},
    {"drug_a": "warfarin", "drug_b": "amiodarone", "severity": RISK_MAJOR,
     "mechanism": "CYP2C9 抑制", "clinical_effect": "华法林血药浓度升高，出血风险"},
    {"drug_a": "warfarin", "drug_b": "fluconazole", "severity": RISK_MAJOR,
     "mechanism": "CYP2C9/CYP3A4 抑制", "clinical_effect": "华法林代谢受阻，INR 升高"},
    {"drug_a": "warfarin", "drug_b": "rifampin", "severity": RISK_MODERATE,
     "mechanism": "CYP2C9 诱导", "clinical_effect": "华法林血药浓度降低，需调整剂量"},
    {"drug_a": "warfarin", "drug_b": "phenytoin", "severity": RISK_MAJOR,
     "mechanism": "双向 CYP 代谢相互作用", "clinical_effect": "两药血药浓度均改变"},
    {"drug_a": "warfarin", "drug_b": "sulfamethoxazole", "severity": RISK_MAJOR,
     "mechanism": "CYP2C9 抑制 + 蛋白置换", "clinical_effect": "INR 升高，出血风险"},

    # ===== 他汀类相互作用 =====
    {"drug_a": "simvastatin", "drug_b": "itraconazole", "severity": RISK_CONTRAINDICATED,
     "mechanism": "CYP3A4 强抑制", "clinical_effect": "横纹肌溶解风险"},
    {"drug_a": "simvastatin", "drug_b": "clarithromycin", "severity": RISK_CONTRAINDICATED,
     "mechanism": "CYP3A4 抑制", "clinical_effect": "横纹肌溶解风险"},
    {"drug_a": "simvastatin", "drug_b": "ketoconazole", "severity": RISK_CONTRAINDICATED,
     "mechanism": "CYP3A4 强抑制", "clinical_effect": "横纹肌溶解风险"},
    {"drug_a": "simvastatin", "drug_b": "cyclosporine", "severity": RISK_CONTRAINDICATED,
     "mechanism": "OATP1B1 抑制 + CYP3A4 抑制", "clinical_effect": "横纹肌溶解风险"},
    {"drug_a": "atorvastatin", "drug_b": "clarithromycin", "severity": RISK_MAJOR,
     "mechanism": "CYP3A4 抑制", "clinical_effect": "肌病风险增加"},
    {"drug_a": "rosuvastatin", "drug_b": "cyclosporine", "severity": RISK_CONTRAINDICATED,
     "mechanism": "OATP1B1 抑制", "clinical_effect": "横纹肌溶解风险"},
    {"drug_a": "simvastatin", "drug_b": "gemfibrozil", "severity": RISK_CONTRAINDICATED,
     "mechanism": "葡糖醛酸化抑制", "clinical_effect": "横纹肌溶解风险"},

    # ===== CYP3A4 相关相互作用 =====
    {"drug_a": "cyclosporine", "drug_b": "ketoconazole", "severity": RISK_MAJOR,
     "mechanism": "CYP3A4 强抑制", "clinical_effect": "环孢素血药浓度显著升高"},
    {"drug_a": "tacrolimus", "drug_b": "ketoconazole", "severity": RISK_MAJOR,
     "mechanism": "CYP3A4 抑制", "clinical_effect": "他克莫司血药浓度升高"},
    {"drug_a": "cyclosporine", "drug_b": "rifampin", "severity": RISK_MODERATE,
     "mechanism": "CYP3A4 诱导", "clinical_effect": "环孢素血药浓度降低"},
    {"drug_a": "midazolam", "drug_b": "itraconazole", "severity": RISK_MAJOR,
     "mechanism": "CYP3A4 抑制", "clinical_effect": "过度镇静"},

    # ===== 5-羟色胺综合征风险 =====
    {"drug_a": "fluoxetine", "drug_b": "tramadol", "severity": RISK_MAJOR,
     "mechanism": "5-HT 再摄取抑制 + 5-HT 释放", "clinical_effect": "5-羟色胺综合征风险"},
    {"drug_a": "sertraline", "drug_b": "tramadol", "severity": RISK_MAJOR,
     "mechanism": "5-HT 再摄取抑制 + 5-HT 释放", "clinical_effect": "5-羟色胺综合征风险"},
    {"drug_a": "phenelzine", "drug_b": "tramadol", "severity": RISK_CONTRAINDICATED,
     "mechanism": "MAO 抑制 + 5-HT 释放", "clinical_effect": "5-羟色胺综合征风险"},
    {"drug_a": "phenelzine", "drug_b": "fluoxetine", "severity": RISK_CONTRAINDICATED,
     "mechanism": "MAO 抑制 + 5-HT 再摄取抑制", "clinical_effect": "5-羟色胺综合征风险"},
    {"drug_a": "selegiline", "drug_b": "fluoxetine", "severity": RISK_CONTRAINDICATED,
     "mechanism": "MAO-B 抑制 + 5-HT 再摄取抑制", "clinical_effect": "5-羟色胺综合征风险"},

    # ===== QT 延长风险 =====
    {"drug_a": "amiodarone", "drug_b": "haloperidol", "severity": RISK_MAJOR,
     "mechanism": "QT 延长协同", "clinical_effect": "尖端扭转型室速风险"},
    {"drug_a": "amiodarone", "drug_b": "clarithromycin", "severity": RISK_MAJOR,
     "mechanism": "QT 延长 + CYP3A4 抑制", "clinical_effect": "尖端扭转型室速风险"},
    {"drug_a": "haloperidol", "drug_b": "ziprasidone", "severity": RISK_MAJOR,
     "mechanism": "QT 延长协同", "clinical_effect": "尖端扭转型室速风险"},

    # ===== 降压药相互作用 =====
    {"drug_a": "lisinopril", "drug_b": "spironolactone", "severity": RISK_MAJOR,
     "mechanism": "醛固酮拮抗 + ACE 抑制", "clinical_effect": "高钾血症风险"},
    {"drug_a": "enalapril", "drug_b": "potassium", "severity": RISK_MODERATE,
     "mechanism": "钾保留协同", "clinical_effect": "高钾血症风险"},
    {"drug_a": "losartan", "drug_b": "spironolactone", "severity": RISK_MAJOR,
     "mechanism": "醛固酮拮抗 + ARB", "clinical_effect": "高钾血症风险"},

    # ===== 降糖药相互作用 =====
    {"drug_a": "metformin", "drug_b": "contrast_media", "severity": RISK_MAJOR,
     "mechanism": "乳酸酸中毒风险", "clinical_effect": "肾功能损害时乳酸蓄积"},
    {"drug_a": "glyburide", "drug_b": "fluconazole", "severity": RISK_MAJOR,
     "mechanism": "CYP2C9 抑制", "clinical_effect": "低血糖风险"},
    {"drug_a": "warfarin", "drug_b": "glipizide", "severity": RISK_MODERATE,
     "mechanism": "蛋白置换", "clinical_effect": "低血糖 + 出血风险"},

    # ===== 抗肿瘤药相互作用 =====
    {"drug_a": "methotrexate", "drug_b": "trimethoprim", "severity": RISK_CONTRAINDICATED,
     "mechanism": "双重抗叶酸", "clinical_effect": "骨髓抑制风险"},
    {"drug_a": "methotrexate", "drug_b": "nsaids", "severity": RISK_MAJOR,
     "mechanism": "肾清除降低", "clinical_effect": "甲氨蝶呤毒性"},
    {"drug_a": "doxorubicin", "drug_b": "trastuzumab", "severity": RISK_MAJOR,
     "mechanism": "心脏毒性协同", "clinical_effect": "心力衰竭风险"},
    {"drug_a": "cyclophosphamide", "drug_b": "allopurinol", "severity": RISK_MAJOR,
     "mechanism": "骨髓抑制增强", "clinical_effect": "血液毒性增加"},

    # ===== 抗癫痫药相互作用 =====
    {"drug_a": "valproic_acid", "drug_b": "lamotrigine", "severity": RISK_MODERATE,
     "mechanism": "葡糖醛酸化抑制", "clinical_effect": "拉莫三嗪血药浓度升高"},
    {"drug_a": "phenytoin", "drug_b": "valproic_acid", "severity": RISK_MODERATE,
     "mechanism": "蛋白置换 + 代谢抑制", "clinical_effect": "苯妥英毒性"},
    {"drug_a": "carbamazepine", "drug_b": "erythromycin", "severity": RISK_MAJOR,
     "mechanism": "CYP3A4 抑制", "clinical_effect": "卡马西平毒性"},

    # ===== 其他常见相互作用 =====
    {"drug_a": "digoxin", "drug_b": "verapamil", "severity": RISK_MAJOR,
     "mechanism": "P-gp 抑制 + 房室结抑制", "clinical_effect": "地高辛毒性 + 心动过缓"},
    {"drug_a": "digoxin", "drug_b": "amiodarone", "severity": RISK_MAJOR,
     "mechanism": "P-gp 抑制", "clinical_effect": "地高辛血药浓度升高"},
    {"drug_a": "theophylline", "drug_b": "ciprofloxacin", "severity": RISK_MAJOR,
     "mechanism": "CYP1A2 抑制", "clinical_effect": "茶碱毒性"},
    {"drug_a": "theophylline", "drug_b": "smoking", "severity": RISK_MINOR,
     "mechanism": "CYP1A2 诱导", "clinical_effect": "茶碱血药浓度降低"},
    {"drug_a": "acetaminophen", "drug_b": "warfarin", "severity": RISK_MODERATE,
     "mechanism": "维生素 K 依赖因子合成抑制", "clinical_effect": "INR 升高（高剂量时）"},
    {"drug_a": "levothyroxine", "drug_b": "calcium", "severity": RISK_MINOR,
     "mechanism": "吸收减少", "clinical_effect": "甲状腺素疗效降低"},
    {"drug_a": "levothyroxine", "drug_b": "iron", "severity": RISK_MINOR,
     "mechanism": "螯合", "clinical_effect": "甲状腺素吸收减少"},
    {"drug_a": "tetracycline", "drug_b": "calcium", "severity": RISK_MODERATE,
     "mechanism": "螯合", "clinical_effect": "四环素吸收减少"},
    {"drug_a": "ciprofloxacin", "drug_b": "calcium", "severity": RISK_MODERATE,
     "mechanism": "螯合", "clinical_effect": "环丙沙星吸收减少"},
    {"drug_a": "phenytoin", "drug_b": "isoniazid", "severity": RISK_MAJOR,
     "mechanism": "CYP2C9/2C19 抑制", "clinical_effect": "苯妥英毒性"},
    {"drug_a": "allopurinol", "drug_b": "azathioprine", "severity": RISK_CONTRAINDICATED,
     "mechanism": "黄嘌呤氧化酶抑制", "clinical_effect": "骨髓抑制风险"},
    {"drug_a": "spironolactone", "drug_b": "eplerenone", "severity": RISK_MODERATE,
     "mechanism": "双重醛固酮拮抗", "clinical_effect": "高钾血症风险"},
    {"drug_a": "codeine", "drug_b": "paroxetine", "severity": RISK_MAJOR,
     "mechanism": "CYP2D6 抑制", "clinical_effect": "可待因镇痛无效 + 5-HT 综合征"},
]


# ========== 药物 → 靶点映射（用于靶点重合度计算）==========
# 简化版，实际应从 DrugBank/ChEMBL 获取
_DRUG_TARGETS: Dict[str, Set[str]] = {
    "warfarin": {"VKORC1", "CYP2C9"},
    "aspirin": {"PTGS1", "PTGS2"},
    "ibuprofen": {"PTGS1", "PTGS2"},
    "fluoxetine": {"SLC6A4", "CYP2D6"},
    "sertraline": {"SLC6A4", "CYP2D6"},
    "simvastatin": {"HMGCR", "CYP3A4"},
    "atorvastatin": {"HMGCR", "CYP3A4"},
    "rosuvastatin": {"HMGCR", "OATP1B1"},
    "amiodarone": {"KCNQ1", "CYP3A4"},
    "haloperidol": {"DRD2", "HTR2A"},
    "metformin": {"AMPK", "OCT1"},
    "glyburide": {"SUR1", "CYP2C9"},
    "digoxin": {"ATP1A1", "P-gp"},
    "verapamil": {"CACNA1C", "CYP3A4", "P-gp"},
    "tramadol": {"OPRM1", "SLC6A4", "CYP2D6"},
    "phenytoin": {"SCN2A", "CYP2C9", "CYP2C19"},
    "valproic_acid": {"GAD1", "CYP2C9"},
    "carbamazepine": {"SCN2A", "CYP3A4"},
    "methotrexate": {"DHFR", "SLC19A1"},
    "cyclosporine": {"PPP3R1", "CYP3A4", "P-gp"},
    "tacrolimus": {"PPP3R1", "CYP3A4", "P-gp"},
}


class DDIChecker:
    """药物相互作用检查器

    检查策略：
    1. 规则表精确匹配（药物名 → 药物名）
    2. 靶点重合度计算（共享靶点 → 潜在相互作用）
    3. 风险等级汇总（取最高风险等级）
    """

    def __init__(self):
        self._rules = _DDI_RULES
        self._drug_targets = _DRUG_TARGETS

    def check(
        self,
        drug_list: List[str],
        target_list: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """检查药物相互作用

        Args:
            drug_list: 药物名称列表（小写英文）
            target_list: 相关靶点列表（可选，用于靶点重合度检查）
        Returns:
            {
                "interactions": List[Dict],  # 相互作用详情
                "risk_level": str,  # 最高风险等级
                "summary": str,  # 可读性总结
                "drug_count": int,
                "rules_checked": int,
            }
        """
        if not drug_list or len(drug_list) < 2:
            return {
                "interactions": [],
                "risk_level": RISK_NONE,
                "summary": "药物数量不足，无需相互作用检查",
                "drug_count": len(drug_list) if drug_list else 0,
                "rules_checked": 0,
            }

        # 规范化药物名（小写、去空格）
        normalized_drugs = [d.strip().lower() for d in drug_list if d and d.strip()]
        if len(normalized_drugs) < 2:
            return {
                "interactions": [],
                "risk_level": RISK_NONE,
                "summary": "药物数量不足",
                "drug_count": len(normalized_drugs),
                "rules_checked": 0,
            }

        interactions: List[Dict[str, Any]] = []
        risk_levels: List[str] = []

        # 1. 规则表精确匹配（两两组合）
        for i in range(len(normalized_drugs)):
            for j in range(i + 1, len(normalized_drugs)):
                drug_a = normalized_drugs[i]
                drug_b = normalized_drugs[j]
                match = self._match_rule(drug_a, drug_b)
                if match:
                    interactions.append({
                        "drug_a": drug_a,
                        "drug_b": drug_b,
                        "severity": match["severity"],
                        "mechanism": match["mechanism"],
                        "clinical_effect": match["clinical_effect"],
                        "source": "rule_table",
                    })
                    risk_levels.append(match["severity"])

        # 2. 靶点重合度检查
        for i in range(len(normalized_drugs)):
            for j in range(i + 1, len(normalized_drugs)):
                drug_a = normalized_drugs[i]
                drug_b = normalized_drugs[j]
                overlap = self._check_target_overlap(drug_a, drug_b)
                if overlap["overlap_count"] > 0 and overlap["overlap_ratio"] >= 0.5:
                    # 避免重复添加（规则表已匹配的跳过）
                    already_matched = any(
                        (i["drug_a"] == drug_a and i["drug_b"] == drug_b)
                        or (i["drug_a"] == drug_b and i["drug_b"] == drug_a)
                        for i in interactions
                    )
                    if not already_matched:
                        severity = RISK_MODERATE if overlap["overlap_ratio"] >= 0.75 else RISK_MINOR
                        interactions.append({
                            "drug_a": drug_a,
                            "drug_b": drug_b,
                            "severity": severity,
                            "mechanism": f"靶点重合: {', '.join(overlap['common_targets'])}",
                            "clinical_effect": "潜在药效增强或毒性叠加",
                            "source": "target_overlap",
                            "overlap_targets": list(overlap["common_targets"]),
                            "overlap_ratio": overlap["overlap_ratio"],
                        })
                        risk_levels.append(severity)

        # 3. 额外靶点列表检查（用户提供的靶点）
        if target_list:
            target_set = {t.strip().upper() for t in target_list if t and t.strip()}
            for drug in normalized_drugs:
                drug_tgts = self._drug_targets.get(drug, set())
                common = drug_tgts & target_set
                if common and len(common) >= 2:
                    already = any(
                        i["drug_a"] == drug or i["drug_b"] == drug
                        for i in interactions
                    )
                    if not already:
                        interactions.append({
                            "drug_a": drug,
                            "drug_b": "(治疗靶点)",
                            "severity": RISK_MINOR,
                            "mechanism": f"药物与治疗靶点重合: {', '.join(common)}",
                            "clinical_effect": "潜在疗效协同或毒性叠加",
                            "source": "target_list",
                        })
                        risk_levels.append(RISK_MINOR)

        overall_risk = _max_risk(risk_levels)
        summary = self._build_summary(interactions, overall_risk)

        return {
            "interactions": interactions,
            "risk_level": overall_risk,
            "summary": summary,
            "drug_count": len(normalized_drugs),
            "rules_checked": len(self._rules),
        }

    def _match_rule(self, drug_a: str, drug_b: str) -> Optional[Dict[str, str]]:
        """规则表双向匹配"""
        for rule in self._rules:
            if (rule["drug_a"] == drug_a and rule["drug_b"] == drug_b) or \
               (rule["drug_a"] == drug_b and rule["drug_b"] == drug_a):
                return rule
        return None

    def _check_target_overlap(self, drug_a: str, drug_b: str) -> Dict[str, Any]:
        """检查两药物的靶点重合度

        Returns:
            {
                "common_targets": Set[str],
                "overlap_count": int,
                "overlap_ratio": float,  # 交集/并集
            }
        """
        targets_a = self._drug_targets.get(drug_a, set())
        targets_b = self._drug_targets.get(drug_b, set())

        if not targets_a or not targets_b:
            return {"common_targets": set(), "overlap_count": 0, "overlap_ratio": 0.0}

        common = targets_a & targets_b
        union = targets_a | targets_b
        ratio = len(common) / len(union) if union else 0.0

        return {
            "common_targets": common,
            "overlap_count": len(common),
            "overlap_ratio": ratio,
        }

    def _build_summary(self, interactions: List[Dict], risk_level: str) -> str:
        """生成可读性总结"""
        if not interactions:
            return "未检测到药物相互作用"

        risk_labels = {
            RISK_MINOR: "轻微",
            RISK_MODERATE: "中度",
            RISK_MAJOR: "严重",
            RISK_CONTRAINDICATED: "禁忌",
        }

        parts = [f"检测到 {len(interactions)} 项相互作用，最高风险等级：{risk_labels.get(risk_level, '未知')}"]
        major_count = sum(1 for i in interactions if i["severity"] in (RISK_MAJOR, RISK_CONTRAINDICATED))
        if major_count > 0:
            parts.append(f"其中 {major_count} 项为严重或禁忌，建议立即调整方案")

        return "。".join(parts)


# 模块级单例
_ddi_checker: Optional[DDIChecker] = None


def get_ddi_checker() -> DDIChecker:
    """获取 DDIChecker 单例"""
    global _ddi_checker
    if _ddi_checker is None:
        _ddi_checker = DDIChecker()
    return _ddi_checker
