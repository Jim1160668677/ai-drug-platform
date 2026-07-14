---
title: AI 精准药物设计系统
emoji: 💊
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: 干湿闭环、多假设并行、老药新用的 AI 精准药物设计平台
---

<!-- 注意：以上 YAML front matter 仅供 Hugging Face Spaces 识别 Space 元数据。
     GitHub 上展示本 README 时可忽略此 YAML 块。 -->

# AI模式精准药物设计系统

> AI Mode Driven Precision Drug Design System  
> 干湿闭环 | 多假设并行 | 老药新用 | CDISC 标准 | 分级分析 | 11 开源工具集成

灵感来源于 GitLab 联合创始人 Sid Sijbrandij 的个性化癌症治疗经历。系统将 AI 模式的敏捷决策与精准医疗的科学严谨性结合，通过极限诊断数据整合、AI 辅助靶点分析、并行治疗方案设计三大核心能力，实现"一人一药"的个性化精准治疗。

## 系统架构

| 子系统 | 角色 | 核心职责 |
|---|---|---|
| A. 极限诊断数据整合平台 | 数据底座 | 多组学数据接入、清洗、标准化、存储与检索 |
| B. AI辅助靶点发现引擎 | 核心智能 | 靶点识别、分子设计、通路分析、证据链构建 |
| C. 并行治疗方案设计系统 | 治疗决策 | 多疗法组合优化、实时疗效监测、动态调整 |
| D. AI模式协作平台 | 用户界面 | 权限管理、多角色协作、数据看板、合规审计 |

## 技术栈

- **后端**：FastAPI + SQLAlchemy + asyncpg + Alembic + Fernet 对称加密
- **前端**：Next.js 14 + React + TailwindCSS + Zustand + React Query + Zod + ErrorBoundary
- **数据库**：PostgreSQL(+TimescaleDB) / Redis / ChromaDB / Neo4j
- **存储**：MinIO（对象存储）
- **工作流**：Nextflow + nf-core
- **生物信息**：Scanpy / BioPython / RDKit / cyvcf2
- **AI/ML**：litellm / DeepChem / PyTorch Geometric / DiffDock
- **隐私计算**：Flower（联邦学习）/ PySyft（隐私保护）
- **CI/CD**：GitHub Actions（backend-ci / frontend-ci / deploy）+ Docker 多阶段构建

## 快速开始

### 1. 准备环境

需要安装 Docker 和 Docker Compose。

```bash
# 复制环境配置
cp .env.example .env
# 默认 USE_MOCK=true，无需任何 API Key 即可运行
```

### 2. 启动系统

```bash
make up
```

启动后访问：
- **前端**：http://localhost
- **API 文档**：http://localhost/docs
- **MinIO 控制台**：http://localhost:9001
- **Neo4j**：http://localhost:7474

### 3. 初始化数据

```bash
make migrate   # 数据库迁移
make seed      # 灌入样本数据
```

### 4. 切换真实 API

编辑 `.env`：
```env
USE_MOCK=false
OPENAI_API_KEY=sk-...        # 大模型
NVIDIA_NIM_API_KEY=...       # DiffDock 对接（可选）
```

重启服务：`make down && make up`

## Mock/Real 双模式

系统默认使用 Mock 数据运行（`USE_MOCK=true`），无需任何外部 API Key 即可完整演示所有功能：

- **Mock 模式**：返回预置的真实结构数据（EGFR T790M、B7H3 靶点、Osimertinib 分子等）
- **Real 模式**：真实调用 mygene.info / myvariant.info / ebi.ac.uk/chembl / OpenAI / NVIDIA NIM

切换对上层透明，所有 service 层只依赖抽象接口。

## 核心能力

### 第一阶段（P0 已实现）
- 多组学数据接入（RNA-seq / 单细胞 / VCF / FASTA）
- Scanpy 单细胞分析（预处理 + UMAP + Leiden + 差异表达）
- MyGene/MyVariant 基因变异注释
- ChEMBL 药物重定位（老药新用）
- RDKit 类药性评估
- 自然语言问答（分级路由：快速筛查 / 深度洞察）
- CDISC SDTM 导出
- 多假设并行管理（Hypothesis Sandbox）
- 干湿闭环骨架
- 5角色 RBAC 权限

### 第二阶段（P2 代码框架）
- DeepChem 分子性质预测
- PyG 蛋白质互作网络建模
- DiffDock 分子对接

### 第三阶段（P3 代码框架）
- Flower 联邦学习
- PySyft 隐私保护计算
- 实时疗效监测与动态调整

## API 概览

```
POST /api/v1/auth/login                 # 登录
GET/POST /api/v1/projects               # 项目管理
POST /api/v1/data/upload                # 数据上传
POST /api/v1/data/{id}/parse            # 触发解析
POST /api/v1/targets/discover           # 靶点发现
POST /api/v1/targets/{id}/repurpose     # 老药新用
POST /api/v1/knowledge/gene             # 基因查询
POST /api/v1/knowledge/variant          # 变异注释
POST /api/v1/chat                       # 自然语言问答
GET/POST /api/v1/hypotheses             # 多假设并行
POST /api/v1/hypotheses/{id}/analyze    # 强制深度分析
GET/POST /api/v1/experiments            # 实验数据
POST /api/v1/reports/{id}/sdtm          # CDISC 导出
POST /api/v1/workflows/run              # Nextflow 工作流
GET  /api/v1/audit/logs                 # 审计日志
```

## 文档

### 项目文档（docs/）

- [API 接口文档](docs/API接口文档.md) — 16 个模块、100+ 端点的完整 API 参考
- [技术架构文档](docs/技术架构文档.md) — 12 章节 + 5 个 Mermaid 架构图
- [用户使用手册](docs/用户使用手册.md) — 17 章节，覆盖 5 种角色全部功能
- [管理员操作指南](docs/管理员操作指南.md) — 10 章节，含 LLM 配置/用户管理/审计
- [部署说明](docs/部署说明.md) — 15 章节，覆盖 Docker/K8s/单机部署
- [问题分析报告](docs/问题分析报告-工具超时与反馈失败.md) — 工具超时根因与修复方案

### 历史文档

- [开源工具集成指南](2026-07-03-github-opensource-integration-guide.md)
- [实施计划](.trae/documents/精准药物设计系统-实施计划.md)

## 开发命令

```bash
make help            # 查看所有命令
make up              # 启动
make down            # 停止
make logs            # 查看日志
make test            # 运行后端测试（覆盖率 ≥ 80%）
make lint            # 代码检查（ruff + eslint）
make migrate         # 数据库迁移
make seed            # 灌入样本数据
make shell-backend   # 进入后端容器
make shell-frontend  # 进入前端容器
make clean           # 清理所有数据（危险）
```

## 质量保障

- **测试覆盖率**：后端 ≥ 80%（CI 强制校验）
- **CI/CD**：3 个 GitHub Actions 工作流（backend-ci / frontend-ci / deploy）
- **代码规范**：后端 ruff（Python）+ 前端 eslint（TypeScript）
- **类型检查**：前端 `tsc --noEmit` 严格模式
- **Docker 多阶段构建**：前端 standalone 模式，非 root 用户运行，含 healthcheck

## 变更记录

详见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

详见 [LICENSE](LICENSE)。本项目为研究演示用途，按"现状"提供，不提供任何明示或暗示的担保。
