# Agent 系统能力升级技术方案 — 对标 Trae AI

> **文档版本**: v1.0
> **创建日期**: 2026-07-28
> **目标**: 将现有 AI 药物研发平台的 Agent 系统能力提升至与 Trae AI 相当的水平
> **参考依据**: [Trae Agent 概述](https://docs.trae.ai/ide/agent-overview) | [Trae Agent 2.0 架构博客](https://www.trae.ai/blog/product_thought_0617) | [Trae Agent 技术论文 arXiv:2507.23370](https://arxiv.org/pdf/2507.23370) | [Trae Agent 开源仓库](https://github.com/bytedance/trae-agent)

---

## 目录

1. [Trae AI 核心能力深度分析](#一trae-ai-核心能力深度分析)
2. [对标 Trae AI 的 Agent 系统架构设计](#二对标-trae-ai-的-agent-系统架构设计)
3. [关键 Agent 功能模块实现方案](#三关键-agent-功能模块实现方案)
4. [Agent 与工具集成框架](#四agent-与工具集成框架)
5. [系统测试与评估标准](#五系统测试与评估标准)
6. [分阶段实施计划](#六分阶段实施计划)

---

## 一、Trae AI 核心能力深度分析

### 1.1 Trae AI Agent 的四大核心能力

基于 Trae 官方文档和技术博客，Trae AI Agent 具备以下核心能力：

| 能力 | 描述 | 技术实现 |
|------|------|---------|
| **自主运行** | 独立探索代码库，识别相关文件并进行必要修改 | Agentic Loop + 自主工具调度 |
| **完整工具访问** | 搜索、编辑、创建文件、运行终端命令 | Native Function Call + MCP 协议 |
| **上下文理解** | 建立对项目结构和依赖关系的全面理解 | Code Knowledge Graph + 滑动窗口 |
| **多步骤规划** | 将复杂任务拆分为可执行步骤，按顺序处理 | 动态 TO-DO List + Repeated Reminder |

### 1.2 Trae Agent 2.0 架构演进关键洞察

Trae Agent 经历了从 **Workflow 到 Agentic Loop** 的架构演进，其核心设计哲学如下：

#### 1.2.1 从"Plan-then-Execute"到"More Agentic Loop"

```
Agent 1.0 (旧架构):                    Agent 2.0 (新架构):
┌─────────────────────┐               ┌─────────────────────────┐
│ Proposal (规划提案)   │               │                         │
│        ↓             │               │  统一上下文窗口           │
│ Code RAG (固定检索)   │    ─────>    │  (历史+工具日志全可见)     │
│        ↓             │               │                         │
│ Plan/ToolCall Loop   │               │  模型自主决定:           │
│ (固定流程循环)        │               │  - 何时收集上下文         │
│        ↓             │               │  - 何时推理               │
│ 交付验收             │               │  - 何时行动               │
└─────────────────────┘               │  - 何时交付               │
                                      └─────────────────────────┘
```

**关键变化**：
- **去掉固定 Proposal 阶段**：不再先生成完整计划再执行，而是模型根据会话状态动态决策
- **引入 Search Codebase Tool**：代替固定的 Code RAG 流程，实现 **Agentic RAG**（模型自主决定何时检索）
- **统一上下文窗口**：所有历史消息 + 工具调用日志持续可见，帮助模型保持全局视野
- **Prompt Caching**：利用上下文缓存，将有效上下文窗口翻倍，同时优化成本

#### 1.2.2 可控性设计 — "More Agentic ≠ More Controllable"

Trae 团队发现：**更高的自主性并不等于更好的可控性**。为此引入了三项约束机制：

1. **TO-DO List & Repeated Reminder**
   - 引入 TO-DO Tool 约束流程，避免模型过度发散
   - 过程中可更新 TO-DO 实现纠偏
   - Repeated Reminder 机制反复强调重要信息，防止多轮后遗忘

2. **Effective Feedback（有效反馈）**
   - Lint Error 信息在每次文件修改后及时反馈，尽早规避语法错误
   - 对模型幻觉导致的非法 JSON Schema、无效工具调用进行及时引导纠正

3. **Keep Tools Simple（工具精简）**
   - 精简工具列表，避免引入多个语义重叠的工具，降低模型决策难度
   - 使用 **Native Function Call** 代替 JSON Schema 解析

#### 1.2.3 上下文压缩与长期记忆

- **模型驱动的上下文压缩**：利用模型对历史上下文进行总结压缩，代替工程裁剪，保留更多有效信息
- **滑动窗口机制**：更大的上下文窗口 + 由新到旧动态拼接
- **Long-term Memory**：跨多轮会话的重要信息不被遗忘

### 1.3 Trae Agent 的工程实践

基于 QCon 演讲和技术论文，Trae Agent 的工程实践包括：

| 工程能力 | 实现 | 效果 |
|---------|------|------|
| **Graph Orchestration** | 图编排实现 Multi-Agent Workflow | 复杂任务多 Agent 协作 |
| **SOLO Mode** | 全自主编码 Agent | 从需求到部署全自动 |
| **Task Manager** | 任务管理 + 断点续传 | 任务中断后可恢复 |
| **Resume Memory** | 恢复记忆机制 | 跨会话上下文保持 |
| **HTTP/SSE Stream Builder** | 流式输出构建器 | 首字延迟 < 500ms |
| **Native Function Call** | 原生函数调用 | 工具调用准确率 > 95% |
| **Ensemble Reasoning** | 集成推理（Generation/Pruning/Selection） | SWE-bench 75.20% Pass@1 |
| **Turn-Control Strategy** | 动态轮次控制 | 成本降低 12-24% |
| **MCP 协议** | Model Context Protocol 工具生态 | 外部资源按需接入 |
| **Code Knowledge Graph** | 代码知识图谱 | 跨文件理解 |

### 1.4 与现有系统的差距矩阵

| 能力维度 | Trae AI | 本系统现状 | 差距等级 |
|---------|---------|-----------|---------|
| **自主决策** | 模型驱动 Agentic Loop | 固化 ReAct 循环（Plan→Execute） | 🔴 大 |
| **工具调度** | Native Function Call + MCP | JSON Schema 解析 + 自定义协议 | 🔴 大 |
| **上下文理解** | Code Knowledge Graph + Agentic RAG | 项目上下文注入 + 固定 RAG | 🟡 中 |
| **多步骤规划** | 动态 TO-DO + 可更新计划 | 固定 PlannerOutput（≤5 步） | 🔴 大 |
| **上下文保持** | 统一窗口 + 滑动窗口 + Long-term Memory | LLM 摘要压缩（阈值 6000 token） | 🔴 大 |
| **工具质量** | 动态工具选择 + 质量评估 | ToolQualityTracker（未集成到 Planner） | 🟡 中 |
| **失败恢复** | Effective Feedback + 纠偏 | Reflector（仅分析失败，不自动修正） | 🟡 中 |
| **流式输出** | SSE Stream Builder | ✅ 已支持（push_token） | ✅ 对齐 |
| **并行执行** | 原生并行 | DagExecutor（默认关闭） | 🟡 中 |
| **代码执行** | 持久化 + 多语言 + 包管理 | Docker 沙箱（默认关闭 + 仅 Python） | 🔴 大 |
| **多 Agent** | Multi-Agent 编排 + 子 Agent | 单 Agent | 🔴 大 |
| **自评估** | 答案质量自评 | 无 | 🔴 大 |
| **断点续传** | Task Manager + Resume Memory | 无 | 🟡 中 |
| **主动学习** | 从用户反馈学习 | 无 | 🔴 大 |

---

## 二、对标 Trae AI 的 Agent 系统架构设计

### 2.1 目标架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Agent 系统 v2.0 架构                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐   ┌───────────┐ │
│  │  意图识别    │───>│  任务理解    │───>│  动态规划    │──>│ Agentic  │ │
│  │  IntentRcn  │    │  TaskUnder  │    │  DynPlanner │   │  Loop    │ │
│  │             │    │             │    │             │   │  Engine  │ │
│  │ • 模糊指令   │    │ • 需求扩展   │    │ • TO-DO List│   │ • 自主决策│ │
│  │ • 潜在需求   │    │ • 上下文关联  │    │ • 动态调整   │   │ • 工具调度│ │
│  │ • 情绪感知   │    │ • 领域映射   │    │ • 优先级排序  │   │ • 反馈循环│ │
│  └─────────────┘    └─────────────┘    └─────────────┘   └─────┬─────┘ │
│                                                                   │       │
│  ┌───────────────────────────────────────────────────────────────┘       │
│  │                                                                     │
│  ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    统一上下文管理层                                │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │   │
│  │  │ 滑动窗口  │  │ 向量记忆  │  │ 长期记忆  │  │  工作记忆      │  │   │
│  │  │ Sliding  │  │ Vector  │  │ LongTerm│  │  Working     │  │   │
│  │  │ Window   │  │ Memory  │  │ Memory  │  │  Memory      │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └───────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                  │                                     │
│  ┌───────────────────────────────┘                                     │
│  │                                                                     │
│  ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    工具集成框架                                    │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │   │
│  │  │ 工具注册  │  │ 质量评估  │  │ 动态选择  │  │  数据流转      │  │   │
│  │  │ Registry │  │ Quality │  │ Selector │  │  DataFlow     │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └───────────────┘  │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │   │
│  │  │ MCP 网关  │  │ 沙箱执行  │  │ 并行调度  │  │  结果聚合      │  │   │
│  │  │ MCPGW   │  │ Sandbox │  │ Parallel│  │  Aggregator   │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └───────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                  │                                     │
│  ┌───────────────────────────────┘                                     │
│  │                                                                     │
│  ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    增强能力层                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │   │
│  │  │ 反思重试  │  │ 知识盲区  │  │ 自评估   │  │  断点续传      │  │   │
│  │  │ Reflector│  │ GapDet  │  │ Evaluator│  │  Checkpoint   │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └───────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 功能模块划分

基于 Trae AI 的架构和本系统特点，划分为以下 **7 层 18 个模块**：

| 层级 | 模块名 | 职责 | 对标 Trae AI |
|------|--------|------|-------------|
| **L1 感知层** | IntentRecognizer | 用户意图识别 | 需求分析能力 |
| | TaskUnderstanding | 任务理解与扩展 | 需求分析 + 方案设计 |
| **L2 规划层** | DynamicPlanner | 动态任务规划 | 多步骤规划 + TO-DO List |
| | TaskDecomposer | 复杂任务分解 | 任务拆解 |
| **L3 执行层** | AgenticLoopEngine | 自主决策执行引擎 | More Agentic Loop |
| | ToolScheduler | 工具调度与编排 | 完整工具访问 |
| | FeedbackLoop | 反馈循环 | Effective Feedback |
| **L4 记忆层** | SlidingWindowContext | 滑动窗口上下文 | 统一上下文窗口 |
| | VectorMemory | 向量记忆库 | Long-term Memory |
| | LongTermMemory | 长期记忆 | Resume Memory |
| **L5 工具层** | ToolRegistry | 工具注册中心 | 工具管理 |
| | ToolQualityEvaluator | 工具质量评估 | 动态工具选择 |
| | MCPGateway | MCP 协议网关 | MCP 集成 |
| | SandboxExecutor | 沙箱执行器 | 运行终端命令 |
| **L6 增强层** | Reflector | 反思与重试 | 纠偏机制 |
| | KnowledgeGapDetector | 知识盲区检测 | Agentic RAG |
| | SelfEvaluator | 自我评估 | 答案质量自评 |
| | CheckpointManager | 断点续传 | Task Manager |
| **L7 传输层** | StreamBuilder | 流式输出 | SSE Stream Builder |
| | ProgressManager | 进度推送 | WebSocket 事件 |

### 2.3 模块间交互方式

#### 2.3.1 核心数据流

```
用户输入
    │
    ▼
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│IntentRecognizer│──>│  TaskUnderstanding  │──>│DynamicPlanner│
└─────────────┘     └─────────────────┘     └──────┬──────┘
    │                                               │
    │          ┌────────────────────────────────────┘
    │          │
    │          ▼
    │     ┌─────────────────────────────────────────────────┐
    │     │            AgenticLoopEngine                      │
    │     │  ┌──────────────────────────────────────────┐    │
    │     │  │  循环: while not task_done and step < max  │    │
    │     │  │                                          │    │
    │     │  │  1. 构建上下文 (SlidingWindow + Vector)   │    │
    │     │  │  2. LLM 推理 (stream_complete)            │    │
    │     │  │  3. 解析输出 (Action / Final Answer)      │    │
    │     │  │  4. if Action:                           │    │
    │     │  │     a. ToolScheduler 选择最优工具          │    │
    │     │  │     b. 执行工具 (并行/串行)               │    │
    │     │  │     c. FeedbackLoop 检查结果             │    │
    │     │  │     d. Reflector 失败时反思              │    │
    │     │  │     e. SelfEvaluator 评估进展            │    │
    │     │  │     f. 更新 TO-DO List                  │    │
    │     │  │  5. if Final Answer:                    │    │
    │     │  │     a. SelfEvaluator 评估答案质量        │    │
    │     │  │     b. 若不达标 → 继续循环              │    │
    │     │  │  6. CheckpointManager 保存断点          │    │
    │     │  └──────────────────────────────────────────┘    │
    │     └─────────────────────────────────────────────────┘
    │                         │
    │                    ┌────┘
    │                    ▼
    │              ┌──────────┐
    │              │ 最终答案  │
    │              └──────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                 向量记忆 + 长期记忆                        │
│  • 存储本次会话发现到 VectorMemory                        │
│  • 提取关键知识到 LongTermMemory                         │
│  • 更新用户偏好/项目知识                                  │
└─────────────────────────────────────────────────────────┘
```

#### 2.3.2 事件驱动通信

模块间采用 **事件总线** 模式解耦：

```python
# 事件类型定义
class AgentEventType(Enum):
    INTENT_RECOGNIZED = "intent_recognized"
    TASK_UNDERSTOOD = "task_understood"
    PLAN_GENERATED = "plan_generated"
    PLAN_UPDATED = "plan_updated"          # 动态调整
    TOOL_SELECTED = "tool_selected"
    TOOL_EXECUTING = "tool_executing"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    REFLECTION_TRIGGERED = "reflection_triggered"
    KNOWLEDGE_GAP_DETECTED = "knowledge_gap_detected"
    CONTEXT_COMPRESSED = "context_compressed"
    CHECKPOINT_SAVED = "checkpoint_saved"
    SELF_EVALUATION = "self_evaluation"
    TASK_COMPLETED = "task_completed"
```

各模块订阅感兴趣的事件，实现松耦合：

```python
class AgenticLoopEngine:
    @handler(AgentEventType.INTENT_RECOGNIZED)
    async def on_intent_recognized(self, event):
        # 根据意图调整执行策略
        ...

    @handler(AgentEventType.TOOL_FAILED)
    async def on_tool_failed(self, event):
        # 触发反思
        await self.reflector.reflect(...)
```

### 2.4 整体数据流设计

#### 2.4.1 请求处理流水线

```
[用户消息] 
    → [Guardrail 输入校验]
    → [IntentRecognizer 意图识别] 
    → [TaskUnderstanding 任务理解]
    → [SlidingWindowContext 加载上下文]
    → [VectorMemory 检索相关记忆]
    → [DynamicPlanner 生成 TO-DO]
    → [AgenticLoopEngine 执行循环]
        → [LLM 推理（流式）]
        → [ToolScheduler 工具选择]
        → [工具执行（含沙箱/并行）]
        → [FeedbackLoop 结果反馈]
        → [Reflector 失败反思]
        → [SelfEvaluator 进展评估]
        → [DynamicPlanner 更新 TO-DO]
        → [CheckpointManager 保存断点]
    → [SelfEvaluator 答案质量评估]
    → [Guardrail 输出校验]
    → [VectorMemory 存储记忆]
    → [LongTermMemory 提取知识]
    → [最终答案返回（流式）]
```

#### 2.4.2 上下文数据流

```
┌──────────────────────────────────────────────────────────────┐
│                     统一上下文窗口                            │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  System Prompt (固定)                                   │ │
│  │  • 角色定义 + 能力描述 + 领域知识 + 约束规则               │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  项目上下文 (动态加载)                                    │ │
│  │  • 项目信息 + Top 5 靶点 + Top 5 分子 + 近期分析          │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  长期记忆摘要 (跨会话)                                    │ │
│  │  • 用户偏好 + 项目知识 + 历史发现                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  向量检索结果 (按需)                                      │ │
│  │  • 相关历史对话 + 相关工具结果 + 相关知识                  │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  会话历史 (滑动窗口)                                      │ │
│  │  • 最近 N 轮对话 (完整保留)                               │ │
│  │  • 更早的对话 (LLM 摘要压缩)                              │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  当前任务上下文                                           │ │
│  │  • TO-DO List + 已完成步骤 + 当前步骤 + 工具调用日志      │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  用户当前消息                                            │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  Token 预算管理: 优先保留 System + 项目上下文 + 当前消息      │
│  超额时按优先级淘汰: 向量检索 > 历史摘要 > 早期对话           │
└────────────────────────────────────────────────────────────────┘
```

### 2.5 与现有架构的兼容性设计

升级采用 **渐进式增强** 策略，保证现有功能不受影响：

| 现有模块 | 升级方式 | 兼容性 |
|---------|---------|--------|
| `AgentEngine` | 保留为 `LegacyEngine`，新 `AgenticLoopEngine` 继承核心逻辑 | ✅ 配置开关切换 |
| `TaskPlanner` | 升级为 `DynamicPlanner`，保留 `plan()` 接口 | ✅ 向下兼容 |
| `SessionManager` | 扩展 `VectorMemory` 和 `LongTermMemory` | ✅ 原有接口不变 |
| `ToolRegistry` | 扩展 `MCPGateway` 和 `ToolQualityEvaluator` | ✅ 原有注册不变 |
| `ProgressManager` | 扩展事件类型 | ✅ 原有事件不变 |
| `Reflector` | 保留并增强自动修正能力 | ✅ 向下兼容 |
| `KnowledgeGapDetector` | 保留并增强主动搜索能力 | ✅ 向下兼容 |

**配置开关**：

```python
# config.py 新增配置
AGENT_VERSION: str = "v2"           # v1 (Legacy) / v2 (Agentic Loop)
AGENT_USE_NATIVE_FUNCTION_CALL: bool = True    # Native Function Call
AGENT_USE_DYNAMIC_PLANNER: bool = True         # 动态规划
AGENT_USE_VECTOR_MEMORY: bool = False          # 向量记忆（需 chromadb）
AGENT_USE_LONG_TERM_MEMORY: bool = True        # 长期记忆
AGENT_USE_SELF_EVALUATION: bool = True         # 自我评估
AGENT_USE_CHECKPOINT: bool = True              # 断点续传
AGENT_USE_MCP_GATEWAY: bool = False            # MCP 网关（实验性）
AGENT_TODO_MAX_ITEMS: int = 10                 # TO-DO List 最大项数
AGENT_SELF_EVAL_THRESHOLD: float = 0.7         # 自评估达标阈值
```

---

## 三、关键 Agent 功能模块实现方案

### 3.1 智能任务理解模块（TaskUnderstanding）

#### 3.1.1 设计目标

对标 Trae AI 的"需求分析"能力，实现对模糊、不完整用户指令的准确解析与扩展。

#### 3.1.2 核心能力

| 子能力 | 描述 | 实现方式 |
|--------|------|---------|
| **指令解析** | 解析用户自然语言指令，提取关键实体和意图 | LLM + 领域 NER |
| **模糊指令扩展** | 对不完整指令自动补全缺失信息 | LLM + 上下文推断 |
| **上下文关联** | 关联当前会话历史和项目上下文 | 向量检索 + 上下文注入 |
| **领域映射** | 将用户语言映射到药物研发领域概念 | 领域知识图谱 |
| **潜在需求挖掘** | 识别用户未明确表达但实际需要的服务 | LLM + 意图分类 |

#### 3.1.3 架构设计

```python
# app/services/agent/understanding.py

class TaskUnderstanding:
    """智能任务理解模块
    
    对标 Trae AI 的"需求分析"阶段：
    1. 深入理解任务目标及代码库上下文
    2. 明确需求要点
    """

    def __init__(self, llm_router: LLMRouter, vector_memory: VectorMemory):
        self.llm_router = llm_router
        self.vector_memory = vector_memory

    async def understand(
        self,
        user_input: str,
        session_context: Dict[str, Any],
        project_context: Optional[Dict[str, Any]] = None,
    ) -> TaskUnderstandingResult:
        """理解用户输入，生成结构化任务描述
        
        Returns:
            TaskUnderstandingResult:
                - primary_intent: 主意图（分析/设计/查询/解释/操作）
                - entities: 提取的实体（基因/靶点/分子/疾病）
                - missing_info: 缺失的关键信息
                - inferred_needs: 推断的潜在需求
                - context_relevance: 相关上下文（从向量记忆检索）
                - task_complexity: 任务复杂度（simple/medium/complex）
                - suggested_tools: 建议使用的工具
                - expanded_query: 扩展后的完整查询
        """
        # 1. 意图分类
        intent = await self._classify_intent(user_input)

        # 2. 实体提取（领域 NER）
        entities = await self._extract_entities(user_input)

        # 3. 缺失信息检测
        missing_info = self._detect_missing_info(intent, entities, session_context)

        # 4. 上下文关联（向量检索相关历史）
        context_relevance = await self._retrieve_relevant_context(
            user_input, session_context
        )

        # 5. 潜在需求挖掘
        inferred_needs = await self._infer_needs(
            user_input, intent, entities, project_context
        )

        # 6. 任务复杂度评估
        task_complexity = self._assess_complexity(
            intent, entities, missing_info, inferred_needs
        )

        # 7. 扩展查询生成
        expanded_query = await self._expand_query(
            user_input, entities, missing_info, inferred_needs
        )

        return TaskUnderstandingResult(
            primary_intent=intent,
            entities=entities,
            missing_info=missing_info,
            inferred_needs=inferred_needs,
            context_relevance=context_relevance,
            task_complexity=task_complexity,
            suggested_tools=self._suggest_tools(intent, entities),
            expanded_query=expanded_query,
        )
```

#### 3.1.4 意图分类体系

```python
class UserIntent(Enum):
    """用户意图分类"""
    # 分析类
    DATA_ANALYSIS = "data_analysis"           # 多组学数据分析
    TARGET_DISCOVERY = "target_discovery"     # 靶点发现
    PATHWAY_ANALYSIS = "pathway_analysis"     # 通路分析
    
    # 设计类
    MOLECULE_DESIGN = "molecule_design"       # 分子设计
    DRUG_REPURPOSING = "drug_repurposing"     # 老药新用
    TREATMENT_PLAN = "treatment_plan"         # 治疗方案
    
    # 查询类
    LITERATURE_QUERY = "literature_query"     # 文献查询
    KNOWLEDGE_QUERY = "knowledge_query"       # 知识查询
    WEB_SEARCH = "web_search"                 # 网络搜索
    
    # 解释类
    CONCEPT_EXPLANATION = "concept_explanation"  # 概念解释
    RESULT_INTERPRETATION = "result_interpretation"  # 结果解读
    
    # 操作类
    FILE_OPERATION = "file_operation"         # 文件操作
    CODE_EXECUTION = "code_execution"         # 代码执行
    PROJECT_MANAGEMENT = "project_management"  # 项目管理
    
    # 通用类
    GREETING = "greeting"                     # 问候
    FEEDBACK = "feedback"                     # 反馈
    CLARIFICATION = "clarification"           # 澄清
```

#### 3.1.5 领域实体识别

```python
# 领域实体类型
class EntityType(Enum):
    GENE = "gene"                     # 基因（EGFR, TP53, KRAS）
    PROTEIN = "protein"               # 蛋白
    TARGET = "target"                 # 靶点
    MOLECULE = "molecule"             # 分子
    DRUG = "drug"                     # 药物
    DISEASE = "disease"              # 疾病
    PATHWAY = "pathway"              # 通路
    DATASET = "dataset"              # 数据集
    PROJECT = "project"              # 项目
    BIOMARKER = "biomarker"          # 生物标志物
    VARIANT = "variant"              # 变异
    CLINICAL_TRIAL = "clinical_trial"  # 临床试验

# 实体提取 Prompt
ENTITY_EXTRACTION_PROMPT = """从用户输入中提取药物研发领域的实体。

# 用户输入
{user_input}

# 已知实体库（部分）
- 基因: EGFR, TP53, KRAS, BRAF, PIK3CA, MET, ALK, ROS1, HER2, BRCA1/2...
- 药物: Osimertinib, Gefitinib, Erlotinib, Crizotinib, Pembrolizumab...
- 疾病: NSCLC, SCLC, 乳腺癌, 结直肠癌, 黑色素瘤...

# 输出格式（JSON）
{{
  "entities": [
    {{"type": "gene", "value": "EGFR", "confidence": 0.95}},
    {{"type": "drug", "value": "Osimertinib", "confidence": 0.90}}
  ],
  "missing_context": ["患者癌型未指定", "未明确分析类型"]
}}
"""
```

### 3.2 自主决策执行模块（AgenticLoopEngine）

#### 3.2.1 设计目标

对标 Trae AI 的 "More Agentic Loop"——模型自主决定何时收集上下文、何时推理、何时行动。

#### 3.2.2 核心改进

| 现有 ReAct 循环 | Agentic Loop（v2） |
|----------------|-------------------|
| 固定循环：Thought→Action→Observation | 模型自主决定下一步 |
| 单步串行 | 支持并行工具调用 |
| 失败仅反思 | 失败反思 + 成功优化 + 自评估 |
| 固定步数上限 | 动态步数控制 |
| 不可中断 | 支持中断恢复 |
| 无 TO-DO 约束 | TO-DO List 约束流程 |

#### 3.2.3 架构设计

```python
# app/services/agent/agentic_loop.py

class AgenticLoopEngine:
    """自主决策执行引擎
    
    对标 Trae Agent 2.0 的 More Agentic Loop:
    - 去掉固定 Proposal，模型自主决策
    - 统一上下文窗口
    - TO-DO List 约束
    - Effective Feedback
    - 动态步数控制
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_router: LLMRouter,
        tool_scheduler: ToolScheduler,
        context_manager: ContextManager,
        planner: DynamicPlanner,
        reflector: Reflector,
        evaluator: SelfEvaluator,
        checkpoint_mgr: CheckpointManager,
        progress: ProgressManager,
        audit: AuditLogger,
    ):
        self.db = db
        self.llm_router = llm_router
        self.tool_scheduler = tool_scheduler
        self.context_manager = context_manager
        self.planner = planner
        self.reflector = reflector
        self.evaluator = evaluator
        self.checkpoint_mgr = checkpoint_mgr
        self.progress = progress
        self.audit = audit

    async def run(
        self,
        task_id: str,
        query: str,
        session_id: str,
        user: User,
        understanding: Optional[TaskUnderstandingResult] = None,
    ) -> Dict[str, Any]:
        """Agentic Loop 主循环"""
        
        # 1. 初始化 TO-DO List
        todo_list = await self.planner.init_todo(
            query=query,
            understanding=understanding,
            user=user,
        )
        await self.progress.push_plan(todo_list.to_dict())

        # 2. 动态步数控制
        max_steps = self._dynamic_max_steps(understanding)
        step = 0

        while step < max_steps:
            step += 1

            # 3. 构建统一上下文
            context = await self.context_manager.build_context(
                query=query,
                session_id=session_id,
                todo_list=todo_list,
                step=step,
            )

            # 4. LLM 自主推理（流式）
            llm_output = await self._llm_reason(context, step, max_steps)

            # 5. 解析输出（Action / Final Answer / Update TODO）
            parsed = self._parse_output(llm_output)

            if parsed.is_final_answer:
                # 6a. 自评估
                eval_result = await self.evaluator.evaluate_answer(
                    query=query,
                    answer=parsed.answer,
                    todo_list=todo_list,
                )
                if eval_result.is_acceptable:
                    # 答案达标，返回
                    await self._save_memory(query, parsed.answer, session_id)
                    return self._build_result(parsed, todo_list, step)
                else:
                    # 答案不达标，继续循环
                    context.add_system_note(
                        f"自评估未达标（分数 {eval_result.score:.2f}），"
                        f"建议改进: {eval_result.improvement_suggestions}"
                    )
                    continue

            elif parsed.is_update_todo:
                # 6b. 动态更新 TO-DO List
                todo_list = self.planner.update_todo(todo_list, parsed.todo_update)
                await self.progress.push_plan(todo_list.to_dict())

            elif parsed.is_action:
                # 6c. 工具调用
                tool_result = await self.tool_scheduler.execute(
                    tool_name=parsed.action,
                    tool_args=parsed.action_input,
                    user=user,
                    context=context,
                )

                # 7. Effective Feedback
                feedback = self._generate_feedback(tool_result)
                context.add_observation(feedback)

                # 8. 失败反思
                if not tool_result.success:
                    reflection = await self.reflector.reflect(
                        query=query,
                        tool_name=parsed.action,
                        tool_args=parsed.action_input,
                        error=tool_result.error,
                        recent_steps=context.recent_steps,
                        available_tools=await self.tool_scheduler.list_tools(user),
                    )
                    context.add_observation(reflection.observation_for_llm)

                # 9. 更新 TO-DO 状态
                todo_list.mark_completed(parsed.action)
                await self.progress.push_plan(todo_list.to_dict())

            # 10. 保存断点
            await self.checkpoint_mgr.save(
                task_id=task_id,
                step=step,
                todo_list=todo_list,
                context_summary=context.summary(),
            )

        # 超出步数兜底
        return await self._generate_final_answer_fallback(query, context)
```

#### 3.2.4 动态步数控制

```python
def _dynamic_max_steps(self, understanding: Optional[TaskUnderstandingResult]) -> int:
    """动态步数控制
    
    对标 Trae 的 Turn-Control Strategy：
    - 简单任务：4 步（快速响应）
    - 中等任务：8 步（标准 ReAct）
    - 复杂任务：15 步（深度推理）
    - 超复杂任务：25 步（多阶段执行）
    """
    if understanding is None:
        return settings.AGENT_MAX_STEPS  # 默认 8

    complexity = understanding.task_complexity
    if complexity == "simple":
        return 4
    elif complexity == "medium":
        return 8
    elif complexity == "complex":
        return 15
    else:  # ultra
        return 25
```

#### 3.2.5 TO-DO List 约束机制

```python
class TodoList:
    """动态 TO-DO List — 对标 Trae 的 TO-DO Tool
    
    约束流程避免模型过度发散
    过程中可更新以实现纠偏
    """
    
    items: List[TodoItem]
    
    def add_item(self, description: str, tool: str = None, priority: int = 0):
        """动态添加任务项（支持运行时调整）"""
        ...
    
    def mark_completed(self, item_id: str):
        """标记完成"""
        ...
    
    def mark_failed(self, item_id: str, reason: str):
        """标记失败"""
        ...
    
    def reorder(self, new_order: List[str]):
        """重新排序（模型可调整优先级）"""
        ...
    
    def get_next_pending(self) -> Optional[TodoItem]:
        """获取下一个待办项"""
        ...
    
    def to_prompt(self) -> str:
        """渲染为 prompt 文本（注入到 LLM 上下文）"""
        lines = ["## 当前任务清单（TO-DO List）"]
        for i, item in enumerate(self.items, 1):
            status = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", 
                      "failed": "❌"}[item.status]
            lines.append(f"{i}. {status} {item.description}")
        return "\n".join(lines)
```

### 3.3 多步骤问题解决模块（DynamicPlanner + CheckpointManager）

#### 3.3.1 设计目标

对标 Trae AI 的"多步骤规划"——将复杂任务拆分为可执行步骤，支持动态调整和断点续传。

#### 3.3.2 动态规划器

```python
# app/services/agent/dynamic_planner.py

class DynamicPlanner:
    """动态任务规划器
    
    对标 Trae Agent 2.0：
    - 不生成固定完整计划
    - 生成初始 TO-DO List 作为约束
    - 运行中可动态调整
    """

    async def init_todo(
        self,
        query: str,
        understanding: TaskUnderstandingResult,
        user: User,
    ) -> TodoList:
        """初始化 TO-DO List
        
        策略：
        - simple 任务：1-2 个 TODO 项（直接回答）
        - medium 任务：3-5 个 TODO 项
        - complex 任务：5-10 个 TODO 项（分阶段）
        - ultra 任务：10-20 个 TODO 项（里程碑式）
        """
        complexity = understanding.task_complexity
        
        if complexity == "simple":
            return TodoList(items=[
                TodoItem(id="t1", description=f"回答: {query}", tool=None)
            ])
        
        # 中等以上复杂度：调用 LLM 生成 TO-DO
        prompt = self._build_todo_prompt(query, understanding, complexity)
        response = await self.llm_router.stream_complete(prompt)
        return self._parse_todo_response(response)

    async def replan(
        self,
        current_todo: TodoList,
        execution_context: ExecutionContext,
        reason: str,
    ) -> TodoList:
        """动态重新规划
        
        触发条件：
        - 工具失败且无法恢复
        - 发现新需求
        - 用户追加要求
        - 自评估不达标
        """
        prompt = self._build_replan_prompt(current_todo, execution_context, reason)
        response = await self.llm_router.stream_complete(prompt)
        new_todo = self._parse_todo_response(response)
        
        # 保留已完成项
        for item in current_todo.items:
            if item.status == "completed":
                new_todo.mark_completed(item.id)
        
        return new_todo
```

#### 3.3.3 断点续传管理器

```python
# app/services/agent/checkpoint.py

class CheckpointManager:
    """断点续传管理器 — 对标 Trae 的 Task Manager + Resume Memory
    
    功能：
    - 每步自动保存执行状态
    - 任务中断后可恢复
    - 支持跨会话恢复
    """
    
    async def save(
        self,
        task_id: str,
        step: int,
        todo_list: TodoList,
        context_summary: str,
        tool_results: List[Dict] = None,
    ) -> str:
        """保存检查点
        
        存储：
        - 当前步数
        - TO-DO List 状态
        - 上下文摘要
        - 工具调用结果
        - 时间戳
        """
        checkpoint = AgentCheckpoint(
            task_id=task_id,
            step=step,
            todo_list=todo_list.to_dict(),
            context_summary=context_summary,
            tool_results=tool_results or [],
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(checkpoint)
        await self.db.commit()
        return checkpoint.id

    async def resume(self, task_id: str) -> Optional[ResumeContext]:
        """从最近检查点恢复"""
        checkpoint = await self._get_latest_checkpoint(task_id)
        if not checkpoint:
            return None
        
        return ResumeContext(
            step=checkpoint.step,
            todo_list=TodoList.from_dict(checkpoint.todo_list),
            context_summary=checkpoint.context_summary,
            tool_results=checkpoint.tool_results,
        )
```

### 3.4 上下文保持模块（ContextManager）

#### 3.4.1 设计目标

对标 Trae AI 的"统一上下文窗口 + 滑动窗口 + Long-term Memory"。

#### 3.4.2 三层记忆架构

```python
# app/services/agent/memory/context_manager.py

class ContextManager:
    """统一上下文管理器
    
    对标 Trae Agent 2.0:
    - 统一上下文窗口（历史+工具日志全可见）
    - 滑动窗口（新到旧动态拼接）
    - Long-term Memory（跨会话不遗忘）
    """
    
    def __init__(
        self,
        session_mgr: SessionManager,
        vector_memory: VectorMemory,
        long_term_memory: LongTermMemory,
        max_tokens: int = 32000,
    ):
        self.session_mgr = session_mgr
        self.vector_memory = vector_memory
        self.long_term_memory = long_term_memory
        self.max_tokens = max_tokens

    async def build_context(
        self,
        query: str,
        session_id: str,
        todo_list: TodoList,
        step: int,
    ) -> UnifiedContext:
        """构建统一上下文（按优先级拼接）"""
        
        layers = []
        
        # L1: 系统层（固定，最高优先级）
        system_prompt = REACT_SYSTEM_PROMPT.format(
            max_steps=step + 5,
            project_context=await self._load_project_context(session_id),
        )
        layers.append(ContextLayer(
            name="system",
            content=system_prompt,
            priority=100,
            token_count=self._estimate_tokens(system_prompt),
            compressible=False,
        ))
        
        # L2: 长期记忆层（跨会话知识）
        long_term = await self.long_term_memory.retrieve(user_id, query, top_k=3)
        if long_term:
            layers.append(ContextLayer(
                name="long_term_memory",
                content=f"## 跨会话记忆\n{long_term}",
                priority=90,
                token_count=self._estimate_tokens(long_term),
                compressible=True,
            ))
        
        # L3: 向量检索层（相关历史）
        vector_results = await self.vector_memory.search(query, top_k=5)
        if vector_results:
            layers.append(ContextLayer(
                name="vector_memory",
                content=f"## 相关历史\n{vector_results}",
                priority=80,
                token_count=self._estimate_tokens(vector_results),
                compressible=True,
            ))
        
        # L4: TO-DO 层（当前任务约束）
        todo_prompt = todo_list.to_prompt()
        layers.append(ContextLayer(
            name="todo_list",
            content=todo_prompt,
            priority=95,
            token_count=self._estimate_tokens(todo_prompt),
            compressible=False,
        ))
        
        # L5: 会话历史层（滑动窗口）
        history = await self._build_sliding_window(session_id, remaining_tokens)
        layers.append(ContextLayer(
            name="session_history",
            content=history,
            priority=70,
            token_count=self._estimate_tokens(history),
            compressible=True,
        ))
        
        # L6: 当前消息层
        layers.append(ContextLayer(
            name="current_message",
            content=query,
            priority=100,
            token_count=self._estimate_tokens(query),
            compressible=False,
        ))
        
        # Token 预算管理：按优先级保留
        return self._assemble_within_budget(layers, self.max_tokens)
```

#### 3.4.3 滑动窗口机制

```python
async def _build_sliding_window(
    self,
    session_id: str,
    max_tokens: int,
) -> str:
    """滑动窗口上下文构建
    
    策略（对标 Trae）：
    - 最近 N 轮完整保留
    - 更早的对话 LLM 摘要压缩
    - 工具调用日志保留摘要
    """
    context = await self.session_mgr.get_context(session_id)
    messages = context.get("messages", [])
    
    if not messages:
        return ""
    
    # 1. 最近 4 轮完整保留
    recent = messages[-8:]  # 4 轮 = 8 条消息（user+assistant）
    recent_text = self._format_messages(recent)
    recent_tokens = self._estimate_tokens(recent_text)
    
    # 2. 如果预算足够，保留更多
    remaining = max_tokens - recent_tokens
    older = messages[:-8]
    
    if remaining > 500 and older:
        # 从新到旧逐步添加
        kept = []
        for msg in reversed(older):
            msg_tokens = self._estimate_tokens(self._format_message(msg))
            if remaining - msg_tokens < 200:
                break
            kept.insert(0, msg)
            remaining -= msg_tokens
        
        if kept:
            kept_text = self._format_messages(kept)
            # 3. 更早的消息用摘要
            much_older = older[:-len(kept)]
            if much_older:
                summary = context.get("summary", "")
                if summary:
                    return f"## 历史摘要\n{summary}\n\n## 近期对话\n{kept_text}\n{recent_text}"
            return f"{kept_text}\n{recent_text}"
    
    return recent_text
```

#### 3.4.4 向量记忆库

```python
# app/services/agent/memory/vector_memory.py

class VectorMemory:
    """向量记忆库 — 对标 Trae 的 Long-term Memory
    
    功能：
    - 存储历史对话的向量化表示
    - 语义检索相关历史
    - 跨会话知识传递
    """
    
    def __init__(self, embedding_dim: int = 1536):
        self.embedding_dim = embedding_dim
        self._store = None  # chromadb collection
        
    async def store(
        self,
        session_id: str,
        user_id: str,
        content: str,
        metadata: Dict[str, Any],
    ) -> None:
        """存储记忆项"""
        embedding = await self._embed(content)
        self._store.add(
            ids=[str(uuid4())],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{
                "session_id": session_id,
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **metadata,
            }],
        )
    
    async def search(
        self,
        query: str,
        user_id: str = None,
        top_k: int = 5,
    ) -> List[MemoryItem]:
        """语义检索相关记忆"""
        query_embedding = await self._embed(query)
        results = self._store.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"user_id": user_id} if user_id else None,
        )
        return [MemoryItem(...) for ... in results]
```

#### 3.4.5 长期记忆

```python
# app/services/agent/memory/long_term.py

class LongTermMemory:
    """长期记忆 — 对标 Trae 的 Resume Memory
    
    功能：
    - 提取会话中的关键知识
    - 用户偏好积累
    - 项目知识沉淀
    """
    
    async def extract_and_store(
        self,
        session_id: str,
        user_id: str,
        conversation: List[Dict],
    ) -> List[KnowledgeItem]:
        """从会话中提取关键知识并存储
        
        使用 LLM 提取：
        - 用户偏好（如"用户喜欢表格形式"）
        - 项目知识（如"当前项目关注 EGFR 靶点"）
        - 重要发现（如"EGFR 突变率 45%"）
        - 工具使用经验（如"search_ncbi 查 ClinVar 最快"）
        """
        prompt = LONG_TERM_EXTRACTION_PROMPT.format(conversation=conversation)
        response = await self.llm_router.complete(prompt)
        knowledge_items = self._parse_knowledge(response)
        
        for item in knowledge_items:
            await self._store_knowledge(user_id, item)
        
        return knowledge_items
    
    async def retrieve(
        self,
        user_id: str,
        query: str,
        top_k: int = 3,
    ) -> str:
        """检索相关长期记忆"""
        items = await self._search(user_id, query, top_k)
        return "\n".join(f"- {item.content}" for item in items)
```

### 3.5 用户意图识别模块（IntentRecognizer）

#### 3.5.1 设计目标

对标 Trae AI 的"需求分析"——深入理解用户目标及上下文，明确需求要点。

#### 3.5.2 架构设计

```python
# app/services/agent/intent.py

class IntentRecognizer:
    """用户意图识别模块
    
    能力：
    - 模糊指令澄清
    - 潜在需求挖掘
    - 情绪感知
    - 上下文意图推断
    """
    
    async def recognize(
        self,
        user_input: str,
        session_context: Dict[str, Any],
    ) -> IntentRecognitionResult:
        """识别用户意图"""
        
        # 1. 快速意图分类（启发式）
        quick_intent = self._quick_classify(user_input)
        if quick_intent == "greeting":
            return IntentRecognitionResult(
                intent=UserIntent.GREETING,
                confidence=1.0,
                is_ambiguous=False,
            )
        
        # 2. 深度意图分析（LLM）
        deep_result = await self._deep_analyze(user_input, session_context)
        
        # 3. 模糊度评估
        is_ambiguous = self._assess_ambiguity(deep_result)
        
        # 4. 澄清问题生成（如果模糊）
        clarification = None
        if is_ambiguous:
            clarification = await self._generate_clarification(
                user_input, deep_result
            )
        
        return IntentRecognitionResult(
            intent=deep_result.intent,
            confidence=deep_result.confidence,
            is_ambiguous=is_ambiguous,
            clarification_question=clarification,
            potential_needs=deep_result.potential_needs,
            emotional_state=deep_result.emotional_state,
        )
    
    def _quick_classify(self, user_input: str) -> str:
        """快速启发式分类（避免 LLM 调用）"""
        input_lower = user_input.lower().strip()
        
        # 问候
        if input_lower in {"你好", "hello", "hi", "在吗"}:
            return "greeting"
        
        # 命令式（动词开头）
        if any(input_lower.startswith(v) for v in ["分析", "查询", "设计", "创建", "删除"]):
            return "command"
        
        # 疑问式
        if any(input_lower.startswith(q) for q in ["什么是", "为什么", "如何", "怎么"]):
            return "question"
        
        return "unknown"
```

#### 3.5.3 意图识别 Prompt

```python
INTENT_RECOGNITION_PROMPT = """你是用户意图分析专家。分析用户的输入，识别其真实意图。

# 用户输入
{user_input}

# 会话上下文
{session_context}

# 分析维度

1. **主意图分类**（选一）：
   - data_analysis: 数据分析请求
   - target_discovery: 靶点发现
   - molecule_design: 分子设计
   - literature_query: 文献查询
   - concept_explanation: 概念解释
   - result_interpretation: 结果解读
   - project_management: 项目管理
   - greeting: 问候
   - feedback: 反馈
   - clarification: 澄清

2. **模糊度评估**：
   - low: 指令清晰，可直接执行
   - medium: 有歧义但可推断
   - high: 需要澄清才能执行

3. **潜在需求**（用户未明说但可能需要的）：
   例如：用户问"EGFR 是什么"，潜在需求可能包括"EGFR 靶点的临床意义"和"EGFR 相关药物"

4. **情绪状态**（影响回复语气）：
   - neutral: 中性
   - urgent: 紧急
   - confused: 困惑
   - frustrated: 沮丧

# 输出格式（JSON）
{{
  "intent": "<主意图>",
  "confidence": <0.0-1.0>,
  "ambiguity_level": "<low|medium|high>",
  "potential_needs": ["<潜在需求1>", "<潜在需求2>"],
  "emotional_state": "<neutral|urgent|confused|frustrated>",
  "suggested_clarification": "<若 ambiguity=high，建议的澄清问题>"
}}
"""
```

---

## 四、Agent 与工具集成框架

### 4.1 设计目标

确保 Agent 作为"大脑"能够：
- 有效衔接并调度各类工具
- 分析工具返回的数据
- 根据分析结果向各工具发出精准指令
- 实现工具间的数据流转与协同工作

### 4.2 工具集成框架架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Agent（大脑）                                │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  推理决策    │  │  上下文分析  │  │  结果整合    │            │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘            │
│         │                │                │                    │
│         └────────────────┼────────────────┘                    │
│                          │                                      │
└──────────────────────────┼──────────────────────────────────────┘
                           │
                    ┌──────┴──────┐
                    │  ToolScheduler│  ← 工具调度中枢
                    │  (工具调度器)  │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────┴─────┐   ┌─────┴─────┐   ┌─────┴─────┐
    │ 内置工具   │   │ MCP 工具  │   │ 动态工具  │
    │ (19个)    │   │ (外部)    │   │ (运行时)  │
    └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                    ┌──────┴──────┐
                    │ DataFlowMgr  │  ← 数据流转管理
                    │ (数据流转)    │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │ ResultAggr  │  ← 结果聚合
                    │ (结果聚合)    │
                    └─────────────┘
```

### 4.3 工具调度器（ToolScheduler）

```python
# app/services/agent/tool_scheduler.py

class ToolScheduler:
    """工具调度器 — Agent 作为"大脑"调度工具的核心
    
    对标 Trae AI 的"完整的工具访问权限"：
    - 智能工具选择（基于质量评估）
    - 并行/串行调度
    - 参数自动填充
    - 结果数据流转
    """
    
    def __init__(
        self,
        registry: ToolRegistry,
        quality_tracker: ToolQualityTracker,
        data_flow_mgr: DataFlowManager,
    ):
        self.registry = registry
        self.quality_tracker = quality_tracker
        self.data_flow_mgr = data_flow_mgr

    async def execute(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        user: User,
        context: UnifiedContext,
    ) -> ToolResult:
        """执行单个工具"""
        
        # 1. 参数自动补全（从上下文推断缺失参数）
        completed_args = await self._auto_complete_args(
            tool_name, tool_args, context
        )
        
        # 2. 执行工具
        result = await self.registry.execute_tool(
            tool_name=tool_name,
            params=completed_args,
            user=user,
            db=self.db,
            context=context,
        )
        
        # 3. 记录工具质量
        await self.quality_tracker.record(
            tool_name=tool_name,
            success=result.success,
            duration_ms=result.duration_ms,
            error=result.error if not result.success else None,
        )
        
        # 4. 存储结果到数据流管理器
        self.data_flow_mgr.store_result(tool_name, completed_args, result)
        
        return result

    async def execute_parallel(
        self,
        tool_calls: List[ToolCall],
        user: User,
        context: UnifiedContext,
    ) -> List[ToolResult]:
        """并行执行多个工具
        
        对标 Trae 的原生并行能力
        """
        tasks = [
            self.execute(call.name, call.args, user, context)
            for call in tool_calls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 异常转换为 ToolResult.fail
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(ToolResult.fail(
                    error=f"工具执行异常: {result}"
                ))
            else:
                final_results.append(result)
        
        return final_results

    async def recommend_tool(
        self,
        task_description: str,
        available_tools: List[str],
    ) -> str:
        """基于任务描述推荐最优工具"""
        ranked = await self.quality_tracker.rank_tools(available_tools)
        if ranked:
            return ranked[0]["tool_name"]
        return available_tools[0] if available_tools else None
```

### 4.4 数据流转管理器（DataFlowManager）

```python
# app/services/agent/data_flow.py

class DataFlowManager:
    """数据流转管理器
    
    对标 Trae 的工具间数据协同：
    - 工具输出结构化存储
    - 参数模板自动引用上游结果
    - 数据血缘追踪
    """
    
    def __init__(self):
        self._results: Dict[str, ToolResultRecord] = {}
        self._data_lineage: List[DataLineageEdge] = []

    def store_result(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: ToolResult,
    ) -> str:
        """存储工具结果，返回引用 ID"""
        record_id = f"{tool_name}_{len(self._results)}"
        self._results[record_id] = ToolResultRecord(
            id=record_id,
            tool_name=tool_name,
            args=args,
            result=result,
            timestamp=datetime.now(timezone.utc),
        )
        return record_id

    def resolve_reference(self, reference: str) -> Any:
        """解析参数引用 ${step_id.field}"""
        # 例如 ${search_ncbi_0.data.gene_symbol}
        parts = reference.split(".")
        record_id = parts[0]
        field_path = parts[1:]
        
        record = self._results.get(record_id)
        if not record:
            raise ValueError(f"引用不存在: {record_id}")
        
        value = record.result.data
        for field in field_path:
            if isinstance(value, dict):
                value = value.get(field)
            else:
                value = getattr(value, field, None)
        
        return value

    def get_data_lineage(self, tool_name: str = None) -> List[DataLineageEdge]:
        """获取数据血缘（工具间数据依赖关系）"""
        if tool_name:
            return [e for e in self._data_lineage if e.target == tool_name]
        return self._data_lineage
```

### 4.5 参数自动补全

```python
async def _auto_complete_args(
    self,
    tool_name: str,
    args: Dict[str, Any],
    context: UnifiedContext,
) -> Dict[str, Any]:
    """从上下文自动补全缺失的工具参数
    
    对标 Trae 的上下文理解能力：
    - 从项目上下文补全 project_id
    - 从对话历史补全 target_id
    - 从 TO-DO List 补全 analysis_type
    """
    tool_schema = self.registry.get_schema(tool_name)
    completed = dict(args)
    
    for param_name, param_schema in tool_schema.get("properties", {}).items():
        if param_name in completed:
            continue
        
        # 尝试从上下文推断
        if param_name == "project_id":
            project = context.get("project")
            if project:
                completed[param_name] = project["id"]
        
        elif param_name == "target_id":
            recent_target = context.get("recent_target")
            if recent_target:
                completed[param_name] = recent_target["id"]
        
        elif param_name == "dataset_id":
            recent_dataset = context.get("recent_dataset")
            if recent_dataset:
                completed[param_name] = recent_dataset["id"]
    
    return completed
```

### 4.6 Native Function Call 支持

```python
# app/services/agent/native_function_call.py

class NativeFunctionCallAdapter:
    """Native Function Call 适配器
    
    对标 Trae Agent 2.0 的 Keep Tools Simple 原则：
    - 使用 Native Function Call 代替 JSON Schema 解析
    - 降低模型决策难度
    - 提高工具调用准确率
    """
    
    def to_function_schema(self, tools: List[AgentTool]) -> List[Dict]:
        """转换为 LLM 的 function calling 格式"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            }
            for tool in tools
        ]

    async def call_with_functions(
        self,
        llm_router: LLMRouter,
        messages: List[Dict],
        tools: List[AgentTool],
    ) -> LLMResponse:
        """使用 Native Function Call 调用 LLM"""
        function_schemas = self.to_function_schema(tools)
        
        response = await llm_router.chat_with_functions(
            messages=messages,
            functions=function_schemas,
        )
        
        # 解析 function call 结果
        if response.get("function_call"):
            return LLMResponse(
                type="function_call",
                function_name=response["function_call"]["name"],
                function_args=json.loads(response["function_call"]["arguments"]),
            )
        else:
            return LLMResponse(
                type="content",
                content=response["content"],
            )
```

### 4.7 MCP 协议网关

```python
# app/services/agent/mcp_gateway.py

class MCPGateway:
    """MCP (Model Context Protocol) 网关
    
    对标 Trae AI 的 MCP 集成：
    - 外部资源按需接入
    - 统一工具接口
    - 动态发现 MCP Server
    """
    
    async def discover_servers(self) -> List[MCPServerInfo]:
        """发现可用的 MCP Server"""
        ...
    
    async def call_mcp_tool(
        self,
        server: str,
        tool: str,
        args: Dict[str, Any],
    ) -> ToolResult:
        """调用 MCP 工具"""
        ...
    
    def to_agent_tool(self, mcp_tool: MCPTool) -> AgentTool:
        """将 MCP 工具适配为 AgentTool"""
        return MCPToolAdapter(mcp_tool)
```

### 4.8 沙箱执行器增强

```python
# app/services/agent/sandbox_v2.py

class EnhancedSandboxExecutor:
    """增强沙箱执行器
    
    对标 Trae AI 的终端命令执行：
    - 支持多语言（Python/R/Bash）
    - 持久化文件系统
    - 包管理（pip install）
    - GPU 支持（可选）
    - 输出流式推送
    """
    
    async def execute(
        self,
        code: str,
        language: str = "python",
        files: List[FileRef] = None,
        packages: List[str] = None,
        stream_output: bool = True,
    ) -> SandboxResult:
        """执行代码
        
        1. 创建持久化容器（按用户隔离）
        2. 安装请求的包
        3. 挂载用户文件
        4. 流式执行代码
        5. 实时推送 stdout/stderr
        """
        ...
```

---

## 五、系统测试与评估标准

### 5.1 功能完整性测试

#### 5.1.1 测试矩阵

| 测试层级 | 测试范围 | 测试数量 | 通过标准 |
|---------|---------|---------|---------|
| **单元测试** | 每个模块独立功能 | ≥200 | 覆盖率 ≥80% |
| **集成测试** | 模块间交互 | ≥50 | 全部通过 |
| **端到端测试** | 完整工作流 | ≥30 | 全部通过 |
| **压力测试** | 高并发/大数据 | ≥10 | 性能达标 |

#### 5.1.2 关键功能测试用例

```python
# tests/agent_v2/test_intent_recognition.py
class TestIntentRecognition:
    """意图识别测试"""
    
    @pytest.mark.asyncio
    async def test_clear_intent(self):
        """清晰意图识别"""
        result = await recognizer.recognize("分析 EGFR 突变数据", {})
        assert result.intent == UserIntent.DATA_ANALYSIS
        assert result.confidence > 0.8
        assert not result.is_ambiguous
    
    @pytest.mark.asyncio
    async def test_ambiguous_intent(self):
        """模糊意图识别"""
        result = await recognizer.recognize("帮我看看这个", {})
        assert result.is_ambiguous
        assert result.clarification_question is not None
    
    @pytest.mark.asyncio
    async def test_potential_needs(self):
        """潜在需求挖掘"""
        result = await recognizer.recognize("EGFR 是什么", {})
        assert "clinical_significance" in result.potential_needs
    
    @pytest.mark.asyncio
    async def test_emotional_state_urgent(self):
        """情绪感知"""
        result = await recognizer.recognize("紧急！患者用药后出现严重不良反应", {})
        assert result.emotional_state == "urgent"


# tests/agent_v2/test_agentic_loop.py
class TestAgenticLoop:
    """自主决策循环测试"""
    
    @pytest.mark.asyncio
    async def test_autonomous_tool_selection(self):
        """自主工具选择"""
        # Agent 应根据任务自主选择最优工具
        result = await engine.run(
            task_id="t1",
            query="查询 EGFR 相关文献",
            session_id="s1",
            user=test_user,
        )
        assert result["status"] == TaskStatus.COMPLETED
        assert any(step["tool"] == "search_ncbi" for step in result["steps"])
    
    @pytest.mark.asyncio
    async def test_dynamic_todo_management(self):
        """动态 TO-DO 管理"""
        # Agent 应能动态更新 TO-DO List
        result = await engine.run(...)
        todo_history = result["todo_history"]
        assert len(todo_history) > 1  # 有更新
    
    @pytest.mark.asyncio
    async def test_self_evaluation_rejects_low_quality(self):
        """自评估拒绝低质量答案"""
        # 模拟低质量答案，验证 Agent 会继续优化
        ...
    
    @pytest.mark.asyncio
    async def test_checkpoint_resume(self):
        """断点续传"""
        # 执行 3 步后中断，恢复后应从第 4 步继续
        ...
    
    @pytest.mark.asyncio
    async def test_parallel_tool_execution(self):
        """并行工具执行"""
        # 同时查询 NCBI 和网络搜索
        ...
```

### 5.2 性能基准测试

#### 5.2.1 性能指标

| 指标 | 目标值 | 测量方法 |
|------|--------|---------|
| **首字延迟** | < 500ms | 从请求到第一个 token 推送 |
| **简单问答延迟** | < 2s | 无工具调用的问答 |
| **单工具任务延迟** | < 5s | 含 1 次工具调用 |
| **复杂任务延迟** | < 30s | 含 3-5 次工具调用 |
| **超复杂任务延迟** | < 120s | 含 10+ 次工具调用 |
| **并发吞吐量** | ≥ 50 req/s | 同时处理 50 个请求 |
| **工具调用准确率** | ≥ 95% | 正确工具选择 / 总调用 |
| **工具调用成功率** | ≥ 90% | 成功执行 / 总调用 |
| **Token 使用效率** | ≤ 8000 tokens/任务 | 平均 token 消耗 |
| **内存使用** | ≤ 512MB | 单任务峰值内存 |

#### 5.2.2 基准测试脚本

```python
# tests/benchmark/test_agent_benchmark.py

class TestAgentBenchmark:
    """Agent 性能基准测试"""
    
    @pytest.mark.benchmark
    async def test_first_token_latency(self, benchmark):
        """首字延迟基准"""
        async def run():
            engine = build_engine()
            first_token_time = None
            async for event in engine.run_stream(...):
                if event.type == "token" and first_token_time is None:
                    first_token_time = time.time()
                    break
            return first_token_time - start_time
        
        result = benchmark(run)
        assert result < 0.5  # < 500ms
    
    @pytest.mark.benchmark
    async def test_tool_accuracy(self, benchmark):
        """工具选择准确率"""
        test_cases = load_test_cases("tool_selection_cases.json")
        correct = 0
        for case in test_cases:
            result = await engine.select_tool(case.query)
            if result == case.expected_tool:
                correct += 1
        accuracy = correct / len(test_cases)
        assert accuracy >= 0.95
```

### 5.3 用户体验评估

#### 5.3.1 评估维度

| 维度 | 评估指标 | 评分方法 |
|------|---------|---------|
| **响应速度** | 首字延迟 + 完成时间 | 自动测量 |
| **答案质量** | 准确性 + 完整性 + 相关性 | 人工评分 1-5 |
| **交互流畅度** | 对话连贯性 + 上下文保持 | 人工评分 1-5 |
| **工具使用** | 工具选择合理性 + 结果利用 | 人工评分 1-5 |
| **错误处理** | 失败恢复 + 错误提示清晰度 | 人工评分 1-5 |
| **用户满意度** | 整体满意度 | 问卷 1-5 |

#### 5.3.2 评估方法

```python
# tests/evaluation/test_user_experience.py

class UserExperienceEvaluator:
    """用户体验评估器"""
    
    EVALUATION_TASKS = [
        # 简单任务
        {"query": "什么是 EGFR？", "expected_time": 2, "expected_tools": 0},
        # 中等任务
        {"query": "分析当前项目的靶点", "expected_time": 10, "expected_tools": 2},
        # 复杂任务
        {"query": "为 EGFR 靶点设计新分子并评估类药性", "expected_time": 30, "expected_tools": 4},
        # 超复杂任务
        {"query": "整合多组学数据发现靶点，设计分子，并生成治疗方案", "expected_time": 120, "expected_tools": 8},
    ]
    
    async def evaluate(self) -> EvaluationReport:
        """执行全套评估"""
        results = []
        for task in self.EVALUATION_TASKS:
            result = await self._evaluate_task(task)
            results.append(result)
        return EvaluationReport(results)
```

### 5.4 与 Trae AI 的能力对比测试

#### 5.4.1 对比测试框架

```python
# tests/comparison/test_trae_comparison.py

class TraeAIComparisonTest:
    """与 Trae AI 能力对比测试
    
    对比维度：
    1. 自主决策能力
    2. 工具调度准确性
    3. 上下文保持能力
    4. 多步骤任务完成率
    5. 错误恢复能力
    6. 响应延迟
    """
    
    COMPARISON_TASKS = [
        # 任务 1: 自主工具选择
        {
            "name": "autonomous_tool_selection",
            "query": "查询 EGFR 最新研究进展",
            "expected_tools": ["search_ncbi", "web_search"],
            "comparison_metrics": ["accuracy", "latency", "completeness"],
        },
        # 任务 2: 多步骤规划
        {
            "name": "multi_step_planning",
            "query": "发现靶点 → 设计分子 → 评估类药性",
            "expected_steps": 3,
            "comparison_metrics": ["planning_accuracy", "execution_success"],
        },
        # 任务 3: 上下文保持
        {
            "name": "context_retention",
            "queries": [
                "分析项目 P001 的靶点",
                "为第一个靶点设计分子",  # 需要记住"第一个靶点"
                "评估该分子的类药性",     # 需要记住"该分子"
            ],
            "comparison_metrics": ["context_accuracy", "reference_resolution"],
        },
        # 任务 4: 错误恢复
        {
            "name": "error_recovery",
            "query": "查询不存在的基因 XXX 的靶点",
            "expected_behavior": "识别错误 → 切换工具 → 获取结果",
            "comparison_metrics": ["recovery_success", "recovery_speed"],
        },
    ]
```

#### 5.4.2 能力对标矩阵

| 能力 | Trae AI 表现 | 目标表现 | 评估方法 |
|------|-------------|---------|---------|
| 自主决策 | 自主选择工具 | ≥90% 准确率 | 工具选择测试集 |
| 工具调度 | Native Function Call | ≥95% 准确率 | 100 案例测试 |
| 上下文保持 | 统一窗口 | 10 轮对话不失忆 | 多轮上下文测试 |
| 多步骤规划 | 动态 TO-DO | ≥85% 完成率 | 复杂任务测试 |
| 错误恢复 | Effective Feedback | ≥80% 恢复率 | 故障注入测试 |
| 首字延迟 | < 500ms | < 500ms | 性能基准 |
| 答案质量 | SWE-bench 75% | 领域 ≥85% | 人工评估 |

---

## 六、分阶段实施计划

### 6.1 实施路线图

```
Phase 1 (2周)          Phase 2 (3周)          Phase 3 (3周)          Phase 4 (2周)
┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  基础能力     │      │  核心引擎     │      │  高级能力     │      │  优化与验收   │
│  构建         │ ──>  │  重构         │ ──>  │  开发         │ ──>  │  对标        │
└──────────────┘      └──────────────┘      └──────────────┘      └──────────────┘
     │                      │                      │                      │
     ▼                      ▼                      ▼                      ▼
 意图识别              Agentic Loop            向量记忆              性能优化
 任务理解              动态规划器              长期记忆              对标测试
 TO-DO List            工具调度器              自评估                用户评估
                       断点续传                MCP 网关              文档完善
```

### 6.2 Phase 1: 基础能力构建（第 1-2 周）

#### 6.2.1 里程碑

| 里程碑 | 交付物 | 验收标准 |
|--------|--------|---------|
| M1.1 | IntentRecognizer 模块 | 意图分类准确率 ≥85% |
| M1.2 | TaskUnderstanding 模块 | 实体提取 F1 ≥0.8 |
| M1.3 | TodoList + DynamicPlanner 初始版 | TO-DO 生成并通过人工审核 |
| M1.4 | 单元测试 ≥60 个 | 覆盖率 ≥80% |

#### 6.2.2 任务分解

| 任务 | 工作量 | 优先级 | 依赖 |
|------|--------|--------|------|
| 实现 IntentRecognizer | 3d | P0 | - |
| 实现 TaskUnderstanding | 3d | P0 | IntentRecognizer |
| 设计 TodoList 数据结构 | 1d | P0 | - |
| 实现 DynamicPlanner.init_todo | 2d | P0 | TodoList |
| 编写意图识别测试 | 2d | P0 | IntentRecognizer |
| 编写任务理解测试 | 2d | P0 | TaskUnderstanding |
| 集成到 AgentEngine | 1d | P1 | 全部模块 |

#### 6.2.3 资源需求

- 开发人员: 1 名
- 测试人员: 0.5 名
- LLM API 预算: ~$200（开发+测试）

### 6.3 Phase 2: 核心引擎重构（第 3-5 周）

#### 6.3.1 里程碑

| 里程碑 | 交付物 | 验收标准 |
|--------|--------|---------|
| M2.1 | AgenticLoopEngine v2 | 通过 L1-L4 集成测试 |
| M2.2 | ToolScheduler + DataFlowManager | 工具调度准确率 ≥90% |
| M2.3 | CheckpointManager | 断点续传成功率 100% |
| M2.4 | 集成测试 ≥30 个 | 全部通过 |

#### 6.3.2 任务分解

| 任务 | 工作量 | 优先级 | 依赖 |
|------|--------|--------|------|
| 设计 AgenticLoopEngine 架构 | 2d | P0 | Phase 1 |
| 实现自主决策循环 | 5d | P0 | 架构设计 |
| 实现动态步数控制 | 1d | P0 | AgenticLoop |
| 实现 ToolScheduler | 3d | P0 | AgenticLoop |
| 实现 DataFlowManager | 2d | P0 | ToolScheduler |
| 实现 CheckpointManager | 3d | P0 | AgenticLoop |
| 集成 Reflector + KnowledgeGap | 2d | P1 | AgenticLoop |
| 编写引擎集成测试 | 3d | P0 | 全部模块 |
| 性能基准测试 | 2d | P1 | 集成测试 |

### 6.4 Phase 3: 高级能力开发（第 6-8 周）

#### 6.4.1 里程碑

| 里程碑 | 交付物 | 验收标准 |
|--------|--------|---------|
| M3.1 | VectorMemory | 向量检索 Top-5 相关性 ≥0.8 |
| M3.2 | LongTermMemory | 跨会话知识传递验证通过 |
| M3.3 | SelfEvaluator | 答案质量评估准确率 ≥80% |
| M3.4 | MCPGateway（实验性） | 至少接入 1 个 MCP Server |

#### 6.4.2 任务分解

| 任务 | 工作量 | 优先级 | 依赖 |
|------|--------|--------|------|
| 设计三层记忆架构 | 1d | P0 | Phase 2 |
| 实现 VectorMemory | 3d | P0 | 架构设计 |
| 实现 LongTermMemory | 3d | P0 | VectorMemory |
| 实现 ContextManager 统一上下文 | 3d | P0 | VectorMemory |
| 实现 SelfEvaluator | 3d | P0 | AgenticLoop |
| 实现 NativeFunctionCall 适配 | 2d | P1 | ToolScheduler |
| MCPGateway 原型 | 3d | P2 | ToolScheduler |
| 增强沙箱执行器 | 3d | P1 | SandboxExecutor |
| 高级能力测试 | 3d | P0 | 全部模块 |

### 6.5 Phase 4: 优化与验收（第 9-10 周）

#### 6.5.1 里程碑

| 里程碑 | 交付物 | 验收标准 |
|--------|--------|---------|
| M4.1 | 性能优化 | 首字延迟 < 500ms |
| M4.2 | 对标测试报告 | 达到 Trae AI 80% 能力 |
| M4.3 | 完整文档 | API 文档 + 使用手册 |
| M4.4 | 上线发布 | 全量测试通过 |

### 6.6 风险评估与应对策略

| 风险 | 概率 | 影响 | 应对策略 |
|------|------|------|---------|
| **LLM 调用成本超预算** | 高 | 高 | 1. Prompt Caching 优化 2. 动态步数控制 3. 简单问题跳过规划 |
| **向量数据库部署复杂** | 中 | 中 | 1. 优先用 SQLite+FAISS 2. 后期迁移 ChromaDB |
| **沙箱安全风险** | 中 | 高 | 1. Docker 隔离 2. 静态+动态代码检查 3. 资源限制 |
| **MCP 生态不成熟** | 高 | 低 | 1. 标记为实验性 2. 优先完善内置工具 3. 预留扩展接口 |
| **性能不达标** | 中 | 高 | 1. 流式输出 2. 异步并行 3. 缓存优化 4. 模型降级 |
| **测试覆盖率不足** | 低 | 中 | 1. TDD 开发 2. CI 卡点 3. 专项测试时间 |
| **模型升级兼容性** | 中 | 中 | 1. 适配器模式 2. LLMRouter 抽象 3. 版本化 Prompt |
| **并发冲突** | 中 | 中 | 1. 异步锁 2. 乐观并发 3. 状态机管理 |

### 6.7 资源需求总览

| 资源 | Phase 1 | Phase 2 | Phase 3 | Phase 4 | 合计 |
|------|---------|---------|---------|---------|------|
| 开发人员 | 1×2w | 1×3w | 1×3w | 1×2w | 10 人周 |
| 测试人员 | 0.5×2w | 0.5×3w | 0.5×3w | 1×2w | 6.5 人周 |
| LLM API 费用 | $200 | $500 | $300 | $200 | $1200 |
| 基础设施 | - | $100 | $200 | $100 | $400 |
| **总成本** | | | | | **~$1600 + 16.5 人周** |

---

## 附录

### A. 配置参数汇总

```python
# config.py 新增配置项

# ===== Agent v2 架构开关 =====
AGENT_VERSION: str = "v2"                          # v1 (Legacy) / v2 (Agentic)
AGENT_USE_NATIVE_FUNCTION_CALL: bool = True        # Native Function Call
AGENT_USE_DYNAMIC_PLANNER: bool = True             # 动态规划
AGENT_USE_VECTOR_MEMORY: bool = False             # 向量记忆（需 chromadb）
AGENT_USE_LONG_TERM_MEMORY: bool = True            # 长期记忆
AGENT_USE_SELF_EVALUATION: bool = True              # 自我评估
AGENT_USE_CHECKPOINT: bool = True                  # 断点续传
AGENT_USE_MCP_GATEWAY: bool = False                # MCP 网关（实验性）

# ===== 动态步数控制 =====
AGENT_DYNAMIC_STEPS_SIMPLE: int = 4
AGENT_DYNAMIC_STEPS_MEDIUM: int = 8
AGENT_DYNAMIC_STEPS_COMPLEX: int = 15
AGENT_DYNAMIC_STEPS_ULTRA: int = 25

# ===== TO-DO List =====
AGENT_TODO_MAX_ITEMS: int = 10
AGENT_TODO_ENABLE_DYNAMIC_UPDATE: bool = True

# ===== 自评估 =====
AGENT_SELF_EVAL_THRESHOLD: float = 0.7
AGENT_SELF_EVAL_MAX_RETRIES: int = 2

# ===== 上下文管理 =====
AGENT_CONTEXT_MAX_TOKENS: int = 32000
AGENT_CONTEXT_RECENT_ROUNDS: int = 4               # 完整保留的最近轮数
AGENT_CONTEXT_SLIDING_WINDOW: bool = True

# ===== 向量记忆 =====
AGENT_VECTOR_MEMORY_EMBEDDING_DIM: int = 1536
AGENT_VECTOR_MEMORY_TOP_K: int = 5

# ===== 长期记忆 =====
AGENT_LONG_TERM_MEMORY_TOP_K: int = 3
AGENT_LONG_TERM_EXTRACTION_ENABLED: bool = True
```

### B. 新增文件清单

```
backend/app/services/agent/
├── intent.py                          # 意图识别模块
├── understanding.py                   # 任务理解模块
├── agentic_loop.py                    # 自主决策引擎 v2
├── dynamic_planner.py                 # 动态规划器
├── checkpoint.py                      # 断点续传管理器
├── tool_scheduler.py                  # 工具调度器
├── data_flow.py                       # 数据流转管理器
├── native_function_call.py            # Native Function Call 适配
├── mcp_gateway.py                     # MCP 协议网关
├── self_evaluator.py                  # 自评估模块
├── memory/
│   ├── __init__.py
│   ├── context_manager.py             # 统一上下文管理
│   ├── sliding_window.py              # 滑动窗口
│   ├── vector_memory.py               # 向量记忆库
│   └── long_term.py                   # 长期记忆
├── sandbox_v2.py                      # 增强沙箱执行器
└── todo_list.py                       # TO-DO List 数据结构

backend/tests/agent_v2/
├── test_intent.py
├── test_understanding.py
├── test_agentic_loop.py
├── test_dynamic_planner.py
├── test_tool_scheduler.py
├── test_data_flow.py
├── test_checkpoint.py
├── test_context_manager.py
├── test_vector_memory.py
├── test_long_term_memory.py
├── test_self_evaluator.py
└── test_integration.py

backend/tests/benchmark/
├── test_performance.py
└── test_comparison.py
```

### C. 参考文献

- [Trae Agent 概述](https://docs.trae.ai/ide/agent-overview)
- [Trae Agent 2.0 架构博客](https://www.trae.ai/blog/product_thought_0617)
- [Trae Agent 技术论文 arXiv:2507.23370](https://arxiv.org/pdf/2507.23370)
- [Trae Agent 开源仓库](https://github.com/bytedance/trae-agent)
- [Turn-Control Strategies 论文 arXiv:2510.16786](https://arxiv.org/pdf/2510.16786)
