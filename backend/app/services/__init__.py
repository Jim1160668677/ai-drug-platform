"""Services 包 — 业务逻辑层

子包：
- analyzer: 靶点发现 / 网络分析 / 分子设计 / 老药新用 / 证据链
- llm: LLM 编排 / 路由 / RAG / 成本追踪 / 安全护栏
- optimizer: 治疗方案优化 / 疗效监测 / 动态调整 / 联邦学习
- privacy: 隐私层 / 差分隐私 / 数据脱敏
- report: CDISC 导出 / 假设比较
- workflow: 反馈闭环 / 流水线 / Nextflow
- parser: VCF / scRNA / RNA-seq / FASTA 解析
- knowledge: MyGene / MyVariant / ChEMBL / 向量库 / 知识图谱
- experiment: 实验追踪 / LIMS 导入
- cdisc: SDTM 导出
"""
import logging

logger = logging.getLogger(__name__)

__all__ = [
    # analyzer
    "TargetIdentifier", "NetworkModeler", "MoleculeDesigner",
    "DrugRepurposer", "EvidenceChainBuilder",
    # llm
    "LLMOrchestrator", "LLMRouter", "RAGEngine", "RagEngine",
    "CostTracker", "get_cost_tracker", "Guardrail", "get_guardrail",
    # optimizer
    "TreatmentPlanner", "TreatmentOptimizer", "EfficacyMonitor",
    "DynamicAdjuster", "FederatedLearningService", "FederatedLearner",
    "PharmaFedAvg", "FLClient", "ClientRegistry",
    # privacy
    "PrivacyLayer", "DifferentialPrivacy", "PrivacyBudget", "DataMasker",
    # report
    "CdiscExporter", "HypothesisComparator",
    # workflow
    "FeedbackLoop", "ExperimentTracker", "LimsImporter",
    "PipelineManager", "NextflowRunner",
]


# ========== analyzer ==========
try:
    from app.services.analyzer.target_identifier import TargetIdentifier
except ImportError as e:
    logger.warning(f"TargetIdentifier 导入失败: {e}")
    TargetIdentifier = None  # type: ignore

try:
    from app.services.analyzer.network_modeler import NetworkModeler
except ImportError as e:
    logger.warning(f"NetworkModeler 导入失败: {e}")
    NetworkModeler = None  # type: ignore

try:
    from app.services.analyzer.molecule_designer import MoleculeDesigner
except ImportError as e:
    logger.warning(f"MoleculeDesigner 导入失败: {e}")
    MoleculeDesigner = None  # type: ignore

try:
    from app.services.analyzer.drug_repurposer import DrugRepurposer
except ImportError as e:
    logger.warning(f"DrugRepurposer 导入失败: {e}")
    DrugRepurposer = None  # type: ignore

try:
    from app.services.analyzer.evidence_chain import EvidenceChainBuilder
except ImportError as e:
    logger.warning(f"EvidenceChainBuilder 导入失败: {e}")
    EvidenceChainBuilder = None  # type: ignore


# ========== llm ==========
try:
    from app.services.llm.orchestrator import LLMOrchestrator
except ImportError as e:
    logger.warning(f"LLMOrchestrator 导入失败: {e}")
    LLMOrchestrator = None  # type: ignore

try:
    from app.services.llm.router import LLMRouter
except ImportError as e:
    logger.warning(f"LLMRouter 导入失败: {e}")
    LLMRouter = None  # type: ignore

try:
    from app.services.llm.rag import RAGEngine, RagEngine
except ImportError as e:
    logger.warning(f"RAGEngine 导入失败: {e}")
    RAGEngine = RagEngine = None  # type: ignore

try:
    from app.services.llm.cost_tracker import CostTracker, get_cost_tracker
except ImportError as e:
    logger.warning(f"CostTracker 导入失败: {e}")
    CostTracker = None  # type: ignore

    def get_cost_tracker():  # type: ignore
        return None

try:
    from app.services.llm.guardrail import Guardrail, get_guardrail
except ImportError as e:
    logger.warning(f"Guardrail 导入失败: {e}")
    Guardrail = None  # type: ignore

    def get_guardrail():  # type: ignore
        return None


# ========== optimizer ==========
try:
    from app.services.optimizer.treatment_planner import (
        TreatmentPlanner, TreatmentOptimizer,
    )
except ImportError as e:
    logger.warning(f"TreatmentPlanner 导入失败: {e}")
    TreatmentPlanner = TreatmentOptimizer = None  # type: ignore

try:
    from app.services.optimizer.efficacy_monitor import EfficacyMonitor
except ImportError as e:
    logger.warning(f"EfficacyMonitor 导入失败: {e}")
    EfficacyMonitor = None  # type: ignore

try:
    from app.services.optimizer.dynamic_adjuster import DynamicAdjuster
except ImportError as e:
    logger.warning(f"DynamicAdjuster 导入失败: {e}")
    DynamicAdjuster = None  # type: ignore

try:
    from app.services.optimizer.federated_learning import (
        FederatedLearningService, FederatedLearner,
    )
except ImportError as e:
    logger.warning(f"FederatedLearningService 导入失败: {e}")
    FederatedLearningService = FederatedLearner = None  # type: ignore

try:
    from app.services.optimizer.pharma_fedavg import PharmaFedAvg
except ImportError as e:
    logger.warning(f"PharmaFedAvg 导入失败: {e}")
    PharmaFedAvg = None  # type: ignore

try:
    from app.services.optimizer.fl_client import FLClient, ClientRegistry
except ImportError as e:
    logger.warning(f"FLClient 导入失败: {e}")
    FLClient = ClientRegistry = None  # type: ignore


# ========== privacy ==========
try:
    from app.services.privacy.privacy_layer import PrivacyLayer
except ImportError as e:
    logger.warning(f"PrivacyLayer 导入失败: {e}")
    PrivacyLayer = None  # type: ignore

try:
    from app.services.privacy.differential_privacy import (
        DifferentialPrivacy, PrivacyBudget,
    )
except ImportError as e:
    logger.warning(f"DifferentialPrivacy 导入失败: {e}")
    DifferentialPrivacy = PrivacyBudget = None  # type: ignore

try:
    from app.services.privacy.data_masker import DataMasker
except ImportError as e:
    logger.warning(f"DataMasker 导入失败: {e}")
    DataMasker = None  # type: ignore


# ========== report ==========
try:
    from app.services.report.cdisc_exporter import CdiscExporter
except ImportError as e:
    logger.warning(f"CdiscExporter 导入失败: {e}")
    CdiscExporter = None  # type: ignore

try:
    from app.services.report.hypothesis_comparator import HypothesisComparator
except ImportError as e:
    logger.warning(f"HypothesisComparator 导入失败: {e}")
    HypothesisComparator = None  # type: ignore


# ========== workflow ==========
try:
    from app.services.workflow.feedback_loop import (
        FeedbackLoop, ExperimentTracker, LimsImporter,
    )
except ImportError as e:
    logger.warning(f"FeedbackLoop 导入失败: {e}")
    FeedbackLoop = ExperimentTracker = LimsImporter = None  # type: ignore

try:
    from app.services.workflow.pipeline_manager import PipelineManager
except ImportError as e:
    logger.warning(f"PipelineManager 导入失败: {e}")
    PipelineManager = None  # type: ignore

try:
    from app.services.workflow.nextflow_runner import NextflowRunner
except ImportError as e:
    logger.warning(f"NextflowRunner 导入失败: {e}")
    NextflowRunner = None  # type: ignore
