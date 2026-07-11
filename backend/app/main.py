"""AI模式精准药物设计系统 — FastAPI 主应用入口

设计来源：repowiki/zh/content/API参考文档/API概览与规范.md
           repowiki/zh/content/系统架构/后端架构设计/FastAPI应用工厂.md
"""
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.limiter import limiter
from app.core.logging import setup_logging
from app.core.middleware import EnvelopeMiddleware
from app.schemas.common import ApiResponse, ResponseMeta, success_response


def _rate_limit_envelope_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """将 slowapi 的 429 响应包装为统一信封格式"""
    retry_after = getattr(exc, "retry_after", None)
    headers = {}
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        status_code=429,
        headers=headers,
        content={
            "success": False,
            "message": "请求过多，请稍后重试",
            "data": None,
            "error": {
                "code": "RATE_LIMITED",
                "detail": str(exc.detail),
            },
            "meta": {"request_id": getattr(request.state, "request_id", "")},
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动与关闭"""
    setup_logging()
    logger.info("=" * 60)
    logger.info("AI模式精准药物设计系统 启动中...")
    logger.info(f"  环境: {settings.APP_ENV}")
    logger.info(f"  Mock 模式: {settings.USE_MOCK}")
    logger.info(f"  数据库: {settings.DATABASE_URL.split('@')[-1]}")
    logger.info(f"  信封中间件: {'启用' if settings.ENVELOPE_MIDDLEWARE_ENABLED else '禁用'}")
    logger.info(f"  LLM 每日预算: ${settings.LLM_DAILY_BUDGET_USD}")
    logger.info(f"  安全护栏: {'启用' if settings.GUARDRAIL_ENABLED else '禁用'}")
    logger.info("=" * 60)

    # 启动时初始化数据库表（如果 alembic 未执行）
    if settings.APP_ENV == "development":
        try:
            from app.db.session import init_db
            await init_db()
            logger.info("数据库表已就绪")
        except Exception as e:
            logger.warning(f"数据库初始化跳过（可能未连接）: {e}")

    yield

    logger.info("系统关闭")


app = FastAPI(
    title="AI模式精准药物设计系统",
    description=(
        "AI Mode Driven Precision Drug Design System\n\n"
        "干湿闭环 | 多假设并行 | 老药新用 | CDISC 标准 | 分级分析 | 11 开源工具集成\n\n"
        "灵感来源于 GitLab 联合创始人 Sid Sijbrandij 的个性化癌症治疗经历。"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "系统", "description": "健康检查、监控指标"},
        {"name": "认证", "description": "用户登录、注册、Token 管理"},
        {"name": "用户管理", "description": "用户 CRUD、角色权限"},
        {"name": "项目管理", "description": "患者/研究项目 CRUD"},
        {"name": "数据集", "description": "数据上传、解析、质控"},
        {"name": "靶点发现", "description": "靶点识别、深度分析、网络分析"},
        {"name": "分子设计", "description": "分子生成、类药性、对接、ADMET"},
        {"name": "假设管理", "description": "科学假设 CRUD、分析、合并、淘汰"},
        {"name": "实验追踪", "description": "干湿闭环实验记录"},
        {"name": "治疗方案", "description": "方案优化、疗效监测"},
        {"name": "AI 问答", "description": "分级 LLM 问答、RAG"},
        {"name": "报告", "description": "CDISC SDTM/ADaM 导出"},
        {"name": "工作流", "description": "Nextflow 流水线"},
        {"name": "知识库", "description": "MyGene/MyVariant/ChEMBL/ClinicalTrials"},
        {"name": "联邦学习", "description": "PharmaFedAvg 多机构协同"},
        {"name": "隐私计算", "description": "PySyft 域、差分隐私、数据脱敏"},
        {"name": "疗效监测", "description": "Kaplan-Meier、不良事件"},
        {"name": "反馈协作", "description": "用户反馈、问题跟踪"},
        {"name": "审计日志", "description": "操作审计、合规追踪"},
        {"name": "LLM 配置", "description": "大模型配置管理"},
    ],
)

# ========== slowapi 限流器状态 ==========
# 必须在注册 SlowAPIMiddleware 之前把 limiter 挂到 app.state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_envelope_handler)

# ========== 中间件 ==========
# CORS — 跨域资源共享（显式白名单，避免通配符带来的 CSRF 风险）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "Accept", "X-Requested-With"],
    expose_headers=["X-Request-ID", "X-Response-Time-ms"],
)

# 统一信封中间件 — 注入 X-Request-ID / X-Response-Time-ms / meta.duration_ms
# 必须在 SlowAPIMiddleware 内部，否则 BaseHTTPMiddleware 的 body 分块会破坏信封注入
if settings.ENVELOPE_MIDDLEWARE_ENABLED:
    app.add_middleware(EnvelopeMiddleware, max_body_size=settings.ENVELOPE_MAX_BODY_SIZE)

# slowapi 限流中间件 — 最外层，拦截被 @limiter.limit 装饰的端点
app.add_middleware(SlowAPIMiddleware)

# ========== 异常处理器 ==========
register_exception_handlers(app)


# ========== 系统端点 ==========
@app.get("/health", tags=["系统"])
async def health_check():
    """健康检查端点（无信封 — 供 K8s/监控直接消费）"""
    return {
        "status": "healthy",
        "app": "precision-drug-design",
        "version": "1.0.0",
        "mock_mode": settings.USE_MOCK,
        "env": settings.APP_ENV,
    }


@app.get("/", tags=["系统"])
async def root():
    """根路径"""
    return {
        "name": "AI模式精准药物设计系统",
        "docs": "/docs",
        "health": "/health",
    }


# ========== API v1 路由 ==========
# 系统级端点（信封格式）— 从 endpoints.system 导入，路径无 system 前缀（D1）
# GET /api/v1/health  — 信封格式健康检查
# GET /api/v1/metrics — Prometheus 文本格式监控指标
try:
    from app.api.v1.endpoints.system import router as system_router
    app.include_router(system_router, prefix="/api/v1")
    logger.info("系统路由已挂载 (/api/v1/health, /api/v1/metrics)")
except ImportError as e:
    logger.warning(f"系统路由未加载: {e}")


# 挂载业务 API v1 路由
try:
    from app.api.v1.router import api_router
    app.include_router(api_router, prefix="/api/v1")
    logger.info("API v1 路由已挂载")
except ImportError as e:
    logger.warning(f"API 路由未完全加载: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=settings.APP_ENV == "development",
    )
