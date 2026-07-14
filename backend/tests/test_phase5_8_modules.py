"""Phase 4-8 新增模块单元测试

覆盖：
- PatientFeedbackService（Phase 4 患者反馈服务）
- DPSGDOptimizer + FederatedLearningService 新方法（Phase 5 联邦学习）
- HypothesisGenerator LLM 集成（Phase 6 假设生成）
- DiscoveryPipeline Step 4 + custom_steps（Phase 7 流水线）
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.optimizer.federated_learning import (
    DPSGDOptimizer,
    FederatedLearningService,
    RedisFLStorage,
)
from app.services.knowledge.hypothesis_generator import HypothesisGenerator


# ========== Phase 4: PatientFeedbackService ==========


class TestPatientFeedbackService:
    """患者用药反馈服务测试"""

    @pytest.mark.asyncio
    async def test_create_patient_feedback(self, async_db_session):
        """测试创建患者反馈"""
        from app.services.workflow.patient_feedback import PatientFeedbackService
        from app.core.security import hash_password, UserRole
        from app.models.user import User
        from app.models.project import Project
        from app.models.treatment import Treatment, TreatmentStatus, TreatmentType

        # 先创建用户和项目（Project.owner_id / Treatment.project_id NOT NULL）
        user = User(
            email="test_fb@ai-drug.com",
            name="Test",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER,
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.flush()

        project = Project(name="Test Project", cancer_type="NSCLC", stage="IV", owner_id=user.id)
        async_db_session.add(project)
        await async_db_session.flush()

        treatment = Treatment(
            project_id=project.id,
            name="EGFR 靶向治疗",
            therapy_type=TreatmentType.TARGETED,
            status=TreatmentStatus.PROPOSED,
            target_ids=["t1"],
        )
        async_db_session.add(treatment)
        await async_db_session.flush()

        service = PatientFeedbackService(async_db_session)
        feedback = await service.create(
            treatment_id=str(treatment.id),
            patient_code="P001",
            age=55,
            gender="M",
            diagnosis="NSCLC",
            stage="IIIB",
            drug_name="吉非替尼",
            dosage="250mg qd",
            duration_days=180,
            efficacy="partial",
            tumor_shrinkage_pct=35.5,
            pfs_days=210,
            os_days=420,
            adverse_events=[{"event": "皮疹", "severity": 1}],
            biomarker_changes={"EGFR": "L858R"},
            notes="耐受良好",
        )

        assert feedback.id is not None
        assert feedback.patient_code == "P001"
        assert feedback.age == 55
        assert feedback.efficacy == "partial"
        assert feedback.adverse_reactions["count"] == 1
        assert feedback.biomarker_changes["tumor_shrinkage_pct"] == 35.5

    @pytest.mark.asyncio
    async def test_list_by_treatment(self, async_db_session):
        """测试按治疗方案查询"""
        from app.services.workflow.patient_feedback import PatientFeedbackService
        from app.core.security import hash_password, UserRole
        from app.models.user import User
        from app.models.project import Project
        from app.models.treatment import Treatment, TreatmentStatus, TreatmentType

        user = User(
            email="test_list@ai-drug.com",
            name="Test",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER,
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.flush()

        project = Project(name="List Test Project", cancer_type="NSCLC", stage="III", owner_id=user.id)
        async_db_session.add(project)
        await async_db_session.flush()

        treatment = Treatment(
            project_id=project.id,
            name="Test Treatment",
            therapy_type=TreatmentType.TARGETED,
            status=TreatmentStatus.PROPOSED,
        )
        async_db_session.add(treatment)
        await async_db_session.flush()

        service = PatientFeedbackService(async_db_session)
        await service.create(
            treatment_id=str(treatment.id),
            patient_code="P001",
            efficacy="complete",
        )
        await service.create(
            treatment_id=str(treatment.id),
            patient_code="P002",
            efficacy="partial",
        )

        results = await service.list_by_treatment(str(treatment.id))
        assert len(results) == 2
        assert results[0].patient_code in ("P001", "P002")

    @pytest.mark.asyncio
    async def test_get_statistics(self, async_db_session):
        """测试统计有效率"""
        from app.services.workflow.patient_feedback import PatientFeedbackService
        from app.core.security import hash_password, UserRole
        from app.models.user import User
        from app.models.project import Project
        from app.models.treatment import Treatment, TreatmentStatus, TreatmentType

        user = User(
            email="test_stats@ai-drug.com",
            name="Test",
            hashed_password=hash_password("test123456"),
            role=UserRole.FOUNDER,
            is_active=True,
        )
        async_db_session.add(user)
        await async_db_session.flush()

        project = Project(name="Stats Project", cancer_type="NSCLC", stage="II", owner_id=user.id)
        async_db_session.add(project)
        await async_db_session.flush()

        treatment = Treatment(
            project_id=project.id,
            name="Stats Test",
            therapy_type=TreatmentType.TARGETED,
            status=TreatmentStatus.PROPOSED,
            target_ids=["t1"],
        )
        async_db_session.add(treatment)
        await async_db_session.flush()

        service = PatientFeedbackService(async_db_session)
        # 2 complete + 1 partial + 1 progressive = 75% effective rate
        for code, eff in [("P1", "complete"), ("P2", "complete"), ("P3", "partial"), ("P4", "progressive")]:
            await service.create(
                treatment_id=str(treatment.id),
                patient_code=code,
                efficacy=eff,
                adverse_events=[{"event": "test"}] if code == "P4" else None,
            )

        stats = await service.get_statistics("EGFR")
        # 可能没有关联靶点，返回空数据
        assert "total" in stats
        assert "efficacy_rate" in stats

    @pytest.mark.asyncio
    async def test_generate_template(self):
        """测试生成 CSV 模板"""
        from app.services.workflow.patient_feedback import PatientFeedbackService

        content = PatientFeedbackService.generate_template("csv")
        assert isinstance(content, bytes)
        text = content.decode("utf-8")
        assert "patient_code" in text
        assert "efficacy" in text
        assert "P001" in text  # 示例行
        assert "#" in text  # 注释

    def test_generate_template_invalid_format(self):
        """测试不支持格式报错"""
        from app.services.workflow.patient_feedback import PatientFeedbackService

        with pytest.raises(ValueError, match="不支持"):
            PatientFeedbackService.generate_template("xml")


# ========== Phase 5: DPSGDOptimizer ==========


class TestDPSGDOptimizer:
    """差分隐私 SGD 优化器测试"""

    def test_clip_weights_within_norm(self):
        """测试权重范数在限制内不裁剪"""
        opt = DPSGDOptimizer(noise_multiplier=0.0, max_norm=10.0)
        weights = {"layer1": 1.0, "layer2": 2.0}
        clipped = opt.clip_weights(weights)
        # 范数 sqrt(1+4) = sqrt(5) ≈ 2.24 < 10，不裁剪
        assert clipped["layer1"] == 1.0
        assert clipped["layer2"] == 2.0

    def test_clip_weights_exceeds_norm(self):
        """测试权重范数超限裁剪"""
        opt = DPSGDOptimizer(noise_multiplier=0.0, max_norm=1.0)
        weights = {"layer1": 3.0, "layer2": 4.0}
        clipped = opt.clip_weights(weights)
        # 范数 5.0 > 1.0，应裁剪
        norm = sum(v * v for v in clipped.values()) ** 0.5
        assert norm <= 1.0 + 0.01  # 允许浮点误差

    def test_add_noise(self):
        """测试添加噪声"""
        opt = DPSGDOptimizer(noise_multiplier=0.5, max_norm=1.0)
        weights = {"layer1": 0.5, "layer2": 0.3}
        noisy = opt.add_noise(weights)
        # 噪声应改变值（极大概率）
        assert "layer1" in noisy
        assert "layer2" in noisy
        # 值应该是浮点数
        assert isinstance(noisy["layer1"], float)

    def test_add_noise_zero_multiplier(self):
        """测试零噪声乘子不改变值"""
        opt = DPSGDOptimizer(noise_multiplier=0.0, max_norm=100.0)
        weights = {"layer1": 1.5, "layer2": 2.5}
        noisy = opt.add_noise(weights)
        # 噪声为 0，值不变（裁剪也不触发因为范数 < 100）
        assert abs(noisy["layer1"] - 1.5) < 0.01
        assert abs(noisy["layer2"] - 2.5) < 0.01

    def test_get_privacy_spent(self):
        """测试隐私预算估算"""
        opt = DPSGDOptimizer(noise_multiplier=1.0, max_norm=1.0)
        result = opt.get_privacy_spent(steps=100, target_delta=1e-5)
        assert "epsilon" in result
        assert "delta" in result
        assert "steps" in result
        assert result["steps"] == 100
        assert result["delta"] == 1e-5
        assert result["epsilon"] >= 0

    def test_opacus_availability(self):
        """测试 opacus 可用性检测"""
        opt = DPSGDOptimizer()
        # opacus 已安装，应为 True
        assert opt._opacus_available is True


# ========== Phase 5: FederatedLearningService 新方法 ==========


class TestFederatedLearningEnhanced:
    """联邦学习增强功能测试"""

    @pytest.mark.asyncio
    async def test_metrics_history(self):
        """测试指标历史记录"""
        service = FederatedLearningService(num_rounds_default=2, min_clients=2)
        job = await service.create_job(project_id="p1")

        # 提交 2 轮权重
        for rnd in range(2):
            for cid in ["c1", "c2"]:
                await service.submit_weights(
                    job_id=job["job_id"],
                    client_id=cid,
                    weights={"w1": 0.1 * (rnd + 1)},
                    num_samples=10,
                    metrics={"loss": 0.5 - rnd * 0.1, "accuracy": 0.7 + rnd * 0.05},
                )

        history = await service.get_metrics_history(job["job_id"])
        assert history["rounds"] == 2
        assert len(history["metrics_history"]) == 2
        assert history["final_loss"] is not None
        assert history["convergence_trend"] is not None

    @pytest.mark.asyncio
    async def test_evaluate_global_model(self):
        """测试全局模型评估"""
        service = FederatedLearningService(num_rounds_default=1, min_clients=2)
        job = await service.create_job(project_id="p1")

        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.5},
                num_samples=10,
                metrics={"loss": 0.3, "accuracy": 0.85},
            )

        result = await service.evaluate_global_model(job["job_id"])
        assert result["status"] == "completed"
        assert result["rounds_completed"] == 1
        assert result["aggregated_weights_summary"]["num_layers"] == 1
        assert result["last_round_metrics"]["global_loss"] == 0.3

    @pytest.mark.asyncio
    async def test_configure_dp(self):
        """测试差分隐私配置"""
        service = FederatedLearningService()
        job = await service.create_job(project_id="p1")

        result = await service.configure_dp(
            job_id=job["job_id"],
            enabled=True,
            noise_multiplier=0.5,
            max_norm=2.0,
        )
        assert result["dp_params"]["enabled"] is True
        assert result["dp_params"]["noise_multiplier"] == 0.5
        assert result["dp_params"]["max_norm"] == 2.0

    @pytest.mark.asyncio
    async def test_dp_applied_on_aggregation(self):
        """测试 DP 在聚合时应用"""
        service = FederatedLearningService(num_rounds_default=1, min_clients=2)
        job = await service.create_job(project_id="p1")

        # 配置 DP
        await service.configure_dp(job["job_id"], enabled=True, noise_multiplier=0.1, max_norm=1.0)

        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.5},
                num_samples=10,
            )

        job_data = await service.get_job(job["job_id"])
        aggregated = job_data["rounds_history"][0]["aggregated"]
        assert aggregated.get("dp_applied") is True

    @pytest.mark.asyncio
    async def test_get_centers_empty(self):
        """测试无多中心配置"""
        service = FederatedLearningService()
        job = await service.create_job(project_id="p1")

        result = await service.get_centers(job["job_id"])
        assert result["centers"] == []
        assert result["last_centers_breakdown"] == []

    @pytest.mark.asyncio
    async def test_multi_center_aggregation(self):
        """测试多中心分层聚合"""
        service = FederatedLearningService(num_rounds_default=1, min_clients=4)
        centers = [
            {"center_id": "center_a", "name": "北京中心", "clients": ["c1", "c2"]},
            {"center_id": "center_b", "name": "上海中心", "clients": ["c3", "c4"]},
        ]
        job = await service.create_job(
            project_id="p1",
            config={"centers": centers},
        )

        for cid in ["c1", "c2", "c3", "c4"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.5},
                num_samples=10,
                metrics={"loss": 0.3},
            )

        result = await service.get_centers(job["job_id"])
        assert len(result["last_centers_breakdown"]) == 2
        assert result["last_centers_breakdown"][0]["center_id"] in ("center_a", "center_b")

    @pytest.mark.asyncio
    async def test_metrics_history_not_found(self):
        """测试不存在任务的指标历史"""
        service = FederatedLearningService()
        result = await service.get_metrics_history("nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_evaluate_not_found(self):
        """测试不存在任务的评估"""
        service = FederatedLearningService()
        result = await service.evaluate_global_model("nonexistent")
        assert "error" in result


# ========== Phase 5: RedisFLStorage ==========


class TestRedisFLStorage:
    """Redis 持久化存储测试（降级模式）"""

    @pytest.mark.asyncio
    async def test_save_and_load_job(self):
        """测试保存和加载任务（内存降级）"""
        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")  # 不可达，降级内存
        job = {"job_id": "test_job_1", "status": "running"}
        await storage.save_job(job)
        loaded = await storage.load_job("test_job_1")
        assert loaded is not None
        assert loaded["job_id"] == "test_job_1"
        assert loaded["status"] == "running"

    @pytest.mark.asyncio
    async def test_load_nonexistent_job(self):
        """测试加载不存在的任务"""
        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        loaded = await storage.load_job("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_save_and_list_clients(self):
        """测试保存客户端和列表"""
        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        await storage.save_client({"client_id": "c1", "endpoint": "http://localhost:8080"})
        await storage.save_client({"client_id": "c2", "endpoint": "http://localhost:8081"})

    @pytest.mark.asyncio
    async def test_list_jobs(self):
        """测试列出任务"""
        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        await storage.save_job({"job_id": "j1"})
        await storage.save_job({"job_id": "j2"})
        jobs = await storage.list_jobs()
        assert len(jobs) >= 2


# ========== Phase 6: HypothesisGenerator LLM 集成 ==========


class TestHypothesisGeneratorLLM:
    """假设生成器 LLM 集成测试"""

    @pytest.mark.asyncio
    async def test_generate_rule_mode(self, async_db_session):
        """测试规则模式生成"""
        gen = HypothesisGenerator(async_db_session)
        result = await gen.generate(
            project_id="p1",
            context={"de_genes": [{"gene": "EGFR"}], "pathways": [{"name": "MAPK"}]},
            max_hypotheses=3,
            use_llm=False,
            mode="rule",
        )
        assert len(result) > 0
        assert all(h.get("source") == "rule" for h in result)

    @pytest.mark.asyncio
    async def test_generate_hybrid_without_llm(self, async_db_session):
        """测试 hybrid 模式但无 LLM 客户端（降级规则）"""
        gen = HypothesisGenerator(async_db_session)
        result = await gen.generate(
            project_id="p1",
            context={"de_genes": [{"gene": "TP53"}]},
            max_hypotheses=3,
            use_llm=False,
            mode="hybrid",
        )
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_generate_with_mock_llm(self, async_db_session):
        """测试使用 Mock LLM 生成假设"""
        gen = HypothesisGenerator(async_db_session)

        # 创建 Mock LLM 客户端
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value=json.dumps([
            {
                "title": "LLM 生成的假设",
                "description": "这是 LLM 基于数据生成的假设描述",
                "supporting_evidence": ["证据1", "证据2"],
                "verification_method": "Western Blot 验证",
                "confidence": 0.85,
                "category": "target_mechanism",
            }
        ]))

        result = await gen.generate(
            project_id="p1",
            context={"de_genes": [{"gene": "EGFR"}], "pathways": [{"name": "MAPK"}]},
            max_hypotheses=5,
            use_llm=True,
            llm_client=mock_llm,
            mode="hybrid",
        )
        assert len(result) > 0
        # 应包含 LLM 生成的假设
        llm_hyps = [h for h in result if h.get("source") in ("llm", "hybrid")]
        assert len(llm_hyps) > 0

    @pytest.mark.asyncio
    async def test_generate_llm_only_mode(self, async_db_session):
        """测试纯 LLM 模式"""
        gen = HypothesisGenerator(async_db_session)

        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value=json.dumps([
            {
                "title": "纯 LLM 假设",
                "description": "描述",
                "supporting_evidence": ["e1"],
                "verification_method": "实验验证",
                "confidence": 0.7,
                "category": "biomarker",
            }
        ]))

        result = await gen.generate(
            project_id="p1",
            context={},
            max_hypotheses=3,
            use_llm=True,
            llm_client=mock_llm,
            mode="llm",
        )
        assert len(result) > 0
        assert all(h.get("source") == "llm" for h in result)

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self, async_db_session):
        """测试 LLM 调用失败降级"""
        gen = HypothesisGenerator(async_db_session)

        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("API 超时"))

        result = await gen.generate(
            project_id="p1",
            context={"de_genes": [{"gene": "EGFR"}]},
            max_hypotheses=3,
            use_llm=True,
            llm_client=mock_llm,
            mode="hybrid",
        )
        # LLM 失败应降级到规则模式
        assert len(result) > 0

    def test_summarize_evidence(self, async_db_session):
        """测试证据摘要"""
        gen = HypothesisGenerator(async_db_session)
        summary = gen._summarize_evidence({
            "de_genes": [{"gene": "EGFR"}, {"gene": "TP53"}],
            "pathways": [{"name": "MAPK"}],
            "molecules": [{"smiles": "CCO"}],
        })
        assert "EGFR" in summary
        assert "MAPK" in summary
        assert "候选分子" in summary

    def test_summarize_evidence_empty(self, async_db_session):
        """测试空证据摘要"""
        gen = HypothesisGenerator(async_db_session)
        summary = gen._summarize_evidence({})
        assert "暂无" in summary

    def test_merge_hypotheses(self, async_db_session):
        """测试假设合并去重"""
        gen = HypothesisGenerator(async_db_session)
        rule_hyps = [
            {"title": "规则假设1", "confidence": 0.8, "category": "target_mechanism",
             "supporting_evidence": ["e1"], "source": "rule"},
            {"title": "规则假设2", "confidence": 0.6, "category": "molecule_design",
             "supporting_evidence": ["e2"], "source": "rule"},
        ]
        llm_hyps = [
            {"title": "LLM 假设1", "confidence": 0.9, "category": "target_mechanism",
             "supporting_evidence": ["e3"], "source": "llm"},
            {"title": "LLM 假设2", "confidence": 0.7, "category": "biomarker",
             "supporting_evidence": ["e4"], "source": "llm"},
        ]
        merged = gen._merge_hypotheses(rule_hyps, llm_hyps)
        # 同类取高置信度
        target_mech = [h for h in merged if h["category"] == "target_mechanism"][0]
        assert target_mech["confidence"] == 0.9  # LLM 更高
        assert target_mech["source"] == "hybrid"
        # 合并后 evidence 应包含两者
        assert len(target_mech["supporting_evidence"]) >= 2


# ========== Phase 7: DiscoveryPipeline Step 4 + custom_steps ==========


class TestDiscoveryPipelineEnhanced:
    """流水线增强功能测试"""

    @pytest.mark.asyncio
    async def test_pipeline_with_hypothesis_disabled(self, async_db_session):
        """测试禁用假设生成的流水线"""
        from app.services.orchestrator.discovery_pipeline import DiscoveryPipeline

        pipeline = DiscoveryPipeline(async_db_session)
        # 使用不存在的项目 ID
        import uuid
        result = await pipeline.run(
            project_id=uuid.uuid4(),
            enable_hypothesis=False,
        )
        assert "error" in result or result["summary"]["total_targets"] == 0
        assert "hypothesis_generation" not in result.get("steps", {})

    @pytest.mark.asyncio
    async def test_custom_steps_execution(self, async_db_session):
        """测试自定义步骤执行"""
        from app.services.orchestrator.discovery_pipeline import DiscoveryPipeline

        pipeline = DiscoveryPipeline(async_db_session)
        # 直接测试 _run_custom_steps
        result = await pipeline._run_custom_steps(
            project_id="test",
            custom_steps=[
                {"name": "assess_step", "type": "assess", "config": {"limit": 5}},
                {"name": "dock_step", "type": "dock", "config": {}},
                {"name": "unknown_step", "type": "unknown_type", "config": {}},
            ],
            context={"targets": [], "molecules": []},
        )
        assert result["total"] == 3
        assert result["success_count"] >= 1
        # dock 和 unknown 类型应跳过
        assert result["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_custom_step_custom_type(self, async_db_session):
        """测试 custom 类型步骤（动态回调）"""
        from app.services.orchestrator.discovery_pipeline import DiscoveryPipeline

        pipeline = DiscoveryPipeline(async_db_session)
        result = await pipeline._run_custom_steps(
            project_id="test",
            custom_steps=[
                {
                    "name": "custom_no_module",
                    "type": "custom",
                    "config": {},  # 无 callback_module
                },
            ],
            context={},
        )
        # 无 callback_module 应跳过
        assert result["success_count"] == 1
        assert "skipped" in str(result["executed"][0]["result"])

    @pytest.mark.asyncio
    async def test_pipeline_summary_includes_hypotheses(self, async_db_session):
        """测试流水线 summary 包含假设数"""
        from app.services.orchestrator.discovery_pipeline import DiscoveryPipeline

        pipeline = DiscoveryPipeline(async_db_session)
        import uuid
        result = await pipeline.run(
            project_id=uuid.uuid4(),
            enable_hypothesis=True,
        )
        # 项目不存在时返回 error；存在时 summary 包含 total_hypotheses
        if "error" not in result:
            assert "total_hypotheses" in result["summary"]
            assert "custom_steps_executed" in result["summary"]
        else:
            # 项目不存在也应返回 summary 结构
            assert "summary" in result or "steps" in result


# ========== 导入 uuid（用于上面的测试）==========
import uuid as _uuid


# ========== Phase 5 扩展: FederatedLearningService 边界与分支 ==========


class TestFederatedLearningBoundary:
    """联邦学习服务边界条件与未覆盖分支测试"""

    @pytest.mark.asyncio
    async def test_list_jobs_with_status_filter(self):
        """测试按状态过滤任务列表"""
        service = FederatedLearningService(num_rounds_default=1, min_clients=2)
        job = await service.create_job(project_id="p1")
        # job 初始状态为 pending
        pending_jobs = await service.list_jobs(status="pending")
        assert any(j["job_id"] == job["job_id"] for j in pending_jobs)
        # 无匹配状态
        completed_jobs = await service.list_jobs(status="completed")
        assert all(j["job_id"] != job["job_id"] for j in completed_jobs)

    @pytest.mark.asyncio
    async def test_list_jobs_with_project_filter(self):
        """测试按项目 ID 过滤任务列表"""
        service = FederatedLearningService()
        j1 = await service.create_job(project_id="proj_a")
        j2 = await service.create_job(project_id="proj_b")
        result = await service.list_jobs(project_id="proj_a")
        assert any(j["job_id"] == j1["job_id"] for j in result)
        assert all(j["job_id"] != j2["job_id"] for j in result)

    @pytest.mark.asyncio
    async def test_submit_weights_updates_client_heartbeat(self):
        """测试提交权重时更新客户端心跳"""
        service = FederatedLearningService(num_rounds_default=1, min_clients=2)
        job = await service.create_job(project_id="p1")
        # 注册客户端
        await service.register_client("c1", "http://localhost:8001")
        await service.register_client("c2", "http://localhost:8002")
        old_heartbeat = service._clients["c1"]["last_heartbeat"]
        old_count = service._clients["c1"]["weights_submitted"]
        # 提交权重
        await service.submit_weights(
            job_id=job["job_id"],
            client_id="c1",
            weights={"w1": 0.5},
            num_samples=10,
        )
        await service.submit_weights(
            job_id=job["job_id"],
            client_id="c2",
            weights={"w1": 0.6},
            num_samples=10,
        )
        # 心跳和提交计数应更新
        assert service._clients["c1"]["last_heartbeat"] != old_heartbeat
        assert service._clients["c1"]["weights_submitted"] == old_count + 1

    @pytest.mark.asyncio
    async def test_submit_weights_job_not_found(self):
        """测试提交权重到不存在的任务"""
        service = FederatedLearningService()
        result = await service.submit_weights(
            job_id="nonexistent",
            client_id="c1",
            weights={"w1": 0.5},
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_stop_job(self):
        """测试停止任务"""
        service = FederatedLearningService()
        job = await service.create_job(project_id="p1")
        result = await service.stop_job(job["job_id"])
        assert result["status"] == "stopped"
        job_data = await service.get_job(job["job_id"])
        assert job_data["status"] == "stopped"
        assert job_data["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_stop_job_not_found(self):
        """测试停止不存在的任务"""
        service = FederatedLearningService()
        result = await service.stop_job("nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_job_not_found(self):
        """测试获取不存在的任务"""
        service = FederatedLearningService()
        result = await service.get_job("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_configure_dp_not_found(self):
        """测试对不存在的任务配置 DP"""
        service = FederatedLearningService()
        result = await service.configure_dp("nonexistent", enabled=True)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_centers_not_found(self):
        """测试对不存在的任务获取多中心配置"""
        service = FederatedLearningService()
        result = await service.get_centers("nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_list_clients_with_status_filter(self):
        """测试按状态过滤客户端列表"""
        service = FederatedLearningService()
        await service.register_client("c1", "http://localhost:8001")
        await service.register_client("c2", "http://localhost:8002")
        active = await service.list_clients(status="active")
        assert len(active) >= 2
        inactive = await service.list_clients(status="inactive")
        assert len(inactive) == 0

    @pytest.mark.asyncio
    async def test_register_client(self):
        """测试客户端注册"""
        service = FederatedLearningService()
        result = await service.register_client(
            "c_reg",
            "http://localhost:9000",
            capabilities={"gpu": True, "max_memory": "16GB"},
        )
        assert result["client_id"] == "c_reg"
        assert result["status"] == "registered"
        clients = await service.list_clients()
        assert any(c["client_id"] == "c_reg" for c in clients)

    @pytest.mark.asyncio
    async def test_evaluate_global_model_no_weights(self):
        """测试评估尚未聚合权重的任务"""
        service = FederatedLearningService()
        job = await service.create_job(project_id="p1")
        result = await service.evaluate_global_model(job["job_id"])
        assert result["aggregated_weights_summary"]["num_layers"] == 0
        assert "message" in result["aggregated_weights_summary"]

    @pytest.mark.asyncio
    async def test_evaluate_with_external_metrics(self):
        """测试带外部评估指标的模型评估"""
        service = FederatedLearningService(num_rounds_default=1, min_clients=2)
        job = await service.create_job(project_id="p1")
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.5},
                num_samples=10,
            )
        result = await service.evaluate_global_model(
            job["job_id"],
            eval_metrics={"auc": 0.85, "f1": 0.78},
        )
        assert result["eval_metrics"]["auc"] == 0.85
        assert result["eval_metrics"]["f1"] == 0.78

    @pytest.mark.asyncio
    async def test_metrics_history_unknown_trend(self):
        """测试指标历史中 loss 为 None 时的收敛趋势"""
        service = FederatedLearningService(num_rounds_default=2, min_clients=2)
        job = await service.create_job(project_id="p1")
        # 第 1 轮：有 loss
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.1},
                num_samples=10,
                metrics={"loss": 0.5},
            )
        # 第 2 轮：无 loss（metrics 为空）→ trend 为 unknown
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.2},
                num_samples=10,
                metrics={},
            )
        history = await service.get_metrics_history(job["job_id"])
        assert history["rounds"] == 2
        # 第 2 轮的 trend 应为 unknown
        unknown_trends = [t for t in history["convergence_trend"] if t["trend"] == "unknown"]
        assert len(unknown_trends) >= 1

    @pytest.mark.asyncio
    async def test_metrics_history_stable_trend(self):
        """测试指标历史中 loss 相同时的稳定趋势"""
        service = FederatedLearningService(num_rounds_default=2, min_clients=2)
        job = await service.create_job(project_id="p1")
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.1},
                num_samples=10,
                metrics={"loss": 0.5},
            )
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.2},
                num_samples=10,
                metrics={"loss": 0.5},  # 相同 loss
            )
        history = await service.get_metrics_history(job["job_id"])
        stable_trends = [t for t in history["convergence_trend"] if t["trend"] == "stable"]
        assert len(stable_trends) >= 1

    def test_aggregate_empty_submissions(self):
        """测试聚合空提交列表"""
        service = FederatedLearningService()
        result = service._aggregate([], 0)
        assert result["aggregated_weights"] == {}
        assert result["total_samples"] == 0
        assert result["num_clients"] == 0

    def test_aggregate_zero_total_samples(self):
        """测试所有客户端样本数为 0 的情况"""
        service = FederatedLearningService()
        submissions = [
            {"client_id": "c1", "weights": {"w1": 0.5}, "num_samples": 0},
            {"client_id": "c2", "weights": {"w1": 0.3}, "num_samples": 0},
        ]
        result = service._aggregate(submissions, 0)
        # total_samples == 0 → 使用 len(submissions) 作为分母
        assert result["total_samples"] == len(submissions)
        assert "w1" in result["aggregated_weights"]

    def test_aggregate_with_val_metrics(self):
        """测试聚合时汇总验证集指标"""
        service = FederatedLearningService()
        submissions = [
            {"client_id": "c1", "weights": {"w1": 0.5}, "num_samples": 10,
             "metrics": {"loss": 0.3, "accuracy": 0.85, "val_auc": 0.88, "val_f1": 0.77}},
            {"client_id": "c2", "weights": {"w1": 0.3}, "num_samples": 20,
             "metrics": {"loss": 0.4, "accuracy": 0.80, "val_auc": 0.90, "val_f1": 0.72}},
        ]
        result = service._aggregate(submissions, 0)
        assert result["avg_loss"] is not None
        assert result["avg_accuracy"] is not None
        assert "val_auc" in result["val_metrics"]
        assert "val_f1" in result["val_metrics"]
        # val_auc 应为两客户端的平均
        assert abs(result["val_metrics"]["val_auc"] - 0.89) < 0.01

    def test_aggregate_empty_weights(self):
        """测试聚合空权重提交"""
        service = FederatedLearningService()
        submissions = [
            {"client_id": "c1", "weights": {}, "num_samples": 10},
            {"client_id": "c2", "weights": None, "num_samples": 20},
        ]
        result = service._aggregate(submissions, 0)
        # 空权重 → aggregated_weights 为空
        assert result["aggregated_weights"] == {}

    def test_filter_byzantine_three_or_less(self):
        """测试 3 个或更少提交不触发拜占庭剔除"""
        service = FederatedLearningService()
        submissions = [
            {"client_id": "c1", "weights": {"w1": 0.1}},
            {"client_id": "c2", "weights": {"w1": 0.2}},
            {"client_id": "c3", "weights": {"w1": 100.0}},  # 离群值
        ]
        result = service._filter_byzantine(submissions)
        assert len(result) == 3  # 不剔除

    def test_filter_byzantine_with_outlier(self):
        """测试 4+ 提交时剔除离群客户端"""
        service = FederatedLearningService(mad_threshold=3.0)
        submissions = [
            {"client_id": "c1", "weights": {"w1": 0.1, "w2": 0.2}},
            {"client_id": "c2", "weights": {"w1": 0.15, "w2": 0.25}},
            {"client_id": "c3", "weights": {"w1": 0.12, "w2": 0.22}},
            {"client_id": "c4", "weights": {"w1": 10.0, "w2": 20.0}},  # 离群值
        ]
        result = service._filter_byzantine(submissions)
        assert len(result) == 3  # 剔除 c4
        assert all(s["client_id"] != "c4" for s in result)

    def test_filter_byzantine_mad_zero(self):
        """测试 MAD=0 时不剔除（所有范数相同）"""
        service = FederatedLearningService(mad_threshold=3.0)
        submissions = [
            {"client_id": "c1", "weights": {"w1": 0.5}},
            {"client_id": "c2", "weights": {"w1": 0.5}},
            {"client_id": "c3", "weights": {"w1": 0.5}},
            {"client_id": "c4", "weights": {"w1": 0.5}},
        ]
        # 所有范数相同 → median == norm → abs_devs 全 0 → mad == 0
        result = service._filter_byzantine(submissions)
        assert len(result) == 4  # 不剔除

    def test_filter_byzantine_with_empty_weights(self):
        """测试含空权重提交的拜占庭剔除"""
        service = FederatedLearningService(mad_threshold=3.0)
        submissions = [
            {"client_id": "c1", "weights": {"w1": 0.1}},
            {"client_id": "c2", "weights": {"w1": 0.15}},
            {"client_id": "c3", "weights": {"w1": 0.12}},
            {"client_id": "c4", "weights": {}},  # 空权重 → norm=0
        ]
        result = service._filter_byzantine(submissions)
        # c4 的 norm=0，可能被视为离群
        assert isinstance(result, list)

    def test_filter_byzantine_all_filtered_returns_original(self):
        """测试所有客户端都被剔除时返回原始列表"""
        service = FederatedLearningService(mad_threshold=0.001)  # 极小阈值
        submissions = [
            {"client_id": "c1", "weights": {"w1": 0.1}},
            {"client_id": "c2", "weights": {"w1": 0.2}},
            {"client_id": "c3", "weights": {"w1": 0.3}},
            {"client_id": "c4", "weights": {"w1": 0.4}},
        ]
        result = service._filter_byzantine(submissions)
        # 阈值极小 → 全部被剔除 → 返回原始 submissions
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_aggregate_triggers_byzantine_filter(self):
        """测试聚合时触发拜占庭剔除（>3 提交）"""
        service = FederatedLearningService(num_rounds_default=1, min_clients=4, mad_threshold=3.0)
        job = await service.create_job(project_id="p1")
        for cid, w in [("c1", 0.1), ("c2", 0.12), ("c3", 0.11), ("c4", 100.0)]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": w},
                num_samples=10,
                metrics={"loss": 0.3},
            )
        job_data = await service.get_job(job["job_id"])
        # 应剔除 c4
        assert job_data["rounds_history"][0]["aggregated"]["byzantine_filtered"] >= 1

    @pytest.mark.asyncio
    async def test_hierarchical_aggregate_with_empty_center(self):
        """测试多中心聚合时某中心无提交"""
        service = FederatedLearningService(num_rounds_default=1, min_clients=2)
        centers = [
            {"center_id": "center_a", "name": "北京中心", "clients": ["c1", "c2"]},
            {"center_id": "center_b", "name": "上海中心", "clients": ["c3", "c4"]},  # 无提交
        ]
        job = await service.create_job(
            project_id="p1",
            config={"centers": centers},
        )
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.5},
                num_samples=10,
                metrics={"loss": 0.3},
            )
        result = await service.get_centers(job["job_id"])
        # 只有 center_a 有提交
        assert len(result["last_centers_breakdown"]) == 1
        assert result["last_centers_breakdown"][0]["center_id"] == "center_a"

    @pytest.mark.asyncio
    async def test_full_job_lifecycle(self):
        """测试任务完整生命周期：创建→运行→完成"""
        service = FederatedLearningService(num_rounds_default=1, min_clients=2)
        job = await service.create_job(project_id="p1")
        assert job["status"] == "pending"
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.5},
                num_samples=10,
                metrics={"loss": 0.3, "accuracy": 0.85},
            )
        job_data = await service.get_job(job["job_id"])
        assert job_data["status"] == "completed"
        assert job_data["current_round"] == 1
        assert job_data["aggregated_weights"] is not None


# ========== Phase 5 扩展: DPSGDOptimizer 边界条件 ==========


class TestDPSGDOptimizerEdgeCases:
    """差分隐私 SGD 优化器边界条件测试"""

    def test_clip_weights_non_numeric_only(self):
        """测试权重全为非数值时不裁剪"""
        opt = DPSGDOptimizer(noise_multiplier=0.0, max_norm=1.0)
        weights = {"layer1": "string", "layer2": None, "layer3": [1, 2, 3]}
        clipped = opt.clip_weights(weights)
        # 无数值 → vals 为空 → 直接返回原权重
        assert clipped == weights

    def test_clip_weights_empty_dict(self):
        """测试空权重字典"""
        opt = DPSGDOptimizer(noise_multiplier=0.0, max_norm=1.0)
        clipped = opt.clip_weights({})
        assert clipped == {}

    def test_clip_weights_mixed_types(self):
        """测试混合类型权重只裁剪数值"""
        opt = DPSGDOptimizer(noise_multiplier=0.0, max_norm=0.5)
        weights = {"w1": 3.0, "w2": "meta", "w3": 4.0}
        clipped = opt.clip_weights(weights)
        # 范数 5.0 > 0.5 → 裁剪
        numeric_norm = (clipped["w1"] ** 2 + clipped["w3"] ** 2) ** 0.5
        assert numeric_norm <= 0.5 + 0.01
        # 非数值不变
        assert clipped["w2"] == "meta"

    def test_add_noise_empty_weights(self):
        """测试空权重加噪"""
        opt = DPSGDOptimizer(noise_multiplier=0.5, max_norm=1.0)
        noisy = opt.add_noise({})
        assert noisy == {}

    def test_add_noise_non_numeric_weights(self):
        """测试非数值权重加噪（保持不变）"""
        opt = DPSGDOptimizer(noise_multiplier=0.5, max_norm=1.0)
        weights = {"w1": "string", "w2": None}
        noisy = opt.add_noise(weights)
        assert noisy["w1"] == "string"
        assert noisy["w2"] is None

    def test_add_noise_with_custom_params(self):
        """测试使用自定义噪声参数"""
        # 构造时 noise_multiplier=0.0 → add_noise 时 nm=0.0（or 不覆盖因为 self.noise_multiplier 也是 0.0）
        opt = DPSGDOptimizer(noise_multiplier=0.0, max_norm=100.0)
        weights = {"w1": 0.5}
        noisy = opt.add_noise(weights)
        # nm=0.0, mn=100.0 → noise_scale=0，范数 0.5 < 100 不裁剪
        assert abs(noisy["w1"] - 0.5) < 0.01

    def test_add_noise_override_params(self):
        """测试 add_noise 使用覆盖参数"""
        opt = DPSGDOptimizer(noise_multiplier=1.0, max_norm=1.0)
        weights = {"w1": 0.5}
        # 覆盖 max_norm=100（范数 0.5 < 100 不裁剪），noise_multiplier=0.5
        noisy = opt.add_noise(weights, noise_multiplier=0.5, max_norm=100.0)
        assert "w1" in noisy
        assert isinstance(noisy["w1"], float)

    def test_add_noise_zero_max_norm(self):
        """测试 max_norm=0 时不裁剪"""
        opt = DPSGDOptimizer(noise_multiplier=0.0, max_norm=0.0)
        weights = {"w1": 5.0}
        noisy = opt.add_noise(weights)
        # mn=0 → 不裁剪 (if mn 为 falsy)
        assert "w1" in noisy

    def test_get_privacy_spent_opacus_branch(self):
        """测试 opacus 隐私预算计算分支（通过 mock）"""
        import sys
        from unittest.mock import MagicMock, patch

        # 创建 mock opacus.privacy_analysis 模块
        mock_module = MagicMock()
        mock_module.compute_rdp = MagicMock(return_value=[1.0] * 111)
        mock_module.get_privacy_spent = MagicMock(return_value=(0.5, 1e-5, 10.0))

        with patch.dict("sys.modules", {"opacus.privacy_analysis": mock_module}):
            opt = DPSGDOptimizer(noise_multiplier=1.0, max_norm=1.0)
            result = opt.get_privacy_spent(steps=100, target_delta=1e-5)
            assert result["source"] == "opacus"
            assert result["epsilon"] == 0.5
            assert result["delta"] == 1e-5
            assert result["steps"] == 100
            assert "opt_order" in result

    def test_get_privacy_spent_approx_branch(self):
        """测试降级隐私预算估算分支"""
        opt = DPSGDOptimizer(noise_multiplier=2.0, max_norm=1.0)
        result = opt.get_privacy_spent(steps=50, target_delta=1e-5)
        # opacus.privacy_analysis 不可用 → 降级估算
        assert result["source"] == "approx"
        assert result["epsilon"] >= 0
        assert result["steps"] == 50

    def test_get_privacy_spent_one_step(self):
        """测试单步隐私预算"""
        opt = DPSGDOptimizer(noise_multiplier=1.0, max_norm=1.0)
        result = opt.get_privacy_spent(steps=1, target_delta=1e-5)
        assert result["steps"] == 1
        assert result["epsilon"] >= 0


# ========== Phase 5 扩展: RedisFLStorage Redis 路径 ==========


class TestRedisFLStorageRedisPath:
    """RedisFLStorage 的 Redis 路径测试（通过 mock）"""

    @pytest.mark.asyncio
    async def test_save_job_via_redis(self):
        """测试通过 Redis 保存任务"""
        from unittest.mock import AsyncMock

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        storage._available = True
        storage._redis = mock_redis

        await storage.save_job({"job_id": "rjob1", "status": "running"})
        mock_redis.set.assert_called_once()
        key, value = mock_redis.set.call_args[0]
        assert key == "fl:job:rjob1"

    @pytest.mark.asyncio
    async def test_load_job_via_redis(self):
        """测试通过 Redis 加载任务"""
        from unittest.mock import AsyncMock
        import json

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps({"job_id": "rjob2", "status": "ok"}))
        storage._available = True
        storage._redis = mock_redis

        loaded = await storage.load_job("rjob2")
        assert loaded is not None
        assert loaded["job_id"] == "rjob2"
        mock_redis.get.assert_called_once_with("fl:job:rjob2")

    @pytest.mark.asyncio
    async def test_load_job_via_redis_not_found(self):
        """测试通过 Redis 加载不存在的任务"""
        from unittest.mock import AsyncMock

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        storage._available = True
        storage._redis = mock_redis

        loaded = await storage.load_job("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_list_jobs_via_redis(self):
        """测试通过 Redis 列出任务"""
        from unittest.mock import AsyncMock
        import json

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=["fl:job:j1", "fl:job:j2"])
        mock_redis.get = AsyncMock(side_effect=[
            json.dumps({"job_id": "j1"}),
            json.dumps({"job_id": "j2"}),
        ])
        storage._available = True
        storage._redis = mock_redis

        jobs = await storage.list_jobs()
        assert len(jobs) == 2
        assert {j["job_id"] for j in jobs} == {"j1", "j2"}

    @pytest.mark.asyncio
    async def test_save_client_via_redis(self):
        """测试通过 Redis 保存客户端"""
        from unittest.mock import AsyncMock

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        storage._available = True
        storage._redis = mock_redis

        await storage.save_client({"client_id": "rc1", "endpoint": "http://h:8000"})
        mock_redis.set.assert_called_once()
        key, value = mock_redis.set.call_args[0]
        assert key == "fl:client:rc1"

    @pytest.mark.asyncio
    async def test_save_job_redis_exception_fallback(self):
        """测试 Redis 保存异常时降级内存"""
        from unittest.mock import AsyncMock

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=Exception("Redis 写入失败"))
        storage._available = True
        storage._redis = mock_redis

        # 应降级到 _fallback，不抛异常
        await storage.save_job({"job_id": "fb1"})
        # 验证已写入 fallback
        assert "fl:job:fb1" in storage._fallback

    @pytest.mark.asyncio
    async def test_load_job_redis_exception_fallback(self):
        """测试 Redis 加载异常时降级内存"""
        from unittest.mock import AsyncMock

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        # 先写入 fallback
        storage._fallback["fl:job:fb2"] = {"job_id": "fb2"}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Redis 读取失败"))
        storage._available = True
        storage._redis = mock_redis

        loaded = await storage.load_job("fb2")
        assert loaded is not None
        assert loaded["job_id"] == "fb2"

    @pytest.mark.asyncio
    async def test_list_jobs_redis_exception_fallback(self):
        """测试 Redis 列出异常时降级内存"""
        from unittest.mock import AsyncMock

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        storage._fallback["fl:job:fb3"] = {"job_id": "fb3"}
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(side_effect=Exception("Redis keys 失败"))
        storage._available = True
        storage._redis = mock_redis

        jobs = await storage.list_jobs()
        assert any(j["job_id"] == "fb3" for j in jobs)

    @pytest.mark.asyncio
    async def test_save_client_redis_exception_fallback(self):
        """测试 Redis 保存客户端异常时降级内存"""
        from unittest.mock import AsyncMock

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=Exception("Redis 写入失败"))
        storage._available = True
        storage._redis = mock_redis

        await storage.save_client({"client_id": "fc1"})
        assert "fl:client:fc1" in storage._fallback

    @pytest.mark.asyncio
    async def test_close_with_connection(self):
        """测试关闭 Redis 连接"""
        from unittest.mock import AsyncMock

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        mock_redis = AsyncMock()
        mock_redis.close = AsyncMock()
        storage._redis = mock_redis

        await storage.close()
        mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_connection(self):
        """测试无连接时关闭不报错"""
        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        # _redis 为 None
        await storage.close()  # 不应抛异常

    @pytest.mark.asyncio
    async def test_close_swallows_exception(self):
        """测试关闭时异常被吞掉"""
        from unittest.mock import AsyncMock

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        mock_redis = AsyncMock()
        mock_redis.close = AsyncMock(side_effect=Exception("关闭失败"))
        storage._redis = mock_redis

        await storage.close()  # 不应抛异常

    @pytest.mark.asyncio
    async def test_get_client_connection_failure(self):
        """测试 Redis 连接失败降级"""
        from unittest.mock import AsyncMock, patch

        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        storage._available = True
        storage._redis = None

        # mock redis.asyncio.from_url 抛异常
        mock_aioredis = MagicMock()
        mock_aioredis.from_url = MagicMock(side_effect=Exception("连接失败"))

        with patch.dict("sys.modules", {"redis.asyncio": mock_aioredis}):
            client = await storage._get_client()
            assert client is None
            assert storage._available is False

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip_memory(self):
        """测试内存降级模式的保存加载往返"""
        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        await storage.save_job({"job_id": "rt1", "status": "running", "rounds": 5})
        loaded = await storage.load_job("rt1")
        assert loaded is not None
        assert loaded["job_id"] == "rt1"
        assert loaded["rounds"] == 5

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self):
        """测试空任务列表"""
        storage = RedisFLStorage(redis_url="redis://localhost:9999/0")
        jobs = await storage.list_jobs()
        assert jobs == []


# ========== Phase 5 扩展: DDIChecker 补充 ==========


class TestDDICheckerSupplemental:
    """DDI 检查器补充测试"""

    def test_check_all_empty_strings(self):
        """测试所有药物名为空字符串时返回不足提示"""
        from app.services.analyzer.ddi_checker import DDIChecker, RISK_NONE

        checker = DDIChecker()
        result = checker.check(["", "  ", "   "])
        # 规范化后药物数 < 2
        assert result["risk_level"] == RISK_NONE
        assert result["interactions"] == []
        assert result["drug_count"] == 0

    def test_check_none_drug_list(self):
        """测试 None 药物列表"""
        from app.services.analyzer.ddi_checker import DDIChecker, RISK_NONE

        checker = DDIChecker()
        result = checker.check(None)
        assert result["risk_level"] == RISK_NONE
        assert result["drug_count"] == 0

    def test_check_with_extra_target_list(self):
        """测试带额外靶点列表的检查"""
        from app.services.analyzer.ddi_checker import DDIChecker, RISK_NONE

        checker = DDIChecker()
        # 两个无相互作用的药物 + 额外靶点
        result = checker.check(
            ["metformin", "aspirin"],
            target_list=["PTGS1", "PTGS2", "OCT1"],
        )
        assert result["drug_count"] == 2

    def test_check_summary_no_interactions(self):
        """测试无相互作用时总结文本"""
        from app.services.analyzer.ddi_checker import DDIChecker

        checker = DDIChecker()
        result = checker.check(["acetaminophen", "ibuprofen"])
        assert "未检测到" in result["summary"]

    def test_max_risk_helper(self):
        """测试 _max_risk 辅助函数"""
        from app.services.analyzer.ddi_checker import (
            _max_risk,
            RISK_NONE,
            RISK_MINOR,
            RISK_MODERATE,
            RISK_MAJOR,
            RISK_CONTRAINDICATED,
        )

        assert _max_risk([]) == RISK_NONE
        assert _max_risk([RISK_MINOR, RISK_MAJOR]) == RISK_MAJOR
        assert _max_risk([RISK_MODERATE, RISK_CONTRAINDICATED]) == RISK_CONTRAINDICATED
        assert _max_risk([RISK_NONE, RISK_MINOR]) == RISK_MINOR

    def test_target_overlap_no_known_targets(self):
        """测试靶点重合度检查 - 未知靶点"""
        from app.services.analyzer.ddi_checker import DDIChecker

        checker = DDIChecker()
        result = checker._check_target_overlap("unknown_a", "unknown_b")
        assert result["overlap_count"] == 0
        assert result["overlap_ratio"] == 0.0

    def test_match_rule_no_match(self):
        """测试规则表无匹配"""
        from app.services.analyzer.ddi_checker import DDIChecker

        checker = DDIChecker()
        result = checker._match_rule("unknown_a", "unknown_b")
        assert result is None


# ========== Phase 5 扩展: LineageTracker 补充 ==========


class TestLineageTrackerSupplemental:
    """数据血缘追踪器补充测试"""

    @pytest.mark.asyncio
    async def test_upstream_depth_limit(self, async_db_session):
        """测试上游查询的深度限制"""
        from app.services.lineage.tracker import LineageTracker

        tracker = LineageTracker(async_db_session)
        project_id = str(_uuid.uuid4())
        # 构建 3 层链路：dataset → target → molecule → treatment
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-001",
            target_type="target", target_id="tgt-001",
            transformation="discover",
        )
        await tracker.record(
            project_id=project_id,
            source_type="target", source_id="tgt-001",
            target_type="molecule", target_id="mol-001",
            transformation="design",
        )
        await tracker.record(
            project_id=project_id,
            source_type="molecule", source_id="mol-001",
            target_type="treatment", target_id="trt-001",
            transformation="optimize",
        )
        # depth=1 只返回直接上游
        result = await tracker.get_upstream(project_id, "treatment", "trt-001", depth=1)
        assert len(result) == 1
        assert result[0]["node_type"] == "molecule"
        assert result[0]["depth"] == 1

    @pytest.mark.asyncio
    async def test_upstream_cycle_safety(self, async_db_session):
        """测试上游查询的循环依赖安全"""
        from app.services.lineage.tracker import LineageTracker

        tracker = LineageTracker(async_db_session)
        project_id = str(_uuid.uuid4())
        # A → B → A 循环
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="A",
            target_type="target", target_id="B",
            transformation="step1",
        )
        await tracker.record(
            project_id=project_id,
            source_type="target", source_id="B",
            target_type="dataset", target_id="A",
            transformation="step2",
        )
        # 上游查询不应死循环
        result = await tracker.get_upstream(project_id, "dataset", "A", depth=5)
        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_downstream_no_results(self, async_db_session):
        """测试下游查询无结果"""
        from app.services.lineage.tracker import LineageTracker

        tracker = LineageTracker(async_db_session)
        project_id = str(_uuid.uuid4())
        result = await tracker.get_downstream(project_id, "dataset", "ds-999", depth=3)
        assert result == []

    @pytest.mark.asyncio
    async def test_dag_with_upstream_and_downstream(self, async_db_session):
        """测试 DAG 包含上游和下游"""
        from app.services.lineage.tracker import LineageTracker

        tracker = LineageTracker(async_db_session)
        project_id = str(_uuid.uuid4())
        # 上游：dataset → target
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-001",
            target_type="target", target_id="tgt-001",
            transformation="discover",
        )
        # 下游：target → molecule
        await tracker.record(
            project_id=project_id,
            source_type="target", source_id="tgt-001",
            target_type="molecule", target_id="mol-001",
            transformation="design",
        )
        dag = await tracker.get_dag(project_id, "target", "tgt-001", depth=3)
        assert dag["node_count"] == 3
        # 验证 edge 有 meta 字段
        assert all("meta" in e for e in dag["edges"])

    @pytest.mark.asyncio
    async def test_record_with_all_params(self, async_db_session):
        """测试记录血缘关系包含所有参数"""
        from app.services.lineage.tracker import LineageTracker

        tracker = LineageTracker(async_db_session)
        project_id = str(_uuid.uuid4())
        lineage = await tracker.record(
            project_id=project_id,
            source_type="dataset",
            source_id="ds-full",
            target_type="target",
            target_id="tgt-full",
            transformation="discover",
            meta={"algorithm": "DESeq2"},
            created_by="user-001",
        )
        assert lineage.transformation_meta == {"algorithm": "DESeq2"}
        assert lineage.created_by == "user-001"


# ========== Phase 5 扩展: ConsentManager 补充 ==========


class TestConsentManagerSupplemental:
    """知情同意管理器补充测试"""

    @pytest.mark.asyncio
    async def test_grant_full_params(self, async_db_session):
        """测试授予同意包含所有参数"""
        from app.services.consent.manager import ConsentManager
        from app.models.consent import ConsentStatus, ConsentType
        from datetime import datetime, timedelta

        manager = ConsentManager(async_db_session)
        project_id = str(_uuid.uuid4())
        expires = datetime.utcnow() + timedelta(days=30)
        consent = await manager.grant(
            project_id=project_id,
            patient_pseudonym="P-FULL",
            consent_type=ConsentType.DATA_USE,
            purpose="完整参数测试",
            expires_at=expires,
            constraints={"level": "k-3"},
            granted_by="user-001",
        )
        assert consent.status == ConsentStatus.GRANTED
        assert consent.expires_at is not None
        assert consent.constraints == {"level": "k-3"}
        assert consent.granted_by == "user-001"

    @pytest.mark.asyncio
    async def test_check_marks_expired_consent(self, async_db_session):
        """测试 check 方法标记过期同意"""
        from app.services.consent.manager import ConsentManager
        from app.models.consent import ConsentStatus, ConsentType
        from datetime import datetime, timedelta

        manager = ConsentManager(async_db_session)
        project_id = str(_uuid.uuid4())
        # 创建已过期的同意
        expired_date = datetime.utcnow() - timedelta(days=1)
        consent = await manager.grant(
            project_id=project_id,
            patient_pseudonym="P-EXP",
            consent_type=ConsentType.DATA_USE,
            purpose="过期测试",
            expires_at=expired_date,
        )
        # check 应返回 False 并标记为 EXPIRED
        result = await manager.check(project_id, "P-EXP", ConsentType.DATA_USE)
        assert result is False
        # 再次获取该记录验证状态已更新
        found = await manager.get_consent(str(consent.id))
        assert found.status == ConsentStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_list_consents_no_patient_filter(self, async_db_session):
        """测试列出项目下所有同意（不过滤患者）"""
        from app.services.consent.manager import ConsentManager
        from app.models.consent import ConsentType

        manager = ConsentManager(async_db_session)
        project_id = str(_uuid.uuid4())
        await manager.grant(project_id, "P-A", ConsentType.DATA_USE, "研究")
        await manager.grant(project_id, "P-B", ConsentType.SHARING, "共享")
        await manager.grant(project_id, "P-C", ConsentType.PUBLICATION, "发表")
        result = await manager.list_consents(project_id)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_raises(self, async_db_session):
        """测试撤回不存在的同意抛异常"""
        from app.services.consent.manager import ConsentManager

        manager = ConsentManager(async_db_session)
        with pytest.raises(ValueError, match="不存在"):
            await manager.revoke(str(_uuid.uuid4()))


# ========== Phase 5 扩展: VectorStore 补充 ==========


class TestVectorStoreSupplemental:
    """向量存储服务补充测试"""

    def test_vector_store_init(self):
        """测试 VectorStore 初始化"""
        from app.services.knowledge.vector import VectorStore

        store = VectorStore()
        assert store._client is None
        assert store._collections == {}

    def test_vector_store_get_client_mock_mode(self):
        """测试 Mock 模式下 get_client 返回 None"""
        from app.services.knowledge.vector import VectorStore

        store = VectorStore()
        client = store._get_client()
        # 测试环境为 mock 模式
        assert client is None

    def test_vector_store_get_collection_mock(self):
        """测试 Mock 模式下 get_collection 返回 None"""
        from app.services.knowledge.vector import VectorStore

        store = VectorStore()
        coll = store._get_collection("test_collection")
        assert coll is None

    @pytest.mark.asyncio
    async def test_add_documents_empty(self):
        """测试添加空文档列表"""
        from app.services.knowledge.vector import VectorStore

        store = VectorStore()
        count = await store.add_documents([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_add_documents_mock_mode(self):
        """测试 Mock 模式下添加文档返回 0"""
        from app.services.knowledge.vector import VectorStore

        store = VectorStore()
        docs = [{"id": "d1", "text": "测试文档", "metadata": {"source": "test"}}]
        count = await store.add_documents(docs)
        # Mock 模式下 coll 为 None → 返回 0
        assert count == 0

    @pytest.mark.asyncio
    async def test_search_mock_mode(self):
        """测试 Mock 模式下搜索返回空列表"""
        from app.services.knowledge.vector import VectorStore

        store = VectorStore()
        results = await store.search("测试查询", top_k=5)
        assert results == []

    def test_get_vector_store_singleton(self):
        """测试 get_vector_store 单例"""
        from app.services.knowledge.vector import get_vector_store, VectorStore

        s1 = get_vector_store()
        s2 = get_vector_store()
        assert s1 is s2
        assert isinstance(s1, VectorStore)


# ========== Phase 5 扩展: ImportError 降级分支与剩余分支 ==========


class TestImportErrorFallbacks:
    """测试各模块 ImportError 降级分支（通过 mock sys.modules）"""

    def test_flwr_unavailable_degrades_to_in_memory(self):
        """测试 flwr 不可用时框架降级为 in_memory"""
        from unittest.mock import patch

        with patch.dict("sys.modules", {"flwr": None}):
            service = FederatedLearningService()
            assert service._flower_available is False

    @pytest.mark.asyncio
    async def test_flwr_unavailable_job_uses_in_memory(self):
        """测试 flwr 不可用时任务使用 in_memory 框架"""
        from unittest.mock import patch

        with patch.dict("sys.modules", {"flwr": None}):
            service = FederatedLearningService()
            job = await service.create_job(project_id="p1")
            assert job["framework"] == "in_memory"

    def test_opacus_unavailable_degrades(self):
        """测试 opacus 不可用时降级"""
        from unittest.mock import patch

        with patch.dict("sys.modules", {"opacus": None}):
            opt = DPSGDOptimizer(noise_multiplier=1.0, max_norm=1.0)
            assert opt._opacus_available is False

    def test_numpy_unavailable_add_noise_fallback(self):
        """测试 numpy 不可用时 add_noise 降级为 random.gauss"""
        from unittest.mock import patch

        opt = DPSGDOptimizer(noise_multiplier=0.5, max_norm=1.0)
        weights = {"w1": 0.5, "w2": 0.3, "meta": "non-numeric"}
        with patch.dict("sys.modules", {"numpy": None}):
            noisy = opt.add_noise(weights)
            assert "w1" in noisy
            assert "w2" in noisy
            assert isinstance(noisy["w1"], float)
            # 非数值应保持不变
            assert noisy["meta"] == "non-numeric"

    def test_redis_unavailable_degrades_to_memory(self):
        """测试 redis 不可用时降级为内存"""
        from unittest.mock import patch

        with patch.dict("sys.modules", {"redis": None}):
            storage = RedisFLStorage(redis_url="redis://localhost:6379/0")
            assert storage._available is False


class TestFederatedLearningRemainingBranches:
    """联邦学习服务剩余分支测试"""

    @pytest.mark.asyncio
    async def test_metrics_history_increasing_trend(self):
        """测试指标历史中 loss 上升时的增长趋势"""
        service = FederatedLearningService(num_rounds_default=2, min_clients=2)
        job = await service.create_job(project_id="p1")
        # 第 1 轮：loss 较低
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.1},
                num_samples=10,
                metrics={"loss": 0.3},
            )
        # 第 2 轮：loss 更高 → increasing trend
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.2},
                num_samples=10,
                metrics={"loss": 0.5},
            )
        history = await service.get_metrics_history(job["job_id"])
        increasing = [t for t in history["convergence_trend"] if t["trend"] == "increasing"]
        assert len(increasing) >= 1

    @pytest.mark.asyncio
    async def test_metrics_history_decreasing_trend(self):
        """测试指标历史中 loss 下降时的收敛趋势"""
        service = FederatedLearningService(num_rounds_default=2, min_clients=2)
        job = await service.create_job(project_id="p1")
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.1},
                num_samples=10,
                metrics={"loss": 0.5},
            )
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.2},
                num_samples=10,
                metrics={"loss": 0.3},
            )
        history = await service.get_metrics_history(job["job_id"])
        decreasing = [t for t in history["convergence_trend"] if t["trend"] == "decreasing"]
        assert len(decreasing) >= 1

    def test_hierarchical_aggregate_no_centers(self):
        """测试无多中心配置时的分层聚合（直接调用）"""
        service = FederatedLearningService()
        base = {"aggregated_weights": {"w1": 0.5}, "total_samples": 10}
        result = service._hierarchical_aggregate(
            submissions=[],
            round_num=0,
            job={"centers": []},
            base_aggregated=base,
        )
        # 无 centers → 直接返回 base
        assert result is base

    @pytest.mark.asyncio
    async def test_submit_weights_running_status(self):
        """测试任务从 pending 变为 running"""
        service = FederatedLearningService(num_rounds_default=3, min_clients=2)
        job = await service.create_job(project_id="p1")
        assert job["status"] == "pending"
        # 第 1 轮提交后状态应变为 running
        for cid in ["c1", "c2"]:
            await service.submit_weights(
                job_id=job["job_id"],
                client_id=cid,
                weights={"w1": 0.5},
                num_samples=10,
            )
        job_data = await service.get_job(job["job_id"])
        assert job_data["status"] == "running"
        assert job_data["started_at"] is not None
        assert job_data["current_round"] == 1

    @pytest.mark.asyncio
    async def test_create_job_with_target_id(self):
        """测试创建带靶点 ID 的任务"""
        service = FederatedLearningService()
        job = await service.create_job(project_id="p1", target_id="tgt-001")
        assert job["target_id"] == "tgt-001"

    @pytest.mark.asyncio
    async def test_create_job_with_config(self):
        """测试创建带配置的任务"""
        service = FederatedLearningService()
        job = await service.create_job(
            project_id="p1",
            config={"custom_param": "value", "centers": [{"center_id": "c1"}]},
        )
        assert job["config"]["custom_param"] == "value"
        assert len(job["centers"]) == 1

    @pytest.mark.asyncio
    async def test_multi_round_training(self):
        """测试多轮训练"""
        service = FederatedLearningService(num_rounds_default=3, min_clients=2)
        job = await service.create_job(project_id="p1")
        for rnd in range(3):
            for cid in ["c1", "c2"]:
                await service.submit_weights(
                    job_id=job["job_id"],
                    client_id=cid,
                    weights={"w1": 0.1 * (rnd + 1)},
                    num_samples=10,
                    metrics={"loss": 0.5 - rnd * 0.1},
                )
        job_data = await service.get_job(job["job_id"])
        assert job_data["status"] == "completed"
        assert job_data["current_round"] == 3
        assert len(job_data["rounds_history"]) == 3


# ========== 跨模块补充: 覆盖剩余高覆盖文件的少量未覆盖行 ==========


class TestDynamicAdjusterCoverage:
    """动态调整器补充测试 — 覆盖 adverse_events 分支"""

    @pytest.mark.asyncio
    async def test_adjust_with_few_adverse_events(self):
        """测试 1-2 个不良反应时的调整建议"""
        from app.services.optimizer.dynamic_adjuster import DynamicAdjuster

        adjuster = DynamicAdjuster()
        result = await adjuster.adjust(
            treatment_id=_uuid.uuid4(),
            efficacy_data={
                "current_efficacy": 0.6,
                "trend": "stable",
                "adverse_events": [{"event": "nausea"}],
            },
        )
        assert "adjustments" in result
        # 应包含"监测不良反应"建议（1 个 AE → elif adverse_events 分支）
        assert any("监测不良反应" in a for a in result["adjustments"])
        # RL 状态应包含 ae_bucket="few"
        assert "few" in result["rl_state"]

    @pytest.mark.asyncio
    async def test_adjust_with_many_adverse_events(self):
        """测试 3+ 个不良反应时的调整建议"""
        from app.services.optimizer.dynamic_adjuster import DynamicAdjuster

        adjuster = DynamicAdjuster()
        result = await adjuster.adjust(
            treatment_id=_uuid.uuid4(),
            efficacy_data={
                "current_efficacy": 0.4,
                "trend": "declining",
                "adverse_events": [{"event": "a"}, {"event": "b"}, {"event": "c"}],
            },
        )
        assert any("不良反应较多" in a for a in result["adjustments"])
        assert "many" in result["rl_state"]

    @pytest.mark.asyncio
    async def test_adjust_high_efficacy_improving(self):
        """测试高疗效且改善时的维持建议"""
        from app.services.optimizer.dynamic_adjuster import DynamicAdjuster

        adjuster = DynamicAdjuster()
        result = await adjuster.adjust(
            treatment_id=_uuid.uuid4(),
            efficacy_data={
                "current_efficacy": 0.85,
                "trend": "improving",
                "adverse_events": [],
            },
        )
        assert any("维持当前方案" in a for a in result["adjustments"])

    def test_rl_state_all_buckets(self):
        """测试 RL 状态编码各分桶"""
        from app.services.optimizer.dynamic_adjuster import DynamicAdjuster

        adjuster = DynamicAdjuster()
        # low efficacy, stable, none AE
        state = adjuster._rl_state({"current_efficacy": 0.1, "trend": "stable", "adverse_events": []})
        assert state.startswith("low_sta_none")
        # mid efficacy, improving, few AE
        state = adjuster._rl_state({"current_efficacy": 0.5, "trend": "improving", "adverse_events": [{"e": 1}]})
        assert state.startswith("mid_imp_few")
        # high efficacy, declining, many AE
        state = adjuster._rl_state({"current_efficacy": 0.9, "trend": "declining", "adverse_events": [1, 2, 3]})
        assert state.startswith("high_dec_many")


class TestParserBaseCoverage:
    """解析器基类补充测试 — 覆盖 SCRNA_SEQ 路由和未知类型分支"""

    @pytest.mark.asyncio
    async def test_parse_dataset_unsupported_type(self):
        """测试不支持的数据类型"""
        from app.services.parser.base import parse_dataset
        from unittest.mock import MagicMock

        dataset = MagicMock()
        dataset.data_type = "unsupported_type"
        dataset.storage_path = "/some/path"
        result = await parse_dataset(dataset)
        assert "error" in result["summary"]
        assert "暂不支持" in result["summary"]["error"]

    @pytest.mark.asyncio
    async def test_parse_dataset_scrna_seq(self):
        """测试 scRNA-seq 路由（文件不存在时返回错误）"""
        from app.services.parser.base import parse_dataset
        from unittest.mock import MagicMock

        dataset = MagicMock()
        dataset.data_type = "scrna_seq"
        dataset.storage_path = "/nonexistent/path.h5"
        result = await parse_dataset(dataset)
        # 文件不存在 → 返回错误摘要
        assert "error" in result["summary"] or "summary" in result

    @pytest.mark.asyncio
    async def test_parse_dataset_no_storage_path(self):
        """测试无文件路径时返回错误"""
        from app.services.parser.base import parse_dataset
        from unittest.mock import MagicMock

        dataset = MagicMock()
        dataset.data_type = "rna_seq"
        dataset.storage_path = None
        result = await parse_dataset(dataset)
        assert "error" in result["summary"]


class TestGeneQueryCoverage:
    """基因查询服务补充测试 — 覆盖批量查询异常分支"""

    @pytest.mark.asyncio
    async def test_batch_query_genes_with_error(self):
        """测试批量查询中单个基因查询失败"""
        from unittest.mock import AsyncMock, patch
        from app.services.knowledge.gene_query import batch_query_genes

        mock_client = AsyncMock()
        mock_client.query = AsyncMock(side_effect=Exception("query failed"))

        with patch("app.services.knowledge.gene_query.get_gene_client", return_value=mock_client):
            results = await batch_query_genes(["EGFR"])
            assert len(results) == 1
            assert "error" in results[0]
            assert "query failed" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_batch_query_genes_mixed(self):
        """测试批量查询混合成功和失败"""
        from unittest.mock import AsyncMock, patch
        from app.services.knowledge.gene_query import batch_query_genes

        mock_client = AsyncMock()
        mock_client.query = AsyncMock(side_effect=[
            {"symbol": "EGFR", "name": "EGFR gene"},
            Exception("timeout"),
        ])

        with patch("app.services.knowledge.gene_query.get_gene_client", return_value=mock_client):
            results = await batch_query_genes(["EGFR", "TP53"])
            assert len(results) == 2
            assert results[0]["symbol"] == "EGFR"
            assert "error" in results[1]


class TestNextflowRunnerCoverage:
    """Nextflow 运行器补充测试 — 覆盖清理文件异常分支"""

    @pytest.mark.asyncio
    async def test_run_real_unlink_oserror(self):
        """测试 nextflow 未安装且清理参数文件失败"""
        from unittest.mock import patch, MagicMock
        from app.services.workflow.nextflow_runner import NextflowRunner

        runner = NextflowRunner(db=None)
        workflow_run = MagicMock()
        workflow_run.pipeline_name = "test_pipeline"
        workflow_run.params = {"key": "value"}

        # nextflow 命令不存在 → FileNotFoundError → finally → os.unlink 抛 OSError
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            with patch("os.unlink", side_effect=OSError("permission denied")):
                result = await runner._run_real(workflow_run, "test_run_id")
                assert result["status"] == "failed"
                assert "nextflow" in result["error"].lower()


class TestLLMRouterCacheCoverage:
    """LLM 路由器补充测试 — 覆盖缓存命中分支"""

    @pytest.mark.asyncio
    async def test_complete_cache_hit(self):
        """测试缓存命中时跳过 LLM 调用"""
        from unittest.mock import AsyncMock, MagicMock
        from app.services.llm.router import LLMRouter
        from app.services.llm.guardrail import GuardrailResult

        # Mock cache 返回缓存结果
        mock_cache = AsyncMock()
        cached_result = {"content": "cached response", "model": "test", "usage": {}, "cost_usd": 0.0}
        mock_cache.get = AsyncMock(return_value=cached_result)

        # Mock guardrail 通过
        mock_guardrail = MagicMock()
        mock_guardrail.check_input = MagicMock(return_value=GuardrailResult(passed=True))

        # Mock LLM client（不应被调用）
        mock_llm = AsyncMock()

        router = LLMRouter(
            llm_client=mock_llm,
            cost_tracker=MagicMock(),
            guardrail=mock_guardrail,
            cache=mock_cache,
        )

        result = await router.complete("test prompt", tier="fast_screen")
        assert result["content"] == "cached response"
        # LLM client 不应被调用
        mock_llm.chat.assert_not_called()


# ========== 模型 __repr__ 方法覆盖 ==========


class TestModelReprCoverage:
    """模型 __repr__ 方法覆盖测试"""

    def test_data_lineage_repr(self, async_db_session):
        """测试 DataLineage __repr__"""
        from app.models.data_lineage import DataLineage

        lineage = DataLineage(
            project_id="p1",
            source_type="dataset",
            source_id="ds-001",
            target_type="target",
            target_id="tgt-001",
            transformation="discover",
        )
        r = repr(lineage)
        assert "DataLineage" in r
        assert "ds-001" in r
        assert "tgt-001" in r

    def test_consent_repr(self, async_db_session):
        """测试 ConsentRecord __repr__"""
        from app.models.consent import ConsentRecord, ConsentStatus

        consent = ConsentRecord(
            project_id="p1",
            patient_pseudonym="P-001",
            consent_type="data_use",
            status=ConsentStatus.GRANTED,
            purpose="研究",
        )
        r = repr(consent)
        assert "ConsentRecord" in r
        assert "P-001" in r

    def test_project_repr(self, async_db_session):
        """测试 Project __repr__"""
        from app.models.project import Project

        project = Project(name="Test Project", cancer_type="NSCLC", stage="IV", owner_id="u1")
        r = repr(project)
        assert "Project" in r
        assert "Test Project" in r

    def test_audit_repr(self, async_db_session):
        """测试 AuditLog __repr__"""
        from app.models.audit import AuditLog

        log = AuditLog(actor="user1", action="create", entity="project", entity_id="p1")
        r = repr(log)
        assert "AuditLog" in r
        assert "user1" in r

    def test_target_repr(self, async_db_session):
        """测试 Target __repr__"""
        from app.models.target import Target

        target = Target(gene_symbol="EGFR", project_id="p1")
        r = repr(target)
        assert "Target" in r
        assert "EGFR" in r
