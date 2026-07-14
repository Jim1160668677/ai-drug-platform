"""患者用药反馈服务 — 干湿实验闭环核心组件

整合患者基本信息、用药方案、治疗效果、不良反应数据，
建立标准化数据采集模板，实现实验数据与临床数据的有效关联。

形成完整的"湿实验-数据分析-干实验预测-临床验证"闭环流程。
"""
import csv
import io
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.treatment import ClinicalFeedback, Treatment

logger = logging.getLogger(__name__)


class PatientFeedbackService:
    """患者用药反馈服务 — 录入、查询、统计、模板生成"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        treatment_id: str,
        patient_code: Optional[str] = None,
        age: Optional[int] = None,
        gender: Optional[str] = None,
        diagnosis: Optional[str] = None,
        stage: Optional[str] = None,
        drug_name: Optional[str] = None,
        dosage: Optional[str] = None,
        duration_days: Optional[int] = None,
        efficacy: Optional[str] = None,
        tumor_shrinkage_pct: Optional[float] = None,
        pfs_days: Optional[int] = None,
        os_days: Optional[int] = None,
        adverse_events: Optional[List[Dict[str, Any]]] = None,
        biomarker_changes: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> ClinicalFeedback:
        """创建患者用药反馈记录

        Args:
            treatment_id: 关联的治疗方案 ID
            patient_code: 患者编码（脱敏）
            age: 年龄
            gender: 性别
            diagnosis: 诊断
            stage: 分期
            drug_name: 药物名称
            dosage: 剂量
            duration_days: 用药天数
            efficacy: 疗效评价 (complete/partial/stable/progressive)
            tumor_shrinkage_pct: 肿瘤缩小百分比
            pfs_days: 无进展生存期（天）
            os_days: 总生存期（天）
            adverse_events: 不良反应列表 [{event, severity, action}]
            biomarker_changes: 生物标志物变化
            notes: 备注
        Returns:
            ClinicalFeedback 记录
        """
        # 组装 dosage 字段（包含药物名称）
        dosage_str = dosage or ""
        if drug_name:
            dosage_str = f"{drug_name} {dosage_str}".strip()

        # 组装 adverse_reactions
        adverse_reactions = None
        if adverse_events:
            adverse_reactions = {"events": adverse_events, "count": len(adverse_events)}

        # 组装 biomarker_changes（包含疗效详情）
        biomarker_data = biomarker_changes or {}
        if tumor_shrinkage_pct is not None:
            biomarker_data["tumor_shrinkage_pct"] = tumor_shrinkage_pct
        if pfs_days is not None:
            biomarker_data["pfs_days"] = pfs_days
        if os_days is not None:
            biomarker_data["os_days"] = os_days
        if diagnosis:
            biomarker_data["diagnosis"] = diagnosis
        if stage:
            biomarker_data["stage"] = stage

        feedback = ClinicalFeedback(
            treatment_id=treatment_id,
            patient_code=patient_code,
            age=age,
            gender=gender,
            dosage=dosage_str or None,
            duration_days=duration_days,
            efficacy=efficacy,
            adverse_reactions=adverse_reactions,
            biomarker_changes=biomarker_data if biomarker_data else None,
            notes=notes,
        )
        self.db.add(feedback)
        await self.db.flush()
        logger.info("患者反馈创建: treatment=%s, patient=%s, efficacy=%s",
                    treatment_id, patient_code, efficacy)
        return feedback

    async def list_by_treatment(
        self,
        treatment_id: str,
        limit: int = 100,
    ) -> List[ClinicalFeedback]:
        """按治疗方案查询患者反馈"""
        result = await self.db.execute(
            select(ClinicalFeedback)
            .where(ClinicalFeedback.treatment_id == treatment_id)
            .order_by(ClinicalFeedback.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_target(
        self,
        target_symbol: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """按靶点查询患者反馈（通过 Treatment.target_ids 关联）

        Args:
            target_symbol: 靶点基因符号
            limit: 返回上限
        Returns:
            [{feedback, treatment_name, target_symbol}]
        """
        # 先查找包含该靶点的治疗方案
        from app.models.target import Target

        target_stmt = select(Target).where(Target.gene_symbol == target_symbol)
        target_result = await self.db.execute(target_stmt)
        targets = list(target_result.scalars().all())
        if not targets:
            return []

        target_ids = [str(t.id) for t in targets]

        # 查询治疗方案（target_ids 是 JSON 列表）
        treatment_stmt = select(Treatment)
        treatment_result = await self.db.execute(treatment_stmt)
        treatments = list(treatment_result.scalars().all())

        # 过滤包含目标靶点的治疗方案
        matching_treatment_ids = []
        for t in treatments:
            t_ids = t.target_ids or []
            if any(tid in target_ids for tid in [str(tid) for tid in t_ids]):
                matching_treatment_ids.append(str(t.id))

        if not matching_treatment_ids:
            return []

        # 查询这些治疗方案的患者反馈
        feedback_stmt = (
            select(ClinicalFeedback)
            .where(ClinicalFeedback.treatment_id.in_(matching_treatment_ids))
            .order_by(ClinicalFeedback.created_at.desc())
            .limit(limit)
        )
        feedback_result = await self.db.execute(feedback_stmt)
        feedbacks = list(feedback_result.scalars().all())

        # 组装返回数据
        treatment_map = {str(t.id): t.name for t in treatments if str(t.id) in matching_treatment_ids}
        results = []
        for fb in feedbacks:
            results.append({
                "id": str(fb.id),
                "treatment_id": fb.treatment_id,
                "treatment_name": treatment_map.get(fb.treatment_id, ""),
                "patient_code": fb.patient_code,
                "age": fb.age,
                "gender": fb.gender,
                "efficacy": fb.efficacy,
                "adverse_reactions": fb.adverse_reactions,
                "biomarker_changes": fb.biomarker_changes,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
            })
        return results

    async def get_statistics(self, target_symbol: str) -> Dict[str, Any]:
        """按靶点统计有效率/不良反应率

        Args:
            target_symbol: 靶点基因符号
        Returns:
            {target_symbol, total, effective_count, adverse_count,
             efficacy_rate, adverse_rate, efficacy_breakdown}
        """
        feedbacks = await self.list_by_target(target_symbol, limit=500)

        if not feedbacks:
            return {
                "target_symbol": target_symbol,
                "total": 0,
                "effective_count": 0,
                "adverse_count": 0,
                "efficacy_rate": 0.0,
                "adverse_rate": 0.0,
                "efficacy_breakdown": {},
                "message": "无足够数据",
            }

        total = len(feedbacks)
        # 有效 = complete + partial（RECIST 标准）
        effective_efficacies = {"complete", "partial"}
        effective_count = sum(
            1 for f in feedbacks
            if (f.get("efficacy") or "").lower() in effective_efficacies
        )
        adverse_count = sum(
            1 for f in feedbacks
            if f.get("adverse_reactions") and (f["adverse_reactions"].get("count", 0) > 0)
        )

        # 疗效分布
        efficacy_breakdown: Dict[str, int] = {}
        for f in feedbacks:
            eff = (f.get("efficacy") or "unknown").lower()
            efficacy_breakdown[eff] = efficacy_breakdown.get(eff, 0) + 1

        return {
            "target_symbol": target_symbol,
            "total": total,
            "effective_count": effective_count,
            "adverse_count": adverse_count,
            "efficacy_rate": round(effective_count / total, 4),
            "adverse_rate": round(adverse_count / total, 4),
            "efficacy_breakdown": efficacy_breakdown,
        }

    async def link_to_prediction(
        self,
        feedback_id: UUID,
        experiment_id: UUID,
    ) -> Dict[str, Any]:
        """关联患者反馈与干实验预测

        Args:
            feedback_id: 患者反馈 ID
            experiment_id: 实验 ID
        Returns:
            {status, feedback_id, experiment_id}
        """
        feedback = await self.db.get(ClinicalFeedback, feedback_id)
        if not feedback:
            return {"status": "not_found", "feedback_id": str(feedback_id)}

        # 在 notes 中记录关联（简化实现，避免修改模型）
        link_note = f"[linked_experiment:{experiment_id}]"
        if feedback.notes:
            feedback.notes = f"{feedback.notes}\n{link_note}"
        else:
            feedback.notes = link_note
        await self.db.flush()

        return {
            "status": "linked",
            "feedback_id": str(feedback_id),
            "experiment_id": str(experiment_id),
        }

    @staticmethod
    def generate_template(format: str = "csv") -> bytes:
        """生成标准化数据采集模板

        Args:
            format: 模板格式 (csv)
        Returns:
            模板文件二进制内容
        """
        if format != "csv":
            raise ValueError(f"不支持的模板格式: {format}，目前仅支持 csv")

        output = io.StringIO()
        writer = csv.writer(output)
        # 表头
        writer.writerow([
            "patient_code", "age", "gender", "diagnosis", "stage",
            "drug_name", "dosage", "duration_days",
            "efficacy", "tumor_shrinkage_pct", "pfs_days", "os_days",
            "adverse_event_1", "severity_1", "adverse_event_2", "severity_2",
            "biomarker_changes", "notes",
        ])
        # 示例行
        writer.writerow([
            "P001", "55", "M", "非小细胞肺癌", "IIIB",
            "吉非替尼", "250mg qd", "180",
            "partial", "35.5", "210", "420",
            "皮疹", "1", "腹泻", "2",
            "EGFR L858R 突变转阴", "无明显不适",
        ])
        # 空行模板
        writer.writerow(["P002"] + [""] * 17)

        content = output.getvalue()
        # 添加说明注释
        header_comment = (
            "# 患者用药反馈标准化数据采集模板\n"
            "# efficacy 取值: complete(完全缓解) / partial(部分缓解) / stable(疾病稳定) / progressive(疾病进展)\n"
            "# severity 取值: 1-5 (CTCAE 分级)\n"
            "# 请删除注释行后填入数据\n"
        )
        return (header_comment + content).encode("utf-8")
