# 精准药物设计系统 — ADMET 预测与分子可解释性功能开发计划

## Context

当前系统中两个分子端点返回占位数据，属于功能性缺陷：

1. `POST /molecules/predict-properties` — ADMET 性质预测，返回固定占位数据 `{"solubility": 0.5, "toxicity": "low", "bioavailability": 0.7}`，标注 `TODO: P2 集成 DeepChem ADMET 预测模型`
2. `POST /molecules/explain` — 分子可解释性分析，返回空数组 `{"fragments": [], "functional_groups": []}`，标注 `TODO: P2 集成 RDKit 子结构匹配`

**关键发现**：RDKit 已安装可用（`rdkit==2024.3.5`），且现有 `assess_druglikeness()` 函数已成功使用 RDKit 的 `Chem`/`Descriptors`/`Crippen` 模块。无需等待 DeepChem，即可用 RDKit 实现真实的 ADMET 预测和分子可解释性分析。

前端 API 函数 `predictProperties` 和 `explainMolecule` 已在 `frontend/lib/api.ts`（行 297-304）中定义，但分子页面缺少对应的 UI 入口。

**目标**：用 RDKit 实现真实的 ADMET 预测和分子可解释性分析，替换占位数据，并完善前端交互。

---

## 实现方案

### 步骤 1：后端服务函数（`app/services/analyzer/molecule_designer.py`）

在 `assess_druglikeness` 函数之后新增两个同步函数 + 两个 Mock 回退函数，遵循现有的 `try/except ImportError` 降级模式。

#### 1.1 SMARTS 模式字典（模块级常量）

```python
PAINS_PATTERNS = {
    "rhodanine": "C1=NC(=O)NC(=O)C1",
    "toxoflavin": "c1nc2n(sc2c(=O)[nH]1)",
    "isothiazolone": "C1=CC(=O)NS1",
    "hydroquinone": "c1cc(O)cc(O)1",
    "furan_reactive": "c1ccoc1C(=O)",
    "ene_one_michael": "C=CC(=O)",
    "azo_dye": "NN=N",
}

TOXICOPHORE_PATTERNS = {
    "nitro": "[N+](=O)[O-]",
    "azo": "N=N",
    "alkyl_halide": "[CX4][F,Cl,Br,I]",
    "aldehyde": "C(=O)[H]",
    "isocyanate": "N=C=O",
    "thiol": "[SH]",
    "epoxide": "C1OC1",
    "anhydride": "C(=O)OC(=O)",
    "peroxide": "OO",
    "heavy_metal_organic": "[Hg,Pb,Sn]",
}

FUNCTIONAL_GROUP_PATTERNS = {
    "hydroxyl": "[OX2H]",
    "carbonyl": "[CX3]=[OX1]",
    "carboxyl": "[CX3](=O)[OX1H0-,OX2H1]",
    "primary_amine": "[NX3;H2]",
    "secondary_amine": "[NX3;H1]",
    "tertiary_amine": "[NX3;H0]",
    "amide": "[NX3][CX3](=[OX1])",
    "ester": "[CX3](=O)[OX2H0]",
    "ether": "[OD2]([#6])[#6]",
    "aromatic_ring": "c1ccccc1",
    "halogen": "[F,Cl,Br,I]",
    "nitrile": "C#N",
    "sulfonamide": "[SX4]([OX2])([OX2])[NX3]",
}
```

#### 1.2 `predict_admet(smiles: str) -> Dict[str, Any]`

返回结构：
```python
{
    "smiles": str,
    "logS": float,                      # GSE: 0.5 - 0.01*(MW-20) - LogP
    "bbb_permeability": str,            # "high" | "medium" | "low"
    "bioavailability_score": float,     # 0.0-1.0
    "pains_alerts": List[Dict],         # [{"name", "smarts"}]
    "toxicophore_alerts": List[Dict],
    "herg_risk": str,                   # "high" | "medium" | "low"
    "caco2_permeability": str,          # "high" | "medium" | "low"
    "plasma_protein_binding": str,      # "low" | "medium" | "high"
    "summary": {"toxicity": str, "risk_count": int},
}
```

计算逻辑（均使用 RDKit）：
- **LogS**：General Solubility Equation `0.5 - 0.01*(MW-20) - LogP`
- **BBB 渗透性**：TPSA<90 且 1≤LogP≤3 → "high"；TPSA<140 且 0≤LogP≤4 → "medium"；否则 "low"
- **生物利用度评分**：Lipinski 违规数（-0.25/项）+ Veber 通过（+0.25）+ MW 200-500（+0.25）+ LogP 1-3（+0.25），clamp 0-1
- **PAINS/毒性警示**：SMARTS 子结构匹配
- **hERG 风险**：MW>400 且 LogP>3 且 TPSA<80 → "high"；MW>300 且 LogP>2 → "medium"；否则 "low"
- **Caco-2 渗透性**：TPSA<60 且 1≤LogP≤3 → "high"；TPSA<140 且 0≤LogP≤4 → "medium"；否则 "low"
- **血浆蛋白结合**：LogP>3 → "high"；1≤LogP≤3 → "medium"；否则 "low"

#### 1.3 `explain_molecule(smiles: str) -> Dict[str, Any]`

返回结构：
```python
{
    "smiles": str,
    "functional_groups": List[Dict],    # [{"name", "count", "smarts"}]
    "rings": {"aromatic": int, "aliphatic": int, "total": int},
    "stereochemistry": {"chiral_centers": int, "stereo_bonds": int},
    "atom_counts": Dict[str, int],      # {"C": 8, "O": 2, ...}
}
```

计算逻辑：
- **功能团**：SMARTS 匹配 + 计数
- **环分析**：`mol.GetRingInfo().AtomRings()` + 芳香性判断
- **立体化学**：`FindMolChiralCenters(mol)` + 遍历键的 `GetStereo()`
- **原子计数**：遍历 `mol.GetAtoms()`，按元素符号分组

#### 1.4 Mock 回退函数

`_mock_predict_admet(smiles)` 和 `_mock_explain_molecule(smiles)`：基于 SMILES 字符串特征估算（复用 `_mock_assess_druglikeness` 的原子计数逻辑），返回相同 schema + `_note` 字段。

### 步骤 2：修改端点（`app/api/v1/endpoints/molecules.py`）

**`predict_properties`（行 129-146）**：替换 TODO 块为：
```python
from app.services.analyzer.molecule_designer import predict_admet
result = predict_admet(smiles)
return success_response(result)
```

**`explain_molecule`（行 164-173）**：替换 TODO 块为：
```python
from app.services.analyzer.molecule_designer import explain_molecule as _explain
result = _explain(smiles)
return success_response(result)
```

### 步骤 3：后端测试

#### 3.1 单元测试（`tests/test_services_integration.py`，添加到 `TestMoleculeDesigner` 类）

| 测试 | 输入 | 断言 |
|------|------|------|
| `test_predict_admet_valid` | `"CC(=O)Oc1ccccc1C(=O)O"` (阿司匹林) | logS 为 float，bbb/caco2/herg 在有效集合，pains/toxicophore 为 list |
| `test_predict_admet_invalid` | `"invalid_smiles"` | `"error" in result` |
| `test_predict_admet_empty` | `""` | `result == {"error": "SMILES 不能为空"}` |
| `test_predict_admet_pains` | rhodanine SMILES | `len(pains_alerts) >= 1` |
| `test_predict_admet_toxicophore` | `"O=[N+]([O-])c1ccccc1"` (硝基苯) | toxicophore 含 nitro |
| `test_explain_valid` | `"CN1C=NC2=C1C(=O)N(C(=O)N2C)C"` (咖啡因) | functional_groups 非空，rings.total ≥ 1 |
| `test_explain_invalid` | `"invalid"` | `"error" in result` |
| `test_explain_chiral` | `"C[C@H](N)C(=O)O"` (L-丙氨酸) | `stereochemistry.chiral_centers >= 1` |

RDKit 不可用时用 `pytest.importorskip("rdkit")` 跳过，Mock 路径单独测试。

#### 3.2 端点直调测试（`tests/test_endpoints_direct.py`，`TestMoleculeEndpoints` 类）

| 测试 | 断言 |
|------|------|
| `test_predict_properties_endpoint` | `result["success"] is True`，`"logS" in result["data"]` |
| `test_explain_endpoint` | `"functional_groups" in result["data"]` |

#### 3.3 集成测试（`tests/test_api_integration.py`）

| 测试 | 断言 |
|------|------|
| `test_predict_properties_http` | POST 200 + `assert_envelope_success` |
| `test_explain_molecule_http` | POST 200 + envelope |

### 步骤 4：前端增强（`frontend/app/workbench/molecules/page.tsx`）

1. **新增导入**：`predictProperties`, `explainMolecule` from `@/lib/api`；`ShieldCheck`, `Microscope` 图标
2. **新增状态 + useMutation**：`showAdmet`/`admetResult`/`admetMutation`，`showExplain`/`explainResult`/`explainMutation`
3. **新增两个按钮**：在 header 的按钮组中添加"ADMET 预测"和"结构解析"
4. **AdmetModal 组件**：SMILES 输入 + 结果展示
   - 指标卡片网格：LogS、生物利用度评分、Caco-2、BBB
   - 风险徽章：hERG、毒性、血浆蛋白结合（颜色编码）
   - PAINS/毒性警示折叠列表
   - Mock 模式提示横幅
5. **ExplainModal 组件**：SMILES 输入 + 结果展示
   - 功能团表格（名称、计数、SMARTS）
   - 环分析摘要卡片
   - 原子计数条形图
   - 立体化学信息

---

## 验证方案

### 后端验证
```bash
cd g:\软件开发\AI药物\backend
# 单元测试
python -m pytest tests/test_services_integration.py -k "admet or explain" -v --no-cov
# 端点测试
python -m pytest tests/test_endpoints_direct.py -k "predict_properties or explain" -v --no-cov
# 集成测试
python -m pytest tests/test_api_integration.py -k "predict_properties or explain" -v --no-cov
# 全量回归
python -m pytest --no-cov -q
```

### 前端验证
```bash
cd g:\软件开发\AI药物\frontend
npm run build  # TypeScript 类型检查 + 构建
```

### 手动验证
1. 启动后端 `uvicorn app.main:app --reload`
2. 登录后在 `/docs` 测试 `POST /molecules/predict-properties` 和 `POST /molecules/explain`
3. 前端分子页面点击"ADMET 预测"和"结构解析"按钮，输入 SMILES 验证结果展示

---

## 关键文件

| 文件 | 变更类型 |
|------|----------|
| `backend/app/services/analyzer/molecule_designer.py` | 新增 `predict_admet`/`_mock_predict_admet`/`explain_molecule`/`_mock_explain_molecule` + SMARTS 常量 |
| `backend/app/api/v1/endpoints/molecules.py` | 修改 2 个端点（替换 TODO 占位） |
| `backend/tests/test_services_integration.py` | 新增 8 个单元测试 |
| `backend/tests/test_endpoints_direct.py` | 新增 2 个端点测试 |
| `backend/tests/test_api_integration.py` | 新增 2 个集成测试 |
| `frontend/app/workbench/molecules/page.tsx` | 新增 AdmetModal/ExplainModal 组件 + 按钮 + 状态 |

## 预期成果

- ADMET 预测从占位数据升级为 RDKit 真实计算（8 项指标）
- 分子可解释性从空数组升级为真实 SMARTS 匹配（13 种功能团 + 环分析 + 立体化学）
- 新增 12 个测试（8 单元 + 2 端点 + 2 集成）
- 前端新增 2 个交互面板
- 全量测试无回归（1532 + 12 = 1544 passed）
