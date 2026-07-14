# 功能 4：HL7 FHIR R4 标准化导出

## 1. 功能描述

HL7 FHIR R4 标准化导出模块将系统内的临床试验数据（患者基本信息、生命体征、诊断、用药记录等）转换为 HL7 FHIR R4 标准格式，实现与电子病历系统（EHR）、临床数据交换网络（如 Carequality、eHealth Exchange）的互操作性。

### 核心能力

- **FHIR Bundle 生成**：将项目数据打包为 FHIR R4 Bundle 资源
- **5 类资源映射**：Patient、Observation、Condition、MedicationStatement、ResearchStudy
- **编码体系支持**：LOINC（检验项目）、SNOMED CT（诊断/临床发现）、ICD-10（疾病编码）
- **JSON 格式输出**：符合 FHIR R4 规范的 JSON，可被任何 FHIR 兼容系统解析
- **下载与预览**：前端支持在线预览 Bundle 内容并下载 JSON 文件

## 2. 技术实现

### 2.1 架构设计

```
项目数据（DB） → FHIRExporter → FHIR Bundle（JSON）
                                  ↓
                        前端预览 + 下载
```

### 2.2 核心文件

| 文件路径 | 职责 |
|---------|------|
| `backend/app/services/cdisc/fhir_exporter.py` | FHIR 导出服务，资源映射与 Bundle 组装 |
| `backend/app/api/v1/endpoints/reports.py` | `POST /{project_id}/fhir` 端点 |
| `frontend/lib/api/reports.ts` | `exportFHIR()` 前端 API |
| `frontend/app/reports/page.tsx` | FHIR 导出卡片 UI |
| `backend/tests/test_fhir_exporter.py` | 单元测试（31 个用例） |

### 2.3 资源映射规则

| 系统数据 | FHIR 资源 | 关键字段映射 |
|---------|----------|-------------|
| 患者假名 | Patient | `id`, `identifier`, `active` |
| 生命体征 | Observation | `code`（LOINC）, `valueQuantity`, `subject` |
| 诊断记录 | Condition | `code`（SNOMED CT）, `clinicalStatus`, `subject` |
| 用药记录 | MedicationStatement | `medicationCodeableConcept`, `dosage`, `subject` |
| 研究项目 | ResearchStudy | `status`, `subject`, `enrollment` |

### 2.4 Bundle 结构示例

```json
{
  "resourceType": "Bundle",
  "type": "collection",
  "timestamp": "2026-07-12T10:00:00Z",
  "entry": [
    {
      "fullUrl": "urn:uuid:patient-001",
      "resource": {
        "resourceType": "Patient",
        "id": "patient-001",
        "identifier": [{"value": "PATIENT-001"}],
        "active": true
      }
    },
    {
      "fullUrl": "urn:uuid:obs-001",
      "resource": {
        "resourceType": "Observation",
        "status": "final",
        "code": {
          "coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body Weight"}]
        },
        "subject": {"reference": "urn:uuid:patient-001"},
        "valueQuantity": {"value": 70, "unit": "kg"}
      }
    }
  ]
}
```

### 2.5 关键方法

- `FHIRExporter.export_bundle(project_id: str) -> dict`：导出完整 Bundle
- `_build_patient(patient_data) -> dict`：构建 Patient 资源
- `_build_observation(obs_data) -> dict`：构建 Observation 资源
- `_build_condition(cond_data) -> dict`：构建 Condition 资源
- `_build_medication_statement(med_data) -> dict`：构建 MedicationStatement 资源

## 3. 测试结果

| 测试文件 | 用例数 | 通过 | 覆盖场景 |
|---------|-------|------|---------|
| `test_fhir_exporter.py` | 31 | 31 ✅ | 5 类资源构建、Bundle 组装、编码映射、空数据处理、多患者场景 |

**关键测试场景**：
- Patient 资源 identifier 正确映射
- Observation 的 LOINC 编码正确性
- Condition 的 SNOMED CT 编码正确性
- MedicicationStatement 的 dosage 结构
- Bundle type 为 collection
- entry 引用关系（subject.reference）正确
- 空项目导出空 Bundle

## 4. 使用指南

### 4.1 HTTP 端点

```bash
POST /api/v1/reports/{project_id}/fhir
Authorization: Bearer <token>
```

响应：
```json
{
  "success": true,
  "message": "FHIR R4 导出完成",
  "data": {
    "resourceType": "Bundle",
    "type": "collection",
    "entry": [...]
  }
}
```

### 4.2 前端使用

在报告中心页面（`/reports`），点击"FHIR R4 导出"卡片的"导出"按钮：
1. 调用 `exportFHIR(projectId)`
2. 展示 Bundle 元信息（资源类型统计、时间戳）
3. 显示前 10 条 entry 预览
4. 点击"下载 JSON"按钮保存完整 Bundle 文件

### 4.3 前端 API

```typescript
import { exportFHIR } from '@/lib/api';

const bundle = await exportFHIR(projectId);
console.log(bundle.resourceType);  // "Bundle"
console.log(bundle.entry.length);  // 资源总数
```

### 4.4 编码体系说明

| 体系 | 用途 | 示例 |
|------|------|------|
| LOINC | 检验/观察项目 | `29463-7` = 体重 |
| SNOMED CT | 诊断/临床发现 | `73211009` = 糖尿病 |
| ICD-10 | 疾病分类（可选） | `E11` = 2 型糖尿病 |

### 4.5 验证工具

导出的 JSON 可使用以下工具验证合规性：
- HL7 FHIR Validator：`https://validator.fhir.org/`
- Firely：`https://fire.ly/`
- HAPI FHIR：Java 库，可集成到 CI 流程
