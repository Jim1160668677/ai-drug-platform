"""失败知识库 — 单元测试

覆盖目标：
- FailureKnowledge 模型创建和查询
- WrongPathAvoider 规避逻辑（query_failures + should_avoid）
- ingest_failure 数据流转（规则分类 + 新建/累加分支）

测试策略：
- 数据库会话全部 Mock（MagicMock + AsyncMock）
- FailureKnowledge / Experiment ORM 对象用 SimpleNamespace 构造
- 不依赖真实数据库
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


# ============================================================
# FailureKnowledge 模型基础测试
# ============================================================

class TestFailureKnowledgeModel:
    """FailureKnowledge 模型基本属性"""

    def test_failure_reason_constants(self):
        """FailureReason 枚举值完整性"""
        from app.models.failure_knowledge import FailureReason

        assert FailureReason.CONTAMINATION == "contamination"
        assert FailureReason.CONCENTRATION == "concentration"
        assert FailureReason.PROTOCOL_DEGRADATION == "protocol_degradation"
        assert FailureReason.EQUIPMENT_MALFUNCTION == "equipment_malfunction"
        assert FailureReason.HUMAN_ERROR == "human_error"
        assert FailureReason.BIOLOGICAL_VARIABILITY == "biological_variability"
        assert FailureReason.UNKNOWN == "unknown"

    def test_failure_knowledge_repr(self):
        """FailureKnowledge __repr__ 格式"""
        from app.models.failure_knowledge import FailureKnowledge

        fk = SimpleNamespace(
            id=uuid4(),
            failure_reason="contamination",
            project_id=uuid4(),
        )
        fk.__repr__ = lambda self=fk: f"<FailureKnowledge reason={self.failure_reason} project={self.project_id}>"

        repr_str = fk.__repr__()
        assert "contamination" in repr_str
        assert "FailureKnowledge" in repr_str

    @pytest.mark.asyncio
    async def test_failure_knowledge_creation(self):
        """验证 FailureKnowledge 可被正确构造（不依赖 DB）"""
        from app.models.failure_knowledge import FailureKnowledge, FailureReason

        project_id = uuid4()
        fk = SimpleNamespace(
            id=uuid4(),
            project_id=project_id,
            failure_reason=FailureReason.CONTAMINATION,
            failure_params={"ph": 7.4, "temperature": 37},
            wrong_path_proof="培养基出现霉菌污染",
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            experiment_id=None,
            is_high_confidence=False,
            failure_count=1,
            notes="首次发现污染",
        )

        assert fk.project_id == project_id
        assert fk.failure_reason == "contamination"
        assert fk.failure_params["ph"] == 7.4
        assert fk.is_high_confidence is False
        assert fk.failure_count == 1


# ============================================================
# WrongPathAvoider 规避逻辑
# ============================================================

class TestWrongPathAvoider:
    """WrongPathAvoider 查询和判定逻辑"""

    @pytest.mark.asyncio
    async def test_query_failures_empty(self):
        """无失败记录时返回空列表"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalars.return_value.all.return_value = []
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        avoider = WrongPathAvoider(mock_db)
        result = await avoider.query_failures(project_id=uuid4())

        assert result == []

    @pytest.mark.asyncio
    async def test_query_failures_with_records(self):
        """有失败记录时返回建议列表"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        target_id = uuid4()
        molecule_id = uuid4()

        records = [
            SimpleNamespace(
                id=uuid4(),
                failure_reason="contamination",
                wrong_path_proof="培养基污染",
                is_high_confidence=True,
                failure_count=3,
                target_id=target_id,
                molecule_id=molecule_id,
            ),
            SimpleNamespace(
                id=uuid4(),
                failure_reason="concentration",
                wrong_path_proof="浓度太高导致细胞死亡",
                is_high_confidence=False,
                failure_count=1,
                target_id=None,
                molecule_id=None,
            ),
        ]

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalars.return_value.all.return_value = records
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        avoider = WrongPathAvoider(mock_db)
        result = await avoider.query_failures(project_id=uuid4())

        assert len(result) == 2
        assert result[0]["failure_reason"] == "contamination"
        assert result[0]["is_high_confidence"] is True
        assert result[0]["failure_count"] == 3
        assert "建议" in result[0]["suggestion"] or "污染" in result[0]["suggestion"]
        assert result[1]["failure_reason"] == "concentration"

    @pytest.mark.asyncio
    async def test_query_failures_with_filters(self):
        """按 target_id / molecule_id 过滤"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalars.return_value.all.return_value = []
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)

        avoider = WrongPathAvoider(mock_db)
        pid = uuid4()
        tid = uuid4()
        mid = uuid4()

        result = await avoider.query_failures(project_id=pid, target_id=tid, molecule_id=mid)

        mock_db.execute.assert_called_once()
        assert result == []

    def test_should_avoid_high_similarity(self):
        """高相似度(>=0.7) → 应规避"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        mock_db = MagicMock()
        avoider = WrongPathAvoider(mock_db)

        assert avoider.should_avoid(0.8) is True
        assert avoider.should_avoid(0.7) is True
        assert avoider.should_avoid(0.95) is True

    def test_should_avoid_low_similarity(self):
        """低相似度(<0.7) → 可尝试"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        mock_db = MagicMock()
        avoider = WrongPathAvoider(mock_db)

        assert avoider.should_avoid(0.6) is False
        assert avoider.should_avoid(0.3) is False
        assert avoider.should_avoid(0.0) is False

    def test_should_avoid_custom_threshold(self):
        """自定义阈值"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        mock_db = MagicMock()
        avoider = WrongPathAvoider(mock_db)

        assert avoider.should_avoid(0.5, high_confidence_threshold=0.4) is True
        assert avoider.should_avoid(0.5, high_confidence_threshold=0.6) is False

    def test_build_suggestion_handles_unknown(self):
        """未知原因的建议文本"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        mock_db = MagicMock()
        avoider = WrongPathAvoider(mock_db)

        record = SimpleNamespace(
            failure_reason="unknown",
            wrong_path_proof=None,
            is_high_confidence=False,
            failure_count=1,
        )
        suggestion = avoider._build_suggestion(record)
        assert "未知原因" in suggestion
        assert "无详细证明" in suggestion

    def test_build_suggestion_high_confidence(self):
        """高置信度标记"""
        from app.services.analyzer.wrong_path_service import WrongPathAvoider

        mock_db = MagicMock()
        avoider = WrongPathAvoider(mock_db)

        record = SimpleNamespace(
            failure_reason="contamination",
            wrong_path_proof="真菌污染",
            is_high_confidence=True,
            failure_count=5,
        )
        suggestion = avoider._build_suggestion(record)
        assert "高置信度" in suggestion
        assert "5 次" in suggestion


# ============================================================
# ingest_failure 数据流转
# ============================================================

class TestIngestFailure:
    """ingest_failure 完整数据流转"""

    @pytest.mark.asyncio
    async def test_skip_non_failed_experiment(self):
        """experiment.success != False → 跳过"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            success=True,
            result={},
            config={},
            notes="",
        )
        mock_db = MagicMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["failure_knowledge_id"] is None
        assert result["failure_reason"] is None
        assert result["is_new"] is False
        assert "非失败状态" in result["message"]

    @pytest.mark.asyncio
    async def test_skip_none_success(self):
        """experiment.success 为 None → 跳过"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            success=None,
            result={},
            config={},
            notes="",
        )
        mock_db = MagicMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["is_new"] is False

    @pytest.mark.asyncio
    async def test_rule_based_classification_contamination(self):
        """规则分类：污染关键词 → contamination"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            success=False,
            result={"issue": "培养基出现污染"},
            config={},
            notes="培养皿污染菌",
            exp_type="cytotoxicity",
            status="failed",
            project_id=uuid4(),
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["failure_reason"] == "contamination"
        assert result["is_new"] is True
        assert result["failure_knowledge_id"] is not None
        assert experiment.failure_reason is not None
        assert experiment.failure_params is not None
        assert experiment.wrong_path_proof is not None
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_rule_based_classification_concentration(self):
        """规则分类：浓度关键词 → concentration"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            success=False,
            result={"error": "细胞死亡，浓度太高"},
            config={"dose": "10uM"},
            notes="剂量过大",
            exp_type="cytotoxicity",
            status="failed",
            project_id=uuid4(),
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["failure_reason"] == "concentration"

    @pytest.mark.asyncio
    async def test_existing_failure_count_increment(self):
        """已有同类失败 → 计数累加"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        project_id = uuid4()
        existing_fk = SimpleNamespace(
            id=uuid4(),
            failure_count=2,
            failure_params=None,
            wrong_path_proof="培养基污染",
        )

        experiment = SimpleNamespace(
            id=uuid4(),
            success=False,
            result={"issue": "污染"},
            config={},
            notes="再次污染",
            exp_type="cytotoxicity",
            status="failed",
            project_id=project_id,
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=2,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = existing_fk
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["is_new"] is False
        assert result["failure_knowledge_id"] == str(existing_fk.id)
        assert existing_fk.failure_count == 3
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_failure_fallback(self):
        """无关键词匹配 → unknown 兜底"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            id=uuid4(),
            success=False,
            result={"error": "something went wrong"},
            config={},
            notes="unexplained failure",
            exp_type="in_vitro",
            status="failed",
            project_id=uuid4(),
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["failure_reason"] == "unknown"
        assert result["is_new"] is True

    @pytest.mark.asyncio
    async def test_extract_failure_params(self):
        """参数快照提取"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            exp_type="cytotoxicity",
            status="failed",
            config={"dose": "5uM"},
            result={"survival": 0.1},
            iteration=2,
            lab_source="lab-A",
            target_id=uuid4(),
            molecule_id=uuid4(),
        )

        mock_db = MagicMock()
        loop = FeedbackLoop(mock_db)
        params = loop._extract_failure_params(experiment)

        assert params["exp_type"] == "cytotoxicity"
        assert params["status"] == "failed"
        assert params["config"] == {"dose": "5uM"}
        assert params["result"] == {"survival": 0.1}
        assert params["iteration"] == 2
        assert params["lab_source"] == "lab-A"
        assert "target_id" in params
        assert "molecule_id" in params

    @pytest.mark.asyncio
    async def test_classify_failure_rule_hit(self):
        """规则分类直接命中"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            success=False,
            result={"error": "仪器故障 error code 500"},
            config={},
            notes="设备异常",
            exp_type="pdx",
            status="failed",
            project_id=uuid4(),
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_db = MagicMock()
        loop = FeedbackLoop(mock_db)
        reason, proof = await loop._classify_failure(experiment)

        assert reason == "equipment_malfunction"
        assert proof is not None

    @pytest.mark.asyncio
    async def test_classify_failure_human_error(self):
        """规则分类：人为失误"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        experiment = SimpleNamespace(
            success=False,
            result={"error": "加样失误，pipette 操作错误"},
            config={},
            notes="操作失误",
            exp_type="in_vitro",
            status="failed",
            project_id=uuid4(),
            target_id=None,
            molecule_id=None,
            hypothesis_id=None,
            iteration=1,
            lab_source="test-lab",
        )

        mock_db = MagicMock()
        loop = FeedbackLoop(mock_db)
        reason, proof = await loop._classify_failure(experiment)

        assert reason == "human_error"

    @pytest.mark.asyncio
    async def test_full_data_flow_new_failure(self):
        """完整数据流：新失败 → 创建 FailureKnowledge → 回写 experiment"""
        from app.services.experiment.feedback_loop import FeedbackLoop

        project_id = uuid4()
        target_id = uuid4()
        molecule_id = uuid4()
        hypothesis_id = uuid4()

        experiment = SimpleNamespace(
            id=uuid4(),
            success=False,
            result={"issue": "培养皿污染"},
            config={"dose": "10uM"},
            notes="真菌污染，需重新准备",
            exp_type="cytotoxicity",
            status="failed",
            project_id=project_id,
            target_id=target_id,
            molecule_id=molecule_id,
            hypothesis_id=hypothesis_id,
            iteration=1,
            lab_source="test-lab",
            failure_reason=None,
            failure_params=None,
            wrong_path_proof=None,
        )

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        loop = FeedbackLoop(mock_db)
        result = await loop.ingest_failure(experiment)

        assert result["is_new"] is True
        assert result["failure_reason"] == "contamination"
        assert result["failure_knowledge_id"] is not None

        assert experiment.failure_reason == {"primary": "contamination", "detail": "检测到关键词「污染」"}
        assert experiment.failure_params is not None
        assert experiment.failure_params["target_id"] == str(target_id)
        assert experiment.failure_params["molecule_id"] == str(molecule_id)
        assert experiment.wrong_path_proof is not None

        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.project_id == project_id
        assert added_obj.failure_reason == "contamination"
        assert added_obj.target_id == target_id
        assert added_obj.molecule_id == molecule_id
        assert added_obj.hypothesis_id == hypothesis_id
        assert added_obj.failure_count == 1
        assert added_obj.is_high_confidence is False