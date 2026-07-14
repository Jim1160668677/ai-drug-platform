# ========== Hugging Face Spaces 专用 Dockerfile ==========
# HF Spaces 强制要求：
#   1. 端口固定为 7860
#   2. 非 root 用户运行
#   3. Dockerfile 必须在仓库根目录
#
# 此 Dockerfile 直接复用 backend/ 子目录的代码与依赖，
# 通过多阶段优化避免重复内容，并适配 HF Spaces 的安全约束。
# ========================================================

FROM python:3.11-slim

# ========== 环境变量 ==========
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# ========== 系统依赖（生物信息库需要） ==========
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        zlib1g-dev \
        libgomp1 \
        libgl1-mesa-glx \
        libxrender1 \
        libxext6 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ========== 创建非 root 用户（HF Spaces 强制要求） ==========
RUN useradd -m -u 1000 user

WORKDIR /app

# ========== 复制后端依赖文件并安装 ==========
COPY --chown=user:user backend/requirements.txt ./
RUN pip install --upgrade pip && pip install --r requirements.txt

# ========== 复制后端代码 ==========
COPY --chown=user:user backend/ ./

# ========== 应用配置（mock 模式，免外部数据库） ==========
ENV APP_ENV=development \
    USE_MOCK=true \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=7860 \
    CORS_ORIGINS="*" \
    LOG_LEVEL=INFO \
    GUARDRAIL_ENABLED=true \
    ENVELOPE_MIDDLEWARE_ENABLED=true

# 切换非 root 用户
USER user

# HF Spaces 端口
EXPOSE 7860

# 启动后端
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
