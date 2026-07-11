---
kind: build_system
name: Python 依赖与质量工具链（Conda + pip + Ruff + MyPy + Pytest）
category: build_system
scope:
    - '**'
source_files:
    - precision-drug-design/environment.yml
    - precision-drug-design/backend/requirements.txt
    - precision-drug-design/frontend/requirements.txt
    - precision-drug-design/pyproject.toml
    - precision-drug-design/scripts/setup_env.ps1
    - precision-drug-design/.env.example
---

## 构建系统概览
本项目采用「双清单 + 单入口」的 Python 构建策略：以 `environment.yml`（Conda）作为权威环境定义，`backend/requirements.txt` 作为 pip 镜像清单，配合 `pyproject.toml` 集中管理代码质量、测试与覆盖率规则。无 Makefile / Dockerfile / CI 流水线，本地开发通过 PowerShell 脚本一键初始化。

## 关键文件与职责
- `precision-drug-design/environment.yml` — Conda 环境声明，按 conda-forge / bioconda / defaults 三通道安装 Python 3.11、RDKit、OpenJDK 17、Node.js 20、Nextflow 等系统级依赖，并在 pip 子段中分阶段（P0/P2/P3）列出纯 Python 包。
- `precision-drug-design/backend/requirements.txt` — 与 environment.yml 平行的 pip 清单，用于非 Conda 场景或容器内二次安装；注释标注了 C 扩展库建议走 conda 安装。
- `precision-drug-design/frontend/requirements.txt` — Streamlit 前端最小依赖集（streamlit、httpx）。
- `precision-drug-design/pyproject.toml` — 统一配置 Ruff（lint/format）、MyPy（类型检查）、Pytest（测试路径、标记、异步模式）、Coverage（源目录、排除规则、HTML 报告）。
- `scripts/setup_env.ps1` — Windows 一键环境安装器：检测 conda/pip 两种模式、创建 `pdd-system` 环境、按需安装阶段依赖、复制 `.env.example` 为 `.env`、预建 data/logs/models 目录。
- `.env.example` / `.env` — 环境变量模板，涵盖数据库、Redis、S3、LLM 密钥、CORS、联邦学习、CDISC 等全部运行时参数。

## 架构与约定
- **Python 版本锁定**：全局要求 `>=3.11`，Conda 固定 `3.11.*`，理由见 environment.yml 注释（Scanpy/DeepChem/PyTorch 对 3.11 支持最完善）。
- **依赖分层**：
  - 系统级（Rust/C++ 扩展）：RDKit、cyvcf2、pysam、OpenJDK → 强制走 conda。
  - Web/数据科学核心：FastAPI、Uvicorn、Pydantic、NumPy、Pandas、SciPy、Scikit-learn → 双清单同步。
  - 阶段可选：P2（torch/geometric/deepchem）、P3（flwr/syft/opacus）在 environment.yml 中以注释分组，pip 清单中保留但可跳过安装。
- **质量门禁**：
  - Ruff：行宽 100、启用 E/W/F/I/B/C4/UP/N/SIM 规则集，针对 tests/*、frontend/pages/*、scripts/* 放宽 import 顺序与命名约束。
  - MyPy：strict=false，逐步收紧 `disallow_untyped_defs`，忽略缺失 stub 的第三方导入。
  - Pytest：自动发现 `tests/test_*.py`，开启 `--cov=backend/app --cov-fail-under=75`，支持 `slow/integration/gpu` 标记。
  - Coverage：仅统计 `services/core/utils`，排除 api/models/schemas/main.py 等薄封装层。
- **运行方式**：后端 `uvicorn backend.app.main:app --reload`，前端 `streamlit run frontend/streamlit_app/app.py`，由 setup_env.ps1 输出最终命令。
- **容器化现状**：README 与 docs 中包含 docker build/run 示例片段，但仓库未提供独立 Dockerfile/docker-compose.yml，属于文档占位而非实际构建产物。

## 开发者应遵循的规则
1. 新增依赖优先写入 `environment.yml`，再同步到 `backend/requirements.txt`，保持两者一致。
2. 含 C 扩展的库（RDKit、cyvcf2、pysam、torch 等）必须通过 conda 安装，避免 pip 编译失败。
3. 修改代码后执行 `ruff check . && ruff format . && mypy backend/app`，确保不触发 pyproject.toml 中的规则。
4. 编写测试时按 `tests/test_<module>.py` 命名，使用 `@pytest.mark.slow` / `integration` / `gpu` 标记分类，覆盖率需维持 ≥75%。
5. 新增环境变量需在 `.env.example` 中补充说明，并更新 `setup_env.ps1` 的目录/步骤（如适用）。
6. 不要提交 `.env`、`data/`、`logs/`、`models/`、`.venv/`、`htmlcov/` 等生成物（已在 `.gitignore` 中排除）。