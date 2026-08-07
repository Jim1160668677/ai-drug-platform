"""KnownDrugValidator 测试 — 验证 5 个已知药物的合成路线生成

覆盖：
1. validate_all 返回结构（3 测试）
2. 难度分组（2 测试）
3. 汇总统计（3 测试）
4. list_known_drugs（1 测试）
5. 路线准确性范围（1 测试）
"""
import pytest

from app.core.security import hash_password, UserRole
from app.models.user import User
from app.services.synthesis.known_drug_validator import KnownDrugValidator


# ========== 辅助 fixture ==========

@pytest.fixture
async def setup_user(async_db_session):
    user = User(
        email="known-drug-test@ai-drug.com",
        name="Known Drug Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


# ========== validate_all 返回结构测试 ==========

class TestValidateAllReturnsStructure:
    @pytest.mark.asyncio
    async def test_validate_all_returns_dict(self, async_db_session, setup_user):
        """返回 dict 含 results / summary / conclusion"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        assert isinstance(result, dict)
        assert "results" in result
        assert "summary" in result
        assert "conclusion" in result

    @pytest.mark.asyncio
    async def test_validate_all_runs_5_drugs(self, async_db_session, setup_user):
        """results 含 5 个药物案例"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        assert len(result["results"]) == 5

    @pytest.mark.asyncio
    async def test_validate_all_total_field(self, async_db_session, setup_user):
        """total 字段 = 5"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        assert result.get("total") == 5


# ========== 难度分组测试 ==========

class TestValidateDifficulty:
    @pytest.mark.asyncio
    async def test_aspirin_easy_difficulty(self, async_db_session, setup_user):
        """阿司匹林 expected_difficulty = easy"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        aspirin = next((r for r in result["results"] if r.get("drug_name") == "阿司匹林"), None)
        assert aspirin is not None
        assert aspirin.get("expected_difficulty") == "easy"

    @pytest.mark.asyncio
    async def test_omeprazole_hard_difficulty(self, async_db_session, setup_user):
        """奥美拉唑 expected_difficulty = hard"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        omeprazole = next((r for r in result["results"] if r.get("drug_name") == "奥美拉唑"), None)
        assert omeprazole is not None
        assert omeprazole.get("expected_difficulty") == "hard"


# ========== 汇总统计测试 ==========

class TestValidateSummary:
    @pytest.mark.asyncio
    async def test_summary_has_avg_score(self, async_db_session, setup_user):
        """summary 含 avg_score"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        assert "avg_score" in result["summary"]
        assert 0 <= result["summary"]["avg_score"] <= 1

    @pytest.mark.asyncio
    async def test_summary_has_pass_rate(self, async_db_session, setup_user):
        """summary 含 pass_rate"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        assert "pass_rate" in result["summary"]
        assert 0 <= result["summary"]["pass_rate"] <= 1

    @pytest.mark.asyncio
    async def test_summary_has_by_difficulty(self, async_db_session, setup_user):
        """summary 含 by_difficulty 分组"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        assert "by_difficulty" in result["summary"]
        assert isinstance(result["summary"]["by_difficulty"], dict)


# ========== list_known_drugs 测试 ==========

class TestListKnownDrugs:
    def test_list_known_drugs_returns_5(self):
        """list_known_drugs() 返回 5 个药物"""
        drugs = KnownDrugValidator.list_known_drugs()
        assert len(drugs) == 5
        for d in drugs:
            assert "drug_name" in d
            assert "smiles" in d
            assert "target_gene" in d
            assert "expected_difficulty" in d


# ========== 路线准确性测试 ==========

class TestRouteAccuracy:
    @pytest.mark.asyncio
    async def test_route_accuracy_in_range(self, async_db_session, setup_user):
        """route_accuracy_score 在 0-1 之间"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        for r in result["results"]:
            score = r.get("route_accuracy_score", 0)
            assert 0 <= score <= 1, f"非法 score: {score} (drug={r.get('drug_name')})"

    @pytest.mark.asyncio
    async def test_conclusion_string_nonempty(self, async_db_session, setup_user):
        """conclusion 字符串非空"""
        validator = KnownDrugValidator(async_db_session, llm_client=None)
        result = await validator.validate_all(user=setup_user)
        assert isinstance(result["conclusion"], str)
        assert len(result["conclusion"]) > 0
