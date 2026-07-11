"""API v1 路由聚合"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth, projects, data, targets, molecules, treatments,
    hypotheses, experiments, workflows, reports,
    knowledge, chat, audit, dashboard, llm_config, users,
    feedback, federated, privacy, efficacy, ws,
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

# P1.3 新增端点
api_router.include_router(feedback.router, prefix="/feedback", tags=["反馈协作"])
api_router.include_router(federated.router, prefix="/federated", tags=["联邦学习"])
api_router.include_router(privacy.router, prefix="/privacy", tags=["隐私计算"])
api_router.include_router(efficacy.router, prefix="/efficacy", tags=["疗效监测"])
api_router.include_router(ws.router, prefix="", tags=["WebSocket"])

# 路径别名 — 旧前端兼容（保留 1 版本周期，include_in_schema=False 避免文档重复）
api_router.include_router(data.router, prefix="/datasets", tags=["数据接入"], include_in_schema=False)
