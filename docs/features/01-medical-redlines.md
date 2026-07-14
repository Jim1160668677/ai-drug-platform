# 功能 1：AI 医学红线规则

## 1. 功能描述

AI 医学红线规则模块是系统的 P0 级安全守卫组件，用于在 LLM 生成医学建议、药物推荐、诊断结论等高风险输出前，进行强制性合规校验。该模块确保 AI 输出不越过医学伦理和法律红线，避免向用户提供可能造成健康损害的建议。

### 核心能力

- **红线规则库**：内置 12 类医学红线规则，涵盖药物剂量、禁忌症、孕妇/儿童用药、替代诊断等场景
- **实时拦截**：在 LLM 响应链路中作为中间件运行，对每次输出进行 < 50ms 的快速校验
- **可解释拒绝**：触发红线时返回结构化拒绝原因，包含规则编号、风险等级、建议引导
- **审计留痕**：所有拦截事件写入审计日志，支持事后追溯

## 2. 技术实现

### 2.1 架构设计

```
用户请求 → LLM 生成 → 红线守卫拦截 → 安全响应 / 拒绝响应
                              ↓
                         审计日志记录
```

### 2.2 核心文件

| 文件路径 | 职责 |
|---------|------|
| `backend/app/services/guardrail/medical_redlines.py` | 红线规则引擎，规则匹配与决策 |
| `backend/app/api/v1/endpoints/guardrail.py` | HTTP 端点，供前端/外部调用校验 |
| `backend/tests/test_guardrail_medical.py` | 单元测试（71 个用例） |

### 2.3 规则定义示例

```python
RED_LINES = [
    {
        "id": "RL001",
        "category": "drug_dosage",
        "severity": "critical",
        "pattern": r"推荐.*超过.*最大剂量",
        "action": "block",
        "message": "禁止推荐超过药品说明书最大剂量的用药方案",
    },
    {
        "id": "RL002",
        "category": "diagnosis_replacement",
        "severity": "critical",
        "pattern": r"确诊|诊断为",
        "action": "block",
        "message": "AI 不得替代医师做出最终确诊，应表述为'可能提示'",
    },
    # ... 共 12 条规则
]
```

### 2.4 关键方法

- `check(text: str) -> GuardrailResult`：对文本执行全量规则匹配
- `check_batch(texts: list[str]) -> list[GuardrailResult]`：批量校验
- `add_rule(rule: dict) -> None`：动态扩展规则库
- `get_rules() -> list[dict]`：查询当前生效规则

## 3. 测试结果

| 测试文件 | 用例数 | 通过 | 覆盖场景 |
|---------|-------|------|---------|
| `test_guardrail_medical.py` | 71 | 71 ✅ | 12 条规则正例/反例、批量校验、动态扩展、边界条件 |

**关键测试场景**：
- 药物剂量超限拦截
- 孕妇禁用药物提示
- AI 替代确诊的表述拦截
- 儿童用药禁忌
- 正常医学描述的误拦率（应为 0）

## 4. 使用指南

### 4.1 后端调用

```python
from app.services.guardrail.medical_redlines import MedicalRedlineGuard

guard = MedicalRedlineGuard()
result = guard.check("建议患者每日服用阿司匹林 500mg 用于镇痛")
if not result.passed:
    # 返回拒绝响应
    return StandardResponse(
        success=False,
        message=f"触发医学红线: {result.violated_rule_id}",
        data={"reason": result.message}
    )
```

### 4.2 HTTP 端点

```bash
POST /api/v1/guardrail/check
Content-Type: application/json

{
  "text": "建议患者..."
}
```

响应：
```json
{
  "success": true,
  "data": {
    "passed": false,
    "violated_rule_id": "RL001",
    "severity": "critical",
    "message": "禁止推荐超过药品说明书最大剂量..."
  }
}
```

### 4.3 前端集成

前端在 AI 问答页面、治疗方案推荐页面接收到 LLM 响应后，自动调用红线校验端点。若未通过，在 UI 上显示醒目的安全提示卡片，并隐藏原始内容。

### 4.4 运维扩展

新增红线规则无需重启服务，通过管理后台 `POST /api/v1/guardrail/rules` 动态添加，立即对所有后续请求生效。
