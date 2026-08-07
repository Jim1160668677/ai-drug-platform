"""Co-Scientist 报告导出器单元测试 — Phase B5

覆盖范围：
- CoScientistSDTMExporter: export() / _build_ho_domain() / _build_ts_domain() / _build_dl_domain() / to_csv()
- CoScientistFHIRExporter: export_research_study() / _build_research_study() / _build_research_subject()
- CoScientistMarkdownExporter: export_markdown()

测试策略：
- 使用 SimpleNamespace 构造 mock 模型对象，规避 ORM 校验
- AsyncMock 模拟 db.execute / db.get
- 覆盖正常流程、边界条件（空数据/None 字段）、异常场景（运行不存在）
- 验证 SDTM HO 域字段映射、FHIR ResearchStudy 资源结构、Markdown 报告章节
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.services.coscientist.exporters import (
    CoScientistFHIRExporter,
    CoScientistMarkdownExporter,
    CoScientistSDTMExporter,
    _elo_bucket,
    _RUN_STATUS_TO_FHIR,
    _RUN_STATUS_TO_SDTM,
)


# ============================================================
# 测试数据工厂
# ============================================================

_UNSET = object()
# 区分"未传 total_token_usage"与"显式传 None"
_UNSET_TOKEN = object()


def _make_run(
    *,
    run_id=None,
    status="completed",
    case_type="aml",
    research_goal="Discover AML drug repurposing candidates",
    current_phase="meta_review",
    current_round=5,
    max_rounds=5,
    started_at=_UNSET,
    completed_at=_UNSET,
    duration_sec=120.5,
    total_cost_usd=0.0123,
    total_token_usage=_UNSET_TOKEN,
    meta_review="Top hypothesis: Repurpose Tamoxifen for AML",
    expert_feedback=None,
    error_message=None,
    updated_at=_UNSET,
):
    """构造 CoScientistRun-like SimpleNamespace

    使用哨兵 _UNSET_TOKEN 区分"未传 total_token_usage"（用默认值）与"显式传 None"（保留 None）。
    """
    if total_token_usage is _UNSET_TOKEN:
        total_token_usage = {"prompt": 5000, "completion": 2000, "total": 7000}
    return SimpleNamespace(
        id=run_id or uuid4(),
        status=status,
        case_type=case_type,
        research_goal=research_goal,
        current_phase=current_phase,
        current_round=current_round,
        max_rounds=max_rounds,
        started_at=(
            datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
            if started_at is _UNSET
            else started_at
        ),
        completed_at=(
            datetime(2026, 7, 1, 10, 2, 0, tzinfo=timezone.utc)
            if completed_at is _UNSET
            else completed_at
        ),
        duration_sec=duration_sec,
        total_cost_usd=total_cost_usd,
        total_token_usage=total_token_usage,
        meta_review=meta_review,
        expert_feedback=expert_feedback,
        error_message=error_message,
        updated_at=(
            datetime(2026, 7, 1, 10, 2, 0, tzinfo=timezone.utc)
            if updated_at is _UNSET
            else updated_at
        ),
    )


def _make_hypothesis(
    *,
    hyp_id=None,
    name="Hypothesis A",
    description="Test mechanism description",
    mechanism="Inhibition of FLT3 pathway",
    status="completed",
    evolution_strategy="initial",
    elo_score=1200.0,
    novelty_score=8.5,
    plausibility_score=7.0,
    testability_score=9.0,
    safety_score=6.5,
    rank=1,
    created_at=_UNSET,
    updated_at=_UNSET,
):
    """构造 Hypothesis-like SimpleNamespace"""
    return SimpleNamespace(
        id=hyp_id or uuid4(),
        name=name,
        description=description,
        mechanism=mechanism,
        status=status,
        evolution_strategy=evolution_strategy,
        elo_score=elo_score,
        novelty_score=novelty_score,
        plausibility_score=plausibility_score,
        testability_score=testability_score,
        safety_score=safety_score,
        rank=rank,
        created_at=(
            datetime(2026, 7, 1, 9, 0, 0, tzinfo=timezone.utc)
            if created_at is _UNSET
            else created_at
        ),
        updated_at=(
            datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
            if updated_at is _UNSET
            else updated_at
        ),
    )


def _make_debate(
    *,
    debate_id=None,
    hyp_id=None,
    round_num=1,
    proponent_argument="The mechanism is plausible due to X",
    opponent_argument="Counter-evidence shows Y",
    judge_assessment="Consensus reached on mechanism",
    consensus_score=0.85,
    mechanism_agreed=True,
    refined_hypothesis="Refined: mechanism valid under condition Z",
    created_at=_UNSET,
):
    """构造 CoScientistDebateLog-like SimpleNamespace"""
    return SimpleNamespace(
        id=debate_id or uuid4(),
        hypothesis_id=hyp_id or uuid4(),
        round_num=round_num,
        proponent_argument=proponent_argument,
        opponent_argument=opponent_argument,
        judge_assessment=judge_assessment,
        consensus_score=consensus_score,
        mechanism_agreed=mechanism_agreed,
        refined_hypothesis=refined_hypothesis,
        created_at=(
            datetime(2026, 7, 1, 9, 30, 0, tzinfo=timezone.utc)
            if created_at is _UNSET
            else created_at
        ),
    )


def _make_db_mock(run=None, hypotheses=None, debates=None):
    """构造 AsyncSession mock

    - db.get(CoScientistRun, run_id) → run
    - db.execute(select(...)) → 返回带 scalars().all() 的结果
    """
    db = AsyncMock()
    db.get = AsyncMock(return_value=run)

    # 模拟 scalars().all() 链
    def _make_execute_result(items):
        result = MagicMock()
        result.scalars.return_value.all.return_value = items
        return result

    hypotheses = hypotheses or []
    debates = debates or []

    async def _execute(stmt):
        # 通过检查编译后的 SQL 字符串来判断返回什么
        stmt_str = str(stmt)
        if "hypotheses" in stmt_str.lower() or "Hypothesis" in stmt_str:
            return _make_execute_result(hypotheses)
        if "coscientist_debate_logs" in stmt_str.lower() or "CoScientistDebateLog" in stmt_str:
            return _make_execute_result(debates)
        return _make_execute_result([])

    db.execute = AsyncMock(side_effect=_execute)
    return db


# ============================================================
# 辅助函数测试
# ============================================================


class TestEloBucket:
    """_elo_bucket() 测试"""

    def test_high(self):
        assert _elo_bucket(1500.0) == "HIGH"

    def test_high_boundary(self):
        assert _elo_bucket(1200.0) == "HIGH"

    def test_mid(self):
        assert _elo_bucket(1100.0) == "MID"

    def test_mid_boundary(self):
        assert _elo_bucket(1000.0) == "MID"

    def test_low(self):
        assert _elo_bucket(800.0) == "LOW"

    def test_none(self):
        assert _elo_bucket(None) == "UNKNOWN"

    def test_negative(self):
        assert _elo_bucket(-100.0) == "LOW"


class TestStatusMaps:
    """状态映射常量测试"""

    def test_sdtm_status_map_completeness(self):
        from app.models.coscientist_run import RunStatus

        for status in [
            RunStatus.PENDING,
            RunStatus.RUNNING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        ]:
            assert status in _RUN_STATUS_TO_SDTM

    def test_fhir_status_map_completeness(self):
        from app.models.coscientist_run import RunStatus

        for status in [
            RunStatus.PENDING,
            RunStatus.RUNNING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        ]:
            assert status in _RUN_STATUS_TO_FHIR

    def test_fhir_status_values(self):
        from app.models.coscientist_run import RunStatus

        assert _RUN_STATUS_TO_FHIR[RunStatus.COMPLETED] == "completed"
        assert _RUN_STATUS_TO_FHIR[RunStatus.FAILED] == "stopped"
        assert _RUN_STATUS_TO_FHIR[RunStatus.PENDING] == "in-progress"


# ============================================================
# CoScientistSDTMExporter 测试
# ============================================================


class TestCoScientistSDTMExporterExport:
    """CoScientistSDTMExporter.export() 测试"""

    @pytest.mark.asyncio
    async def test_export_run_not_found(self):
        """运行不存在时抛出 NotFoundError"""
        db = _make_db_mock(run=None)
        exporter = CoScientistSDTMExporter(db)

        with pytest.raises(NotFoundError):
            await exporter.export(uuid4())

    @pytest.mark.asyncio
    async def test_export_success_basic(self):
        """成功导出 — 包含 HO/TS/DL 三个域"""
        run = _make_run()
        hyps = [
            _make_hypothesis(name="Hyp A", rank=1, elo_score=1200.0),
            _make_hypothesis(name="Hyp B", rank=2, elo_score=1100.0),
        ]
        debates = [_make_debate(round_num=1)]
        db = _make_db_mock(run=run, hypotheses=hyps, debates=debates)

        exporter = CoScientistSDTMExporter(db)
        result = await exporter.export(run.id)

        assert "domains" in result
        assert "metadata" in result
        assert set(result["domains"].keys()) == {"HO", "TS", "DL"}
        assert len(result["domains"]["HO"]) == 2
        assert len(result["domains"]["TS"]) == 5
        assert len(result["domains"]["DL"]) == 1

    @pytest.mark.asyncio
    async def test_export_metadata_fields(self):
        """元数据字段完整性"""
        run = _make_run()
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistSDTMExporter(db)
        result = await exporter.export(run.id)
        meta = result["metadata"]

        assert meta["source"] == "Co-Scientist"
        assert meta["run_id"] == str(run.id)
        assert meta["study_id"].startswith("CS-")
        assert "SDTMIG 3.3" in meta["version"]
        assert "record_counts" in meta
        assert meta["record_counts"]["HO"] == 0
        assert meta["record_counts"]["TS"] == 5
        assert meta["record_counts"]["DL"] == 0

    @pytest.mark.asyncio
    async def test_export_empty_hypotheses_and_debates(self):
        """空假设和空辩论时仍能正常导出"""
        run = _make_run()
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistSDTMExporter(db)
        result = await exporter.export(run.id)

        assert result["domains"]["HO"] == []
        assert result["domains"]["DL"] == []
        # TS 域始终有 5 条
        assert len(result["domains"]["TS"]) == 5


class TestCoScientistSDTMExporterHODomain:
    """CoScientistSDTMExporter._build_ho_domain() 测试"""

    def test_ho_domain_field_mapping(self):
        """HO 域字段映射正确性"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        study_id = "CS-ABC12345"
        usubjid = "run-123"
        hyps = [
            _make_hypothesis(
                name="Test Hyp",
                evolution_strategy="enhancement",
                elo_score=1300.0,
                status="completed",
                rank=1,
            ),
        ]

        records = exporter._build_ho_domain(study_id, usubjid, hyps)

        assert len(records) == 1
        rec = records[0]
        assert rec["STUDYID"] == study_id
        assert rec["DOMAIN"] == "HO"
        assert rec["USUBJID"] == usubjid
        assert rec["HOSEQ"] == 1
        assert rec["HOTERM"] == "Test Hyp"
        assert rec["HOCAT"] == "enhancement"
        assert rec["HOSCD"] == "HIGH"
        assert rec["HOORRES"] == "completed"
        assert rec["HOTSTRESC"] == "1"
        assert rec["HOBLFL"] == ""  # enhancement → not baseline
        assert "T" in rec["HODTC"]  # ISO datetime

    def test_ho_domain_baseline_flag_for_initial(self):
        """initial 策略标记为基线（HOBLFL=Y）"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        hyps = [
            _make_hypothesis(evolution_strategy="initial"),
            _make_hypothesis(evolution_strategy="enhancement"),
            _make_hypothesis(evolution_strategy=None),  # None 也视为 initial
        ]

        records = exporter._build_ho_domain("CS-X", "run", hyps)

        assert records[0]["HOBLFL"] == "Y"
        assert records[1]["HOBLFL"] == ""
        assert records[2]["HOBLFL"] == "Y"

    def test_ho_domain_seq_increments(self):
        """HOSEQ 从 1 递增"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        hyps = [_make_hypothesis() for _ in range(5)]

        records = exporter._build_ho_domain("CS-X", "run", hyps)

        seqs = [r["HOSEQ"] for r in records]
        assert seqs == [1, 2, 3, 4, 5]

    def test_ho_domain_elo_buckets(self):
        """HOSCD 字段反映 Elo 分级"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        hyps = [
            _make_hypothesis(elo_score=1500.0, name="High"),
            _make_hypothesis(elo_score=1100.0, name="Mid"),
            _make_hypothesis(elo_score=800.0, name="Low"),
            _make_hypothesis(elo_score=None, name="Unknown"),
        ]

        records = exporter._build_ho_domain("CS-X", "run", hyps)

        assert records[0]["HOSCD"] == "HIGH"
        assert records[1]["HOSCD"] == "MID"
        assert records[2]["HOSCD"] == "LOW"
        assert records[3]["HOSCD"] == "UNKNOWN"

    def test_ho_domain_none_rank_empty_string(self):
        """rank 为 None 时 HOTSTRESC 为空字符串"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        hyps = [_make_hypothesis(rank=None)]

        records = exporter._build_ho_domain("CS-X", "run", hyps)

        assert records[0]["HOTSTRESC"] == ""

    def test_ho_domain_name_truncation(self):
        """HOTERM 超长时截断到 200 字符"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        long_name = "A" * 300
        hyps = [_make_hypothesis(name=long_name)]

        records = exporter._build_ho_domain("CS-X", "run", hyps)

        assert len(records[0]["HOTERM"]) == 200

    def test_ho_domain_none_created_at(self):
        """created_at 为 None 时 HODTC 为空字符串"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        hyps = [_make_hypothesis(created_at=None)]

        records = exporter._build_ho_domain("CS-X", "run", hyps)

        assert records[0]["HODTC"] == ""


class TestCoScientistSDTMExporterTSDomain:
    """CoScientistSDTMExporter._build_ts_domain() 测试"""

    def test_ts_domain_has_5_params(self):
        """TS 域包含 5 条固定参数"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        run = _make_run()

        records = exporter._build_ts_domain("CS-X", run)

        assert len(records) == 5
        parmcds = [r["TSPARMCD"] for r in records]
        assert set(parmcds) == {"TITLE", "STYPE", "PHASE", "STATUS", "ROUND"}

    def test_ts_domain_status_mapping(self):
        """TS 域 STATUS 字段正确映射"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        run = _make_run(status="completed")

        records = exporter._build_ts_domain("CS-X", run)
        status_rec = next(r for r in records if r["TSPARMCD"] == "STATUS")
        assert status_rec["TSVAL"] == "COMPLETED"

    def test_ts_domain_round_format(self):
        """TS 域 ROUND 字段格式为 current/max"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        run = _make_run(current_round=3, max_rounds=7)

        records = exporter._build_ts_domain("CS-X", run)
        round_rec = next(r for r in records if r["TSPARMCD"] == "ROUND")
        assert round_rec["TSVAL"] == "3/7"

    def test_ts_domain_title_truncation(self):
        """TSVAL TITLE 字段截断到 500 字符"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        long_goal = "X" * 600
        run = _make_run(research_goal=long_goal)

        records = exporter._build_ts_domain("CS-X", run)
        title_rec = next(r for r in records if r["TSPARMCD"] == "TITLE")
        assert len(title_rec["TSVAL"]) == 500

    def test_ts_domain_none_case_type(self):
        """case_type 为 None 时回退到 custom"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        run = _make_run(case_type=None)

        records = exporter._build_ts_domain("CS-X", run)
        stype_rec = next(r for r in records if r["TSPARMCD"] == "STYPE")
        assert stype_rec["TSVAL"] == "custom"


class TestCoScientistSDTMExporterDLDomain:
    """CoScientistSDTMExporter._build_dl_domain() 测试"""

    def test_dl_domain_field_mapping(self):
        """DL 域字段映射正确性"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        debates = [
            _make_debate(
                round_num=1,
                consensus_score=0.92,
                mechanism_agreed=True,
                refined_hypothesis="Refined hypothesis text",
            ),
        ]

        records = exporter._build_dl_domain("CS-X", "run", debates)

        assert len(records) == 1
        rec = records[0]
        assert rec["DOMAIN"] == "DL"
        assert rec["DLSEQ"] == 1
        assert rec["DLTERM"] == "Refined hypothesis text"
        assert rec["DLCAT"] == "scientific_debate"
        assert "0.920" in rec["DLORRES"]
        assert rec["DLSTRESC"] == "AGREED"

    def test_dl_domain_disputed(self):
        """mechanism_agreed=False 时 DLSTRESC=DISPUTED"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        debates = [_make_debate(mechanism_agreed=False)]

        records = exporter._build_dl_domain("CS-X", "run", debates)
        assert records[0]["DLSTRESC"] == "DISPUTED"

    def test_dl_domain_fallback_to_proponent(self):
        """refined_hypothesis 为空时回退到 proponent_argument"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        debates = [
            _make_debate(refined_hypothesis=None, proponent_argument="Proponent arg"),
        ]

        records = exporter._build_dl_domain("CS-X", "run", debates)
        assert records[0]["DLTERM"] == "Proponent arg"

    def test_dl_domain_none_consensus(self):
        """consensus_score 为 None 时显示 N/A"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        debates = [_make_debate(consensus_score=None)]

        records = exporter._build_dl_domain("CS-X", "run", debates)
        assert "N/A" in records[0]["DLORRES"]

    def test_dl_domain_empty(self):
        """空辩论列表返回空记录"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        records = exporter._build_dl_domain("CS-X", "run", [])
        assert records == []


class TestCoScientistSDTMExporterToCSV:
    """CoScientistSDTMExporter.to_csv() 测试"""

    def test_csv_contains_metadata_header(self):
        """CSV 包含元数据头"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        sdtm_data = {
            "domains": {"HO": [], "TS": [], "DL": []},
            "metadata": {
                "study_id": "CS-TEST1234",
                "version": "SDTMIG 3.3",
                "source": "Co-Scientist",
                "export_time": "2026-07-31T00:00:00+00:00",
                "record_counts": {"HO": 0, "TS": 0, "DL": 0},
            },
        }

        csv = exporter.to_csv(sdtm_data)
        assert "# CDISC SDTM Export (Co-Scientist)" in csv
        assert "CS-TEST1234" in csv

    def test_csv_contains_domain_sections(self):
        """CSV 包含域分隔符"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        sdtm_data = {
            "domains": {
                "HO": [
                    {
                        "STUDYID": "CS-X",
                        "DOMAIN": "HO",
                        "USUBJID": "run-1",
                        "HOSEQ": 1,
                        "HOTERM": "Test",
                    }
                ],
                "TS": [],
                "DL": [],
            },
            "metadata": {
                "study_id": "CS-X",
                "version": "",
                "source": "",
                "export_time": "",
                "record_counts": {},
            },
        }

        csv = exporter.to_csv(sdtm_data)
        assert "--- HO Domain ---" in csv

    def test_csv_skips_empty_domains(self):
        """空域不出现在 CSV 中"""
        exporter = CoScientistSDTMExporter(db=MagicMock())
        sdtm_data = {
            "domains": {"HO": [], "TS": [], "DL": []},
            "metadata": {
                "study_id": "",
                "version": "",
                "source": "",
                "export_time": "",
                "record_counts": {},
            },
        }

        csv = exporter.to_csv(sdtm_data)
        assert "--- HO Domain ---" not in csv
        assert "--- TS Domain ---" not in csv


# ============================================================
# CoScientistFHIRExporter 测试
# ============================================================


class TestCoScientistFHIRExporterExport:
    """CoScientistFHIRExporter.export_research_study() 测试"""

    @pytest.mark.asyncio
    async def test_export_run_not_found(self):
        """运行不存在时抛出 NotFoundError"""
        db = _make_db_mock(run=None)
        exporter = CoScientistFHIRExporter(db)

        with pytest.raises(NotFoundError):
            await exporter.export_research_study(uuid4())

    @pytest.mark.asyncio
    async def test_export_bundle_structure(self):
        """Bundle 结构完整性"""
        run = _make_run()
        hyps = [_make_hypothesis(), _make_hypothesis(name="Hyp B")]
        db = _make_db_mock(run=run, hypotheses=hyps, debates=[])

        exporter = CoScientistFHIRExporter(db)
        bundle = await exporter.export_research_study(run.id)

        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "transaction"
        assert bundle["total"] == 3  # 1 ResearchStudy + 2 ResearchSubject
        assert len(bundle["entry"]) == 3

    @pytest.mark.asyncio
    async def test_export_first_entry_is_research_study(self):
        """第一条 entry 是 ResearchStudy"""
        run = _make_run()
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistFHIRExporter(db)
        bundle = await exporter.export_research_study(run.id)

        first_resource = bundle["entry"][0]["resource"]
        assert first_resource["resourceType"] == "ResearchStudy"

    @pytest.mark.asyncio
    async def test_export_research_subjects_count(self):
        """ResearchSubject 数量等于假设数"""
        run = _make_run()
        hyps = [_make_hypothesis() for _ in range(5)]
        db = _make_db_mock(run=run, hypotheses=hyps, debates=[])

        exporter = CoScientistFHIRExporter(db)
        bundle = await exporter.export_research_study(run.id)

        subjects = [
            e["resource"]
            for e in bundle["entry"]
            if e["resource"]["resourceType"] == "ResearchSubject"
        ]
        assert len(subjects) == 5

    @pytest.mark.asyncio
    async def test_export_bundle_id_format(self):
        """Bundle ID 格式为 cs-bundle-{run_id}"""
        run = _make_run()
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistFHIRExporter(db)
        bundle = await exporter.export_research_study(run.id)

        assert bundle["id"] == f"cs-bundle-{run.id}"


class TestCoScientistFHIRExporterResearchStudy:
    """CoScientistFHIRExporter._build_research_study() 测试"""

    def test_research_study_basic_fields(self):
        """ResearchStudy 基本字段"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        run = _make_run()
        study = exporter._build_research_study(run, [], [])

        assert study["resourceType"] == "ResearchStudy"
        assert study["id"] == str(run.id)
        assert study["status"] == "completed"
        assert study["enrollment"] == 0
        assert study["focus"][0]["text"] == run.research_goal

    def test_research_study_status_mapping(self):
        """运行状态 → FHIR status 映射"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        for run_status, fhir_status in [
            ("pending", "in-progress"),
            ("running", "in-progress"),
            ("completed", "completed"),
            ("failed", "stopped"),
            ("cancelled", "stopped"),
        ]:
            run = _make_run(status=run_status)
            study = exporter._build_research_study(run, [], [])
            assert study["status"] == fhir_status

    def test_research_study_arm_from_hypotheses(self):
        """假设 → arm 映射"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        hyps = [
            _make_hypothesis(name="Hyp A", evolution_strategy="initial"),
            _make_hypothesis(name="Hyp B", evolution_strategy="enhancement"),
        ]
        run = _make_run()
        study = exporter._build_research_study(run, hyps, [])

        assert len(study["arm"]) == 2
        assert study["arm"][0]["name"] == "Hyp A"
        assert study["arm"][0]["type"]["text"] == "initial"
        assert study["arm"][1]["type"]["text"] == "enhancement"

    def test_research_study_objective_from_meta_review(self):
        """meta_review → objective"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        run = _make_run(meta_review="Final synthesis report")
        study = exporter._build_research_study(run, [], [])

        assert "objective" in study
        assert study["objective"][0]["name"] == "Meta Review"
        assert study["objective"][0]["description"] == "Final synthesis report"

    def test_research_study_no_objective_when_meta_review_none(self):
        """meta_review 为 None 时不包含 objective"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        run = _make_run(meta_review=None)
        study = exporter._build_research_study(run, [], [])

        assert "objective" not in study

    def test_research_study_notes_from_debates(self):
        """辩论 → note"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        debates = [
            _make_debate(round_num=1, consensus_score=0.9, mechanism_agreed=True),
            _make_debate(round_num=2, consensus_score=0.5, mechanism_agreed=False),
        ]
        run = _make_run()
        study = exporter._build_research_study(run, [], debates)

        assert "note" in study
        assert len(study["note"]) == 2
        assert "Round 1" in study["note"][0]["text"]

    def test_research_study_notes_capped_at_20(self):
        """note 数量上限 20"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        debates = [
            _make_debate(round_num=i, consensus_score=0.5, mechanism_agreed=True)
            for i in range(1, 30)
        ]
        run = _make_run()
        study = exporter._build_research_study(run, [], debates)

        assert len(study["note"]) <= 20

    def test_research_study_extensions_for_cost_and_tokens(self):
        """成本和 token 用量 → extension"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        run = _make_run(total_cost_usd=0.5, total_token_usage={"total": 10000})
        study = exporter._build_research_study(run, [], [])

        ext_urls = [e["url"] for e in study["extension"]]
        assert any("totalCostUsd" in u for u in ext_urls)
        assert any("tokenUsage" in u for u in ext_urls)

    def test_research_study_no_extension_when_no_cost(self):
        """无成本数据时不包含 extension"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        run = _make_run(total_cost_usd=None, total_token_usage=None)
        study = exporter._build_research_study(run, [], [])

        assert "extension" not in study

    def test_research_study_category_coding(self):
        """category 包含案例类型编码"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        run = _make_run(case_type="aml")
        study = exporter._build_research_study(run, [], [])

        coding = study["category"][0]["coding"][0]
        assert coding["code"] == "aml"
        assert "AML" in coding["display"]

    def test_research_study_period(self):
        """period 包含 started_at 和 completed_at"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        run = _make_run()
        study = exporter._build_research_study(run, [], [])

        assert study["period"]["start"] is not None
        assert study["period"]["end"] is not None


class TestCoScientistFHIRExporterResearchSubject:
    """CoScientistFHIRExporter._build_research_subject() 测试"""

    def test_research_subject_basic_fields(self):
        """ResearchSubject 基本字段"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        hyp = _make_hypothesis()
        run = _make_run()
        subject = exporter._build_research_subject(hyp, run)

        assert subject["resourceType"] == "ResearchSubject"
        assert subject["id"].startswith("rs-")
        assert subject["study"]["reference"] == f"ResearchStudy/{run.id}"
        assert subject["individual"]["display"] == hyp.name

    def test_research_subject_status_mapping(self):
        """假设状态 → ResearchSubject.status"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        run = _make_run()
        for hyp_status, expected in [
            ("draft", "candidate"),
            ("completed", "active"),
            ("eliminated", "failed"),
            ("eliminated_by_expert", "failed"),
            ("merged", "completed"),
        ]:
            hyp = _make_hypothesis(status=hyp_status)
            subject = exporter._build_research_subject(hyp, run)
            assert subject["status"] == expected

    def test_research_subject_extensions_for_scores(self):
        """Elo/rank/评分维度 → extension"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        hyp = _make_hypothesis(
            elo_score=1200.0,
            rank=3,
            novelty_score=8.0,
            plausibility_score=7.0,
            testability_score=9.0,
            safety_score=6.0,
        )
        run = _make_run()
        subject = exporter._build_research_subject(hyp, run)

        ext_urls = [e["url"] for e in subject["extension"]]
        assert any("eloScore" in u for u in ext_urls)
        assert any("rank" in u for u in ext_urls)
        assert any("noveltyScore" in u for u in ext_urls)
        assert any("plausibilityScore" in u for u in ext_urls)
        assert any("testabilityScore" in u for u in ext_urls)
        assert any("safetyScore" in u for u in ext_urls)

    def test_research_subject_no_extension_when_no_scores(self):
        """无评分数据时不包含 extension"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        hyp = _make_hypothesis(
            elo_score=None,
            rank=None,
            novelty_score=None,
            plausibility_score=None,
            testability_score=None,
            safety_score=None,
        )
        run = _make_run()
        subject = exporter._build_research_subject(hyp, run)

        assert "extension" not in subject


class TestCoScientistFHIRExporterMakeEntry:
    """CoScientistFHIRExporter._make_entry() 测试"""

    def test_make_entry_structure(self):
        """entry 结构完整性"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        resource = {"resourceType": "ResearchStudy", "id": "test-123"}

        entry = exporter._make_entry(resource)

        assert entry["fullUrl"] == "urn:uuid:test-123"
        assert entry["resource"] == resource
        assert entry["request"]["method"] == "POST"
        assert entry["request"]["url"] == "ResearchStudy"

    def test_make_entry_empty_id(self):
        """资源无 ID 时 fullUrl 为空字符串"""
        exporter = CoScientistFHIRExporter(db=MagicMock())
        resource = {"resourceType": "ResearchStudy"}

        entry = exporter._make_entry(resource)

        assert entry["fullUrl"] == ""


# ============================================================
# CoScientistMarkdownExporter 测试
# ============================================================


class TestCoScientistMarkdownExporter:
    """CoScientistMarkdownExporter 测试"""

    @pytest.mark.asyncio
    async def test_export_run_not_found(self):
        """运行不存在时抛出 NotFoundError"""
        db = _make_db_mock(run=None)
        exporter = CoScientistMarkdownExporter(db)

        with pytest.raises(NotFoundError):
            await exporter.export_markdown(uuid4())

    @pytest.mark.asyncio
    async def test_export_markdown_basic_structure(self):
        """Markdown 报告基本结构"""
        run = _make_run()
        hyps = [_make_hypothesis(name="Test Hyp", rank=1)]
        db = _make_db_mock(run=run, hypotheses=hyps, debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "# Co-Scientist 运行报告" in md
        assert "## 1. 基本信息" in md
        assert "## 2. 假设排名" in md
        assert "## 3. 辩论摘要" in md
        assert "## 5. 资源消耗" in md

    @pytest.mark.asyncio
    async def test_export_markdown_contains_research_goal(self):
        """报告包含研究目标"""
        run = _make_run(research_goal="Find cure for XYZ disease")
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "Find cure for XYZ disease" in md

    @pytest.mark.asyncio
    async def test_export_markdown_contains_meta_review(self):
        """报告包含元评审"""
        run = _make_run(meta_review="This is the meta review content")
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "## 4. 元评审报告" in md
        assert "This is the meta review content" in md

    @pytest.mark.asyncio
    async def test_export_markdown_no_meta_review_section_when_none(self):
        """meta_review 为 None 时不包含元评审章节"""
        run = _make_run(meta_review=None)
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "## 4. 元评审报告" not in md

    @pytest.mark.asyncio
    async def test_export_markdown_hypothesis_table(self):
        """报告包含假设排名表"""
        run = _make_run()
        hyps = [
            _make_hypothesis(name="Hyp A", rank=1, elo_score=1200.0),
            _make_hypothesis(name="Hyp B", rank=2, elo_score=1100.0),
        ]
        db = _make_db_mock(run=run, hypotheses=hyps, debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "| 排名 |" in md
        assert "Hyp A" in md
        assert "Hyp B" in md
        assert "#1" in md
        assert "#2" in md

    @pytest.mark.asyncio
    async def test_export_markdown_empty_hypotheses(self):
        """空假设列表显示暂无数据"""
        run = _make_run()
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "_暂无假设数据_" in md

    @pytest.mark.asyncio
    async def test_export_markdown_debate_table(self):
        """报告包含辩论摘要表"""
        run = _make_run()
        debates = [
            _make_debate(round_num=1, consensus_score=0.9, mechanism_agreed=True),
        ]
        db = _make_db_mock(run=run, hypotheses=[], debates=debates)

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "| 轮次 |" in md
        assert "0.900" in md
        assert "✓" in md

    @pytest.mark.asyncio
    async def test_export_markdown_empty_debates(self):
        """空辩论列表显示暂无数据"""
        run = _make_run()
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "_暂无辩论记录_" in md

    @pytest.mark.asyncio
    async def test_export_markdown_top_n_limit(self):
        """top_n 参数限制假设数量

        注：SQL .limit() 由数据库执行，单元测试 mock 无法模拟。
        此处模拟 DB 返回限制后的 5 条记录，验证报告标题和内容正确。
        """
        run = _make_run()
        # 模拟 DB 应用 limit(5) 后返回的结果
        hyps = [_make_hypothesis(name=f"Hyp {i}", rank=i) for i in range(1, 6)]
        db = _make_db_mock(run=run, hypotheses=hyps, debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id, top_n=5)

        assert "Top 5" in md
        assert "Hyp 1" in md
        assert "Hyp 5" in md
        assert "Hyp 6" not in md

    @pytest.mark.asyncio
    async def test_export_markdown_cost_and_tokens(self):
        """报告包含成本和 token 用量"""
        run = _make_run(
            total_cost_usd=0.123456,
            total_token_usage={"prompt": 1000, "completion": 500, "total": 1500},
        )
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "$0.123456" in md
        assert "prompt=1000" in md
        assert "completion=500" in md
        assert "total=1500" in md

    @pytest.mark.asyncio
    async def test_export_markdown_expert_feedback(self):
        """报告包含专家反馈历史"""
        run = _make_run(
            expert_feedback=[
                {
                    "round": 1,
                    "feedback_text": "Need more evidence",
                    "feedback_type": "critique",
                }
            ]
        )
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "## 6. 专家反馈历史" in md
        assert "Need more evidence" in md
        assert "critique" in md

    @pytest.mark.asyncio
    async def test_export_markdown_no_expert_feedback_section_when_empty(self):
        """无专家反馈时不包含该章节"""
        run = _make_run(expert_feedback=None)
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "## 6. 专家反馈历史" not in md

    @pytest.mark.asyncio
    async def test_export_markdown_footer(self):
        """报告包含生成时间页脚"""
        run = _make_run()
        db = _make_db_mock(run=run, hypotheses=[], debates=[])

        exporter = CoScientistMarkdownExporter(db)
        md = await exporter.export_markdown(run.id)

        assert "AI 药物研发平台 Co-Scientist 引擎自动生成" in md
        assert "UTC" in md
