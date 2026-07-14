# 功能 7：知情同意管理

## 1. 功能描述

### 业务价值
管理患者对数据使用、共享、发表的授权同意，满足 GDPR/HIPAA 合规要求，支持同意的授予、撤回和校验。

### 用户场景
- 医生为患者授予数据使用同意，设定过期时间
- 患者主动撤回同意，系统记录撤回原因
- 数据访问前校验同意状态，未授权则拒绝
- 研究人员查询项目的同意列表

### 需求来源
v3.0 文档第 11 章数据安全与隐私保护 + GDPR/HIPAA 合规要求。

## 2. 实现方法

### 技术方案
- **ConsentRecord 模型**：记录同意类型、状态、过期时间、约束条件
- **ConsentManager 服务**：grant / revoke / check / list / get 五个方法
- **三种同意类型**：data_use（数据使用）、sharing（数据共享）、publication（学术发表）
- **三种状态**：granted（已授权）、withdrawn（已撤回）、expired（已过期）
- **RBAC 集成**：授予/撤回需 doctor 以上角色

### 文件清单
| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/models/consent.py` | 新建 | ConsentRecord 模型 + ConsentStatus + ConsentType |
| `backend/app/services/consent/manager.py` | 新建 | ConsentManager 服务 |
| `backend/app/api/v1/endpoints/consent.py` | 新建 | 5 个 API 端点 |
| `backend/app/models/__init__.py` | 修改 | 注册 ConsentRecord |
| `backend/app/db/session.py` | 修改 | 模型导入同步 |
| `backend/tests/conftest.py` | 修改 | 测试 fixture 同步 |
| `backend/app/api/v1/router.py` | 修改 | 路由注册 |
| `backend/tests/test_consent.py` | 新建 | 19 个测试用例 |
| `frontend/lib/api/consent.ts` | 新建 | API 客户端 |
| `frontend/lib/api/index.ts` | 修改 | 统一导出 |
| `frontend/app/workbench/consent/page.tsx` | 新建 | 同意管理页面 |
| `frontend/components/layout/Sidebar.tsx` | 修改 | 新增导航入口 |

### API 端点
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/v1/consent` | 授予同意 | doctor+ |
| DELETE | `/api/v1/consent/{id}` | 撤回同意 | doctor+ |
| GET | `/api/v1/consent` | 同意列表 | 登录用户 |
| GET | `/api/v1/consent/check` | 校验状态 | 登录用户 |
| GET | `/api/v1/consent/{id}` | 同意详情 | 登录用户 |

## 3. 测试结果

| 指标 | 结果 |
|------|------|
| 测试用例数 | 19 |
| 通过率 | 100% |

### 测试覆盖
- 授予同意（基本 + 过期时间 + 约束条件 + 授权人）
- 撤回同意（基本 + 原因 + 不存在记录）
- 校验状态（已授权 True + 无记录 False + 已撤回 False + 已过期 False + 不同类型 False + 未过期 True）
- 列表查询（按项目 + 按患者过滤）
- 跨项目隔离
- 详情查询（存在 + 不存在）

## 4. 使用指南

### API 调用
```bash
# 授予同意
POST /api/v1/consent
{
  "project_id": "...",
  "patient_pseudonym": "PATIENT-001",
  "consent_type": "data_use",
  "purpose": "药物研发数据分析",
  "expires_at": "2027-12-31T00:00:00"
}

# 校验同意
GET /api/v1/consent/check?project_id=...&patient_pseudonym=PATIENT-001&consent_type=data_use
# Returns: {"granted": true, ...}

# 撤回同意
DELETE /api/v1/consent/{consent_id}
{"reason": "患者主动撤回"}
```

### 前端使用
侧边栏点击"知情同意"进入页面：
1. 点击"授予同意"按钮，填写患者假名、同意类型、用途、过期时间
2. 同意列表展示所有记录，按状态（已授权/已撤回/已过期）着色
3. 已授权记录可点击"撤回"按钮，输入撤回原因后确认
