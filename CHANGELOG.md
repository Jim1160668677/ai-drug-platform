# 变更记录

本项目所有重要变更均记录于此文件。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 即将推出

- DeepChem 分子性质预测（P2 完整实现）
- PyG 蛋白质互作网络建模（P2 完整实现）
- DiffDock 分子对接（P2 完整实现）
- Flower 联邦学习（P3 完整实现）
- PySyft 隐私保护计算（P3 完整实现）
- 实时疗效监测与动态调整（P3 完整实现）

## [1.0.0] — 2026-07-05

首个完整可部署版本。覆盖干湿闭环、多假设并行、老药新用、CDISC 标准、分级分析、11 开源工具集成全部 P0 能力，并包含 P2/P3 阶段代码框架。

### 新增 — 后端

#### API 模块（16 个端点模块，100+ 接口）

- **认证模块** (`/api/v1/auth`)：JWT 登录/注册/刷新/登出，密码 bcrypt 哈希
- **项目管理** (`/api/v1/projects`)：CRUD、成员管理、角色分配
- **数据接入** (`/api/v1/data`)：多组学文件上传、异步解析、MinIO 对象存储
- **靶点发现** (`/api/v1/targets`)：靶点识别、证据链构建、老药新用
- **分子设计** (`/api/v1/molecules`)：分子 CRUD、类药性评估（RDKit）
- **治疗方案** (`/api/v1/treatments`)：多疗法组合优化
- **多假设并行** (`/api/v1/hypotheses`)：Hypothesis Sandbox、强制深度分析
- **干湿闭环** (`/api/v1/experiments`)：实验数据管理、Target/Molecule/Treatment 关系建模
- **工作流** (`/api/v1/workflows`)：Nextflow 工作流触发与状态查询
- **报告导出** (`/api/v1/reports`)：CDISC SDTM 格式导出
- **知识库** (`/api/v1/knowledge`)：MyGene 基因查询、MyVariant 变异注释
- **自然语言问答** (`/api/v1/chat`)：分级路由（快速筛查 / 深度洞察）
- **审计日志** (`/api/v1/audit`)：全操作审计，IP/User-Agent 提取
- **全局看板** (`/api/v1/dashboard`)：聚合统计
- **LLM 配置** (`/api/v1/llm-configs`)：多模型配置管理、激活、API Key Fernet 加密
- **用户管理** (`/api/v1/users`)：5 角色 RBAC、状态管理、角色修改

#### 服务模块（8 个核心服务）

- `ScRnaSeqParser`：Scanpy 单细胞分析（预处理 + UMAP + Leiden + 差异表达）
- `VcfParser`：cyvcf2 VCF 解析与变异注释
- `VectorStore`：ChromaDB 向量检索
- `NetworkModeler`：PyG 蛋白质互作网络建模（P2 框架）
- `TargetIdentifier`：靶点识别引擎
- `KnowledgeGraph`：Neo4j 知识图谱
- `LLMOrchestrator`：多模型编排（litellm）
- `MoleculeDesigner`：分子设计与类药性评估
- `DrugRepurposer`：ChEMBL 老药新用
- `PrivacyLayer`：PySyft 隐私保护（P3 框架）
- `NextflowRunner`：工作流执行器
- `DbSession`：异步数据库会话管理

#### 数据模型

- **SQLAlchemy ORM**：完整模型定义，含 UUID 主键、TimestampMixin
- **双向关系**：`back_populates` 配置，Target ↔ Molecule ↔ Treatment ↔ Experiment
- **RBAC 模型**：User/Role/Permission，5 种角色（founder/chief_researcher/researcher/doctor/data_engineer）
- **审计模型**：AuditLog，含 IP/User-Agent/Action/Resource
- **Fernet 加密**：API Key 字段加密存储，`enc:` 前缀标识密文，无密钥降级明文

#### 安全与权限

- **JWT 认证**：访问令牌 + 刷新令牌
- **RBAC 权限控制**：`require_role()` 依赖注入
- **Fernet 对称加密**：API Key 加密存储
- **审计日志**：全操作记录，含 IP 与 User-Agent
- **CORS 配置**：可配置允许的源

### 新增 — 前端

#### 页面（12 个核心页面）

- **登录/注册页**：表单验证、JWT 存储
- **工作台首页**：项目概览、快捷入口
- **项目管理**：列表/详情/成员管理
- **数据接入**：文件上传、解析状态、结果预览
- **靶点发现**：靶点列表、证据链可视化
- **分子设计**：分子列表、类药性评估
- **多假设并行**：Hypothesis Sandbox、深度分析
- **干湿闭环**：实验数据管理
- **审计日志**：日志查询、过滤
- **全局看板**：数据可视化
- **管理员后台**：LLM 配置、用户管理

#### 组件与工具

- **ErrorBoundary**：React 错误边界，捕获渲染异常，支持自定义 fallback
- **Toast 通知**：全局通知系统，集成 React Query mutations.onError
- **Zod 表单验证**：`lib/validation.ts` + `useZodForm` hook，覆盖登录/注册/项目/靶点/分子/LLM 配置/假设/实验/反馈
- **FormError / FieldLabel**：表单错误显示组件
- **JsonViewer**：JSON 数据可视化
- **Providers**：全局 Provider 集成（QueryClient + ErrorBoundary + Toast）

#### 前端工程化

- **Next.js 14 App Router**：`output: 'standalone'` 模式
- **React Query**：服务端状态管理
- **Zustand**：客户端状态管理
- **TailwindCSS**：原子化 CSS
- **TypeScript 严格模式**：`tsc --noEmit` 校验

### 新增 — DevOps 与部署

#### Docker 编排（11 服务）

- **基础设施**：PostgreSQL（含 TimescaleDB）、Redis、ChromaDB、Neo4j、MinIO
- **应用层**：backend、worker、frontend
- **工作流**：Nextflow
- **接入层**：Nginx 反向代理
- **监控**：Flower（联邦学习服务，profile=phase3）
- **Healthcheck**：所有服务配置健康检查
- **数据卷**：持久化存储配置

#### Dockerfile

- **后端** (`backend/Dockerfile`)：python:3.11-slim，含生物信息库系统依赖
- **前端** (`frontend/Dockerfile`)：3 阶段构建（deps → builder → runner），node:20-alpine，非 root 用户，healthcheck

#### CI/CD（GitHub Actions）

- **backend-ci**：Python 3.11 + ruff lint + pytest --cov（≥80%）+ Docker 构建
- **frontend-ci**：Node 20 + npm ci + lint + tsc --noEmit + next build
- **deploy**：main 分支 push 触发，构建并推送 Docker 镜像，创建 GitHub Release，Slack 通知，支持 workflow_dispatch 回滚，post-deploy health check

#### Makefile 快捷命令

- `make up/down/dev/build/logs/ps`：服务管理
- `make migrate/seed/migrate-new`：数据库操作
- `make test/lint`：质量检查
- `make shell-backend/shell-frontend/shell-db`：容器交互
- `make up-phase3`：第三阶段服务
- `make backend-only/frontend-only`：单独服务
- `make clean`：清理（危险）

#### 项目治理

- **PR 模板** (`.github/PULL_REQUEST_TEMPLATE.md`)：变更说明/类型/关联 Issue/测试方案/检查清单
- **Issue 模板**：bug_report.md / feature_request.md
- **CODEOWNERS**：代码所有权配置

### 新增 — 文档（6 份，共 241 KB）

- **API 接口文档** (`docs/API接口文档.md`)：59523 字节，1647 行，16 模块端点全覆盖
- **技术架构文档** (`docs/技术架构文档.md`)：49046 字节，931 行，12 章 + 2 附录，5 个 Mermaid 图
- **用户使用手册** (`docs/用户使用手册.md`)：39854 字节，1009 行，17 章节
- **管理员操作指南** (`docs/管理员操作指南.md`)：32917 字节，573 行，10 章节
- **部署说明** (`docs/部署说明.md`)：50579 字节，1489 行，15 章节
- **问题分析报告** (`docs/问题分析报告-工具超时与反馈失败.md`)：9968 字节，根因分析与修复方案

### 新增 — 测试

- **后端单元测试**：覆盖率 ≥ 91%（目标 80%），514 个测试
- **集成测试** (`backend/tests/test_new_modules.py`)：37 个测试，覆盖 Encryption/AuditExtraction/UserManagement/ExperimentRelationships/AuditLogAction
- **测试报告** (`TEST_REPORT.md`)：详细覆盖率与测试结果

### 新增 — 开源工具集成（11 个）

| 工具 | 用途 | 集成方式 |
|---|---|---|
| Scanpy | 单细胞分析 | `ScRnaSeqParser` 服务 |
| BioPython | 生物序列处理 | 序列解析模块 |
| RDKit | 化学信息学 | `MoleculeDesigner` 类药性评估 |
| cyvcf2 | VCF 解析 | `VcfParser` 服务 |
| MyGene.info | 基因注释 | 知识库模块 |
| MyVariant.info | 变异注释 | 知识库模块 |
| ChEMBL | 药物重定位 | `DrugRepurposer` 服务 |
| Nextflow + nf-core | 工作流 | `NextflowRunner` |
| litellm | 多模型路由 | `LLMOrchestrator` |
| Flower | 联邦学习 | `PrivacyLayer`（P3 框架） |
| PySyft | 隐私计算 | `PrivacyLayer`（P3 框架） |

### Mock/Real 双模式

- **USE_MOCK=true**（默认）：返回预置真实结构数据（EGFR T790M、B7H3 靶点、Osimertinib 分子等）
- **USE_MOCK=false**：真实调用 mygene.info / myvariant.info / ebi.ac.uk/chembl / OpenAI / NVIDIA NIM
- 切换对上层透明，所有 service 层只依赖抽象接口

### 已知限制

1. **P2 阶段为代码框架**：DeepChem / PyG / DiffDock 完整实现待 v1.1
2. **P3 阶段为代码框架**：Flower / PySyft / 实时疗效监测待 v1.2
3. **前端 plotly.js 类型错误**：11 行预先存在的 TypeScript 类型告警（非阻塞）
4. **AuditLog SQLite 兼容性**：测试环境使用 mock db，生产环境 PostgreSQL 不受影响

### 升级指引

#### 从 0.x 升级到 1.0.0

1. 拉取最新代码：`git pull origin main`
2. 更新环境变量：`cp .env.example .env`，新增 `API_KEY_ENCRYPTION_KEY`（生成方法见 .env.example）
3. 重启服务：`make down && make up`
4. 执行迁移：`make migrate`
5. 灌入样本数据（可选）：`make seed`

---

## 版本号说明

- **主版本号**：不兼容的 API 修改
- **次版本号**：向下兼容的功能新增
- **修订号**：向下兼容的问题修复

## 链接

[Unreleased]: https://github.com/your-org/precision-drug-design/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/your-org/precision-drug-design/releases/tag/v1.0.0
