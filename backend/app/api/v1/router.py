"""API v1 路由聚合"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth, projects, data, targets, molecules, treatments,
    hypotheses, experiments, workflows, reports,
    knowledge, chat, audit, dashboard, llm_config, users, user_llm,
    feedback, federated, privacy, efficacy, ws,
    pipeline, lineage, consent,
    agent, sandbox, genome,
    organizations,
    translations,
    validations,
    # 计算引擎与合成模块
    structures, docking, cells, screening, benchmarks, synthesis,
    # 模型切换监控
    model_switch,
    # Co-Scientist 多智能体科学推理
    coscientist,
    coscientist_insights,
    # 统一智能系统（融合 AI 问答/科学推理/Agent/多模态/规则引擎）
    intelligence,
)

api_router = APIRouter()

# 挂载各模块路由
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(projects.router, prefix="/projects", tags=["项目管理"])
api_router.include_router(data.router, prefix="/data", tags=["数据接入"])
api_router.include_router(targets.router, prefix="/targets", tags=["靶点发现"])
api_router.include_router(molecules.router, prefix="/molecules", tags=["分子设计"])
api_router.include_router(treatments.router, prefix="/treatments", tags=["治疗方案"])
api_router.include_router(hypotheses.router, prefix="/hypotheses", tags=["多假设并行"])
api_router.include_router(experiments.router, prefix="/experiments", tags=["干湿闭环"])
api_router.include_router(workflows.router, prefix="/workflows", tags=["工作流"])
api_router.include_router(reports.router, prefix="/reports", tags=["报告导出"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["知识库"])
api_router.include_router(chat.router, prefix="/chat", tags=["自然语言问答"])
api_router.include_router(audit.router, prefix="/audit", tags=["审计日志"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["全局看板"])
api_router.include_router(llm_config.router, prefix="/llm-configs", tags=["LLM 配置"])
api_router.include_router(users.router, prefix="/users", tags=["用户管理"])
api_router.include_router(user_llm.router, prefix="/users/me/llm-configs", tags=["用户 LLM 配置"])
api_router.include_router(genome.router, prefix="/genome", tags=["个人基因组解读"])

# P1.3 新增端点
api_router.include_router(feedback.router, prefix="/feedback", tags=["反馈协作"])
api_router.include_router(federated.router, prefix="/federated", tags=["联邦学习"])
api_router.include_router(privacy.router, prefix="/privacy", tags=["隐私计算"])
api_router.include_router(efficacy.router, prefix="/efficacy", tags=["疗效监测"])
api_router.include_router(ws.router, prefix="", tags=["WebSocket"])

# 端到端流水线
api_router.include_router(pipeline.router, prefix="/pipeline", tags=["端到端流水线"])

# 数据血缘
api_router.include_router(lineage.router, prefix="/lineage", tags=["数据血缘"])

# 知情同意
api_router.include_router(consent.router, prefix="/consent", tags=["知情同意"])

# Agent 工作台（ReAct 引擎 + 工具调用 + WS 推送）
api_router.include_router(agent.router, prefix="/agent", tags=["Agent"])
api_router.include_router(sandbox.router, prefix="/sandbox", tags=["代码沙箱"])

# 机构与职能维度
api_router.include_router(organizations.router, prefix="/organizations", tags=["机构与职能"])

# 合作方与转化路径
api_router.include_router(translations.router, prefix="/translations", tags=["合作方与转化路径"])

# 干湿闭环验证
api_router.include_router(validations.router, prefix="/validations", tags=["干湿闭环验证"])

# 计算引擎与合成模块（新闻洞察与混合架构）
api_router.include_router(structures.router, prefix="/structures", tags=["蛋白结构"])
api_router.include_router(docking.router, prefix="/docking", tags=["分子对接"])
api_router.include_router(cells.router, prefix="/cells", tags=["单细胞分析"])
api_router.include_router(screening.router, prefix="/screening", tags=["双上下文筛选"])
api_router.include_router(benchmarks.router, prefix="/benchmarks", tags=["基准评测"])
api_router.include_router(synthesis.router, prefix="/synthesis", tags=["合成规划"])

# 模型切换监控（智谱 GLM 降级链路）
api_router.include_router(model_switch.router, prefix="/model-switch", tags=["模型切换监控"])

# Co-Scientist 多智能体科学推理引擎
api_router.include_router(coscientist.router, prefix="/coscientist", tags=["Co-Scientist"])
# Co-Scientist 洞察管理（嵌入式协作层）— 与 coscientist 共用前缀
api_router.include_router(coscientist_insights.router, prefix="/coscientist", tags=["Co-Scientist"])

# 统一智能系统（融合 AI 问答 / 科学推理 / Agent / 多模态 / 规则引擎，22 端点）
api_router.include_router(intelligence.router, prefix="/intelligence", tags=["统一智能系统"])

# 路径别名 — 旧前端兼容（保留 1 版本周期，include_in_schema=False 避免文档重复）
api_router.include_router(data.router, prefix="/datasets", tags=["数据接入"], include_in_schema=False)
