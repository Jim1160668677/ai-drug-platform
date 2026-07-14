# Bug 修复与生信分析功能增强实施计划

## 概述

本计划针对用户报告的两大类问题：

1. **前端 Bug 修复**：Next.js 水合不匹配（Hydration Mismatch）导致 `/dashboard`、`/workbench/*`、`/admin` 等所有受保护页面出现 `net::ERR_ABORTED`，以及后端 `/targets/discover` 在 `deep_insight` 模式下因 LLM 超时返回 502。
2. **生信分析系统功能增强**：流水线断点续行、生信分析功能完善、非基因数据处理、整体健壮性。

## 当前状态分析

### 前端水合不匹配根因（已通过代码审查确认）

| 文件 | 行号 | 问题 |
|---|---|---|
| `frontend/lib/auth.ts` | 45-48, 50-59, 61-63 | `getToken()` / `getCurrentUser()` / `isLoggedIn()` 在服务端返回 `null/false`，客户端返回实际值 → 服务端与客户端首次渲染不一致 |
| `frontend/app/dashboard/page.tsx` | 35, 38-40 | `enabled: isLoggedIn()` 服务端 false；`if (!isLoggedIn()) { return null; }` 服务端渲染 `null`，客户端渲染完整页面 → 水合失败 |
| `frontend/lib/store.ts` | 22-37 | Zustand `persist` 中间件缺少 `skipHydration: true`，客户端首次渲染时同步从 localStorage 读取状态 → SSR 不一致 |
| `frontend/components/Providers.tsx` | 8-37 | 未在 `useEffect` 中手动调用 `useAppStore.persist.rehydrate()` |
| `frontend/components/layout/Header.tsx` | 14, 22-26 | 使用 Zustand store 的 `user`；在 `useEffect` 中调用 `getCurrentUser()` 设置 user → 首次渲染时 `user=null`，effect 后变化 |
| `frontend/middleware.ts` | 23 | 已正确使用 cookie 鉴权（无需修改） |

### 后端 API 错误处理根因

| 文件 | 行号 | 问题 |
|---|---|---|
| `backend/app/api/v1/endpoints/targets.py` | 23-35 | `/discover` 端点无 try/except，`TargetIdentifier.discover()` 抛出异常时直接变为 502 |
| `backend/app/services/analyzer/target_identifier.py` | 264-280 | `deep_insight` 模式调用 LLM 时无 `asyncio.wait_for()` 超时保护；`get_llm_client()` 异常未单独处理 |
| `backend/app/api/v1/endpoints/targets.py` | 167-193 | `force_deep_analysis` 端点同样无 try/except |

### 流水线与生信分析现状

| 文件 | 行号 | 现状 |
|---|---|---|
| `backend/app/services/orchestrator/discovery_pipeline.py` | 43-211 | 已有 per-step try/except，失败记为 FAILED，后续步骤继续。但**无 `resume_from_step` / `skip_steps` 参数**，无法从指定步骤恢复或跳过特定步骤 |
| `backend/app/api/v1/endpoints/pipeline.py` | 43-54 | `PipelineRunRequest` 无 `resume_from_step` / `skip_steps` 字段 |
| `backend/app/services/parser/base.py` | 38-70 | 工厂函数 `parse_dataset()` 仅路由 RNA_SEQ / SCRNA_SEQ / WES / WGS / FASTA / GENE_REPORT，**未路由 PROTEOMICS / METABOLOMICS** |
| `backend/app/models/dataset.py` | 18-19 | `DataType.PROTEOMICS = "proteomics"` 和 `DataType.METABOLOMICS = "metabolomics"` **枚举值已存在**，但无对应解析器实现 |
| `backend/app/services/parser/rna_seq.py` | 1-80 | 作为新解析器的参考模式（CSV/TSV 矩阵解析） |
| `backend/app/services/analyzer/bio_analyzer.py` | 全文 | 已确认实现完整（包含 DEG、富集、聚类、归一化），无需修改 |

## 实施变更

### Part A: 前端水合修复（Critical — 阻断所有页面）

#### A1. 新建 `frontend/lib/hooks/useMounted.ts`

**目的**：提供标准的"已挂载"检测 Hook，确保服务端和客户端首次渲染都返回 `false`，`useEffect` 执行后返回 `true`。

**实现**：
```typescript
import { useEffect, useState } from 'react';

export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}
```

#### A2. 修改 `frontend/lib/store.ts`

**目的**：阻止 Zustand `persist` 在客户端首次渲染时同步从 localStorage 读取状态，确保 SSR 与首次客户端渲染一致。

**变更**：在 `persist` 配置对象中添加 `skipHydration: true`。

```typescript
{
  name: 'ai-drug-store',
  skipHydration: true,  // 新增
}
```

#### A3. 修改 `frontend/components/Providers.tsx`

**目的**：在客户端挂载后手动调用 `rehydrate()`，从 localStorage 恢复 Zustand 状态。

**变更**：添加 `useEffect` 调用 `useAppStore.persist.rehydrate()`。

```typescript
import { useEffect } from 'react';
import { useAppStore } from '@/lib/store';

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(...);

  useEffect(() => {
    useAppStore.persist.rehydrate();
  }, []);

  return (...);
}
```

#### A4. 修改 `frontend/lib/auth.ts`

**目的**：让 `getToken()` / `getCurrentUser()` 在服务端也能从 cookie 读取认证状态，避免 SSR/CSR 不一致。

**变更**：使用 `next/headers` 的 `cookies()` 在服务端读取 cookie。

```typescript
import { cookies } from 'next/headers';

export const getToken = (): string | null => {
  if (typeof window === 'undefined') {
    // 服务端：从 cookie 读取
    const cookieStore = cookies();
    const token = cookieStore.get(TOKEN_COOKIE)?.value;
    return token ? decodeURIComponent(token) : null;
  }
  return localStorage.getItem(TOKEN_KEY);
};
```

**注意**：`getCurrentUser()` 在服务端无法从 localStorage 读取用户对象。需考虑两种方案：
- **方案 A**：服务端只读 token，user 对象延迟到客户端挂载后从 localStorage 读取（`useMounted` + `useEffect`）。
- **方案 B**：将 user 信息也存入 cookie（JSON）。

**决策**：采用方案 A，避免在 cookie 中存储大对象，且 user 信息在客户端挂载后即可获取，不阻塞首屏渲染。

```typescript
export const getCurrentUser = (): AuthUser | null => {
  if (typeof window === 'undefined') {
    return null;  // 服务端返回 null，客户端挂载后通过 useEffect 填充
  }
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
};
```

#### A5. 修改 `frontend/app/dashboard/page.tsx`

**目的**：使用 `useMounted()` 模式，在挂载前渲染 loading skeleton，避免服务端渲染 `null` 与客户端渲染完整页面的水合不匹配。

**变更**：
1. 导入 `useMounted`。
2. 在 `isLoggedIn()` 和 `useQuery enabled` 之前添加 `const mounted = useMounted();`。
3. 在 `if (!isLoggedIn())` 之前添加 `if (!mounted) return <LoadingSkeleton />;`。
4. `useQuery` 的 `enabled` 改为 `mounted && isLoggedIn()`。

```typescript
const mounted = useMounted();
const { data, isLoading, error } = useQuery({
  queryKey: ['dashboard-overview'],
  queryFn: getDashboardOverview,
  enabled: mounted && isLoggedIn(),
});

if (!mounted) {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center">
        <Activity className="w-10 h-10 mx-auto mb-3 text-primary-500 animate-pulse" />
        <div className="text-sm text-gray-500">加载中...</div>
      </div>
    </div>
  );
}

if (!isLoggedIn()) {
  return null;
}
```

#### A6. 修改 `frontend/components/layout/Header.tsx`

**目的**：使用 `useMounted()` 控制 user 渲染，避免服务端 `user=null` 与客户端 `user={...}` 的水合不匹配。

**变更**：
```typescript
import { useMounted } from '@/lib/hooks/useMounted';

export default function Header() {
  const mounted = useMounted();
  // ...
  return (
    <header>
      {/* ... */}
      <div className="text-sm font-medium">
        {mounted ? (user?.name || '用户') : '用户'}
      </div>
      <div className="text-xs text-gray-500">
        {mounted ? user?.email : ''}
      </div>
      {/* ... */}
    </header>
  );
}
```

#### A7. 修改 `frontend/components/layout/Sidebar.tsx`（如需）

**目的**：若 Sidebar 使用 Zustand store 的 `user` 或 `sidebarCollapsed` 渲染差异化内容，添加 `useMounted()` 保护。

**变更**：检查 Sidebar 是否有角色相关的条件渲染（如 `user.role === 'founder'` 显示管理菜单）。若有，添加 `useMounted()` 保护。

### Part B: 后端 API 错误处理

#### B1. 修改 `backend/app/api/v1/endpoints/targets.py` — `/discover` 端点

**目的**：捕获 `discover()` 抛出的异常，返回 200 + 错误信息而非 502。

**变更**：
```python
@router.post("/discover", response_model=StandardResponse, summary="靶点发现")
async def discover_targets(
    project_id: UUID,
    dataset_id: Optional[UUID] = Query(None, description="指定数据集分析"),
    tier: str = Query("fast_screen", description="分析层级: fast_screen/deep_insight"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从数据集中发现靶点 — 突变→注释→通路→证据分级"""
    from app.services.analyzer.target_identifier import TargetIdentifier
    from app.core.exceptions import AppException
    identifier = TargetIdentifier(db)
    try:
        result = await identifier.discover(project_id=project_id, dataset_id=dataset_id, tier=tier)
        return StandardResponse(message=f"发现 {len(result.get('targets', []))} 个靶点", data=result)
    except AppException:
        raise  # 业务异常按原状态码传播
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"靶点发现失败: {e}", exc_info=True)
        return StandardResponse(
            success=False,
            message=f"靶点发现失败: {str(e)}",
            data={"project_id": str(project_id), "tier": tier, "error": str(e)},
        )
```

#### B2. 修改 `backend/app/services/analyzer/target_identifier.py` — LLM 超时保护

**目的**：为 `deep_insight` 模式的 LLM 调用添加 60 秒超时，避免无限等待导致 502。

**变更**（L264-280）：
```python
if tier == "deep_insight":
    try:
        llm = get_llm_client()
        deep_targets = targets_data[:5]

        async def _deep_analyze(td: Dict[str, Any]):
            prompt = self._build_deep_analysis_prompt(td)
            response = await asyncio.wait_for(
                llm.chat([
                    {"role": "system", "content": "你是精准医学专家..."},
                    {"role": "user", "content": prompt},
                ]),
                timeout=60.0,
            )
            td["deep_analysis"] = response.get("content")
            td["references"] = response.get("references", [])

        await asyncio.gather(*[_deep_analyze(td) for td in deep_targets])
    except asyncio.TimeoutError:
        logger.warning("深度分析 LLM 调用超时（60s），跳过深度分析")
    except Exception as e:
        logger.warning(f"深度分析失败: {e}")
```

#### B3. 修改 `backend/app/api/v1/endpoints/targets.py` — `force_deep_analysis` 端点

**目的**：与 B1 一致的错误处理。

**变更**：添加 try/except，模式同 B1。

### Part C: 流水线断点续行

#### C1. 修改 `backend/app/services/orchestrator/discovery_pipeline.py`

**目的**：添加 `resume_from_step` 和 `skip_steps` 参数，支持从指定步骤恢复或跳过特定步骤。

**变更**：
1. `run()` 方法签名添加两个参数：
   ```python
   async def run(
       self,
       project_id: UUID,
       dataset_id: Optional[UUID] = None,
       tier: str = "fast_screen",
       max_targets: int = 5,
       molecules_per_target: int = 15,
       molecule_strategy: str = "fragment",
       skip_existing: bool = True,
       current_user: Any = None,
       enable_hypothesis: bool = True,
       hypothesis_config: Optional[Dict[str, Any]] = None,
       custom_steps: Optional[List[Dict[str, Any]]] = None,
       resume_from_step: Optional[str] = None,  # 新增
       skip_steps: Optional[List[str]] = None,   # 新增
   ) -> Dict[str, Any]:
   ```

2. 定义步骤顺序常量：
   ```python
   STEP_ORDER = ["target_discovery", "molecule_generation", "treatment_matching", "hypothesis_generation"]
   ```

3. 在每个步骤前检查是否应跳过：
   ```python
   skip_steps_set = set(skip_steps or [])
   
   def should_run(step_name: str) -> bool:
       if step_name in skip_steps_set:
           return False
       if resume_from_step:
           resume_idx = STEP_ORDER.index(resume_from_step) if resume_from_step in STEP_ORDER else 0
           step_idx = STEP_ORDER.index(step_name) if step_name in STEP_ORDER else 0
           return step_idx >= resume_idx
       return True
   ```

4. 在每个步骤执行前调用 `should_run()`，跳过时记录为 SKIPPED：
   ```python
   if not should_run("target_discovery"):
       steps_result["target_discovery"] = {
           "status": PipelineStepStatus.SKIPPED,
           "reason": "被 resume_from_step/skip_steps 跳过",
           "duration_sec": 0,
       }
   else:
       # 原有逻辑
   ```

5. 在 summary 中添加跳过步骤信息：
   ```python
   "summary": {
       "total_targets": len(targets),
       "total_molecules": len(molecules),
       "total_treatments": ...,
       "total_hypotheses": ...,
       "custom_steps_executed": ...,
       "skipped_steps": [s for s in steps_result if steps_result[s].get("status") == PipelineStepStatus.SKIPPED],
       "resumed_from": resume_from_step,
   }
   ```

#### C2. 修改 `backend/app/api/v1/endpoints/pipeline.py`

**目的**：`PipelineRunRequest` 添加新字段，并传递给 `pipeline.run()`。

**变更**：
```python
class PipelineRunRequest(BaseModel):
    # ... 原有字段
    resume_from_step: Optional[str] = Field(None, description="从指定步骤恢复（跳过之前的步骤）: target_discovery/molecule_generation/treatment_matching/hypothesis_generation")
    skip_steps: Optional[List[str]] = Field(None, description="跳过指定步骤列表")
```

并在 `run_pipeline` 中传递：
```python
result = await pipeline.run(
    # ... 原有参数
    resume_from_step=payload.resume_from_step,
    skip_steps=payload.skip_steps,
)
```

### Part D: 非基因数据解析器

#### D1. 新建 `backend/app/services/parser/proteomics.py`

**目的**：解析蛋白质组学数据（CSV/TSV 蛋白表达矩阵）。

**实现**：参照 `rna_seq.py` 模式，但 `summary` 中同时包含 `top_proteins`（语义化）和 `top_genes`（兼容性，复用同一份数据），便于下游分析器统一处理。

```python
"""蛋白质组学解析器 — CSV/TSV 蛋白表达矩阵"""
import os
from typing import Any, Dict

from app.services.parser.base import Parser


class ProteomicsParser(Parser):
    """蛋白质组学 CSV/TSV 表达矩阵解析器"""

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {"summary": {"error": f"文件不存在: {path}"}, "quality_metrics": {}}

        import pandas as pd
        import numpy as np

        try:
            df = pd.read_csv(path, sep=None, engine="python", index_col=0, nrows=10000)
        except Exception:
            try:
                df = pd.read_csv(path, index_col=0, nrows=10000)
            except Exception as e2:
                return {"summary": {"error": f"CSV 解析失败: {e2}"}, "quality_metrics": {}}

        n_proteins, n_samples = df.shape
        if n_samples == 0:
            return {"summary": {"error": "数据矩阵为空"}, "quality_metrics": {}}

        missing_rate = float(df.isna().mean().mean())
        row_means = df.mean(axis=1)
        low_abundance_ratio = float((row_means < 1.0).mean())

        all_values = df.values.flatten()
        finite_values = all_values[np.isfinite(all_values)]

        top_proteins = [
            {"symbol": str(idx), "mean_abundance": float(row_means.loc[idx])}
            for idx in row_means.nlargest(10).index
        ]

        summary = {
            "proteins": int(n_proteins),
            "samples": int(n_samples),
            "file_format": dataset.file_format,
            "top_proteins": top_proteins,
            "top_genes": top_proteins,  # 兼容性：复用同一份数据供下游分析
            "sample_columns": list(df.columns[:20]),
            "value_distribution": {
                "mean": float(np.mean(finite_values)) if len(finite_values) > 0 else 0,
                "median": float(np.median(finite_values)) if len(finite_values) > 0 else 0,
                "std": float(np.std(finite_values)) if len(finite_values) > 0 else 0,
                "min": float(np.min(finite_values)) if len(finite_values) > 0 else 0,
                "max": float(np.max(finite_values)) if len(finite_values) > 0 else 0,
            },
            "data_type": "proteomics",
        }

        quality_metrics = {
            "missing_rate": round(missing_rate, 4),
            "low_abundance_ratio": round(low_abundance_ratio, 4),
            "sample_missing_rates": {
                str(c): round(float(df[c].isna().mean()), 4) for c in df.columns
            },
            "data_type": "proteomics",
        }

        return {"summary": summary, "quality_metrics": quality_metrics}
```

#### D2. 新建 `backend/app/services/parser/metabolomics.py`

**目的**：解析代谢组学数据（CSV/TSV 代谢物丰度矩阵）。

**实现**：同 ProteomicsParser 模式，字段语义改为代谢物。

```python
"""代谢组学解析器 — CSV/TSV 代谢物丰度矩阵"""
import os
from typing import Any, Dict

from app.services.parser.base import Parser


class MetabolomicsParser(Parser):
    """代谢组学 CSV/TSV 丰度矩阵解析器"""

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {"summary": {"error": f"文件不存在: {path}"}, "quality_metrics": {}}

        import pandas as pd
        import numpy as np

        try:
            df = pd.read_csv(path, sep=None, engine="python", index_col=0, nrows=10000)
        except Exception:
            try:
                df = pd.read_csv(path, index_col=0, nrows=10000)
            except Exception as e2:
                return {"summary": {"error": f"CSV 解析失败: {e2}"}, "quality_metrics": {}}

        n_metabolites, n_samples = df.shape
        if n_samples == 0:
            return {"summary": {"error": "数据矩阵为空"}, "quality_metrics": {}}

        missing_rate = float(df.isna().mean().mean())
        row_means = df.mean(axis=1)

        all_values = df.values.flatten()
        finite_values = all_values[np.isfinite(all_values)]

        top_metabolites = [
            {"symbol": str(idx), "mean_abundance": float(row_means.loc[idx])}
            for idx in row_means.nlargest(10).index
        ]

        summary = {
            "metabolites": int(n_metabolites),
            "samples": int(n_samples),
            "file_format": dataset.file_format,
            "top_metabolites": top_metabolites,
            "top_genes": top_metabolites,  # 兼容性
            "sample_columns": list(df.columns[:20]),
            "value_distribution": {
                "mean": float(np.mean(finite_values)) if len(finite_values) > 0 else 0,
                "median": float(np.median(finite_values)) if len(finite_values) > 0 else 0,
                "std": float(np.std(finite_values)) if len(finite_values) > 0 else 0,
                "min": float(np.min(finite_values)) if len(finite_values) > 0 else 0,
                "max": float(np.max(finite_values)) if len(finite_values) > 0 else 0,
            },
            "data_type": "metabolomics",
        }

        quality_metrics = {
            "missing_rate": round(missing_rate, 4),
            "low_abundance_ratio": round(float((row_means < 1.0).mean()), 4),
            "sample_missing_rates": {
                str(c): round(float(df[c].isna().mean()), 4) for c in df.columns
            },
            "data_type": "metabolomics",
        }

        return {"summary": summary, "quality_metrics": quality_metrics}
```

#### D3. 修改 `backend/app/services/parser/base.py`

**目的**：在 `parse_dataset()` 工厂函数中添加 PROTEOMICS / METABOLOMICS 路由。

**变更**（在 `elif data_type == DataType.FASTA:` 之后添加）：
```python
elif data_type == DataType.PROTEOMICS:
    from app.services.parser.proteomics import ProteomicsParser
    parser = ProteomicsParser()
elif data_type == DataType.METABOLOMICS:
    from app.services.parser.metabolomics import MetabolomicsParser
    parser = MetabolomicsParser()
```

#### D4. 修改 `backend/app/services/parser/__init__.py`

**目的**：导出新解析器（若 `__init__.py` 有显式导出）。

**变更**：检查 `__init__.py` 是否有 `__all__` 或显式导出，若有则添加新解析器。

### Part E: 测试

#### E1. 前端水合修复测试

**新建** `frontend/lib/hooks/__tests__/useMounted.test.ts`（若前端有测试基础设施）或通过手动浏览器测试验证：
1. 访问 `/dashboard` 不再出现 hydration 警告
2. 访问 `/workbench`、`/workbench/targets` 等所有受保护页面不再出现 `net::ERR_ABORTED`
3. 控制台无 `Hydration failed` 错误

#### E2. 后端 API 错误处理测试

**新建** `backend/tests/test_targets_discover_error_handling.py`：
1. `test_discover_handles_exception_returns_success_false` — mock `TargetIdentifier.discover` 抛出异常，验证返回 200 + `success=False`
2. `test_discover_propagates_app_exception` — mock 抛出 `AppException`，验证按原状态码传播
3. `test_force_deep_analysis_handles_exception` — 同上
4. `test_deep_insight_llm_timeout_does_not_raise` — mock LLM 调用超时，验证 `discover()` 仍返回结果（跳过深度分析）

#### E3. 流水线断点续行测试

**新建** `backend/tests/test_pipeline_resume.py`：
1. `test_resume_from_molecule_generation` — 设置 `resume_from_step="molecule_generation"`，验证 target_discovery 被跳过（SKIPPED），molecule_generation 正常执行
2. `test_skip_treatment_matching` — 设置 `skip_steps=["treatment_matching"]`，验证 treatment_matching 被跳过，其他步骤正常
3. `test_skipped_steps_in_summary` — 验证 summary 中包含 `skipped_steps` 列表
4. `test_invalid_resume_from_step_ignored` — 设置无效的 `resume_from_step`，验证从第一步开始执行

#### E4. 非基因数据解析器测试

**新建** `backend/tests/test_proteomics_metabolomics_parser.py`：
1. `test_proteomics_parser_parses_csv` — 创建蛋白质表达矩阵 CSV，验证解析结果包含 `top_proteins` 和 `top_genes`
2. `test_metabolomics_parser_parses_csv` — 同上，针对代谢物
3. `test_parse_dataset_routes_proteomics` — 验证 `parse_dataset()` 工厂函数正确路由到 `ProteomicsParser`
4. `test_parse_dataset_routes_metabolomics` — 同上
5. `test_proteomics_parser_handles_missing_file` — 验证文件不存在时返回 error
6. `test_proteomics_parser_handles_empty_matrix` — 验证空矩阵时返回 error

## 假设与决策

1. **假设**：前端使用 Next.js App Router（已确认），`next/headers` 的 `cookies()` 可在 Server Components 中同步读取。
2. **决策**：`getCurrentUser()` 在服务端返回 `null`，user 信息延迟到客户端挂载后通过 `useEffect` 填充（方案 A），避免在 cookie 中存储大对象。
3. **决策**：非基因数据解析器的 `summary` 中同时包含语义化字段（`top_proteins` / `top_metabolites`）和兼容性字段（`top_genes`，复用同一份数据），确保下游分析器无需修改即可处理非基因数据。
4. **假设**：`DataType.PROTEOMICS` 和 `DataType.METABOLOMICS` 枚举值已存在（已确认 L18-19），无需修改 enum。
5. **决策**：流水线断点续行通过 `resume_from_step`（从指定步骤恢复，跳过之前的步骤）和 `skip_steps`（跳过特定步骤列表）两个参数组合实现，提供最大灵活性。
6. **决策**：`/discover` 端点异常时返回 200 + `success=False` 而非 502，让前端能正常处理错误信息而非显示网络错误。
7. **假设**：项目测试覆盖率要求 ≥80%（来自 project_memory），新增测试需保持覆盖率。
8. **决策**：LLM 调用超时设为 60 秒（平衡响应速度与 LLM 推理时间），超时后跳过深度分析但返回基础分析结果。

## 验证步骤

### 前端验证
1. 启动前端 dev server：`cd frontend && npm run dev`
2. 访问 `http://localhost:3000/dashboard`，验证：
   - 控制台无 `Hydration failed` 错误
   - 控制台无 `net::ERR_ABORTED` 错误
   - 页面正常渲染（先 loading，后内容）
3. 访问 `/workbench`、`/workbench/targets`、`/workbench/projects`、`/workbench/molecules`、`/workbench/data`、`/workbench/treatments`、`/workbench/experiments`、`/workbench/hypotheses`、`/workbench/lineage`、`/workbench/chat`、`/workbench/federated`、`/workbench/privacy`、`/admin`，验证所有页面无水合错误
4. 刷新页面，验证 Zustand store 状态（如 currentProject）正确恢复

### 后端验证
1. 启动后端：`cd backend && uvicorn app.main:app --reload --port 8000`
2. 调用 `POST /api/v1/targets/discover?project_id=<existing>&tier=deep_insight`，验证：
   - 不再返回 502
   - LLM 超时时返回 200 + 基础分析结果（无 deep_analysis 字段）
3. 调用 `POST /api/v1/pipeline/run`，body 中设置 `skip_steps: ["treatment_matching"]`，验证：
   - 返回 200
   - `steps.treatment_matching.status == "skipped"`
   - `summary.skipped_steps` 包含 "treatment_matching"
4. 调用 `POST /api/v1/pipeline/run`，body 中设置 `resume_from_step: "molecule_generation"`，验证：
   - `steps.target_discovery.status == "skipped"`
   - `steps.molecule_generation` 正常执行
   - `summary.resumed_from == "molecule_generation"`
5. 上传蛋白质组学 CSV 文件，调用解析接口，验证 `summary.top_proteins` 和 `summary.top_genes` 都存在
6. 上传代谢组学 CSV 文件，验证 `summary.top_metabolites` 和 `summary.top_genes` 都存在

### 测试验证
1. 运行 `cd backend && pytest tests/test_targets_discover_error_handling.py tests/test_pipeline_resume.py tests/test_proteomics_metabolomics_parser.py -v`，验证所有测试通过
2. 运行 `cd backend && pytest --cov=app --cov-report=term-missing`，验证覆盖率仍 ≥80%
3. 前端如有测试基础设施，运行 `cd frontend && npm test`（如有）

## 实施顺序

1. **Part A**（前端水合修复）— Critical，阻断所有页面，优先实施
   - A1 → A2 → A3 → A4 → A5 → A6 → A7
2. **Part B**（后端 API 错误处理）— 解决 502 错误
   - B1 → B2 → B3
3. **Part D**（非基因数据解析器）— 独立模块，可并行
   - D1 → D2 → D3 → D4
4. **Part C**（流水线断点续行）— 依赖 B 已完成
   - C1 → C2
5. **Part E**（测试）— 在所有功能完成后
   - E1 → E2 → E3 → E4
