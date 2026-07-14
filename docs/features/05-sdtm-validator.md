# 功能 5：Pinnacle 21 CDISC 校验

## 1. 功能描述

### 业务价值
对导出的 SDTM 数据进行 FDA 标准校验，确保临床试验数据质量，减少监管提交被退回的风险。纯 Python 实现，无需 Java 环境。

### 用户场景
- 研究人员导出 SDTM 数据后，点击"校验"按钮验证数据合规性
- 系统列出所有错误和警告，按 FDA 规则编号分类
- 合规数据通过校验，问题数据精确定位到域和记录

### 需求来源
v3.0 文档第 8 章 v3.0 开源工具集成策略包含 Pinnacle 21。

## 2. 实现方法

### 技术方案
纯 Python 实现 8 条 FDA 核心校验规则：

| 规则 ID | 严重级别 | 说明 |
|---------|----------|------|
| CG0001 | error | USUBJID 必须唯一 |
| CG0002 | error | DOMAIN 必填且与域名匹配 |
| CG0003 | error | STUDYID 跨域一致 |
| CG0004 | error | USUBJID 跨域引用完整（非 DM 域的 USUBJID 必须在 DM 中存在） |
| CG0005 | warning | --SEQ 必须连续 |
| CG0006 | warning | 必填变量非空（域特定） |
| CG0007 | error | 变量名 ≤ 8 字符 |
| CG0008 | warning | 日期格式 ISO 8601 |

### 文件清单
| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/services/cdisc/sdtm_validator.py` | 新建 | SDTMValidator 类 + 8 条规则 |
| `backend/app/api/v1/endpoints/reports.py` | 修改 | 新增校验端点 |
| `backend/tests/test_sdtm_validator.py` | 新建 | 31 个测试用例 |
| `frontend/lib/api/reports.ts` | 修改 | 新增 validateSDTM 函数 |
| `frontend/app/reports/page.tsx` | 修改 | SDTM 卡片新增"校验"按钮 + 结果弹窗 |

### 关键代码
```python
class SDTMValidator:
    def validate(self, sdtm_data: Dict) -> Dict:
        """校验 SDTM 数据
        Returns: {errors, warnings, passed, rules_checked, total_issues, summary}
        """
        # 逐规则检查 domains 中的每条记录
```

### API 端点
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/reports/{project_id}/sdtm/validate` | 生成 SDTM 并校验 |

## 3. 测试结果

| 指标 | 结果 |
|------|------|
| 测试用例数 | 31 |
| 通过率 | 100% |
| 校验规则数 | 8 |
| 测试覆盖 | 每规则正例+反例+边界 |

### 验收清单
- [x] 重复 USUBJID → error
- [x] 缺失 DOMAIN → error
- [x] STUDYID 不一致 → error
- [x] 跨域引用不完整 → error
- [x] 变量名超长 → error
- [x] 必填变量为空 → warning
- [x] 日期格式非 ISO 8601 → warning
- [x] 合规数据 → passed=True

## 4. 使用指南

### API 调用
```bash
POST /api/v1/reports/{project_id}/sdtm/validate
Authorization: Bearer {token}

# 返回校验结果
{
  "errors": [{"rule_id": "CG0001", "message": "...", "domain": "DM", "record_index": 0}],
  "warnings": [{"rule_id": "CG0006", "message": "...", "domain": "VS", "record_index": 2}],
  "passed": false,
  "rules_checked": 8,
  "total_issues": 2,
  "summary": "校验未通过：1 个错误，1 个警告"
}
```

### 前端使用
在报告中心页面，SDTM 卡片有"生成"和"校验"两个按钮。点击"校验"后弹窗展示错误/警告数量、通过状态和详情列表。
