# 精准药物设计系统 — ADMET 与分子可解释性功能收尾开发计划

## 摘要

本计划承接上一会话的工作，完成 ADMET 性质预测与分子可解释性分析功能的收尾开发。后端服务函数（`predict_admet` / `explain_molecule`）和 API 端点（`/predict-properties` / `/explain`）已实现，本计划聚焦于：编写单元测试与集成测试、新增前端交互组件（AdmetModal / ExplainModal）、执行全量验证（pytest + ruff + 前端构建）、修复开发中产生的 bug，并输出完整开发文档。

---

## 一、当前状态分析

### 已完成（上一会话）

| 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|
| 后端服务 | [molecule_designer.py](file:///g:/软件开发/AI药物/backend/app/services/analyzer/molecule_designer.py) | ✅ | 行 405-783：3 个 SMARTS 常量字典 + `predict_admet` + `_mock_predict_admet` + `explain_molecule` + `_mock_explain_molecule` |
| 后端端点 | [molecules.py](file:///g:/软件开发/AI药物/backend/app/api/v1/endpoints/molecules.py) | ✅ | 行 129-138：`/predict-properties` 调用 `predict_admet`；行 156-165：`/explain` 调用 `explain_molecule` |
| 前端 API | [api.ts](file:///g:/软件开发/AI药物/frontend/lib/api.ts) | ✅ | 行 297-304：`predictProperties` 和 `explainMolecule` 已定义 |

### 待完成（本计划）

| 任务 | 文件 | 说明 |
|------|------|------|
| 后端单元测试 | [test_services_integration.py](file:///g:/软件开发/AI药物/backend/tests/test_services_integration.py) | 在 `TestMoleculeDesigner` 类（行 31-107）末尾插入 8 个单元测试 |
| 后端集成测试 | [test_api_integration.py](file:///g:/软件开发/AI药物/backend/tests/test_api_integration.py) | 在 `TestMoleculeDesign` 类（行 723-782）末尾插入 2 个集成测试 |
| 前端组件 | [page.tsx](file:///g:/软件开发/AI药物/frontend/app/workbench/molecules/page.tsx) | 新增 `AdmetModal` 和 `ExplainModal` 组件 + 2 个按钮入口 + API 导入 |
| 全量验证 | — | pytest（--no-cov 避免 bcrypt 兼容性问题）+ ruff check + 前端 `npm run build` |
| 开发文档 | `.trae/documents/精准药物设计系统-ADMET功能开发完成报告.md` | 功能说明 + 测试报告 + bug 修复记录 |

### 关键发现

1. **test_endpoints_direct.py 不存在**：原计划的 2 个端点直连测试改为在 `test_api_integration.py` 中以 HTTP 集成测试形式添加。
2. **RDKit 已安装**：`requirements.txt` 包含 `rdkit==2024.3.5`，真实计算路径可被测试覆盖。
3. **前端响应信封**：API 返回 `{success, data, meta}` 格式，Modal 需从 `res.data` 提取业务数据。
4. **现有 Modal 模式**：`AssessModal`（行 319-442）和 `DesignModal`（行 210-317）提供了成熟的 Modal 组件模式，新 Modal 应遵循同样的布局、样式和交互逻辑。

---

## 二、实现方案

### 步骤 1：后端单元测试（8 个）

**文件**：`backend/tests/test_services_integration.py`

**插入位置**：行 106（`test_mock_assess_druglikeness_empty` 方法之后、行 108 空行处、`TestNetworkModeler` 类之前）

**测试用例**：

| # | 方法名 | 输入 SMILES | 断言要点 |
|---|--------|------------|---------|
| 1 | `test_predict_admet_valid` | `CC(=O)Oc1ccccc1C(=O)O`（阿司匹林） | `logS` 为 float；`bbb_permeability`/`caco2_permeability`/`herg_risk`/`plasma_protein_binding` 在 `{"high","medium","low"}` 集合；`pains_alerts`/`toxicophore_alerts` 为 list；`bioavailability_score` 在 [0,1]；`summary.toxicity` 在 `{"high","medium","low"}` |
| 2 | `test_predict_admet_invalid` | `not_a_smiles` | `"error" in result` |
| 3 | `test_predict_admet_empty` | `""` | `result == {"error": "SMILES 不能为空"}` |
| 4 | `test_predict_admet_pains` | `C=CC(=O)C`（甲基乙烯基酮，匹配 `ene_one_michael`） | RDKit 可用时 `len(pains_alerts) >= 1`；RDKit 不可用时跳过 |
| 5 | `test_predict_admet_toxicophore` | `O=[N+]([O-])c1ccccc1`（硝基苯） | RDKit 可用时 `toxicophore_alerts` 含 `nitro`；RDKit 不可用时跳过 |
| 6 | `test_explain_valid` | `CN1C=NC2=C1C(=O)N(C(=O)N2C)C`（咖啡因） | `functional_groups` 为 list 且非空；`rings.total >= 1`；`atom_counts` 含 `C`/`N`/`O` |
| 7 | `test_explain_invalid` | `invalid_smiles` | `"error" in result` |
| 8 | `test_explain_chiral` | `C[C@H](N)C(=O)O`（L-丙氨酸） | RDKit 可用时 `stereochemistry.chiral_centers >= 1`；RDKit 不可用时跳过 |

**实现模式**（遵循现有 `test_assess_druglikeness_*` 模式）：

```python
def test_predict_admet_valid(self):
    """ADMET 预测 — 阿司匹林真实计算"""
    try:
        from rdkit import Chem  # noqa: F401
    except ImportError:
        pytest.skip("RDKit 未安装，跳过真实计算测试")

    from app.services.analyzer.molecule_designer import predict_admet
    result = predict_admet("CC(=O)Oc1ccccc1C(=O)O")
    assert "error" not in result
    assert isinstance(result["logS"], float)
    valid_levels = {"high", "medium", "low"}
    assert result["bbb_permeability"] in valid_levels
    # ... 其余断言
```

**RDKit 可用性处理**：
- 真实计算测试（#1, #4, #5, #6, #8）：用 `try/except ImportError + pytest.skip` 跳过
- Mock 路径测试：不跳过（无 RDKit 依赖）
- 空 SMILES 测试（#3）：不跳过（函数在 RDKit 检查前就返回错误）
- 无效 SMILES 测试（#2）：RDKit 可用时返回 `{"error": "无效 SMILES"}`，RDKit 不可用时 Mock 路径也会返回结果（需用 `pytest.skip` 或断言 `"error" in result or "_note" in result`）

### 步骤 2：后端集成测试（2 个）

**文件**：`backend/tests/test_api_integration.py`

**插入位置**：行 781（`test_list_models` 方法之后、行 783 空行处、`TestChat` 类之前）

**测试用例**：

| # | 方法名 | 端点 | 断言要点 |
|---|--------|------|---------|
| 1 | `test_predict_properties` | `POST /api/v1/molecules/predict-properties` | 200 + `assert_envelope_success`；`body["data"]` 含 `logS`/`bbb_permeability`/`pains_alerts` |
| 2 | `test_explain_molecule` | `POST /api/v1/molecules/explain` | 200 + `assert_envelope_success`；`body["data"]` 含 `functional_groups`/`rings`/`atom_counts` |

**实现模式**（遵循现有 `test_assess_druglikeness` 模式）：

```python
@pytest.mark.asyncio
async def test_predict_properties(self, client: AsyncClient, auth_headers: dict):
    """POST /molecules/predict-properties ADMET 预测 → 200 + ApiResponse 信封"""
    resp = await client.post(
        "/api/v1/molecules/predict-properties",
        json={"smiles": "CCO"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"predict-properties failed: {resp.text}"
    body = resp.json()
    assert_envelope_success(body, resp.headers)
    assert "logS" in body["data"]

@pytest.mark.asyncio
async def test_explain_molecule(self, client: AsyncClient, auth_headers: dict):
    """POST /molecules/explain 分子可解释性 → 200 + ApiResponse 信封"""
    resp = await client.post(
        "/api/v1/molecules/explain",
        json={"smiles": "CCO"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"explain failed: {resp.text}"
    body = resp.json()
    assert_envelope_success(body, resp.headers)
    assert "functional_groups" in body["data"]
```

**注意**：端点使用 `Body(..., embed=True)`，所以请求体为 `{"smiles": "CCO"}`（JSON body），不是 query params。这与 `/assess` 端点（用 query params）不同。

### 步骤 3：前端组件开发

**文件**：`frontend/app/workbench/molecules/page.tsx`

#### 3.1 修改导入（行 5-6）

```typescript
// 修改前
import { Atom, X, FlaskConical, Plus, Gauge } from 'lucide-react';
import { getMolecules, designMolecule, assessDruglikeness } from '@/lib/api';

// 修改后
import { Atom, X, FlaskConical, Plus, Gauge, Microscope, ScanSearch } from 'lucide-react';
import {
  getMolecules, designMolecule, assessDruglikeness,
  predictProperties, explainMolecule,
} from '@/lib/api';
```

#### 3.2 新增状态和 Mutation（行 17 之后）

```typescript
const [showAdmet, setShowAdmet] = useState(false);
const [showExplain, setShowExplain] = useState(false);
const [admetResult, setAdmetResult] = useState<any>(null);
const [explainResult, setExplainResult] = useState<any>(null);

const admetMutation = useMutation({
  mutationFn: (smiles: string) => predictProperties(smiles),
  onSuccess: (res) => {
    const data = (res as any)?.data || res;
    setAdmetResult(data);
  },
});

const explainMutation = useMutation({
  mutationFn: (smiles: string) => explainMolecule(smiles),
  onSuccess: (res) => {
    const data = (res as any)?.data || res;
    setExplainResult(data);
  },
});
```

#### 3.3 新增按钮入口（行 49-56 的按钮区域）

在「评估 SMILES」和「设计分子」按钮之间插入两个新按钮：

```tsx
<Button variant="secondary" onClick={() => { setAdmetResult(null); setShowAdmet(true); }}>
  <Microscope className="w-4 h-4" /> ADMET 预测
</Button>
<Button variant="secondary" onClick={() => { setExplainResult(null); setShowExplain(true); }}>
  <ScanSearch className="w-4 h-4" /> 分子解析
</Button>
```

#### 3.4 新增 Modal 渲染（行 205 之前，与现有 Modal 并列）

```tsx
{showAdmet && (
  <AdmetModal
    loading={admetMutation.isPending}
    result={admetResult}
    onClose={() => setShowAdmet(false)}
    onSubmit={(smiles) => admetMutation.mutate(smiles)}
  />
)}
{showExplain && (
  <ExplainModal
    loading={explainMutation.isPending}
    result={explainResult}
    onClose={() => setShowExplain(false)}
    onSubmit={(smiles) => explainMutation.mutate(smiles)}
  />
)}
```

#### 3.5 AdmetModal 组件（文件末尾，MetricCard 之后）

**展示内容**：
- SMILES 输入框 + 评估按钮（复用 AssessModal 的输入布局）
- 8 项 ADMET 指标卡片网格：`logS`、`bbb_permeability`、`bioavailability_score`、`caco2_permeability`、`herg_risk`、`plasma_protein_binding`、PAINS 警告数、毒性警示数
- 风险等级汇总徽章（`summary.toxicity`：high=红 / medium=黄 / low=绿）
- PAINS 警告和毒性警示结构列表（展开显示 name + smarts）
- Mock 模式提示（`_note` 字段）

**布局参考**：AssessModal 的 MetricCard 网格 + 颜色编码徽章模式。

#### 3.6 ExplainModal 组件

**展示内容**：
- SMILES 输入框 + 解析按钮
- 功能团识别列表：每个功能团显示 name、count、smarts（用 Badge 标签样式）
- 环系统统计：芳香环数、脂肪环数、总环数
- 立体化学：手性中心数、立体键数
- 原子组成：原子符号 → 数量（横向 Badge 列表）
- Mock 模式提示（`_note` 字段）

**布局参考**：AssessModal 的卡片网格 + Detail 抽屉的属性展示模式。

### 步骤 4：全量验证与 Bug 修复

#### 4.1 后端验证

```bash
# 1. ruff 静态检查（重点关注新增测试代码）
cd backend && ruff check app/ tests/

# 2. 单元测试 + 集成测试（--no-cov 避免 bcrypt 兼容性问题）
pytest tests/test_services_integration.py -v --no-cov
pytest tests/test_api_integration.py::TestMoleculeDesign -v --no-cov

# 3. 全量测试（验证无回归）
pytest --no-cov -x
```

**预期结果**：
- 新增 10 个测试全部通过
- 原有 1532 个测试无回归
- ruff 无新增错误

#### 4.2 前端验证

```bash
cd frontend
npm run lint        # ESLint 检查
npm run build       # TypeScript 编译 + 构建
```

**预期结果**：
- 无 TypeScript 类型错误
- 无 ESLint 错误
- 构建成功

#### 4.3 Bug 修复策略

在测试和构建过程中如发现以下类型 bug，按对应策略修复：

| Bug 类型 | 修复策略 |
|---------|---------|
| 测试断言失败 | 检查实际返回值 vs 预期值，修正断言或服务函数 |
| ruff 错误（F401/E701 等） | 按错误提示修正代码风格 |
| TypeScript 类型错误 | 补充类型声明或修正 props 类型 |
| 前端构建失败 | 检查导入路径、JSX 语法、未使用变量 |
| API 响应格式不匹配 | 检查 `res.data` 提取逻辑，确保与后端信封格式一致 |

### 步骤 5：开发文档

**文件**：`.trae/documents/精准药物设计系统-ADMET功能开发完成报告.md`

**内容结构**：
1. **功能说明**：ADMET 预测（8 项指标）和分子可解释性分析（功能团/环/立体化学/原子组成）的功能描述、技术实现方案（RDKit + SMARTS + Mock 降级）
2. **测试报告**：10 个新增测试的用例表、测试步骤、测试结果（通过/失败统计）、覆盖率影响
3. **Bug 修复记录**：开发过程中发现的 bug 列表、根因分析、修复方案、验证结果
4. **前端交互说明**：AdmetModal 和 ExplainModal 的 UI 截图说明、用户操作流程
5. **遗留问题**：已知限制（如 rhodanine PAINS 模式匹配、Mock 模式精度等）

---

## 三、假设与决策

### 假设
1. RDKit 在测试环境中可用（`requirements.txt` 含 `rdkit==2024.3.5`）
2. 前端 `npm run build` 环境已配置完成（node_modules 已安装）
3. 后端测试使用 `--no-cov` 标志（PyO3/bcrypt 兼容性问题，参考 test_api_integration.py 注释）
4. 前端响应数据提取模式：`res.data` 为 ApiResponse 信封的 `data` 字段（由 axios 拦截器处理）

### 决策
1. **test_endpoints_direct.py 不存在**：原计划的端点直连测试改为 HTTP 集成测试，统一在 `test_api_integration.py` 中添加，保持测试模式一致性。
2. **RDKit 可用性处理**：真实计算路径测试用 `try/except ImportError + pytest.skip` 跳过，Mock 路径测试不跳过，确保两种路径都有覆盖。
3. **前端 Modal 复用模式**：AdmetModal 和 ExplainModal 遵循现有 AssessModal 的布局和样式模式，保持 UI 一致性。
4. **PAINS 模式选择**：测试用 `C=CC(=O)C`（甲基乙烯基酮）验证 `ene_one_michael` 模式，避免 rhodanine SMARTS 匹配问题。
5. **请求体格式**：`/predict-properties` 和 `/explain` 端点使用 `Body(..., embed=True)`，请求体为 `{"smiles": "..."}`（JSON body），非 query params。

---

## 四、验证步骤

### 后端验证清单
- [ ] `ruff check app/ tests/` 无新增错误
- [ ] `pytest tests/test_services_integration.py -v --no-cov` 中 8 个新测试全部通过
- [ ] `pytest tests/test_api_integration.py::TestMoleculeDesign -v --no-cov` 中 2 个新测试全部通过
- [ ] `pytest --no-cov -x` 全量测试无回归（原有 1532 测试 + 新增 10 测试 = 1542 通过）

### 前端验证清单
- [ ] `npm run lint` 无错误
- [ ] `npm run build` 构建成功
- [ ] AdmetModal 能正确展示 8 项 ADMET 指标
- [ ] ExplainModal 能正确展示功能团/环/立体化学/原子组成
- [ ] Mock 模式提示（`_note`）正常显示

### 文档验证清单
- [ ] 开发完成报告包含功能说明、测试报告、bug 修复记录
- [ ] 所有文件路径引用准确
- [ ] 测试用例表完整

---

## 五、关键文件清单

| 文件 | 角色 | 操作 |
|------|------|------|
| [test_services_integration.py](file:///g:/软件开发/AI药物/backend/tests/test_services_integration.py) | 后端单元测试 | 编辑：行 106 后插入 8 个测试 |
| [test_api_integration.py](file:///g:/软件开发/AI药物/backend/tests/test_api_integration.py) | 后端集成测试 | 编辑：行 781 后插入 2 个测试 |
| [page.tsx](file:///g:/软件开发/AI药物/frontend/app/workbench/molecules/page.tsx) | 前端组件 | 编辑：导入 + 状态 + 按钮 + Modal + 2 个新组件 |
| [molecule_designer.py](file:///g:/软件开发/AI药物/backend/app/services/analyzer/molecule_designer.py) | 后端服务 | 只读参考（已实现） |
| [molecules.py](file:///g:/软件开发/AI药物/backend/app/api/v1/endpoints/molecules.py) | 后端端点 | 只读参考（已实现） |
| [api.ts](file:///g:/软件开发/AI药物/frontend/lib/api.ts) | 前端 API | 只读参考（已实现） |
| `.trae/documents/精准药物设计系统-ADMET功能开发完成报告.md` | 开发文档 | 新建 |
