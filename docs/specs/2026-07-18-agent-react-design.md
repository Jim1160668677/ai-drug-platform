# AI Agent 设计文档 — ReAct 增强型智能助手

## 概述

在现有 AI 药物研发平台基础上，构建一个基于 ReAct（Reasoning + Acting）模式的智能 Agent，作为平台的统一入口和指挥中心。Agent 具备自然语言数据分析、自主任务规划与执行、跨模块知识推理、主动建议与预警四大核心能力。

**技术路线**：基于现有 LLM 服务增强，不引入新框架，复用现有 FastAPI 后端和 LLM 基础设施。

---

## 1. 整体架构

```
┌─────────────────────────────────────────────────┐
│                 前端 (Next.js)                    │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │  聊天对话面板  │    │    动态结果面板       │   │
│  │  (左侧)      │    │    (右侧)            │   │
│  └──────────────┘    └──────────────────────┘   │
└────────────────┬────────────────────────────────┘
                 │ WebSocket / REST API
┌────────────────▼────────────────────────────────┐
│            FastAPI 后端 (现有)                     │
│  ┌──────────────────────────────────────────┐   │
│  │        Agent 服务层 (新增)                  │   │
│  │  - 任务规划器 | 工具注册中心 | 执行引擎     │   │
│  │  - 会话管理器                              │   │
│  └────────────────┬─────────────────────────┘   │
│                   │                              │
│  ┌────────────────▼─────────────────────────┐   │
│  │         工具适配器层 (新增)                  │   │
│  │  - 靶点发现 | 分子设计 | ADMET | 数据分析  │   │
│  └────────────────┬─────────────────────────┘   │
│                   │                              │
│  ┌────────────────▼─────────────────────────┐   │
│  │          现有服务层 (复用)                  │   │
│  └────────────────┬─────────────────────────┘   │
│                   │                              │
│  ┌────────────────▼─────────────────────────┐   │
│  │         LLM 基础设施 (复用)                 │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

---

## 2. 核心组件

### 2.1 任务规划器 (Task Planner)

**职责**：接收用户自然语言请求，拆解为可执行的子任务序列。

**实现位置**：`backend/app/services/agent/planner.py`

**关键逻辑**：
- 使用 LLM（agnes-2.0-flash）进行意图识别和任务拆解
- 输出结构化任务列表：`[{tool: str, args: dict, priority: int}]`
- 支持并行任务调度（无依赖关系的工具可并发执行）

### 2.2 工具注册中心 (Tool Registry)

**职责**：统一管理所有可用工具的定义、参数、返回值。

**实现位置**：`backend/app/services/agent/tool_registry.py`

**工具标准接口**：
```python
class AgentTool(Protocol):
    name: str                    # 工具名称（英文标识）
    description: str             # LLM 可理解的工具描述
    args_schema: Type[BaseModel] # Pydantic 参数模型
    tags: List[str]              # 工具分类标签
    requires_confirmation: bool  # 是否需要用户确认
    async def execute(self, **kwargs) -> ToolResult
```

**返回格式**：
```python
class ToolResult(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = {}
```

### 2.3 执行引擎 (Execution Engine)

**职责**：驱动 ReAct 循环（思考→行动→观察→继续）。

**实现位置**：`backend/app/services/agent/engine.py`

**核心循环**：
```
Step N: 思考 → "我需要调用XXX工具"
           ↓
Step N: 行动 → 调用工具 → 获取结果
           ↓
Step N: 观察 → 解析工具返回结果
           ↓
需要更多步骤? → Yes → 回到 Step N+1
              → No  → 生成最终回答
```

**安全约束**：
- 最大步数限制：默认 20 步
- 超时保护：单次执行最多 5 分钟
- 中间结果缓存：工具调用结果自动缓存
- 可中断性：用户可随时终止任务

### 2.4 会话管理器 (Session Manager)

**职责**：维护对话历史、上下文、工具调用日志。

**实现位置**：`backend/app/services/agent/session.py`

**数据模型**：
```python
class AgentSession(BaseModel):
    session_id: str
    project_id: Optional[str]
    user_id: str
    messages: List[Message]          # 对话消息历史
    tool_calls: List[ToolCallRecord] # 工具调用记录
    context: Dict[str, Any]          # 临时上下文（缓存的结果等）
    created_at: datetime
    updated_at: datetime
```

---

## 3. 工具体系

### 3.1 工具分类

| 类别 | 工具示例 | 数据来源 |
|------|---------|---------|
| **数据分析** | `analyze_rna_seq`, `find_differential_genes`, `enrichment_analysis` | parser + bio_analyzer |
| **靶点发现** | `discover_targets`, `get_target_info`, `query_chembl` | targets API + ChEMBL |
| **分子设计** | `design_molecule`, `predict_admet`, `check_ddi` | molecules API + DDI checker |
| **知识查询** | `search_gene`, `search_variant`, `hypothesis_search` | MyGene/MyVariant + 知识图谱 |
| **文件操作** | `read_file`, `generate_report`, `create_visualization` | 文件系统 + 代码沙箱 |

### 3.2 工具适配器

所有现有后端 API 通过适配器包装为标准化工具：

```python
# 示例：靶点发现工具适配器
class DiscoverTargetsTool(AgentTool):
    name = "discover_targets"
    description = "从基因列表中发现潜在药物靶点"
    args_schema = TargetDiscoverySchema
    
    async def execute(self, gene_list: List[str], mode: str = "fast_screen"):
        # 调用现有 targets API
        from app.api.v1.endpoints.targets import discover_targets
        return await discover_targets(genes=gene_list, mode=mode)
```

---

## 4. 前端交互设计

### 4.1 页面布局

**入口**：增强现有 `/workbench/chat` 页面

```
┌─────────────────────────────────────────────────────┐
│  Sidebar  │  Workbench 主区域                         │
│           │  ┌──────────────────────────────────┐   │
│  项目列表  │  │  Header: Agent 状态栏              │   │
│  会话列表  │  │  🟢 Agent 在线 | 当前任务: 分析中  │   │
│           │  └──────────────────────────────────┘   │
│  [+新建会话]│                                         │
│           │  ┌──────────────────┬─────────────────┐ │
│           │  │   聊天对话面板    │   动态结果面板   │ │
│           │  │  - 消息流         │  - 靶点列表     │ │
│           │  │  - 工具调用可视化  │  - 分子结构     │ │
│           │  │  - 快捷指令       │  - 数据分析图表  │ │
│           │  └──────────────────┴─────────────────┘ │
│           │  ┌──────────────────────────────────┐   │
│           │  │  输入框: [输入消息...    📎 🚀]   │   │
│           │  └──────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 4.2 关键交互特性

1. **工具调用可视化**：Agent 每次调用工具时，聊天窗口显示"思考中 → 调用 XXX → 获取结果"的动画
2. **面板联动**：点击聊天中的结果（如靶点名称），右侧面板自动更新对应详情
3. **快捷指令**：输入框支持 `/targets`、`/molecules`、`/analyze` 等快捷命令
4. **任务管理**：Header 显示 Agent 状态，支持暂停/终止正在执行的任务
5. **会话管理**：左侧保留会话历史，每个会话独立维护上下文

### 4.3 通信方式

- **WebSocket**：实时推送 Agent 的每一步推理结果和工具调用状态
- **REST API**：会话创建、历史查询、任务控制等常规操作

---

## 5. 代码沙箱设计

**用途**：执行用户和 Agent 生成的 Python 脚本（数据分析、可视化等）。

**实现方案**：
- 使用 Docker 容器隔离执行环境
- 预装常用科学计算库（pandas, numpy, matplotlib, plotly）
- 资源限制：CPU 1 核、内存 512MB、执行超时 60 秒
- 网络隔离：禁止访问外部网络

**API 端点**：
```
POST /api/v1/agent/sandbox/exec    # 执行代码
GET  /api/v1/agent/sandbox/status   # 查询执行状态
DELETE /api/v1/agent/sandbox/{id}   # 清理容器
```

---

## 6. 文件操作设计

### 6.1 读取文件

Agent 可通过工具读取上传的数据文件：
```python
# 工具：read_file
{
    "path": "/uploads/project_1/dataset.csv",
    "format": "csv"  # 或 "json", "vcf", "tsv"
}
```

### 6.2 生成报告

Agent 可生成分析报告并保存到项目目录：
```python
# 工具：generate_report
{
    "type": "analysis_summary",
    "content": {...},
    "format": "markdown",  # 或 "pdf", "html"
    "output_path": "/reports/project_1/analysis_20260718.md"
}
```

---

## 7. 数据模型

### 7.1 Agent 会话 (新增数据库表)

```python
class AgentSession(Base):
    __tablename__ = "agent_sessions"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"))
    user_id = Column(String, ForeignKey("users.id"))
    title = Column(String)                    # 会话标题（自动生成）
    messages = Column(JSON)                   # 对话消息历史
    tool_calls = Column(JSON)                 # 工具调用记录
    context = Column(JSON)                    # 临时上下文
    status = Column(String)                   # active | paused | completed | failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

### 7.2 Agent 任务 (新增数据库表)

```python
class AgentTask(Base):
    __tablename__ = "agent_tasks"
    
    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("agent_sessions.id"))
    user_message = Column(Text)               # 用户原始请求
    plan = Column(JSON)                       # 任务规划结果
    steps = Column(JSON)                      # 执行步骤记录
    result = Column(JSON)                     # 最终结果
    status = Column(String)                   # pending | running | completed | failed
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
```

---

## 8. API 端点设计

### 8.1 Agent 核心 API

```
POST   /api/v1/agent/chat          # 发送消息，Agent 回复
GET    /api/v1/agent/sessions      # 获取会话列表
GET    /api/v1/agent/sessions/{id} # 获取会话详情
DELETE /api/v1/agent/sessions/{id} # 删除会话
POST   /api/v1/agent/sessions/{id}/stop  # 停止正在执行的任务
GET    /api/v1/agent/tasks/{id}    # 获取任务执行详情
```

### 8.2 WebSocket 事件

```javascript
// 服务端 → 客户端
{
    "type": "thought",           // Agent 思考过程
    "session_id": "...",
    "data": { "text": "我需要先分析数据..." }
}

{
    "type": "tool_call",         // 工具调用开始
    "session_id": "...",
    "data": { "tool": "analyze_rna_seq", "args": {...} }
}

{
    "type": "tool_result",       // 工具调用结果
    "session_id": "...",
    "data": { "tool": "analyze_rna_seq", "result": {...} }
}

{
    "type": "final_response",    // 最终回答
    "session_id": "...",
    "data": { "text": "分析完成，发现了..." }
}

{
    "type": "task_complete",     // 任务完成
    "session_id": "...",
    "data": { "status": "success" }
}
```

---

## 9. 安全与合规

1. **医疗红线**：复用现有 `docs/features/01-medical-redlines.md` 中的安全规则
2. **用户确认**：敏感操作（实验触发、文件写入、治疗方案生成）必须用户确认
3. **审计日志**：所有 Agent 操作记录到现有审计系统
4. **数据隔离**：Agent 只能访问当前项目权限范围内的数据
5. **LLM Guardrail**：复用现有 `services/llm/guardrail.py` 进行输入输出过滤

---

## 10. 开发阶段规划

### Phase 1：基础框架（核心）
- Agent 服务层搭建（planner, registry, engine, session）
- 工具适配器框架 + 首批 5 个核心工具
- 前端聊天界面增强（工具调用可视化）
- WebSocket 实时通信

### Phase 2：能力扩展
- 完整工具体系（数据分析、靶点、分子、知识查询）
- 代码沙箱集成
- 文件操作能力
- 面板联动功能

### Phase 3：智能增强
- 主动建议与预警机制
- 跨模块知识推理优化
- 任务并行调度
- 性能优化与缓存策略

---

## 11. 关键技术决策

| 决策项 | 选择 | 理由 |
|-------|------|------|
| Agent 框架 | 自研 ReAct 引擎 | 复用现有 LLM 基础设施，避免引入新依赖 |
| 工具调用 | JSON Schema 描述 | 与现有 Pydantic 模型兼容 |
| 会话存储 | PostgreSQL JSON 字段 | 灵活存储非结构化对话数据 |
| 实时通信 | WebSocket (现有 ws.py) | 复用已有 WebSocket 基础设施 |
| 代码沙箱 | Docker 隔离 | 安全性高，资源可控 |
| 任务持久化 | 数据库 + Redis 缓存 | 支持断点续传和快速查询 |

---

## 12. 依赖与影响

### 新增依赖
- 无（复用现有 LLM 客户端和工具）
- Docker SDK（用于代码沙箱）

### 影响现有模块
- `app/api/v1/endpoints/chat.py` — 增强为 Agent 入口
- `app/api/v1/endpoints/ws.py` — 添加 Agent WebSocket 事件
- `frontend/app/workbench/chat/page.tsx` — 新增双面板布局
- `frontend/lib/api/chat.ts` — 新增 Agent API 调用

### 复用现有模块
- `services/llm/orchestrator.py` — LLM 调用
- `services/analyzer/` — 生物数据分析
- `clients/` — 外部数据库查询
- `core/middleware.py` — 认证和权限
