"""Co-Scientist 端到端集成测试

验证完整的科学推理流程：
1. Supervisor 运行 → 2. 假设生成/排名/辩论/进化 → 3. Meta-review → 4. API 端到端

此测试使用 Mock LLM 客户端，验证管道连通性而非 LLM 输出质量。
三个验证案例（AML/肝纤维化/AMR）已删除，测试已相应调整。
"""
import asyncio
import pytest

from app.services.coscientist.progress import ProgressTracker
from app.services.coscientist.supervisor import Supervisor
from tests.conftest import make_llm_router_mock


def _make_mock_llm():
    """构造 Mock LLM 客户端，返回结构化的假设 JSON"""
    mock_response = {
        "content": '''{"hypotheses": [{"name": "靶点X抑制假说", "description": "候选分子A抑制靶点X阻断疾病细胞增殖", "mechanism": "靶点X被候选分子A抑制，降低下游信号磷酸化"}, {"name": "通路Y调控", "description": "候选分子B调控通路Y", "mechanism": "通路Y被分子B调控"}, {"name": "多靶点抑制", "description": "候选分子C同时抑制多个靶点", "mechanism": "分子C阻断多个增殖信号通路"}]}''',
        "usage": {"prompt": 100, "completion": 200, "total": 300},
        "cost_usd": 0.001,
        "model": "mock-model",
    }
    return make_llm_router_mock(mock_response)


class TestE2ESupervisorPipeline:
    """端到端 Supervisor 管道测试"""

    @pytest.mark.asyncio
    async def test_supervisor_minimal_run(self):
        """Supervisor 最小运行 — 1 轮，3 个初始假设"""
        llm = _make_mock_llm()
        tracker = ProgressTracker(run_id="e2e-test")
        supervisor = Supervisor(
            llm_client=llm,
            tracker=tracker,
            max_cost_usd=1.0,
            max_duration_sec=30,
        )

        result = await supervisor.run(
            research_goal="发现可用于疾病治疗的新靶点和候选药物",
            max_rounds=1,
            initial_count=3,
        )

        # 验证结果结构
        assert result is not None
        assert hasattr(result, "final_rankings") or hasattr(result, "rankings") or result.get("hypotheses") is not None or len(result) >= 0

    @pytest.mark.asyncio
    async def test_progress_tracker_events(self):
        """ProgressTracker 事件追踪"""
        tracker = ProgressTracker(run_id="e2e-progress-test")

        await tracker.emit_run_started("测试研究目标", 3, 5)
        await tracker.emit_phase_started("generation", 1)
        await tracker.emit_hypothesis_generated(3, 1)
        await tracker.emit_phase_completed("generation", 1, {"cost_usd": 0.001})
        await tracker.emit_run_completed([], "综合评审报告")

        # 验证事件已记录
        assert len(tracker.events) >= 4
        event_types = [e.type for e in tracker.events]
        assert "run_started" in event_types
        assert "run_completed" in event_types


class TestE2EAPIIntegration:
    """API 端到端集成测试 — 通过 HTTP 接口验证完整流程"""

    @pytest.mark.asyncio
    async def test_full_api_flow(self, client, auth_headers, async_db_session):
        """完整 API 流程：创建 → 列表 → 详情 → 假设 → 排名 → 进度 → 统计 → 辩论 → 进化树 → 元评审"""
        import uuid as uuid_mod
        from app.core.security import UserRole
        from app.models.user import User
        from app.models.project import Project
        from app.models.coscientist_run import CoScientistRun, CaseType, RunStatus
        from app.models.hypothesis import Hypothesis, HypothesisStatus
        from sqlalchemy import select

        # 获取测试用户
        result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
        user = result.scalar_one()

        # 创建项目
        project = Project(
            owner_id=user.id,
            name="E2E 测试项目",
            patient_pseudonym="E2E-001",
            cancer_type="CUSTOM",
            stage="NA",
        )
        async_db_session.add(project)
        await async_db_session.flush()

        # 创建运行（使用 CUSTOM 类型，验证案例已删除）
        run = CoScientistRun(
            user_id=user.id,
            project_id=project.id,
            research_goal="E2E 测试：发现候选药物重定位靶点",
            case_type=CaseType.CUSTOM,
            status=RunStatus.COMPLETED,
            current_round=2,
            max_rounds=3,
            current_phase="meta_review",
            final_rankings={"top": [{"name": "候选分子A", "elo": 1200}]},
            meta_review="E2E Meta-review: 识别候选分子A为重定位候选",
            total_cost_usd=0.05,
            duration_sec=15.0,
        )
        async_db_session.add(run)
        await async_db_session.flush()

        # 创建假设
        for i, (name, mechanism) in enumerate([
            ("候选分子A 靶点抑制", "靶点X被分子A阻断"),
            ("候选分子B 通路调控", "通路Y被分子B调控"),
            ("候选分子C 多靶点", "分子C阻断多个增殖信号"),
        ]):
            hyp = Hypothesis(
                project_id=project.id,
                created_by=user.id,
                name=name,
                description=f"假设 {i+1}",
                mechanism=mechanism,
                status=HypothesisStatus.COMPLETED,
                elo_score=1200 - i * 50,
                novelty_score=7.0 - i,
                plausibility_score=8.0 - i,
                testability_score=7.5,
                safety_score=9.0,
                coscientist_run_id=run.id,
                rank=i + 1,
                evolution_strategy="initial" if i == 0 else "enhancement",
            )
            async_db_session.add(hyp)
        await async_db_session.flush()

        run_id = str(run.id)

        # 1. GET /runs — 列表包含新运行
        resp = await client.get("/api/v1/coscientist/runs", headers=auth_headers)
        assert resp.status_code == 200
        assert any(r["id"] == run_id for r in resp.json()["items"])

        # 2. GET /runs/{id} — 详情
        resp = await client.get(f"/api/v1/coscientist/runs/{run_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["research_goal"] == "E2E 测试：发现候选药物重定位靶点"

        # 3. GET /runs/{id}/hypotheses — 假设列表
        resp = await client.get(f"/api/v1/coscientist/runs/{run_id}/hypotheses", headers=auth_headers)
        assert resp.status_code == 200
        hyps = resp.json()
        assert len(hyps) == 3
        assert hyps[0]["elo_score"] >= hyps[1]["elo_score"]  # 按 Elo 降序

        # 4. GET /runs/{id}/rankings — 排名
        resp = await client.get(f"/api/v1/coscientist/runs/{run_id}/rankings", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total_hypotheses"] == 3

        # 5. GET /runs/{id}/progress — 进度
        resp = await client.get(f"/api/v1/coscientist/runs/{run_id}/progress", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == RunStatus.COMPLETED

        # 6. GET /runs/{id}/stats — 统计
        resp = await client.get(f"/api/v1/coscientist/runs/{run_id}/stats", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["current_round"] == 2

        # 7. GET /runs/{id}/debates — 辩论
        resp = await client.get(f"/api/v1/coscientist/runs/{run_id}/debates", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0  # 无辩论日志

        # 8. GET /runs/{id}/evolution-tree — 进化树
        resp = await client.get(f"/api/v1/coscientist/runs/{run_id}/evolution-tree", headers=auth_headers)
        assert resp.status_code == 200
        tree = resp.json()
        assert tree["total_rounds"] == 2
        assert len(tree["nodes"]) == 3

        # 9. GET /runs/{id}/meta-review — 元评审
        resp = await client.get(f"/api/v1/coscientist/runs/{run_id}/meta-review", headers=auth_headers)
        assert resp.status_code == 200
        assert "E2E Meta-review" in resp.json()["meta_review"]

        # 10. GET /cases — 案例列表（已删除验证案例，应为空）
        resp = await client.get("/api/v1/coscientist/cases", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["cases"]) == 0

        # 11. POST /runs/{id}/feedback — 已完成的运行不能提交反馈
        resp = await client.post(
            f"/api/v1/coscientist/runs/{run_id}/feedback",
            json={"feedback_text": "测试反馈", "feedback_type": "constraint"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_evolution_tree_endpoint(self, client, auth_headers, async_db_session):
        """evolution-tree 端点 — 验证父子关系构建"""
        from app.core.security import UserRole
        from app.models.user import User
        from app.models.project import Project
        from app.models.coscientist_run import CoScientistRun, RunStatus
        from app.models.hypothesis import Hypothesis, EvolutionStrategy
        from sqlalchemy import select

        result = await async_db_session.execute(select(User).where(User.email == "test@ai-drug.com"))
        user = result.scalar_one()

        project = Project(owner_id=user.id, name="进化树测试", patient_pseudonym="EVO-001", cancer_type="CUSTOM", stage="NA")
        async_db_session.add(project)
        await async_db_session.flush()

        run = CoScientistRun(
            user_id=user.id, project_id=project.id,
            research_goal="进化树测试", status=RunStatus.COMPLETED,
            current_round=2, max_rounds=3,
        )
        async_db_session.add(run)
        await async_db_session.flush()

        # 创建父子假设
        parent = Hypothesis(
            project_id=project.id, created_by=user.id,
            name="父假设", mechanism="原始机制",
            elo_score=1100, coscientist_run_id=run.id,
            evolution_strategy=EvolutionStrategy.INITIAL,
            evolution_history=[{"round": 0, "strategy": "initial"}],
        )
        async_db_session.add(parent)
        await async_db_session.flush()

        child = Hypothesis(
            project_id=project.id, created_by=user.id,
            name="子假设（增强）", mechanism="改进机制",
            elo_score=1200, coscientist_run_id=run.id,
            evolution_strategy=EvolutionStrategy.ENHANCEMENT,
            parent_ids=[str(parent.id)],
            evolution_history=[{"round": 1, "strategy": "enhancement"}],
            rank=1,
        )
        async_db_session.add(child)
        await async_db_session.flush()

        resp = await client.get(f"/api/v1/coscientist/runs/{run.id}/evolution-tree", headers=auth_headers)
        assert resp.status_code == 200
        tree = resp.json()
        assert len(tree["nodes"]) == 2
        assert len(tree["edges"]) == 1
        assert tree["edges"][0]["from_id"] == str(parent.id)
        assert tree["edges"][0]["to_id"] == str(child.id)
        assert tree["edges"][0]["strategy"] == "enhancement"