"""Phase 1 测试 — 计算引擎与合成模块基础设施验证

覆盖：
1. TestModels（5 测试）— 5 个新数据模型的字段定义 + 常量类
   - ProteinStructure / ComputeJob / BenchmarkReport / Neoantigen / SynthesisPlan
2. TestComputeEngines（5 测试）— 计算引擎导入与 Mock 模式契约
   - 引擎导入 / 注册表 list_available / 注册表 reset / ESMFold Mock 预测 / Vina Mock 对接

设计要点：
- 模型测试只校验字段与常量定义，不写入 DB（避免依赖 async fixture）
- 引擎测试通过 registry.reset_instances() 保证单例隔离
- 所有 Mock 调用应返回合理数值（plddt>0、affinity<0 等）
"""
import pytest

from app.models.benchmark_report import BenchmarkReport, BenchmarkMode
from app.models.compute_job import (
    ComputeEngine,
    ComputeJob,
    ComputeJobStatus,
    ComputeJobType,
    ComputeMode,
)
from app.models.neoantigen import Neoantigen, NeoantigenStatus
from app.models.protein_structure import (
    ProteinStructure,
    ProteinStructureSource,
    ProteinStructureStatus,
)
from app.models.synthesis_plan import (
    SynthesisFeasibility,
    SynthesisPlan,
    SynthesisSource,
)


# ========== 1. 模型字段与常量测试 ==========


class TestModels:
    """5 个新数据模型的字段与常量定义测试"""

    def test_protein_structure_model(self):
        """ProteinStructure 模型 — 字段定义 + JSON 列类型"""
        # 表名
        assert ProteinStructure.__tablename__ == "protein_structures"

        # 关键字段存在
        cols = {c.name for c in ProteinStructure.__table__.columns}
        assert "target_id" in cols, "缺少 target_id 字段"
        assert "sequence" in cols, "缺少 sequence 字段"
        assert "storage_path" in cols, "缺少 storage_path 字段"
        assert "plddt_mean" in cols, "缺少 plddt_mean 字段"
        assert "prediction_source" in cols, "缺少 prediction_source 字段"
        assert "status" in cols, "缺少 status 字段"

        # 常量类存在
        assert hasattr(ProteinStructureSource, "ESMFOLD") or "ESMFOLD" in dir(
            ProteinStructureSource
        ), "ProteinStructureSource 缺少 ESMFOLD 常量"
        assert hasattr(ProteinStructureStatus, "COMPLETED") or "COMPLETED" in dir(
            ProteinStructureStatus
        ), "ProteinStructureStatus 缺少 COMPLETED 常量"

        # JSON 列类型校验（plddt_per_residue 应为 JSON 类型，跨 SQLite/PostgreSQL 兼容）
        from sqlalchemy import JSON

        plddt_col = ProteinStructure.__table__.columns.get("plddt_per_residue")
        assert plddt_col is not None, "缺少 plddt_per_residue 字段"
        assert isinstance(plddt_col.type, JSON), "plddt_per_residue 应为 JSON 类型"

    def test_compute_job_model(self):
        """ComputeJob 模型 — 字段定义 + 4 个常量类"""
        assert ComputeJob.__tablename__ == "compute_jobs"

        cols = {c.name for c in ComputeJob.__table__.columns}
        for required_col in (
            "owner_id",
            "project_id",
            "job_type",
            "engine",
            "mode",
            "status",
            "input_params",
            "result",
            "cost_usd",
            "duration_sec",
            "energy_kwh",
            "token_count",
            "error_message",
        ):
            assert required_col in cols, f"ComputeJob 缺少字段: {required_col}"

        # 4 个常量类 — 应覆盖所有计算类型与引擎
        assert ComputeJobType.DOCKING == "docking"
        assert ComputeJobType.STRUCTURE_PREDICTION == "structure_prediction"
        assert ComputeJobType.PERTURBATION == "perturbation"
        assert ComputeJobType.NEOANTIGEN == "neoantigen"
        assert ComputeJobType.DUAL_CONTEXT_SCREEN == "dual_context_screen"

        assert ComputeEngine.UNIMOL == "unimol"
        assert ComputeEngine.VINA == "vina"
        assert ComputeEngine.ESMFOLD == "esmfold"
        assert ComputeEngine.SCGPT == "scgpt"
        assert ComputeEngine.MHCFLURRY == "mhcflurry"
        assert ComputeEngine.HYBRID == "hybrid"
        assert ComputeEngine.LLM_ONLY == "llm_only"
        assert ComputeEngine.SUPERCOMPUTE == "supercompute"

        assert ComputeMode.MOCK == "mock"
        assert ComputeMode.REAL == "real"
        assert ComputeMode.HYBRID == "hybrid"

        assert ComputeJobStatus.PENDING == "pending"
        assert ComputeJobStatus.RUNNING == "running"
        assert ComputeJobStatus.COMPLETED == "completed"
        assert ComputeJobStatus.FAILED == "failed"

        # input_params 与 result 应为 JSON（跨 SQLite/PostgreSQL 兼容）
        from sqlalchemy import JSON

        assert isinstance(
            ComputeJob.__table__.columns.get("input_params").type, JSON
        ), "input_params 应为 JSON"
        assert isinstance(
            ComputeJob.__table__.columns.get("result").type, JSON
        ), "result 应为 JSON"

    def test_benchmark_report_model(self):
        """BenchmarkReport 模型 — 字段 + BenchmarkMode 常量"""
        assert BenchmarkReport.__tablename__ == "benchmark_reports"

        cols = {c.name for c in BenchmarkReport.__table__.columns}
        for required_col in (
            "case_id",
            "mode",
            "metrics",
            "summary",
            "cost_saving_pct",
            "accuracy_change_pct",
        ):
            assert required_col in cols, f"BenchmarkReport 缺少字段: {required_col}"

        # 3 种基准模式
        assert BenchmarkMode.HYBRID == "hybrid"
        assert BenchmarkMode.TRADITIONAL_SUPERCOMPUTE == "traditional_supercompute"
        assert BenchmarkMode.LLM_ONLY == "llm_only"

    def test_neoantigen_model(self):
        """Neoantigen 模型 — 字段 + NeoantigenStatus 常量"""
        assert Neoantigen.__tablename__ == "neoantigens"

        cols = {c.name for c in Neoantigen.__table__.columns}
        for required_col in (
            "mutant_peptide",
            "wildtype_peptide",
            "mhc_alleles",
            "binding_affinity_nM",
            "is_neoantigen",
            "vaccine_sequence",
            "structure_plddt",
        ):
            assert required_col in cols, f"Neoantigen 缺少字段: {required_col}"

        # NeoantigenStatus 应有合理状态值
        status_values = [v for v in dir(NeoantigenStatus) if not v.startswith("_")]
        assert len(status_values) >= 2, "NeoantigenStatus 至少应有 2 个状态值"

    def test_synthesis_plan_model(self):
        """SynthesisPlan 模型 — 字段 + SynthesisFeasibility / SynthesisSource 常量"""
        assert SynthesisPlan.__tablename__ == "synthesis_plans"

        cols = {c.name for c in SynthesisPlan.__table__.columns}
        for required_col in (
            "smiles",
            "routes",
            "sa_score",
            "sc_score",
            "total_cost_usd",
            "feasibility_label",
            "source_engine",
        ):
            assert required_col in cols, f"SynthesisPlan 缺少字段: {required_col}"

        # 3 个可行性等级
        assert SynthesisFeasibility.EASY == "easy"
        assert SynthesisFeasibility.MEDIUM == "medium"
        assert SynthesisFeasibility.HARD == "hard"

        # 3 个合成来源
        assert SynthesisSource.AIZYNTHFINDER == "aizynthfinder"
        assert SynthesisSource.RDKIT_TEMPLATE == "rdkit_template"
        assert SynthesisSource.LLM_ASSISTED == "llm_assisted"


# ========== 2. 计算引擎导入与 Mock 模式测试 ==========


class TestComputeEngines:
    """计算引擎导入与 Mock 模式契约测试"""

    def test_compute_engines_import(self):
        """5 个计算引擎 + registry 函数全部可导入"""
        from app.services.compute import (
            ESMFoldPredictor,
            MHCflurryPredictor,
            ScGPTEngine,
            UniMolDocking,
            VinaDocking,
            get_esmfold,
            get_mhcflurry,
            get_scgpt,
            get_unimol,
            get_vina,
            list_available,
        )

        # 类应为可调用类型
        assert callable(ESMFoldPredictor)
        assert callable(UniMolDocking)
        assert callable(VinaDocking)
        assert callable(ScGPTEngine)
        assert callable(MHCflurryPredictor)

        # registry 函数
        assert callable(get_esmfold)
        assert callable(get_unimol)
        assert callable(get_vina)
        assert callable(get_scgpt)
        assert callable(get_mhcflurry)
        assert callable(list_available)

    def test_compute_registry_list_available(self):
        """list_available() 返回 6 个引擎的 mock 状态"""
        from app.services.compute import list_available

        available = list_available()
        assert isinstance(available, dict)
        assert len(available) == 6, f"应有 6 个引擎，实际 {len(available)}"

        for engine_name in ("esmfold", "unimol", "vina", "scgpt", "mhcflurry", "protenix"):
            assert engine_name in available, f"缺少引擎: {engine_name}"
            assert available[engine_name] in ("mock", "real"), (
                f"引擎 {engine_name} 状态应为 mock/real，实际 {available[engine_name]}"
            )

        # 测试环境默认全部为 mock
        assert all(v == "mock" for v in available.values()), (
            f"测试环境所有引擎应为 mock，实际 {available}"
        )

    def test_compute_registry_reset(self):
        """reset_instances() 清空单例缓存"""
        from app.services.compute import (
            get_esmfold,
            get_mhcflurry,
            get_scgpt,
            get_unimol,
            get_vina,
            reset_instances,
        )
        from app.services.compute.registry import _instances

        # 先获取所有单例填充缓存
        get_esmfold()
        get_unimol()
        get_vina()
        get_scgpt()
        get_mhcflurry()
        assert len(_instances) == 5, "缓存应有 5 个实例"

        # reset 后缓存清空
        reset_instances()
        assert len(_instances) == 0, "reset 后缓存应为空"

        # 再次获取只创建一个
        get_esmfold()
        assert len(_instances) == 1, "reset 后再获取应只创建 1 个实例"

        # 清理
        reset_instances()

    @pytest.mark.asyncio
    async def test_esmfold_mock_predict(self):
        """ESMFoldPredictor Mock 模式 — 返回合理 plddt + pdb_text"""
        from app.services.compute import ESMFoldPredictor

        predictor = ESMFoldPredictor()
        # 短序列测试
        result = await predictor.predict_structure(
            sequence="MVLSEGEWQLVLHVWAKVEA",
            target_id="test_target",
        )

        # 必需字段
        assert "pdb_text" in result, "缺 pdb_text"
        assert "plddt_mean" in result, "缺 plddt_mean"
        assert "source" in result, "缺 source"
        assert "duration_sec" in result, "缺 duration_sec"

        # Mock 模式合理数值
        assert result["source"] in ("mock", "esmfold"), f"source 异常: {result['source']}"
        assert 0.0 <= result["plddt_mean"] <= 1.0, (
            f"plddt 应在 [0,1]，实际 {result['plddt_mean']}"
        )
        # Mock 模式应有 PDB 文本（非空字符串）
        if result["source"] == "mock":
            assert len(result["pdb_text"]) > 0, "Mock 模式 pdb_text 不应为空"
            # PDB 文本应包含 ATOM 记录
            assert "ATOM" in result["pdb_text"], "Mock PDB 应含 ATOM 记录"

    @pytest.mark.asyncio
    async def test_vina_mock_dock(self):
        """VinaDocking Mock 模式 — 返回合理 affinity + rmsd"""
        from app.services.compute import VinaDocking

        docker = VinaDocking()
        result = await docker.dock(
            smiles="CC(=O)Oc1ccccc1C(=O)O",  # 阿司匹林
            receptor_pdbqt="ATOM      1  N   ALA A   1      11.104  6.134  -6.504  1.00  0.00           N",
        )

        # 必需字段
        assert "rmsd" in result, "缺 rmsd"
        assert "affinity" in result, "缺 affinity"
        assert "pose" in result, "缺 pose"
        assert "source" in result, "缺 source"

        # Mock 模式合理数值（Vina 亲和力为负值，越小越好）
        assert result["source"] in ("mock", "vina", "mock_refine"), (
            f"source 异常: {result['source']}"
        )
        if result["source"] == "mock":
            assert result["affinity"] < 0, (
                f"Vina affinity 应为负值，实际 {result['affinity']}"
            )
            assert 0.0 <= result["rmsd"], f"rmsd 应 >= 0，实际 {result['rmsd']}"
            assert isinstance(result["pose"], dict), "pose 应为 dict"
