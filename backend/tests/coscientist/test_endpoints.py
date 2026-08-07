"""Co-Scientist API 端点测试

验证 13 REST + 1 WS 端点的 HTTP 行为：
- 创建运行、列出、详情、取消
- 专家反馈提交
- 假设列表、排名、辩论日志
- 进度、元评审、统计
- 案例列表
- WebSocket 连接

注意：USE_MOCK=true 时 LLM 客户端返回 Mock 响应，
Supervisor 后台任务可能产出空结果，端点测试聚焦 HTTP 层。
"""
import json
import pytest
import pytest_asyncio

from app.models.coscientist_run import CaseType, CoScientistRun, RunStatus
from app.models.hypothesis import Hypothesis, HypothesisStatus


@pytest_asyncio.fixture
async def test_run(async_db_session, auth_token):
    """直接在 DB 创建一个测试运行记录"""
    from app.core.security import hash_password, UserRole
    from app.models.user import User
    from app.models.project import Project
    import uuid

    # 获取测试用户
    from sqlalchemy import select
    result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
    user = result.scalar_one()

    # 创建一个测试项目（Hypothesis.project_id 不可为空）
    project = Project(
        owner_id=user.id,
        name="Co-Scientist 测试项目",
        patient_pseudonym="CSC-TEST-001",
        cancer_type="CUSTOM",
        stage="NA",
        description="Co-Scientist 端点测试用项目",
    )
    async_db_session.add(project)
    await async_db_session.flush()

    run = CoScientistRun(
        user_id=user.id,
        project_id=project.id,
        research_goal="测试 Co-Scientist 研究目标",
        case_type=CaseType.CUSTOM,
        status=RunStatus.COMPLETED,
        current_round=2,
        max_rounds=5,
        current_phase="meta_review",
        config={"initial_hypothesis_count": 5},
        final_rankings={"top": [{"name": "H1", "elo": 1200}]},
        meta_review="综合评审报告",
        total_cost_usd=0.05,
        duration_sec=30.5,
    )
    async_db_session.add(run)
    await async_db_session.flush()

    # 创建几个假设（Hypothesis 无 user_id 字段，使用 created_by）
    for i in range(3):
        hyp = Hypothesis(
            project_id=project.id,
            created_by=user.id,
            name=f"假设{i+1}",
            description=f"描述{i+1}",
            mechanism=f"机制{i+1}",
            status=HypothesisStatus.COMPLETED,
            elo_score=1000 + i * 50,
            novelty_score=7.0 + i,
            plausibility_score=6.0 + i,
            testability_score=8.0,
            safety_score=9.0,
            coscientist_run_id=run.id,
            rank=i + 1,
        )
        async_db_session.add(hyp)
    await async_db_session.flush()

    return run


class TestRunCRUD:
    """运行 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_list_cases(self, client, auth_headers):
        """GET /cases — 案例列表（内置验证案例已按用户要求永久删除，应为空）"""
        resp = await client.get("/api/v1/coscientist/cases", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "cases" in data
        assert data["cases"] == []

    @pytest.mark.asyncio
    async def test_list_runs_empty(self, client, auth_headers):
        """GET /runs — 空列表"""
        resp = await client.get("/api/v1/coscientist/runs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_runs_with_data(self, client, auth_headers, test_run):
        """GET /runs — 有数据"""
        resp = await client.get("/api/v1/coscientist/runs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert data["items"][0]["research_goal"] == "测试 Co-Scientist 研究目标"

    @pytest.mark.asyncio
    async def test_get_run_detail(self, client, auth_headers, test_run):
        """GET /runs/{id} — 详情"""
        resp = await client.get(f"/api/v1/coscientist/runs/{test_run.id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(test_run.id)
        assert data["status"] == RunStatus.COMPLETED
        assert data["current_round"] == 2

    @pytest.mark.asyncio
    async def test_get_run_not_found(self, client, auth_headers):
        """GET /runs/{id} — 不存在"""
        import uuid
        resp = await client.get(f"/api/v1/coscientist/runs/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_completed_run(self, client, auth_headers, test_run):
        """POST /runs/{id}/cancel — 已完成的运行不能取消"""
        resp = await client.post(f"/api/v1/coscientist/runs/{test_run.id}/cancel", headers=auth_headers)
        assert resp.status_code == 400


class TestHypothesesAndRankings:
    """假设和排名测试"""

    @pytest.mark.asyncio
    async def test_list_hypotheses(self, client, auth_headers, test_run):
        """GET /runs/{id}/hypotheses — 假设列表"""
        resp = await client.get(f"/api/v1/coscientist/runs/{test_run.id}/hypotheses", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        # 按 Elo 降序
        elos = [h["elo_score"] for h in data]
        assert elos == sorted(elos, reverse=True)

    @pytest.mark.asyncio
    async def test_get_hypothesis_detail(self, client, auth_headers, test_run):
        """GET /runs/{id}/hypotheses/{hid} — 假设详情"""
        # 先获取列表拿到 ID
        list_resp = await client.get(f"/api/v1/coscientist/runs/{test_run.id}/hypotheses", headers=auth_headers)
        hyp_id = list_resp.json()[0]["id"]

        resp = await client.get(f"/api/v1/coscientist/runs/{test_run.id}/hypotheses/{hyp_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == hyp_id

    @pytest.mark.asyncio
    async def test_get_rankings(self, client, auth_headers, test_run):
        """GET /runs/{id}/rankings — 排名"""
        resp = await client.get(f"/api/v1/coscientist/runs/{test_run.id}/rankings", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == str(test_run.id)
        assert data["total_hypotheses"] == 3
        assert data["rankings"][0]["rank"] == 1


class TestProgressAndStats:
    """进度和统计测试"""

    @pytest.mark.asyncio
    async def test_get_progress(self, client, auth_headers, test_run):
        """GET /runs/{id}/progress — 进度"""
        resp = await client.get(f"/api/v1/coscientist/runs/{test_run.id}/progress", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == str(test_run.id)
        assert "status" in data
        assert "recent_events" in data

    @pytest.mark.asyncio
    async def test_get_stats(self, client, auth_headers, test_run):
        """GET /runs/{id}/stats — 统计"""
        resp = await client.get(f"/api/v1/coscientist/runs/{test_run.id}/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == str(test_run.id)
        assert "agents" in data
        assert data["current_round"] == 2

    @pytest.mark.asyncio
    async def test_get_meta_review(self, client, auth_headers, test_run):
        """GET /runs/{id}/meta-review — 元评审"""
        resp = await client.get(f"/api/v1/coscientist/runs/{test_run.id}/meta-review", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["meta_review"] == "综合评审报告"

    @pytest.mark.asyncio
    async def test_get_meta_review_not_ready(self, client, auth_headers, async_db_session, auth_token):
        """GET /runs/{id}/meta-review — 尚未生成"""
        from app.core.security import UserRole
        from app.models.user import User
        from sqlalchemy import select

        result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
        user = result.scalar_one()

        run = CoScientistRun(
            user_id=user.id,
            research_goal="未完成的运行",
            status=RunStatus.RUNNING,
            meta_review=None,
        )
        async_db_session.add(run)
        await async_db_session.flush()

        resp = await client.get(f"/api/v1/coscientist/runs/{run.id}/meta-review", headers=auth_headers)
        assert resp.status_code == 404


class TestDebates:
    """辩论日志测试"""

    @pytest.mark.asyncio
    async def test_list_debates_empty(self, client, auth_headers, test_run):
        """GET /runs/{id}/debates — 空辩论日志"""
        resp = await client.get(f"/api/v1/coscientist/runs/{test_run.id}/debates", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["debates"] == []


class TestFeedback:
    """专家反馈测试"""

    @pytest.mark.asyncio
    async def test_submit_feedback_wrong_status(self, client, auth_headers, test_run):
        """POST /runs/{id}/feedback — 已完成的运行不能提交反馈"""
        resp = await client.post(
            f"/api/v1/coscientist/runs/{test_run.id}/feedback",
            json={"feedback_text": "测试反馈", "feedback_type": "constraint"},
            headers=auth_headers,
        )
        assert resp.status_code == 400


class TestCreateRun:
    """创建运行测试"""

    @pytest.mark.asyncio
    async def test_create_run_validation_error(self, client, auth_headers):
        """POST /runs — 研究目标太短"""
        resp = await client.post(
            "/api/v1/coscientist/runs",
            json={"research_goal": "短"},  # min_length=10
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_create_run_success(self, client, auth_headers):
        """POST /runs — 成功创建（Mock LLM 后台任务）"""
        resp = await client.post(
            "/api/v1/coscientist/runs",
            json={
                "research_goal": "这是一个测试研究目标，长度足够",
                "max_rounds": 1,
                "initial_hypothesis_count": 3,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["research_goal"] == "这是一个测试研究目标，长度足够"
        assert data["status"] in (RunStatus.RUNNING, RunStatus.PENDING)
        assert data["max_rounds"] == 1
        assert "id" in data


class TestUnauthorized:
    """未认证测试"""

    @pytest.mark.asyncio
    async def test_no_auth(self, client):
        """无认证访问"""
        resp = await client.get("/api/v1/coscientist/runs")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_auth_cases(self, client):
        resp = await client.get("/api/v1/coscientist/cases")
        assert resp.status_code == 401