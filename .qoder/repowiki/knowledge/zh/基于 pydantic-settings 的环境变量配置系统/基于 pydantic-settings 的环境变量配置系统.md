---
kind: configuration_system
name: 基于 pydantic-settings 的环境变量配置系统
category: configuration_system
scope:
    - '**'
source_files:
    - backend/app/core/config.py
    - .env.example
    - .streamlit/config.toml
    - pyproject.toml
    - environment.yml
    - backend/app/main.py
---

## 1. 采用的系统与工具

- **核心框架**：`pydantic-settings.BaseSettings`，通过声明式字段定义 + 类型校验完成配置加载。
- **配置文件来源（优先级从高到低）**：
  1. 真实环境变量（操作系统 / 容器注入）
  2. `.env` 文件（项目根目录）
  3. 代码中定义的默认值
- **Streamlit 前端配置**：`.streamlit/config.toml`，使用 Streamlit 原生 TOML 配置。
- **依赖与环境**：`environment.yml`（conda 环境）、`pyproject.toml`（Ruff/Mypy/Pytest/Coverage 等工具链配置）。

## 2. 关键文件与包

| 文件 | 作用 |
|---|---|
| `backend/app/core/config.py` | 全局 Settings 模型、字段定义、验证器、`get_settings()` 单例工厂 |
| `.env.example` | 完整环境变量模板，按模块分组注释 |
| `.env` | 本地实际运行时的环境变量（被 .gitignore 排除） |
| `.streamlit/config.toml` | Streamlit 主题、端口、CORS 等运行时配置 |
| `pyproject.toml` | Ruff、Mypy、Pytest、Coverage 等开发期工具配置 |
| `environment.yml` | conda 环境描述（Python 版本、系统依赖、pip 子依赖） |
| `backend/app/main.py` | FastAPI 应用入口，从 `get_settings()` 读取 app_name/version/CORS 等 |
| `frontend/app.py` | Streamlit 主入口，通过硬编码端口 8501 与后端交互（未直接读 .env） |

## 3. 架构与设计约定

### 3.1 统一 Settings 模型

- 所有配置项以 `class Settings(BaseSettings)` 的字段形式集中声明，字段名与 `.env` 中的大写键一一对应（大小写不敏感）。
- 每个字段提供合理的默认值，使系统在无外部配置时也能启动（development 友好）。
- 使用 `@field_validator` 对复合字段做清洗（如 `cors_origins` 去除空白），并通过 `@property` 暴露派生值（`cors_origin_list`、`is_production`）。
- `model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")` 控制加载行为。

### 3.2 单例缓存

- `get_settings()` 使用 `@lru_cache` 包装，保证进程内只创建一次 Settings 实例，避免重复解析 `.env`。
- 测试中可通过 `get_settings.cache_clear()` 重置，配合不同的 `.env` 或环境变量进行隔离。

### 3.3 配置分层与用途

| 层次 | 内容 | 示例 |
|---|---|---|
| 应用元信息 | 名称、版本、环境、调试开关、监听地址/端口 | `APP_NAME`, `APP_ENV`, `APP_DEBUG`, `APP_HOST`, `APP_PORT` |
| 基础设施 | 数据库 URL、Redis、MinIO/S3、Chroma 向量库 | `DATABASE_URL`, `REDIS_URL`, `S3_*`, `CHROMA_PERSIST_DIR` |
| AI/LLM | OpenAI/Anthropic/NVIDIA NIM 密钥与模型路由 | `OPENAI_API_KEY`, `LLM_DEFAULT_MODEL`, `NIM_*` |
| 外部知识库 | MyGene/MyVariant/ChEMBL/PubMed/ClinicalTrials 基址 | `MYGENE_BASE_URL`, `CHEMBL_BASE_URL`, … |
| 安全与认证 | JWT 密钥、算法、过期时间；CORS 白名单 | `JWT_SECRET_KEY`, `CORS_ORIGINS` |
| 高级特性 | 联邦学习 Flower、PySyft 域、CDISC 输出路径、干湿闭环 LIMS | `FLOWER_SERVER_ADDRESS`, `PYSYFT_DOMAIN_PORT`, `CDISC_SDTM_OUTPUT_DIR`, `LIMS_API_URL` |
| 数据处理 | Scanpy/Dask 并行度、数据目录 | `SCANPY_N_JOBS`, `DASK_DASHBOARD_ADDRESS`, `DATA_RAW_DIR` |

### 3.4 前端配置

- Streamlit 前端通过 `.streamlit/config.toml` 独立配置主题色、端口（8501）、headless 模式等，与后端配置解耦。
- 前端页面通过硬编码 `http://localhost:8501` 访问后端 API，未复用后端的 CORS 配置。

### 3.5 开发期工具配置

- `pyproject.toml` 集中管理 Ruff（lint/format）、Mypy、Pytest、Coverage 的行为，包括 per-file ignores、markers、覆盖率阈值等。
- `environment.yml` 同时声明 Python 版本约束（3.11）和第三方库版本范围，作为环境复现的单一事实来源。

## 4. 开发者应遵循的规则

1. **新增配置项必须三处同步更新**
   - 在 `backend/app/core/config.py` 的 `Settings` 类中添加字段（含默认值与可选 validator）。
   - 在 `.env.example` 中添加对应的大写环境变量条目及注释说明。
   - 如需影响前端，检查是否有对应的 Streamlit 配置或硬编码需要调整。

2. **不要绕过 `get_settings()`**
   - 所有模块通过 `from backend.app.core.config import get_settings` 获取配置，禁止直接使用 `os.getenv` 散落在业务代码中。

3. **敏感信息永远不进仓库**
   - `.env` 已在 `.gitignore` 中排除；部署时通过 CI/CD 注入环境变量或使用 secrets 管理器。
   - 仅提交 `.env.example` 作为模板。

4. **保持字段命名一致**
   - Settings 字段名（snake_case）与 `.env` 键名（SCREAMING_SNAKE_CASE）自动映射，修改字段名时需同步更新 `.env.example`。

5. **为复合字段提供 validator/property**
   - 如 `cors_origins` → `cors_origin_list` 的模式，将字符串解析逻辑集中在配置层，避免在各处重复处理。

6. **生产环境切换**
   - 通过设置 `APP_ENV=production` 触发 `settings.is_production` 分支，确保日志级别、调试开关等安全策略生效。

7. **测试隔离**
   - 使用 `get_settings.cache_clear()` 重置配置单例，结合 pytest fixture 注入不同 `.env` 或环境变量，避免测试间污染。
