"""LLM 编排器 — 分级路由核心

复现 Sid 团队流程：提问 → 文献检索 → 假设 → 分析框架 → 运行 → 报告
"""
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analysis_job import AnalysisJob, AnalysisTier, JobStatus
from app.models.user import User
from app.services.llm.prompts import SYSTEM_PROMPTS, build_context_prompt
from app.services.llm.rag import RAGEngine

logger = logging.getLogger(__name__)


# 意图识别关键词
_INTENT_KEYWORDS = {
    "target_discovery": ["靶点", "发现", "target", "discover", "基因", "突变", "变异"],
    "drug_repurposing": ["老药新用", "重定位", "repurpos", "已获批", "现有药物"],
    "molecule_design": ["分子设计", "新药", "smiles", "molecule", "design", "化学"],
    "pathway_analysis": ["通路", "pathway", "信号", "cascade"],
    "clinical_trial": ["临床试验", "trial", "nct", "入组"],
}


def _detect_intent(message: str) -> str:
    """基于关键词的简单意图识别"""
    msg_lower = message.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in msg_lower or kw in message:
                return intent
    return "general_qa"


def _estimate_cost(usage: Dict, tier: str, model: str = "") -> float:
    """根据 token 用量估算成本 — 优先使用 cost_tracker 定价表"""
    prompt_tokens = (usage or {}).get("prompt_tokens", 0)
    completion_tokens = (usage or {}).get("completion_tokens", 0)

    try:
        from app.services.llm.cost_tracker import _MODEL_PRICING
        if model and model in _MODEL_PRICING:
            in_price, out_price = _MODEL_PRICING[model]
            return round((prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000, 4)
    except ImportError:
        pass

    if tier == AnalysisTier.DEEP_INSIGHT:
        return round((prompt_tokens * 5 + completion_tokens * 15) / 1_000_000, 4)
    return round((prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000, 4)


class LLMOrchestrator:
    """LLM 编排器 — 分级路由（fast_screen / deep_insight）"""

    def __init__(self, db: AsyncSession, llm_client, llm_config=None):
        """初始化

        Args:
            db: 数据库会话
            llm_client: LLM 客户端实例（Mock 或 Real）
            llm_config: 数据库激活的 LLMConfig（可选，用于动态选择 fast/deep 模型）
        """
        self.db = db
        self.llm_client = llm_client
        self.llm_config = llm_config
        # 当前请求用户（由 route() 设置，供 _deep_insight/_load_user_genome_context 使用）
        self._current_user: Optional[User] = None

    def select_model(self, tier: str) -> str:
        """根据 tier 选择模型 — 优先使用数据库激活配置，回退到 settings

        公开方法（供 HybridOrchestrator 复用），保证返回非 None：
        若数据库 fast_model/deep_model/test_model 均为空，
        应回退至 settings.LLM_MODEL_FAST / LLM_MODEL_DEEP，避免后续调用 NPE。
        """
        if self.llm_config is not None:
            if tier == AnalysisTier.FAST_SCREEN:
                return (
                    self.llm_config.fast_model
                    or self.llm_config.test_model
                    or settings.LLM_MODEL_FAST
                )
            return (
                self.llm_config.deep_model
                or self.llm_config.test_model
                or settings.LLM_MODEL_DEEP
            )
        # 回退到 settings 默认值
        if tier == AnalysisTier.FAST_SCREEN:
            return settings.LLM_MODEL_FAST
        return settings.LLM_MODEL_DEEP

    async def route(
        self,
        message: str,
        project_id: Optional[str],
        tier: str,
        user: User,
    ) -> Dict[str, Any]:
        """分级路由主入口

        Args:
            message: 用户问题
            project_id: 项目 ID（可选）
            tier: fast_screen / deep_insight
            user: 当前用户
        Returns:
            {answer, tier, cost_usd, duration_sec, model, references, code}
        """
        start = time.time()
        model = self.select_model(tier)
        # 缓存当前用户，供 _deep_insight/_load_user_genome_context 使用
        self._current_user = user

        if tier == AnalysisTier.DEEP_INSIGHT:
            answer, references, code, usage = await self._deep_insight(message, project_id, model)
        else:
            answer, references, code, usage = await self._fast_screen(message, model)

        duration_sec = round(time.time() - start, 3)
        cost_usd = _estimate_cost(usage, tier, model)

        # 记录 AnalysisJob
        try:
            job = AnalysisJob(
                project_id=UUID(project_id) if project_id else None,
                job_type="chat",
                tier=tier,
                status=JobStatus.COMPLETED,
                input_params={"message": message[:500]},
                result={"answer": answer[:500]},
                cost_usd=cost_usd,
                duration_sec=int(duration_sec),
                model_used=model,
                token_count=(usage or {}).get("prompt_tokens", 0) + (usage or {}).get("completion_tokens", 0),
                triggered_by=user.id,
            )
            self.db.add(job)
            await self.db.flush()
        except Exception as e:
            logger.warning(f"记录 AnalysisJob 失败（不影响主流程）: {e}")
            await self.db.rollback()

        return {
            "answer": answer,
            "tier": tier,
            "cost_usd": cost_usd,
            "duration_sec": duration_sec,
            "model": model,
            "references": references,
            "code": code,
        }

    async def _fast_screen(self, message: str, model: str) -> tuple:
        """快速筛查 — 直接调 LLM，无 RAG"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS["fast_screen"]},
            {"role": "user", "content": message},
        ]
        response = await self.llm_client.chat(messages, model=model)
        return (
            response.get("content", ""),
            response.get("references", []),
            response.get("code"),
            response.get("usage"),
        )

    async def _deep_insight(self, message: str, project_id: Optional[str], model: str) -> tuple:
        """深度洞察 — RAG + KnowledgeGraph + LLM"""
        # 1. RAG 检索
        rag = RAGEngine(self.db, self.llm_client)
        retrieved = await rag.retrieve(message, project_id=project_id, top_k=5)
        augmented_query = await rag.augment(message, retrieved)

        # 2. 知识图谱扩展（从消息中提取基因名）
        context: Dict[str, Any] = {"extra": augmented_query}
        gene = self._extract_gene(message)
        if gene:
            try:
                from app.services.knowledge.graph import get_knowledge_graph
                kg = get_knowledge_graph()
                neighbors_result = await kg.get_neighbors(gene, depth=1)
                context["gene"] = gene
                context["ppi_neighbors"] = neighbors_result.get("neighbors", [])
            except Exception as e:
                logger.warning(f"知识图谱扩展失败: {e}")

        # 3. 用户基因组上下文增强（关键词触发，仅当用户已上传基因组时注入）
        if self._current_user is not None:
            try:
                genome_ctx = await self.load_user_genome_context(
                    self._current_user, message
                )
                if genome_ctx:
                    context["user_genome"] = genome_ctx
            except Exception as e:
                logger.warning(f"用户基因组上下文加载失败: {e}")

        context_prompt = build_context_prompt(context)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS["deep_insight"]},
            {"role": "user", "content": f"{context_prompt}\n\n## 用户问题\n{message}"},
        ]
        response = await self.llm_client.chat(messages, model=model)

        references = response.get("references", [])
        # 将 RAG 检索结果也加入引用
        for doc in retrieved:
            references.append({
                "title": (doc.get("metadata") or {}).get("title", "检索文献"),
                "source": (doc.get("metadata") or {}).get("source", "knowledge_base"),
                "similarity": doc.get("similarity", 0),
            })

        return (
            response.get("content", ""),
            references,
            response.get("code"),
            response.get("usage"),
        )

    async def load_user_genome_context(
        self, user: User, message: str
    ) -> Dict[str, Any]:
        """从用户消息中检测基因组相关意图，并加载最新基因组上下文。

        公开方法（供 HybridOrchestrator 复用）。
        关键词触发：基因型 / 基因组 / genome / SNP / rsID / 风险评分 / 性状 / allele / 变异 / 基因检测
        若用户未上传基因组或消息不含关键词，返回空 dict（不注入上下文）。

        Returns:
            dict（可能为空），含：
            - has_genome: bool
            - genome_id, file_name, genome_build, total_variants
            - latest_assessments: list (前 3 项)
            - user_genotypes: list (来自知识图谱缓存，限制 20 条)
        """
        # 1. 关键词检测（不匹配则跳过 DB 查询，避免无谓开销）
        genome_keywords = [
            "基因型", "基因组", "genome", "SNP", "rsID", "风险评分",
            "性状", "allele", "变异", "基因检测",
        ]
        msg_lower = message.lower()
        if not any(kw.lower() in msg_lower or kw in message for kw in genome_keywords):
            return {}

        # 2. 加载用户最新基因组
        try:
            from app.models.personal_genome import PersonalGenome, RiskAssessment
            from sqlalchemy import select

            stmt = (
                select(PersonalGenome)
                .where(PersonalGenome.owner_id == user.id)
                .order_by(PersonalGenome.created_at.desc())
                .limit(1)
            )
            genome = (await self.db.execute(stmt)).scalars().first()
            if not genome:
                return {"has_genome": False, "reason": "no_uploaded_genome"}

            # 3. 加载最近 3 项风险评估
            assess_stmt = (
                select(RiskAssessment)
                .where(RiskAssessment.personal_genome_id == genome.id)
                .order_by(RiskAssessment.created_at.desc())
                .limit(3)
            )
            assessments = (await self.db.execute(assess_stmt)).scalars().all()

            # 4. 从知识图谱读取用户基因型缓存（Mock 内存字典或 Neo4j）
            from app.services.knowledge.graph import get_knowledge_graph
            kg = get_knowledge_graph()
            user_genotypes = kg.get_user_genotypes(str(user.id))

            return {
                "has_genome": True,
                "genome_id": str(genome.id),
                "file_name": genome.file_name,
                "genome_build": genome.genome_build,
                "total_variants": genome.total_variants,
                "latest_assessments": [
                    {
                        "trait_id": str(a.trait_id),
                        "risk_level": a.risk_level,
                        "overall_risk_score": a.overall_risk_score,
                    }
                    for a in assessments
                ],
                "user_genotypes": user_genotypes[:20],  # 限制 token 用量
            }
        except Exception as e:
            logger.warning(f"加载用户基因组上下文失败: {e}")
            return {}

    def _extract_gene(self, message: str) -> Optional[str]:
        """从消息中提取基因名（简单大写词匹配）

        缺口 #9 修复：扩展到 KNOWN_TARGET_GENES 全集（约 200+ 基因），
        覆盖激酶 / 肿瘤抑制因子 / 免疫检查点 / 代谢 / 表观遗传 / DNA 修复 / 细胞周期等。
        """
        known_genes = {
            # === 激酶（Kinases） ===
            "EGFR", "ERBB2", "HER2", "ERBB3", "ERBB4", "KRAS", "NRAS", "HRAS",
            "BRAF", "RAF1", "Araf", "PIK3CA", "PIK3CB", "PIK3CD", "PIK3CG",
            "ALK", "ROS1", "MET", "RET", "FGFR1", "FGFR2", "FGFR3", "FGFR4",
            "FLT3", "FLT1", "KDR", "FLT4", "KIT", "PDGFRA", "PDGFRB",
            "JAK1", "JAK2", "JAK3", "TYK2", "ABL1", "ABL2", "SRC", "YES1",
            "FYN", "LCK", "LYN", "AURKA", "AURKB", "CDK4", "CDK6", "CDK2",
            "CDK1", "CDK5", "CDK7", "CDK9", "CDK12", "MAP2K1", "MAP2K2",
            "MEK1", "MEK2", "MAPK1", "MAPK3", "ERK1", "ERK2", "MTOR",
            "AKT1", "AKT2", "AKT3", "PKB", "RIPK1", "RIPK3", "SIK1", "SIK2",
            # === 肿瘤抑制因子（Tumor Suppressors） ===
            "TP53", "P53", "PTEN", "RB1", "RB", "APC", "BRCA1", "BRCA2",
            "VHL", "WT1", "NF1", "NF2", "STK11", "LKB1", "CDKN2A", "P16",
            "CDKN1A", "P21", "CDKN1B", "P27", "SMAD4", "DPC4", "SMAD2",
            "SMAD3", "TGFBR1", "TGFBR2", "FBXW7", "PPP2R1A",
            # === 免疫检查点（Immune Checkpoints） ===
            "CD274", "PDL1", "PD-L1", "PDCD1", "PD1", "PD-1", "CTLA4",
            "LAG3", "TIM3", "HAVCR2", "TIGIT", "B7H3", "CD276", "B7-H3",
            "VTCN1", "B7-H4", "B7H4", "IDO1", "IDO2", "ICOS", "ICOSLG",
            "CD80", "CD86", "B7-1", "B7-2", "CD40", "CD40LG", "OX40",
            "TNFRSF4", "OX40L", "TNFSF4", "4-1BB", "TNFRSF9", "CD137",
            # === 凋亡与细胞存活（Apoptosis） ===
            "BCL2", "BCL2L1", "BCL-XL", "MCL1", "BCL2L11", "BIM", "BAX",
            "BAK1", "BAK", "CASP3", "CASP8", "CASP9", "CASP7", "FAS",
            "FASLG", "TNFSF10", "TRAIL", "XIAP", "BIRC2", "BIRC3", "BIRC5",
            " survivin", "MDM2", "MDM4", "PUMA", "BBC3", "NOXA", "PMAIP1",
            # === 代谢（Metabolism） ===
            "IDH1", "IDH2", "PKM", "PKM2", "GLS", "GLUL", "LDHA", "LDHB",
            "MCT1", "SLC16A1", "MCT4", "SLC16A3", "HK2", "PFKFB3", "G6PD",
            "ACLY", "FASN", "SCD1", "SREBF1", "SREBP1", "HMGCR", "MVD",
            # === 表观遗传（Epigenetics） ===
            "EZH2", "KMT2D", "MLL2", "KMT2A", "MLL", "DNMT3A", "DNMT3B",
            "DNMT1", "TET2", "TET1", "TET3", "HDAC1", "HDAC2", "HDAC3",
            "HDAC4", "HDAC6", "HDAC8", "SIRT1", "SIRT2", "SIRT3", "KDM1A",
            "LSD1", "KDM5A", "JARID1A", "KDM6A", "UTX", "KDM6B", "JMJD3",
            "BRD4", "BRD2", "BRD3", "BRDT", "SWI/SNF", "ARID1A", "ARID1B",
            "SMARCA4", "BRG1", "SMARCB1", "INI1", "PBRM1",
            # === DNA 修复（DNA Repair） ===
            "ATM", "ATR", "CHEK1", "CHK1", "CHEK2", "CHK2", "PARP1", "PARP2",
            "PARP3", "ERCC1", "ERCC2", "ERCC3", "ERCC4", "XPA", "XPB", "XPC",
            "XPD", "XPF", "XPG", "BRIP1", "BACH1", "PALB2", "RAD51", "RAD51B",
            "RAD51C", "RAD51D", "RAD52", "RAD54L", "NBN", "NBS1", "MRE11",
            "FANCA", "FANCD2", "FANCE", "FANCF", "MLH1", "MSH2", "MSH6",
            "MSH3", "PMS2", "PMS1", "POLE", "POLD1",
            # === 血管生成（Angiogenesis） ===
            "VEGFA", "VEGFB", "VEGFC", "VEGFD", "FIGF", "ANGPT1", "ANGPT2",
            "ANGPTL4", "PDGFA", "PDGFB", "FGF1", "FGF2", "FGF7", "FGF10",
            "HGF", "ANG1", "ANG2", "TIE1", "TEK", "TIE2", "DLL4", "NOTCH1",
            "NOTCH2", "NOTCH3", "JAG1", "JAG2",
            # === 细胞周期（Cell Cycle） ===
            "CCND1", "CYCLIN_D1", "CCND2", "CCND3", "CCNE1", "CYCLIN_E1",
            "CCNE2", "CCNA1", "CCNA2", "CCNB1", "CYCLIN_B1", "CDKN2B", "P15",
            "CDKN2C", "P18", "CDKN2D", "P19", "E2F1", "E2F2", "E2F3",
            # === 药物抵抗（Drug Resistance） ===
            "ABCB1", "MDR1", "ABCC1", "MRP1", "ABCC2", "MRP2", "ABCG2",
            "BCRP", "GSTP1", "NQO1", "CYP3A4", "CYP3A5", "CYP2D6", "TOP1",
            "TOP2A", "TOP2B", "TUBB1", "TUBA1A", "RRM1", "RRM2", "TYMS",
            "TS", "DHFR", "UMP", "UMPS", "UPRT", "DCK",
            # === 其他重要靶点 ===
            "MYC", "MYCN", "MYCL", "REL", "RELA", "NFKB1", "NFKB2", "RELB",
            "IKBKB", "IKBKA", "CHUK", "NFKBIA", "STAT3", "STAT5A", "STAT5B",
            "STAT1", "STAT6", "GATA2", "RUNX1", "AML1", "NPM1", "CEBPA",
            "CEBPB", "KMT2A", "WT1", "ETV6", "TEL", "PDGFRB", "CSF1R",
            "FMS", "FLT3", "AXL", "MER", "MERTK", "TYRO3", "GAS6",
            "WNT1", "WNT2", "WNT3", "WNT3A", "WNT5A", "WNT5B", "WNT7A",
            "WNT7B", "WNT10A", "WNT10B", "WNT11", "WNT16", "FZD1", "FZD2",
            "FZD3", "FZD4", "FZD5", "FZD6", "FZD7", "FZD8", "FZD9", "FZD10",
            "LRP5", "LRP6", "DVL1", "DVL2", "DVL3", "AXIN1", "AXIN2",
            "GSK3B", "CTNNB1", "BETA_CATENIN", "APC", "TCF7L2", "LEF1",
            # === Hedgehog / Notch / 其他信号通路 ===
            "SHH", "IHH", "DHH", "PTCH1", "PTCH2", "SMO", "SMOO", "GLI1",
            "GLI2", "GLI3", "SUFU", "KIF7", "HHIP", "GAS1", "CDON", "BOC",
            # === 其他 ===
            "FAP", "ACTA2", "ALPHA_SMA", "PDGFRB", "COL1A1", "COL1A2",
            "COL3A1", "FN1", "FIBRONECTIN", "TGFBI", "TGFB1", "TGFB2",
            "TGFB3", "IL6", "IL11", "IL1B", "TNF", "TNFA", "CCL2", "MCP1",
            "CCL5", "RANTES", "CXCL10", "CXCL9", "CXCL11", "IFNG", "IFN_GAMMA",
            "IL2", "IL4", "IL5", "IL10", "IL12", "IL17", "IL23", "IL1A",
            # === 肿瘤微环境 ===
            "CA9", "CAIX", "HIF1A", "HIF1", "EPAS1", "HIF2A", "ARNT",
            "VEGFA", "SLC2A1", "GLUT1", "SLC2A3", "GLUT3", "NDRG1", "CXCR4",
            "CCR7", "CD44", "CD24", "ALDH1A1", "EPCAM", "CD133", "PROM1",
            "LGR5", "BMI1", "SOX2", "OCT4", "POU5F1", "KLF4", "NANOG",
        }
        # 去除空格和常见标点后按词分割匹配
        words = set(message.replace(",", " ").replace(".", " ").replace(";", " ").replace("-", "_").split())
        for w in words:
            upper = w.upper().strip("()[]{}\"'")
            if upper in known_genes:
                return upper
        return None

    async def full_analysis(
        self,
        message: str,
        project_id: str,
        tier: str,
        user: User,
    ) -> Dict[str, Any]:
        """完整分析流程 — 复现 Sid 团队做法

        步骤：解析意图 → 调对应 Analyzer → 调 LLM 生成报告 → 生成 Python 代码
        Returns:
            {report, charts, code, references, hypothesis, conclusion}
        """
        start = time.time()
        intent = _detect_intent(message)
        model = self.select_model(tier)

        # 根据意图调用对应分析器
        analysis_data: Dict[str, Any] = {}
        try:
            if intent == "target_discovery":
                from app.services.analyzer.target_identifier import TargetIdentifier
                identifier = TargetIdentifier(self.db)
                analysis_data = await identifier.discover(
                    project_id=UUID(project_id),
                    tier=tier,
                )
            elif intent == "drug_repurposing":
                from app.services.analyzer.target_identifier import TargetIdentifier
                from app.services.analyzer.drug_repurposer import DrugRepurposer
                # 先发现靶点，再对首个靶点做老药新用
                identifier = TargetIdentifier(self.db)
                discover_result = await identifier.discover(project_id=UUID(project_id), tier=tier)
                targets = discover_result.get("targets", [])
                if targets:
                    from app.models.target import Target
                    target = await self.db.get(Target, UUID(targets[0].get("id"))) if targets[0].get("id") else None
                    if target:
                        repurposer = DrugRepurposer(self.db)
                        analysis_data = await repurposer.repurpose(target)
                    else:
                        analysis_data = discover_result
                else:
                    analysis_data = discover_result
            else:
                # 通用分析 — 直接用靶点发现
                from app.services.analyzer.target_identifier import TargetIdentifier
                identifier = TargetIdentifier(self.db)
                analysis_data = await identifier.discover(project_id=UUID(project_id), tier=tier)
        except Exception as e:
            logger.warning(f"分析器调用失败，降级为纯 LLM: {e}")
            analysis_data = {"error": str(e), "intent": intent}

        # 调 LLM 生成结构化报告
        report_prompt = self._build_report_prompt(message, intent, analysis_data)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS["deep_insight"]},
            {"role": "user", "content": report_prompt},
        ]
        response = await self.llm_client.chat(messages, model=model)
        report_text = response.get("content", "")

        # 生成 Python 分析代码
        code = self._generate_analysis_code(intent, analysis_data)

        # 构建图表数据
        charts = self._build_charts(analysis_data)

        # 提取结论
        conclusion = self._extract_conclusion(report_text, analysis_data)

        # 构建假设
        hypothesis = self._build_hypothesis(intent, message, analysis_data)

        duration_sec = round(time.time() - start, 3)

        # 记录 AnalysisJob
        try:
            job = AnalysisJob(
                project_id=UUID(project_id),
                job_type=f"full_analysis_{intent}",
                tier=tier,
                status=JobStatus.COMPLETED,
                input_params={"message": message[:500], "intent": intent},
                result={"conclusion": conclusion[:500]},
                cost_usd=_estimate_cost(response.get("usage"), tier, model),
                duration_sec=int(duration_sec),
                model_used=model,
                token_count=(response.get("usage") or {}).get("prompt_tokens", 0)
                + (response.get("usage") or {}).get("completion_tokens", 0),
                triggered_by=user.id,
            )
            self.db.add(job)
            await self.db.flush()
        except Exception as e:
            logger.warning(f"记录 AnalysisJob 失败: {e}")
            await self.db.rollback()

        return {
            "report": report_text,
            "charts": charts,
            "code": code,
            "references": response.get("references", []),
            "hypothesis": hypothesis,
            "conclusion": conclusion,
            "intent": intent,
            "analysis_data": analysis_data,
            "duration_sec": duration_sec,
        }

    def _build_report_prompt(self, message: str, intent: str, analysis_data: Dict) -> str:
        """构建报告生成 prompt"""
        import json
        data_str = json.dumps(analysis_data, ensure_ascii=False, default=str, indent=2)[:3000]
        return (
            f"## 用户请求\n{message}\n\n"
            f"## 识别意图\n{intent}\n\n"
            f"## 分析结果数据\n{data_str}\n\n"
            "请基于以上分析结果生成一份结构化报告，包含：\n"
            "1. **摘要**（一句话结论）\n"
            "2. **分析方法**（使用了哪些数据源和工具）\n"
            "3. **关键发现**（靶点/药物/变异等）\n"
            "4. **证据评估**（证据等级与置信度）\n"
            "5. **推荐方案**（含具体药物和剂量建议）\n"
            "6. **局限性**（数据缺口与不确定性）\n"
        )

    def _generate_analysis_code(self, intent: str, analysis_data: Dict) -> str:
        """生成 Python 分析代码模板"""
        if intent == "target_discovery":
            targets = analysis_data.get("targets", [])
            gene_list = [t.get("gene_symbol", "?") for t in targets[:10]]
            return (
                f"# 靶点发现分析代码\n"
                f"import pandas as pd\n"
                f"import matplotlib.pyplot as plt\n\n"
                f"# 候选靶点\n"
                f"targets = {gene_list}\n"
                f"df = pd.DataFrame({analysis_data!r}.get('targets', []))\n\n"
                f"# 按置信度排序\n"
                f"if 'confidence_score' in df.columns:\n"
                f"    df = df.sort_values('confidence_score', ascending=False)\n\n"
                f"# 绘制置信度条形图\n"
                f"fig, ax = plt.subplots(figsize=(10, 6))\n"
                f"ax.barh(df['gene_symbol'][:10], df['confidence_score'][:10])\n"
                f"ax.set_xlabel('Confidence Score')\n"
                f"ax.set_title('Top 10 Candidate Targets')\n"
                f"plt.tight_layout()\n"
                f"plt.savefig('targets_confidence.png', dpi=150)\n"
                f"print(df[['gene_symbol', 'evidence_grade', 'confidence_score']].head(10))\n"
            )
        elif intent == "drug_repurposing":
            return (
                "# 老药新用分析代码\n"
                "import pandas as pd\n\n"
                "# 候选药物数据\n"
                "candidates = analysis_data.get('candidates', [])\n"
                "df = pd.DataFrame(candidates)\n"
                "print(df[['name', 'chembl_id', 'max_phase', 'druglikeness_score']])\n"
                "df.to_csv('repurposing_candidates.csv', index=False)\n"
            )
        return (
            "# 通用分析代码\n"
            "import pandas as pd\n"
            "import json\n\n"
            "data = json.loads(open('analysis_result.json').read())\n"
            "print(json.dumps(data, indent=2, ensure_ascii=False))\n"
        )

    def _build_charts(self, analysis_data: Dict) -> List[Dict]:
        """构建图表数据（供前端 Plotly 渲染）"""
        charts = []
        targets = analysis_data.get("targets", [])
        if targets:
            charts.append({
                "type": "bar",
                "title": "靶点置信度排序",
                "x": [t.get("gene_symbol", "?") for t in targets[:10]],
                "y": [t.get("confidence_score", 0) for t in targets[:10]],
                "x_label": "基因",
                "y_label": "置信度",
            })
            # 证据等级分布
            grades = [t.get("evidence_grade", "IV") for t in targets]
            grade_counts = {g: grades.count(g) for g in set(grades)}
            charts.append({
                "type": "pie",
                "title": "证据等级分布",
                "labels": list(grade_counts.keys()),
                "values": list(grade_counts.values()),
            })
        candidates = analysis_data.get("candidates", [])
        if candidates:
            charts.append({
                "type": "bar",
                "title": "老药新用候选评分",
                "x": [c.get("name", "?") for c in candidates[:10]],
                "y": [c.get("druglikeness_score", 0) for c in candidates[:10]],
                "x_label": "药物",
                "y_label": "类药性评分",
            })
        return charts

    def _extract_conclusion(self, report_text: str, analysis_data: Dict) -> str:
        """从报告和分析数据中提取结论"""
        targets = analysis_data.get("targets", [])
        if targets:
            top = targets[0]
            return (
                f"首选靶点：{top.get('gene_symbol', '?')} "
                f"（证据等级 {top.get('evidence_grade', '?')}，"
                f"置信度 {(top.get('confidence_score') or 0):.2f}）"
            )
        candidates = analysis_data.get("candidates", [])
        if candidates:
            top = candidates[0]
            return f"首选老药新用候选：{top.get('name', '?')}（max_phase={top.get('max_phase', '?')}）"
        # 从报告文本提取首句
        first_line = report_text.split("\n")[0] if report_text else "分析完成"
        return first_line[:200]

    def _build_hypothesis(self, intent: str, message: str, analysis_data: Dict) -> str:
        """构建假设描述"""
        targets = analysis_data.get("targets", [])
        gene_str = ", ".join(t.get("gene_symbol", "?") for t in targets[:5]) if targets else "未知"
        return (
            f"基于用户请求「{message[:50]}」，识别意图为「{intent}」。"
            f"候选靶点：{gene_str}。"
            f"建议进一步验证 top 候选靶点的体外/体内活性。"
        )
