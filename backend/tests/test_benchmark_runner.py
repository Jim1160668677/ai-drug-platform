"""BenchmarkRunner 测试 — 覆盖 3 模式对比 × 7 指标 × 9 案例

覆盖：
1. 初始化与常量（2 测试）
2. run_case 三种模式（4 测试）— hybrid / traditional_supercompute / llm_only / 持久化
3. compare_modes（2 测试）— cost_saving_pct / hybrid 综合得分
4. run_all_cases（2 测试）— 9 案例汇总 / energy_saving_pct
"""
import pytest

from app.core.security import hash_password, UserRole
from app.models.benchmark_report import BenchmarkReport, BenchmarkMode
from app.models.project import Project
from app.models.user import User
from app.services.orchestrator.benchmark import BenchmarkRunner


# ========== 辅助 fixture ==========

@pytest.fixture
async def setup_user(async_db_session):
    """创建测试用户"""
    user = User(
        email="bench-test@ai-drug.com",
        name="Bench Tester",
        hashed_password=hash_password("test123456"),
        role=UserRole.FOUNDER,
        is_active=True,
    )
    async_db_session.add(user)
    await async_db_session.flush()
    return user


@pytest.fixture
async def mock_llm_client():
    from app.clients.mock.llm_mock import MockLLMClient
    return MockLLMClient()


# ========== 初始化与常量测试 ==========

class TestBenchmarkRunnerInit:
    def test_init_creates_runner(self, async_db_session):
        """初始化成功"""
        runner = BenchmarkRunner(async_db_session)
        assert runner.db is async_db_session
        assert runner.llm_client is None
        assert runner.llm_orchestrator is None

    def test_benchmark_cases_count(self):
        """BENCHMARK_CASES 含 9 个案例"""
        assert len(BenchmarkRunner.BENCHMARK_CASES) == 9
        case_ids = [c["case_id"] for c in BenchmarkRunner.BENCHMARK_CASES]
        # 验证关键案例存在
        for required in ["aspirin", "ibuprofen", "caffeine", "omeprazole", "imatinib"]:
            assert required in case_ids, f"缺案例 {required}"


# ========== run_case 测试 ==========

class TestRunCase:
    @pytest.mark.asyncio
    async def test_run_case_hybrid_mode(self, async_db_session, setup_user, mock_llm_client):
        """hybrid 模式返回 7 个指标"""
        runner = BenchmarkRunner(async_db_session, llm_client=mock_llm_client)
        result = await runner.run_case(
            case_id="aspirin",
            mode=BenchmarkMode.HYBRID,
            smiles="CC(=O)Oc1ccccc1C(=O)O",
            target_pdb="",
            user=setup_user,
            target_gene="PTGS2",
        )
        assert result["case_id"] == "aspirin"
        assert result["mode"] == BenchmarkMode.HYBRID
        metrics = result["metrics"]
        # 7 个指标
        for key in ["accuracy_score", "cost_usd", "duration_sec", "energy_kwh",
                    "coverage_pct", "novelty_score", "interpretability_score"]:
            assert key in metrics, f"缺指标 {key}"
        assert "report_id" in result

    @pytest.mark.asyncio
    async def test_run_case_traditional_supercompute_mode(
        self, async_db_session, setup_user
    ):
        """traditional_supercompute 模式 cost 应显著高于 hybrid"""
        runner = BenchmarkRunner(async_db_session, llm_client=None)
        result = await runner.run_case(
            case_id="aspirin",
            mode=BenchmarkMode.TRADITIONAL_SUPERCOMPUTE,
            smiles="CC(=O)Oc1ccccc1C(=O)O",
            target_pdb="",
            user=setup_user,
        )
        # 传统超算 24 GPU 小时 × 2.5 USD = 60 USD
        assert result["metrics"]["cost_usd"] >= 50.0
        # 时长 24 小时
        assert result["metrics"]["duration_sec"] >= 80000  # ~22+ 小时

    @pytest.mark.asyncio
    async def test_run_case_llm_only_mode(self, async_db_session, setup_user, mock_llm_client):
        """llm_only 模式 accuracy 应低于 hybrid"""
        runner = BenchmarkRunner(async_db_session, llm_client=mock_llm_client)
        result = await runner.run_case(
            case_id="aspirin",
            mode=BenchmarkMode.LLM_ONLY,
            smiles="CC(=O)Oc1ccccc1C(=O)O",
            target_pdb="",
            user=setup_user,
        )
        # llm_only accuracy 较低
        assert result["metrics"]["accuracy_score"] < 0.85
        # cost 受上限保护
        assert result["metrics"]["cost_usd"] <= 10.0

    @pytest.mark.asyncio
    async def test_run_case_persists_benchmark_report(
        self, async_db_session, setup_user, mock_llm_client
    ):
        """持久化 BenchmarkReport 记录"""
        from sqlalchemy import select

        runner = BenchmarkRunner(async_db_session, llm_client=mock_llm_client)
        await runner.run_case(
            case_id="caffeine",
            mode=BenchmarkMode.HYBRID,
            smiles="CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
            target_pdb="",
            user=setup_user,
        )
        stmt = select(BenchmarkReport).where(BenchmarkReport.case_id == "caffeine")
        result = await async_db_session.execute(stmt)
        reports = result.scalars().all()
        assert len(reports) >= 1


# ========== compare_modes 测试 ==========

class TestCompareModes:
    @pytest.mark.asyncio
    async def test_compare_returns_cost_saving(
        self, async_db_session, setup_user, mock_llm_client
    ):
        """返回 cost_saving_pct（hybrid vs supercompute）"""
        runner = BenchmarkRunner(async_db_session, llm_client=mock_llm_client)
        result = await runner.compare_modes(
            case_id="aspirin",
            smiles="CC(=O)Oc1ccccc1C(=O)O",
            target_pdb="",
            user=setup_user,
            target_gene="PTGS2",
        )
        assert "comparison" in result
        assert "cost_saving_pct" in result["comparison"]
        # hybrid 应比 supercompute 便宜很多
        assert result["comparison"]["cost_saving_pct"] > 50.0
        # 3 个模式结果都在
        assert len(result["results"]) == 3

    @pytest.mark.asyncio
    async def test_compare_hybrid_wins_on_score(
        self, async_db_session, setup_user, mock_llm_client
    ):
        """hybrid 综合得分应高于 traditional（成本占大头）"""
        runner = BenchmarkRunner(async_db_session, llm_client=mock_llm_client)
        result = await runner.compare_modes(
            case_id="ibuprofen",
            smiles="CC(C)Cc1ccc(cc1)C(C)C(=O)O",
            target_pdb="",
            user=setup_user,
        )
        # winner 应为 hybrid（综合得分 = accuracy*0.4 + (1-cost/max)*0.4 + (1-duration/max)*0.2）
        assert result["winner"] == "hybrid"


# ========== run_all_cases 测试 ==========

class TestRunAllCases:
    @pytest.mark.asyncio
    async def test_run_all_cases_returns_summary(
        self, async_db_session, setup_user, mock_llm_client
    ):
        """返回 9 案例汇总"""
        runner = BenchmarkRunner(async_db_session, llm_client=mock_llm_client)
        result = await runner.run_all_cases(user=setup_user)
        assert result["total_cases"] == 9
        assert result["completed"] >= 1  # 至少 1 个成功
        assert "summary" in result
        assert "avg_cost_saving_pct" in result["summary"]
        assert "hybrid_wins" in result["summary"]
        assert "conclusion" in result

    @pytest.mark.asyncio
    async def test_energy_saving_pct_calculated(
        self, async_db_session, setup_user, mock_llm_client
    ):
        """energy_saving_pct 被计算"""
        runner = BenchmarkRunner(async_db_session, llm_client=mock_llm_client)
        result = await runner.compare_modes(
            case_id="paracetamol",
            smiles="CC(=O)Nc1ccc(O)cc1",
            target_pdb="",
            user=setup_user,
        )
        # supercompute 24h vs hybrid ~10s，能耗节省应 > 99%
        assert result["comparison"]["energy_saving_pct"] > 99.0
