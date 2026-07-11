"""CDISC SDTM 导出器 — 基于 TargetReport 的 CDISC 标准导出

将一份靶点发现报告（``TargetReport``）转换为 CDISC SDTM 域格式，
涵盖 TS（Trial Summary）、DM（Demographics）、AE（Adverse Events）、
LB（Laboratory）四个核心域。

设计目标：
- 配置驱动：``settings`` 控制 Mock/Real 切换与下载链接有效期
- Mock/Real 双模式：未配置外部对象存储时降级返回内存 URL
- 完整 type hints + 中文 docstring
- 基于 ``TargetReport`` 模型（``from app.models.report import TargetReport``）
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.report import TargetReport

logger = logging.getLogger(__name__)


# 下载链接默认有效期（小时）
_DEFAULT_LINK_TTL_HOURS = 24


class CdiscExporter:
    """CDISC SDTM 导出器

    将 ``TargetReport`` 转为 CDISC SDTM 四域数据，并生成下载链接。
    P0/P1 阶段为 Mock 模式（不实际上传对象存储），P3 阶段接入 MinIO。

    Examples:
        >>> exporter = CdiscExporter(db)
        >>> result = await exporter.export(report_id=uuid4())
        >>> "download_url" in result and "domains" in result
        True
    """

    def __init__(self, db: AsyncSession):
        """初始化导出器

        Args:
            db: 异步数据库会话
        """
        self.db = db

    async def export(self, report_id: UUID) -> Dict[str, Any]:
        """导出指定报告的 CDISC SDTM 数据

        Args:
            report_id: ``TargetReport`` 主键

        Returns:
            {
                "download_url": str,
                "expires_at": str (ISO8601),
                "domains": ["TS", "DM", "AE", "LB"],
                "record_counts": {domain: int},
                "study_id": str,
                "report_id": str,
            }

        Raises:
            仅为降级友好：未找到报告时返回 ``status="not_found"`` 而非抛异常，
            以匹配项目其他服务的 Mock/Real 降级模式。
        """
        report = await self.db.get(TargetReport, report_id)
        if report is None:
            logger.warning("CDISC 导出：未找到报告 %s", report_id)
            return {
                "download_url": "",
                "expires_at": "",
                "domains": [],
                "status": "not_found",
                "report_id": str(report_id),
            }

        # 构建 SDTM 四域
        ts_records = self._build_ts_domain(report)
        dm_records = self._build_dm_domain(report)
        ae_records = await self._build_ae_domain(report)
        lb_records = await self._build_lb_domain(report)

        # 生成下载链接（Mock 模式：内存 URL；Real 模式：MinIO 预签名 URL）
        download_url, expires_at = self._generate_download_url(report)

        result = {
            "download_url": download_url,
            "expires_at": expires_at,
            "domains": ["TS", "DM", "AE", "LB"],
            "record_counts": {
                "TS": len(ts_records),
                "DM": len(dm_records),
                "AE": len(ae_records),
                "LB": len(lb_records),
            },
            "study_id": ts_records[0]["STUDYID"] if ts_records else "",
            "report_id": str(report.id),
            "status": "exported",
        }
        logger.info(
            "CDISC 导出完成：report=%s, study=%s, 域=%s",
            report.id,
            result["study_id"],
            result["record_counts"],
        )
        return result

    def _build_ts_domain(self, report: TargetReport) -> List[Dict[str, Any]]:
        """构建 TS 域 — Trial Summary（试验概览）

        Args:
            report: 靶点发现报告 ORM 对象

        Returns:
            SDTM TS 域记录列表
        """
        study_id = f"PDD-RPT-{str(report.id)[:8].upper()}"
        content_json = report.content_json or {}
        cancer_type = (
            content_json.get("cancer_type")
            or content_json.get("disease")
            or "NSCLC"
        )
        analysis_tier = report.analysis_tier or "quick"

        ts_records = [
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "TITLE",
                "TSPARM": "Trial Title",
                "TSVAL": f"Precision Drug Discovery - {cancer_type}",
            },
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "INDIC",
                "TSPARM": "Indication",
                "TSVAL": cancer_type,
            },
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "TTYPE",
                "TSPARM": "Trial Type",
                "TSVAL": "DRUG_DISCOVERY",
            },
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "STYPE",
                "TSPARM": "Study Tier",
                "TSVAL": analysis_tier,
            },
            {
                "STUDYID": study_id,
                "DOMAIN": "TS",
                "TSPARMCD": "TPROTCL",
                "TSPARM": "Protocol Identifier",
                "TSVAL": str(report.project_id),
            },
        ]
        return ts_records

    def _build_dm_domain(self, report: TargetReport) -> List[Dict[str, Any]]:
        """构建 DM 域 — Demographics（人口学/受试主体元数据）

        在靶点发现场景下，"subject" 即为该报告所属的项目。

        Args:
            report: 靶点发现报告 ORM 对象

        Returns:
            SDTM DM 域记录列表
        """
        study_id = f"PDD-RPT-{str(report.id)[:8].upper()}"
        usubjid = f"PROJ-{str(report.project_id)[:8].upper()}"
        content_json = report.content_json or {}

        return [
            {
                "STUDYID": study_id,
                "DOMAIN": "DM",
                "USUBJID": usubjid,
                "SUBJID": str(report.project_id),
                "RFICDTC": (
                    report.created_at.isoformat() if report.created_at else ""
                ),
                "ARM": content_json.get("cancer_type", "NSCLC"),
                "AGE": "",
                "SEX": "",
                "RACE": "",
                "ETHNIC": "",
            }
        ]

    async def _build_ae_domain(self, report: TargetReport) -> List[Dict[str, Any]]:
        """构建 AE 域 — Adverse Events（不良事件）

        在靶点发现场景下，将"分析失败/低置信度靶点"映射为 AE 记录，
        以满足 SDTM 标准化报送需求。

        Args:
            report: 靶点发现报告 ORM 对象

        Returns:
            SDTM AE 域记录列表
        """
        study_id = f"PDD-RPT-{str(report.id)[:8].upper()}"
        usubjid = f"PROJ-{str(report.project_id)[:8].upper()}"
        content_json = report.content_json or {}

        ae_records: List[Dict[str, Any]] = []

        # 从 content_json 中提取低置信度靶点作为 AE
        targets = content_json.get("targets") or []
        for i, t in enumerate(targets):
            if not isinstance(t, dict):
                continue
            confidence = float(t.get("confidence_score", 1.0) or 1.0)
            if confidence >= 0.5:
                continue  # 仅低置信度靶点记为 AE
            ae_records.append(
                {
                    "STUDYID": study_id,
                    "DOMAIN": "AE",
                    "USUBJID": usubjid,
                    "AESEQ": i + 1,
                    "AETERM": f"Low confidence target: {t.get('gene_symbol', 'unknown')}",
                    "AEDECOD": "LOW_CONFIDENCE_TARGET",
                    "AESEV": "MILD" if confidence >= 0.3 else "MODERATE",
                    "AEDTC": (
                        report.created_at.isoformat()
                        if report.created_at
                        else ""
                    ),
                }
            )

        # LLM 成本超支作为 AE 记录
        if report.llm_cost_usd and float(report.llm_cost_usd) > settings.FAST_SCREEN_MAX_COST_USD:
            ae_records.append(
                {
                    "STUDYID": study_id,
                    "DOMAIN": "AE",
                    "USUBJID": usubjid,
                    "AESEQ": len(ae_records) + 1,
                    "AETERM": "LLM cost exceeded budget",
                    "AEDECOD": "BUDGET_OVERFLOW",
                    "AESEV": "MODERATE",
                    "AEDTC": (
                        report.created_at.isoformat()
                        if report.created_at
                        else ""
                    ),
                }
            )

        return ae_records

    async def _build_lb_domain(self, report: TargetReport) -> List[Dict[str, Any]]:
        """构建 LB 域 — Laboratory（实验室检查/数据集元数据）

        将报告关联的数据集（如 scRNA-seq、RNA-seq）映射为 LB 记录。

        Args:
            report: 靶点发现报告 ORM 对象

        Returns:
            SDTM LB 域记录列表
        """
        study_id = f"PDD-RPT-{str(report.id)[:8].upper()}"
        usubjid = f"PROJ-{str(report.project_id)[:8].upper()}"
        content_json = report.content_json or {}

        lb_records: List[Dict[str, Any]] = []
        datasets = content_json.get("datasets") or []
        for i, ds in enumerate(datasets):
            if not isinstance(ds, dict):
                continue
            lb_records.append(
                {
                    "STUDYID": study_id,
                    "DOMAIN": "LB",
                    "USUBJID": usubjid,
                    "LBSEQ": i + 1,
                    "LBTESTCD": (ds.get("data_type", "UNKNOWN") or "UNKNOWN")[:8].upper(),
                    "LBTEST": ds.get("name", "Dataset"),
                    "LBORRES": ds.get("file_format", ""),
                    "LBORU": "FILE",
                    "LBCAT": ds.get("data_type", ""),
                    "LBDTC": (
                        report.created_at.isoformat()
                        if report.created_at
                        else ""
                    ),
                }
            )

        # 若无显式数据集信息，至少写入一条报告自身的 LB 记录
        if not lb_records:
            lb_records.append(
                {
                    "STUDYID": study_id,
                    "DOMAIN": "LB",
                    "USUBJID": usubjid,
                    "LBSEQ": 1,
                    "LBTESTCD": "RPT",
                    "LBTEST": "Target Report",
                    "LBORRES": report.analysis_tier,
                    "LBORU": "TIER",
                    "LBCAT": "REPORT",
                    "LBDTC": (
                        report.created_at.isoformat()
                        if report.created_at
                        else ""
                    ),
                }
            )

        return lb_records

    # -------- 内部辅助方法 --------

    def _generate_download_url(
        self, report: TargetReport
    ) -> tuple[str, str]:
        """生成下载链接与过期时间

        Mock 模式：返回内存 URL（``mock://...``）
        Real 模式（settings.USE_MOCK=False 且 MinIO 可用）：返回 MinIO 预签名 URL

        Args:
            report: 报告 ORM 对象

        Returns:
            (download_url, expires_at ISO8601)
        """
        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=_DEFAULT_LINK_TTL_HOURS
        )

        if settings.is_mock:
            # Mock 模式：返回内存 URL，便于本地开发与测试
            url = (
                f"mock://cdisc/exports/{report.id}/"
                f"sdtm_{report.id}.csv"
            )
            return url, expires_at.isoformat()

        # Real 模式：生成 MinIO 预签名 URL（此处给出 URL 模板；
        # P3 阶段应替换为 minio_client.presigned_get_object 的真实调用）
        try:
            url = (
                f"https://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET}"
                f"/cdisc/exports/{report.id}/sdtm_{report.id}.csv"
            )
            return url, expires_at.isoformat()
        except Exception as e:
            logger.warning(
                "MinIO 预签名 URL 生成失败，降级为 Mock URL: %s", e
            )
            url = (
                f"mock://cdisc/exports/{report.id}/"
                f"sdtm_{report.id}.csv"
            )
            return url, expires_at.isoformat()
