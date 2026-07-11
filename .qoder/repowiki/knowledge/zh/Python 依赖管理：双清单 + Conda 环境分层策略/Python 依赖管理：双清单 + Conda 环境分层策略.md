---
kind: dependency_management
name: Python 依赖管理：双清单 + Conda 环境分层策略
category: dependency_management
scope:
    - '**'
source_files:
    - precision-drug-design/environment.yml
    - precision-drug-design/backend/requirements.txt
    - precision-drug-design/backend/requirements-stage1.txt
    - precision-drug-design/frontend/requirements.txt
    - precision-drug-design/pyproject.toml
---

## 1. 使用的系统与工具
- **conda (environment.yml)**：作为主依赖声明文件，集中定义 Python 版本、系统级库（RDKit、OpenJDK、Node.js、Graphviz）以及 bioconda/conda-forge 渠道。
- **pip requirements.txt**：与 conda 并列的纯 pip 依赖清单，用于 `pip install -r backend/requirements.txt` 场景，同时记录精确/宽松版本约束。
- **pyproject.toml**：承载项目元数据、Ruff 代码风格、Mypy 类型检查、Pytest 运行参数与覆盖率阈值等“构建期”配置。
- **requirements-stage1.txt**：第一阶段 P0 最小可运行子集，便于快速启动核心闭环。
- **frontend/requirements.txt**：Streamlit 前端独立的最小依赖集。
- **无 lockfile / vendor 目录**：仓库未提交 `requirements.lock.txt`、`poetry.lock` 或 `uv.lock`，也未使用 vendoring；注释中提示可通过 `pip freeze > requirements.lock.txt` 手动生成。

## 2. 关键文件与位置
- `precision-drug-design/environment.yml` — 全量依赖与环境定义（conda + pip 混合）
- `precision-drug-design/backend/requirements.txt` — 后端完整 pip 依赖清单（三阶段合并）
- `precision-drug-design/backend/requirements-stage1.txt` — P0 最小依赖子集
- `precision-drug-design/frontend/requirements.txt` — Streamlit 前端依赖
- `precision-drug-design/pyproject.toml` — 项目元数据 + Ruff/Mypy/Pytest/Coverage 配置

## 3. 架构与约定
- **分层依赖**：按研发阶段划分
  - P0（基础闭环）：Web 框架、数据库、向量检索、LLM 客户端、可视化、测试工具。
  - P2（深度学习）：torch、torch-geometric、deepchem。
  - P3（联邦学习/隐私计算）：flwr、syft、opacus。
- **conda 优先安装含 C 扩展的库**：RDKit、cyvcf2、pysam、scanpy 等通过 conda/bioconda 安装，避免本地编译失败；其余纯 Python 包走 pip。
- **版本约束风格**：requirements.txt 对核心库采用 `==` 锁定（如 `scanpy==1.12.1`），对生态库采用 `>=X.Y.*` 宽松范围；environment.yml 统一用 `=X.Y.*` 限定小版本区间。
- **多入口隔离**：backend 与 frontend 各自维护独立的 requirements.txt，避免前端引入不必要的后端重型依赖。
- **无私有源/镜像**：channels 仅包含 `conda-forge`、`bioconda`、`defaults`，未见 `.condarc` 或自定义 PyPI index 配置。

## 4. 开发者应遵循的规则
- **新增依赖时同步更新两份清单**：在 `environment.yml` 的 `dependencies.pip:` 段添加条目，并在 `backend/requirements.txt` 对应位置追加相同约束，保持两者一致。
- **严格区分阶段**：P0/P2/P3 依赖分别归入 environment.yml 的对应注释块与 requirements.txt 的分节，避免误装重型库影响开发体验。
- **不要提交 lockfile**：当前策略不追踪锁文件，如需复现固定版本，请在 CI 或部署脚本中执行 `pip freeze > requirements.lock.txt` 并纳入容器镜像。
- **C 扩展库一律走 conda**：涉及 RDKit、BioPython、Scanpy 等含 native 组件的包，不要在 pip 层重新声明，以免破坏 conda 预编译轮子优势。
- **前端只保留必要依赖**：`frontend/requirements.txt` 应保持极简，仅放 Streamlit 及 HTTP 客户端，避免把后端科学栈带入前端环境。