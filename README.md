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
> 干湿闭环 | 多假设并行 | 老药新用 | CDISC 标准 | 分级分析 | 11 开源工具集成 | 自研 ReAct Agent

> **v2.0 复赛交付版**：自研 ReAct Agent 引擎全量落地，8 大功能模块增强，490 测试通过，多套免备案部署方案。
> **比赛信息**：TRAE AI 创造力大赛 · 社会服务赛道 · 复赛（2026.7.21 - 8.9）

灵感来源于 GitLab 联合创始人 Sid Sijbrandij 的个性化癌症治疗经历。系统将 AI 模式的敏捷决策与精准医疗的科学严谨性结合，通过极限诊断数据整合、AI 辅助靶点分析、并行治疗方案设计三大核心能力，实现"一人一药"的个性化精准治疗。

## 📚 复赛材料（必交项）

| 材料 | 路径 | 用途 |
|---|---|---|
| 产品说明书 | [docs/产品说明书.md](docs/产品说明书.md) | 完整产品介绍，针对评审 |
| TRAE 实践证明 | [docs/TRAE实践证明.md](docs/TRAE实践证明.md) | 6 个 Session ID + 4 张截图说明 |
| 社区发帖模板 | [docs/社区发帖模板.md](docs/社区发帖模板.md) | 公开展示用 |
| 飞书问卷提交清单 | [docs/飞书问卷提交清单.md](docs/飞书问卷提交清单.md) | 私密提交核对 |
| 评审体验入口 | [docs/评审体验入口与测试账号.md](docs/评审体验入口与测试账号.md) | 评审快速上手 |
| 部署上线指南 | [docs/部署上线指南-复赛版.md](docs/部署上线指南-复赛版.md) | 多套免备案部署方案 |
| 完整测试报告 | [.trae/documents/agent-full-test-report.md](.trae/documents/agent-full-test-report.md) | 490 测试 + 7 bug 修复 |

## 🚀 体验入口

> 出于 API Key 安全与作品保护，体验链接仅在飞书问卷私密提交，仅评审可见。
> 默认 Mock 模式，无需任何 API Key 即可完整体验。

**测试账号**：
```
邮箱：sid@ai-drug.com
密码：demo123456
角色：founder（最高权限）
```

详见 [评审体验入口与测试账号](docs/评审体验入口与测试账号.md)。

## 系统架构

| 子系统 | 角色 | 核心职责 |
|---|---|---|
| A. 极限诊断数据整合平台 | 数据底座 | 多组学数据接入、清洗、标准化、存储与检索 |
| B. AI辅助靶点发现引擎 | 核心智能 | 靶点识别、分子设计、通路分析、证据链构建 |
| C. 并行治疗方案设计系统 | 治疗决策 | 多疗法组合优化、实时疗效监测、动态调整 |
| D. AI模式协作平台 | 用户界面 | 权限管理、多角色协作、数据看板、合规审计 |
| **E. ReAct Agent 引擎（v2.0 新增）** | **AI 协作** | **自研 ReAct 主循环、DAG 规划、14 工具、WebSocket 实时推送** |

## 技术栈

- **后端**：FastAPI + SQLAlchemy 2.0 异步 + Pydantic v2 + Alembic + Fernet 对称加密
- **前端**：Next.js 14 + React 18 + TailwindCSS + Zustand + XState v5 + reactflow + react-virtuoso + Monaco Editor
- **AI 引擎**：自研 ReAct Agent（AgentEngine / Planner / Registry / Guardrail / Audit）
- **数据库**：PostgreSQL(+TimescaleDB) / Redis / ChromaDB / Neo4j
- **存储**：MinIO（对象存储）
- **工作流**：Nextflow + nf-core
- **生物信息**：Scanpy / BioPython / RDKit / cyvcf2 / gseapy / opacus
- **AI/ML**：litellm / DeepChem / PyTorch Geometric / DiffDock
- **隐私计算**：Flower（联邦学习）/ PySyft（隐私保护）/ DPSGD（差分隐私）
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
make seed      # 灌入样本数据（含 5 角色测试账号 + ReAct Agent 默认会话）
```

### 4. 切换真实 API（可选）

编辑 `.env`：
```env
USE_MOCK=false
AGNES_API_KEY=sk-...    # Agnes 大模型（通过环境变量注入，不在源码出现）
```

或在管理后台 `/admin/llm` 中通过 UI 配置 LLM。重启服务：`make down && make up`

## Mock/Real 双模式

系统默认使用 Mock 数据运行（`USE_MOCK=true`），无需任何外部 API Key 即可完整演示所有功能：

- **Mock 模式**：返回预置的真实结构数据（EGFR T790M、B7H3 靶点、Osimertinib 分子等）
- **Real 模式**：真实调用 mygene.info / myvariant.info / ebi.ac.uk/chembl / Agnes LLM

切换对上层透明，所有 service 层只依赖抽象接口。

## 核心能力

### v1.0 第一阶段（P0 已实现）
- 多组学数据接入（RNA-seq / 单细胞 / VCF / FASTA / 蛋白质组 / 代谢组）
- Scanpy 单细胞分析（预处理 + UMAP + Leiden + 差异表达）
- MyGene/MyVariant 基因变异注释
- ChEMBL 药物重定位（老药新用）
- RDKit 类药性评估
- 自然语言问答（分级路由：快速筛查 / 深度洞察）
- CDISC SDTM 导出
- 多假设并行管理（Hypothesis Sandbox）
- 干湿闭环骨架
- 5角色 RBAC 权限

### v2.0 第二阶段（复赛新增）
- **自研 ReAct Agent 引擎**：Thought → Action → Observation 主循环，max_steps + timeout 双重保护
- **DAG 任务规划**：Planner 将复杂任务分解为有向无环图，reactflow 可视化
- **14 个工具注册表**：discover_targets / design_molecules / assess_druglikeness / repurpose_drugs 等
- **Guardrail 安全护栏**：医疗红线 + 输入输出双重过滤
- **WebSocket 实时推送**：task_started / thought / action / observation / task_completed
- **8 大功能模块增强**：42 子功能（多靶点协同设计 / 患者用药反馈 / HL7 FHIR / Pinnacle 21 / 数据血缘 / 联邦学习 / 差分隐私 / 知情同意 / Agnes LLM 集成）
- **8 个 P0 安全漏洞修复**：WebSocket 鉴权 / 水平越权 / 事件循环阻塞 / 数据库事务 / Guardrail 正则 / 数值校验 / 任务状态查询 / LLM fallback
- **490 测试通过**：L1 单元 387 + L2 集成 93 + L3 系统 6 + L4 UAT 4

### v2.1+ 第三阶段（代码框架）
- DeepChem 分子性质预测（P2 完整实现）
- PyG 蛋白质互作网络建模（P2 完整实现）
- DiffDock 分子对接（P2 完整实现）
- Flower 联邦学习（P3 完整实现）
- PySyft 隐私保护计算（P3 完整实现）
- 实时疗效监测与动态调整（P3 完整实现）

## API 概览

```
# 认证与项目管理
POST /api/v1/auth/login                 # 登录
GET/POST /api/v1/projects               # 项目管理

# 数据与靶点
POST /api/v1/data/upload                # 数据上传
POST /api/v1/data/{id}/parse            # 触发解析
POST /api/v1/targets/discover           # 靶点发现
POST /api/v1/targets/{id}/repurpose     # 老药新用
POST /api/v1/targets/{id}/force-deep-analysis  # 强制深度分析（v2.0 新增）

# 分子与治疗
POST /api/v1/molecules                  # 分子 CRUD
POST /api/v1/molecules/design-multi-target    # 多靶点协同设计（v2.0 新增）
GET/POST /api/v1/treatments             # 治疗方案

# 知识与问答
POST /api/v1/knowledge/gene             # 基因查询
POST /api/v1/knowledge/variant          # 变异注释
POST /api/v1/chat                       # 自然语言问答

# 多假设与实验
GET/POST /api/v1/hypotheses             # 多假设并行
POST /api/v1/hypotheses/{id}/analyze    # 强制深度分析
GET/POST /api/v1/experiments            # 实验数据

# 报告与工作流
POST /api/v1/reports/{id}/sdtm          # CDISC SDTM 导出
POST /api/v1/reports/{id}/fhir          # HL7 FHIR R4 导出（v2.0 新增）
POST /api/v1/workflows/run              # Nextflow 工作流

# ReAct Agent（v2.0 新增）
POST /api/v1/agent/sessions             # 创建 Agent 会话
GET  /api/v1/agent/sessions/{id}        # 获取会话详情
WS   /api/v1/agent/sessions/{id}/tasks  # 实时任务推送

# 联邦学习与隐私（v2.0 增强）
POST /api/v1/federated/jobs             # 创建联邦学习任务
POST /api/v1/federated/jobs/{id}/dp     # 配置差分隐私
GET  /api/v1/consent                    # 知情同意管理
GET  /api/v1/lineage                    # 数据血缘追踪

# 治理
GET  /api/v1/audit/logs                 # 审计日志
GET/POST /api/v1/llm-configs            # LLM 配置管理
GET/POST /api/v1/users                  # 用户管理（5 角色 RBAC）
```

## 文档

### 项目文档（docs/）

- [产品说明书（复赛版）](docs/产品说明书.md) — 完整产品介绍，针对评审
- [TRAE 实践证明](docs/TRAE实践证明.md) — 6 个 Session ID + 4 张截图说明
- [部署上线指南（复赛版）](docs/部署上线指南-复赛版.md) — 多套免备案部署方案
- [评审体验入口与测试账号](docs/评审体验入口与测试账号.md) — 评审快速上手
- [API 接口文档](docs/API接口文档.md) — 16 个模块、100+ 端点的完整 API 参考
- [技术架构文档](docs/技术架构文档.md) — 12 章节 + 5 个 Mermaid 架构图
- [用户使用手册](docs/用户使用手册.md) — 17 章节，覆盖 5 种角色全部功能
- [管理员操作指南](docs/管理员操作指南.md) — 10 章节，含 LLM 配置/用户管理/审计
- [部署说明](docs/部署说明.md) — 15 章节，覆盖 Docker/K8s/单机部署
- [问题分析报告](docs/问题分析报告-工具超时与反馈失败.md) — 工具超时根因与修复方案

### 历史文档

- [开源工具集成指南](2026-07-03-github-opensource-integration-guide.md)
- [ReAct 引擎设计文档](2026-07-18-agent-react-design.md)
- [ReAct 引擎功能设计](2026-07-18-agent-functional-design.md)
- [完整测试报告](.trae/documents/agent-full-test-report.md) — 490 测试 + 7 bug 修复

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

- **测试覆盖率**：后端 ≥ 80%（CI 强制校验），核心模块 engine.py 94%
- **测试体系**：490 测试通过（L1 单元 387 + L2 集成 93 + L3 系统 6 + L4 UAT 4）
- **CI/CD**：3 个 GitHub Actions 工作流（backend-ci / frontend-ci / deploy）
- **代码规范**：后端 ruff（Python）+ 前端 eslint（TypeScript）
- **类型检查**：前端 `tsc --noEmit` 严格模式
- **Docker 多阶段构建**：前端 standalone 模式，非 root 用户运行，含 healthcheck
- **安全加固**：5 角色 RBAC + Fernet 加密 + 审计日志 + 多级权限校验 + WebSocket 鉴权
- **API Key 安全**：通过环境变量注入，不在源码 / 文档 / 视频中明文出现

## 变更记录

详见 [CHANGELOG.md](CHANGELOG.md)。

- **v2.0.0（2026-07-19）**：复赛交付版，ReAct Agent 引擎 + 8 大模块增强 + 490 测试 + 多套部署
- **v1.0.0（2026-07-05）**：首个完整可部署版本，覆盖干湿闭环、多假设并行、老药新用、CDISC 标准

## 许可证

详见 [LICENSE](LICENSE)。本项目为研究演示用途，按"现状"提供，不提供任何明示或暗示的担保。

---

> 本产品全程使用 [TRAE IDE](https://www.trae.cn/ide/download) 开发，关键任务对话 Session ID 不少于 3 个，详见 [TRAE 实践证明](docs/TRAE实践证明.md)。

