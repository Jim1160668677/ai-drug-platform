# 功能 3：DeepDDI 药物相互作用预警

## 1. 功能描述

DeepDDI 药物相互作用预警模块基于深度学习模型预测两种药物联合使用时可能产生的相互作用（DDI），在治疗方案推荐、分子评估等场景中提供安全预警，辅助医师避免有害的药物组合。

### 核心能力

- **DDI 预测**：输入两种药物（SMILES 或名称），输出相互作用类型和概率
- **相互作用类型库**：覆盖 86 种 FDA 标准相互作用类型
- **批量检查**：支持单药物与多药物列表的批量相互作用筛查
- **风险分级**：根据相互作用严重程度分为 contraindicated / major / moderate / minor 四级
- **替代建议**：对高风险组合推荐可选的替代药物

## 2. 技术实现

### 2.1 架构设计

```
药物 A (SMILES) ─┐
                 ├→ DeepDDI 模型 → 相互作用类型 + 概率 → 风险分级 → 预警
药物 B (SMILES) ─┘
```

### 2.2 核心文件

| 文件路径 | 职责 |
|---------|------|
| `backend/app/services/ddi/checker.py` | DDI 检查服务，模型调用与结果分级 |
| `backend/app/services/ddi/__init__.py` | 包初始化 |
| `backend/app/api/v1/endpoints/ddi.py` | HTTP 端点 |
| `backend/tests/test_ddi_checker.py` | 单元测试（26 个用例） |

### 2.3 模型说明

当前使用 Mock 模式（基于规则的知识库匹配），生产环境可切换为 DeepDDI 预训练模型：

```python
class DDIChecker:
    def __init__(self, use_model: bool = False):
        self.use_model = use_model
        if use_model:
            self.model = self._load_deepddi_model()
        else:
            self.knowledge_base = self._load_ddi_kb()

    async def check(self, drug_a: str, drug_b: str) -> DDIResult:
        if self.use_model:
            return await self._predict_with_model(drug_a, drug_b)
        return await self._match_with_kb(drug_a, drug_b)
```

### 2.4 相互作用分级

| 等级 | 含义 | 处置建议 |
|------|------|---------|
| `contraindicated` | 禁忌 | 禁止联合使用 |
| `major` | 严重 | 强烈不建议，需医师评估 |
| `moderate` | 中等 | 谨慎使用，需监测 |
| `minor` | 轻微 | 注意观察 |

### 2.5 关键方法

- `check(drug_a: str, drug_b: str) -> DDIResult`：单对药物检查
- `check_batch(drug: str, others: list[str]) -> list[DDIResult]`：批量检查
- `get_alternatives(drug: str, contraindicated: str) -> list[str]`：获取替代药物

## 3. 测试结果

| 测试文件 | 用例数 | 通过 | 覆盖场景 |
|---------|-------|------|---------|
| `test_ddi_checker.py` | 26 | 26 ✅ | 已知 DDI 匹配、无相互作用、批量检查、风险分级、替代建议、边界条件 |

**关键测试场景**：
- 华法林 + 阿司匹林 → contraindicated（出血风险）
- 西柚汁 + 他汀类 → major（CYP3A4 抑制）
- 对乙酰氨基酚 + 布洛芬 → minor（一般安全）
- 无相互作用的药物对返回 negative
- 批量检查结果数量与输入一致

## 4. 使用指南

### 4.1 HTTP 端点

```bash
POST /api/v1/ddi/check
Content-Type: application/json

{
  "drug_a": "warfarin",
  "drug_b": "aspirin"
}
```

响应：
```json
{
  "success": true,
  "data": {
    "drug_a": "warfarin",
    "drug_b": "aspirin",
    "has_interaction": true,
    "interaction_type": "increased_bleeding_risk",
    "severity": "contraindicated",
    "probability": 0.92,
    "description": "联合使用显著增加出血风险",
    "recommendation": "禁止联合使用，建议更换抗凝方案"
  }
}
```

### 4.2 批量检查

```bash
POST /api/v1/ddi/check-batch
{
  "drug": "warfarin",
  "others": ["aspirin", "ibuprofen", "paracetamol"]
}
```

### 4.3 前端集成

分子库页面和治疗方案页面在展示药物信息时，自动调用 DDI 检查端点。若存在相互作用，在药物卡片上显示红色/橙色警告标签，点击可查看详细相互作用说明。

### 4.4 模型切换

在 `backend/.env` 中配置：
```
DDI_USE_MODEL=true          # 启用深度学习模型
DDI_MODEL_PATH=/models/deepddi.h5
```

未配置时默认使用 Mock 知识库模式，适用于开发和测试环境。
