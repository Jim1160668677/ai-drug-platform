# 建议七后端核心 — ExperimentDSL 调度与联动 设计文档

> Date: 2026-08-07
> Author: user + assistant
> Status: APPROVED

## Background

建议七(ExperimentDSL + 实验设计智能体)的前端部分(DSL schema、Agent工具、编译器、MockAdapter、PromotePanel)已实现。本报告聚焦**后端核心**三步:

1. **Step 3**: `experiment_scheduler.py` — 实验调度智能体
2. **Step 4**: `data_analysis.py` 增强 — `_generate_llm_conclusion`
3. **Step 5**: `supervisor.py` 联动 — Meta-Review → ExperimentDSL 自动生成

## In scope

- `backend/app/services/experiment/scheduler.py` (新增)
- `backend/app/services/agent/tools/data_analysis.py` (增强)
- `backend/app/services/coscientist/supervisor.py` (增强)
- `backend/app/services/coscientist/result.py` (CoScientistResult 新增字段)
- `backend/app/api/v1/endpoints/experiments.py` (新增 schedule/run 端点)
- 测试: `test_experiment_scheduler.py`, `test_data_analysis_conclusion.py`, `test_supervisor_dsl.py`

## Out of scope

- 前端 "设计实验" 按钮与 DSL 预览 (Step 6-7, 后续阶段)
- Nextflow 真实调度 (仅生成 params 文件,不做实际作业提交)
- 物理设备指令 (Hardware-level InstrumentAdapter 实现)
- 端到端联调 (Step 8)

## Design

### 1. ExperimentScheduler

**文件**: `backend/app/services/experiment/scheduler.py` (新增)

```python
class ExperimentScheduler:
    """实验调度智能体
    
    职责:
    1. DSL → 可执行步骤列表 (复用 DSLCompiler)
    2. 资源冲突检测 (时间/仪器/试剂)
    3. 审计链写入
    4. Nextflow params 生成 (computational 实验)
    5. LIMS CSV 批量导入 (湿实验)
    """
    
    async def schedule(
        self,
        dsl: ExperimentDSL,
        project_id: UUID,
        hypothesis_ids: List[str] = None,
    ) -> Dict[str, Any]:
        """调度实验,返回调度结果"""
        
    async def detect_conflicts(
        self,
        existing_experiments: List[Experiment],
        new_schedule: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """检测资源冲突"""
        
    async def write_audit_log(
        self,
        schedule_id: str,
        dsl: ExperimentDSL,
        result: Dict[str, Any],
    ) -> None:
        """写入审计日志"""
```

**冲突检测逻辑**:
- 时间冲突: 同一仪器/时间槽被占用
- 试剂冲突: 关键试剂库存不足
- 人员冲突: 同一研究员同时段多实验

**输出格式**:
```python
{
    "schedule_id": str,
    "steps": List[Dict],  # 可执行步骤
    "nextflow_params": Dict,  # computational 实验
    "lims_csv": str,  # wet lab CSV
    "conflicts": List[Dict],  # 冲突列表
    "audit_log_id": str,
}
```

### 2. data_analysis.py 增强

**文件**: `backend/app/services/agent/tools/data_analysis.py` (修改)

在 `AnalyzeDatasetTool` 新增方法:

```python
class AnalyzeDatasetTool(AgentTool):
    # ... 现有代码 ...
    
    async def _generate_llm_conclusion(
        self,
        analysis_result: Dict[str, Any],
        ctx: ToolContext,
    ) -> str:
        """LLM 生成自然语言专业结论"""
        # 输入: 统计结果 + 图表数据 + 原始数据摘要
        # 输出: 专业结论文本
        # 示例: "数据显示 EGFR 抑制剂对 AML 细胞系表现出剂量依赖性杀伤效应..."
```

**调用点**: 在 `execute()` 返回后追加调用,结果写入 `ToolResult.metadata["llm_conclusion"]`

### 3. supervisor.py 联动

**文件**: `backend/app/services/coscientist/supervisor.py` (修改)

**CoScientistResult 新增字段**:
```python
@dataclass
class CoScientistResult:
    # ... 现有字段 ...
    experiment_dsl: Optional[Dict[str, Any]] = None  # 自动生成的实验设计 DSL
    experiment_schedule_id: Optional[str] = None  # 调度 ID
```

**supervisor.run() 新增步骤**:
```python
# 在 meta_review 完成后
if top_hypotheses and getattr(settings, "COSCIENTIST_AUTO_EXPERIMENT_DESIGN", False):
    dsl = await self._auto_generate_dsl(top_hypotheses, research_goal)
    result.experiment_dsl = dsl.to_dict()
    
    # 可选: 自动调度
    if getattr(settings, "COSCIENTIST_AUTO_SCHEDULE", False):
        schedule = await self._auto_schedule(dsl, project_id)
        result.experiment_schedule_id = schedule["schedule_id"]
```

**新方法**:
```python
async def _auto_generate_dsl(
    self,
    top_hypotheses: List[Dict],
    research_goal: str,
) -> ExperimentDSL:
    """调用 ExperimentDesignTool 生成 DSL"""
    
async def _auto_schedule(
    self,
    dsl: ExperimentDSL,
    project_id: UUID,
) -> Dict[str, Any]:
    """调用 ExperimentScheduler 调度实验"""
```

### 4. API 端点

**文件**: `backend/app/api/v1/endpoints/experiments.py` (修改)

**新增端点**:
```python
@router.post("/schedule", response_model=StandardResponse)
async def schedule_experiment(
    session_id: UUID,
    body: ScheduleRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """调度实验: DSL → 可执行步骤 + 冲突检测 + 审计"""
    
@router.post("/runs/{run_id}/execute", response_model=StandardResponse)
async def execute_experiment(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """执行实验: 调度 → 结果 (Mock 模式)"""
```

**请求/响应模型**:
```python
class ScheduleRequest(BaseModel):
    dsl: Dict[str, Any]
    project_id: UUID
    hypothesis_ids: Optional[List[str]] = None
    
class ScheduleResponse(BaseSchema):
    schedule_id: str
    steps: List[Dict]
    conflicts: List[Dict]
    nextflow_params: Optional[Dict] = None
    lims_csv: Optional[str] = None
```

### 5. 测试计划

**`backend/tests/test_experiment_scheduler.py`**:
- `TestScheduleDSL`: DSL → 步骤列表
- `TestConflictDetection`: 时间/试剂/人员冲突
- `TestAuditLog`: 审计链写入

**`backend/tests/test_data_analysis_conclusion.py`**:
- `TestLLMConclusion`: 统计结果 → 自然语言结论
- `TestEmptyData`: 空数据返回默认结论

**`backend/tests/test_supervisor_dsl.py`**:
- `TestAutoGenerateDSL`: Meta-Review → DSL 生成
- `TestAutoSchedule`: DSL → 调度
- `TestDisabledByDefault`: 开关关闭时不生成

## Verification

- 后端: 新增测试通过 + 全量 `pytest --no-cov` 回归 (预期 3729+ baseline)
- 前端: vitest 回归 (预期 604+ baseline)
- tsc: 0 项目内错误
