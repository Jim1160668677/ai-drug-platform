---
name: "ai-drug-platform"
description: "AI 驱动的药物研发平台。涵盖多组学数据分析、靶点发现、分子设计、治疗方案优化、假设生成、实验管理全流程。当用户需要了解平台功能、开发新功能、修复 bug 或进行全流程操作时使用。"
---

# AI 药物研发平台 (AI Drug Platform)

## 平台概述

AI 驱动的药物研发平台，整合多组学数据分析、AI 靶点发现、分子设计、治疗方案优化、假设生成与实验管理，提供从数据到临床验证的全流程研发支持。

**技术栈**: Next.js 14 (App Router) + FastAPI + SQLAlchemy + React Query + Zustand + Tailwind CSS + Plotly

## 核心功能模块

### 1. 项目管理 (`/workbench/projects`)
- 创建/切换研发项目
- 项目级数据隔离与权限控制
- 角色体系：创始人(founder) / 首席(chief) / 研究员(researcher) / 审计员(auditor)

### 2. 多组学数据管理 (`/workbench/data`)
- **支持 12 种数据类型**：RNA-seq、scRNA-seq、WES、WGS、VCF、FASTA、蛋白质组学、代谢组学、基因报告、IHC、临床影像、临床检验
- 数据上传与自动解析（每种类型有专用解析器 + 通用回退解析器）
- 数据质量评估（缺失率、分布统计、质量指标）
- 解析结果兼容性映射（`top_genes` 字段统一供下游分析使用）

### 3. 靶点发现 (`/workbench/targets`)
- **两级分析模式**：fast_screen（快速筛选）/ deep_insight（LLM 深度分析）
- 从多组学数据中提取差异基因、变异、通路富集信息
- LLM 辅助深度分析（60s 超时保护，超时自动降级）
- 靶点置信度评分与证据等级（Level I-IV）
- 支持强制深度分析（创始人权限）

### 4. 分子设计与优化 (`/workbench/molecules`)
- **单靶点分子设计**：基于靶点结构生成候选分子
- **多靶点协同设计**：自动加载已发现靶点，支持多靶点协同分子设计
- **分子详情增强**：点击详情自动调用 ADMET 预测 + 分子解析 API
  - ADMET 预测：毒性、LogS、生物利用度、BBB 渗透、Caco-2、hERG 风险、PAINS 警告
  - 分子解析：芳香环/脂肪环/总环数、手性中心、立体键、功能团识别
- **类药性评估**：Lipinski 五规则、HBD/HBA/TPSA/可旋转键/环数
- **SMILES 评估**：输入 SMILES 直接评估类药性
- **自动匹配靶点**：一键将分子与靶点匹配，生成药物/治疗方案列表

### 5. 治疗方案优化 (`/workbench/treatments`)
- 个性化治疗组合优化（靶向/免疫/化疗/联合）
- **DDI 药物相互作用检查**：50+ 规则 + 靶点重合度算法
- 疗效评分 / 风险评分 / 置信度评估
- 疗效监测（趋势分析、不良事件追踪）
- **临床反馈闭环**：患者信息→用药方案→疗效→不良反应→数据分析→预测优化
- SDTM/ADaM 标准数据导出

### 6. 假设生成与管理 (`/workbench/hypotheses`)
- **自动假设生成**：三种模式（rule / llm / hybrid）
  - 规则推理：DE基因+通路、多靶点分子、临床反馈、聚类结果、靶点机制
  - LLM 辅助：Agnes-2.0-flash 模型生成更丰富假设描述
  - 混合模式：规则+LLM 合并去重
- 每个假设包含：标题、描述、支持证据、验证方法、置信度、类别
- 假设并行分析、对比看板、合并/淘汰管理
- 数据源：靶点、分子、差异基因、通路富集、治疗方案、临床反馈、聚类

### 7. 实验管理 (`/workbench/experiments`)
- 干湿实验闭环管理
- 实验记录与结果关联
- 支持实验数据上传与分析

### 8. 一键分析流水线 (`/workbench/pipeline`)
- **全流程编排**：靶点发现→分子生成→治疗方案匹配→假设生成
- **断点续行**：`resume_from_step` / `skip_steps` 参数
- 步骤顺序：target_discovery → molecule_generation → treatment_matching → hypothesis_generation
- 支持跳过指定步骤，从数据库加载已有结果

### 9. 联邦学习 (`/workbench/federated`)
- 多中心协作训练
- 差分隐私保护
- 节点管理与性能监控

### 10. 数据隐私与合规 (`/workbench/privacy`, `/workbench/consent`)
- 知情同意管理（100% 覆盖率模块）
- 数据血缘追踪
- 隐私保护策略

### 11. 疗效监测 (`/workbench/efficacy`)
- 患者用药效果追踪
- 不良反应监控
- 趋势分析与预警

### 12. 知识图谱与 AI 对话 (`/workbench/chat`)
- 药物-靶点-疾病知识网络
- 向量检索（99% 覆盖率）
- LLM 驱动的智能问答

### 13. 报告与导出 (`/reports`)
- CDISC SDTM 导出（FDA 认可标准）
- CDISC ADaM 导出（统计分析用）
- 支持 JSON 和 CSV 格式

### 14. 管理后台 (`/admin`)
- 用户管理（角色切换、启用/禁用）
- LLM 配置管理（激活切换、连通性测试）
- 审计日志（不可篡改的操作记录）

## 后端 API 结构

```
/api/v1/
├── auth/          — 认证（登录、注册、token 刷新）
├── projects/      — 项目管理
├── datasets/      — 数据上传与解析
├── targets/       — 靶点发现与管理
│   └── /discover  — 靶点发现（fast_screen/deep_insight）
├── molecules/     — 分子设计与管理
│   ├── /design    — 单靶点设计
│   ├── /design-multi-target — 多靶点协同设计
│   ├── /assess-druglikeness — 类药性评估
│   ├── /predict-properties  — ADMET 预测
│   └── /explain   — 分子解析
├── treatments/    — 治疗方案
│   ├── /optimize  — 组合优化
│   ├── /ddi-check — DDI 检查
│   └── /feedback  — 临床反馈
├── hypotheses/    — 假设管理
│   └── /auto-generate — 自动生成假设
├── experiments/   — 实验管理
├── pipeline/      — 流水线编排
├── reports/       — 报告导出
│   ├── /{id}/sdtm — SDTM 导出
│   └── /{id}/adam — ADaM 导出
├── federated/     — 联邦学习
├── consent/       — 知情同意
├── lineage/       — 数据血缘
├── knowledge/     — 知识图谱
├── llm/           — LLM 配置与监控
├── workflow/      — 干湿实验闭环
└── admin/         — 管理后台
```

## AI 集成

- **LLM 提供商**：Agnes（API key: `sk-EGw4PNgeLncSdPDy09XZJK9DQHa4uUcQ15EEv8bousgPxo39`，模型: `agnes-2.0-flash`）
- **统一后端架构**：模型访问层 + 请求路由 + 认证/配额管理 + 性能监控 + 结果缓存
- **应用场景**：靶点深度分析、假设生成、分子解析、智能问答

## 开发约定

- **单元测试覆盖率**：≥ 80%
- **P0/P1 bug**：100% 解决率
- **删除操作**：不影响核心系统功能
- **AI 能力**：通过统一后端架构接入，标准化接口
- **Python except 块**：不在 except 内部 import 模块
- **前端水合**：使用 `useMounted()` hook + Zustand `skipHydration: true`
- **认证**：middleware 通过 cookie 保护路由，client 通过 localStorage 读取 token
