# 精准药物设计系统 API 接口文档

| 项 | 值 |
| --- | --- |
| 版本号 | v1.0.0 |
| 更新日期 | 2026-07-05 |
| 维护者 | 精准药物设计团队 |
| 后端框架 | FastAPI + SQLAlchemy ORM (Async) + MySQL/PostgreSQL |
| 前端框架 | Next.js 14 |
| API 版本 | v1 |

---

## 1. 概述

### 1.1 Base URL

| 环境 | Base URL |
| --- | --- |
| 开发环境 | `http://localhost:8000/api/v1` |
| 生产环境 | `https://{your-domain}/api/v1` |

所有端点路径均以 `/api/v1` 为前缀。例如登录接口完整路径为 `POST /api/v1/auth/login`。

### 1.2 认证方式

系统采用 **JWT Bearer Token** 认证。

- 通过 `POST /api/v1/auth/login` 获取 `access_token`。
- 在后续请求的 `Authorization` 头中携带：`Authorization: Bearer <access_token>`。
- Token 默认有效期 1440 分钟（24 小时），算法 HS256。

未携带或携带无效 Token 访问受保护资源时返回 `401 Unauthorized`。
账户被禁用时返回 `403 Forbidden`。

### 1.3 统一响应格式

业务型接口统一使用 `StandardResponse` 包裹：

```json
{
  "success": true,
  "message": "",
  "data": null
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| success | boolean | 业务是否成功 |
| message | string | 提示信息（成功/失败描述） |
| data | any | 业务数据，可为对象、数组或 null |

资源型接口（如 `GET /projects`、`POST /auth/login`）直接返回对应的 Pydantic 模型或模型数组，不包一层 `StandardResponse`。

### 1.4 通用说明

#### 1.4.1 角色枚举

| 角色 | 标识 | 权限说明 |
| --- | --- | --- |
| 创始人 | `founder` | 全部权限，包括用户管理、LLM 配置、强制深度分析 |
| 首席研究员 | `chief_researcher` | LLM 配置管理、审计日志查看、强制深度分析 |
| 研究员 | `researcher` | 项目、靶点、分子、实验等业务操作 |
| 医生 | `doctor` | 临床试验、治疗方案查看 |
| 数据工程师 | `data_engineer` | 数据上传、解析、工作流触发 |

#### 1.4.2 分页参数

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| skip | int | 0 | 跳过记录数，≥0 |
| limit | int | 50/100 | 每页数量，1~200（部分接口上限 500） |

#### 1.4.3 通用错误码

| HTTP 状态码 | 含义 | 触发场景 |
| --- | --- | --- |
| 200 | 成功 | 请求处理成功 |
| 400 | 请求错误 | 参数错误、业务校验失败 |
| 401 | 未认证 | Token 缺失/失效 |
| 403 | 无权限 | 账户禁用、角色权限不足 |
| 404 | 资源不存在 | 路径参数对应的实体不存在 |
| 409 | 冲突 | 唯一约束冲突（如配置名重复） |
| 422 | 参数无效 | 枚举值非法、Pydantic 校验失败 |
| 500 | 服务器错误 | 内部异常（如解析失败） |

---

## 2. 认证模块

模块前缀：`/api/v1/auth`，标签：`认证`

### 2.1 用户登录

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/auth/login` |
| 鉴权 | 无 |
| 描述 | 用户登录（OAuth2 兼容），校验邮箱密码并签发 JWT |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| email | string | 是 | 邮箱 |
| password | string | 是 | 密码 |

**响应**：`TokenResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| access_token | string | JWT 访问令牌 |
| token_type | string | 固定 `bearer` |
| role | string | 用户角色 |
| name | string | 用户名 |
| email | string | 邮箱 |

**关键逻辑**：邮箱或密码错误返回 401；账户禁用返回 403。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login?email=alice@example.com&password=Secret123"
```

```javascript
const res = await fetch(
  "http://localhost:8000/api/v1/auth/login?email=alice@example.com&password=Secret123",
  { method: "POST" }
);
const data = await res.json();
localStorage.setItem("token", data.access_token);
```

### 2.2 用户注册

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/auth/register` |
| 鉴权 | 无 |
| 描述 | 用户注册，密码经哈希后存储，角色默认 researcher |

**请求体**：`UserCreate`

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| email | string | 是 | - | 邮箱（唯一） |
| name | string | 是 | - | 用户名 |
| password | string | 是 | - | 明文密码 |
| role | string | 否 | researcher | 角色枚举 |
| organization | string | 否 | null | 所属机构 |

**响应**：`UserResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 用户 ID |
| email | string | 邮箱 |
| name | string | 用户名 |
| role | string | 角色 |
| organization | string\|null | 机构 |
| is_active | boolean | 是否启用 |
| created_at | datetime | 创建时间 |

**关键逻辑**：邮箱已注册返回 400；角色枚举非法时回退为 `researcher`。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"bob@example.com","name":"Bob","password":"Pwd123","role":"researcher"}'
```

### 2.3 获取当前用户

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/auth/me` |
| 鉴权 | JWT |
| 描述 | 根据 Token 解析当前登录用户信息 |

**响应**：`UserResponse`

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer <token>"
```

---

## 3. 用户管理模块

模块前缀：`/api/v1/users`，标签：`用户管理`。全部端点需 **founder** 角色。

### 3.1 用户列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/users` |
| 鉴权 | JWT + founder |
| 描述 | 获取用户列表，支持按角色和状态过滤 |

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| skip | int | 否 | 0 | 跳过记录数 |
| limit | int | 否 | 50 | 每页数量（1~200） |
| role | string | 否 | - | 按角色过滤 |
| is_active | boolean | 否 | - | 按启用状态过滤 |

**响应**：`UserListResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| items | UserResponse[] | 用户列表 |
| total | int | 总数 |
| skip | int | 跳过数 |
| limit | int | 每页数 |

**关键逻辑**：role 值非合法枚举返回 400；按创建时间倒序。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/users?role=researcher&is_active=true&skip=0&limit=20" \
  -H "Authorization: Bearer <token>"
```

### 3.2 修改用户角色

| 项 | 值 |
| --- | --- |
| 方法路径 | `PATCH /api/v1/users/{user_id}/role` |
| 鉴权 | JWT + founder |
| 描述 | 修改指定用户的角色 |

**路径参数**

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| user_id | UUID | 用户 ID |

**请求体**：`UserUpdateRole`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| role | string | 是 | 新角色：founder/chief_researcher/researcher/doctor/data_engineer |

**响应**：`UserResponse`

**关键逻辑**：用户不存在返回 404；不能修改自己的角色（400）；不能将用户提升为 founder（400）。

**示例**

```bash
curl -X PATCH "http://localhost:8000/api/v1/users/3fa85f64-5717-4562-b3fc-2c963f66afa6/role" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"role":"chief_researcher"}'
```

### 3.3 启用/禁用用户

| 项 | 值 |
| --- | --- |
| 方法路径 | `PATCH /api/v1/users/{user_id}/status` |
| 鉴权 | JWT + founder |
| 描述 | 启用或禁用指定用户账户 |

**请求体**：`UserUpdateStatus`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| is_active | boolean | 是 | 启用/禁用 |

**响应**：`UserResponse`

**关键逻辑**：用户不存在返回 404；不能禁用自己（400）；不能禁用 founder 账户（400）。

**示例**

```bash
curl -X PATCH "http://localhost:8000/api/v1/users/3fa85f64-5717-4562-b3fc-2c963f66afa6/status" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"is_active":false}'
```

---

## 4. 审计日志模块

模块前缀：`/api/v1/audit`，标签：`审计日志`

### 4.1 审计日志查询

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/audit/logs` |
| 鉴权 | JWT + `audit:read` 权限（founder/chief_researcher） |
| 描述 | 查询不可篡改的操作日志，支持按操作人、动作、实体过滤 |

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| actor | string | 否 | - | 操作人（邮箱/姓名） |
| action | string | 否 | - | 动作类型 |
| entity | string | 否 | - | 实体类型 |
| skip | int | 否 | 0 | 跳过记录数 |
| limit | int | 否 | 100 | 每页数量（1~500） |

**响应**：`StandardResponse`，`data` 结构：

```json
{
  "total": 100,
  "logs": [
    {
      "id": "uuid",
      "actor": "alice@example.com",
      "role": "founder",
      "action": "create",
      "entity": "llm_config",
      "entity_id": "uuid",
      "ip_address": "192.168.1.1",
      "user_agent": "Mozilla/5.0...",
      "created_at": "2026-07-05T08:00:00",
      "detail": "创建 LLM 配置 Agnes"
    }
  ]
}
```

**关键逻辑**：日志按 `created_at` 倒序；自动从 `X-Forwarded-For` 提取客户端 IP。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/audit/logs?action=create&entity=project&limit=50" \
  -H "Authorization: Bearer <token>"
```

---

## 5. LLM 配置模块

模块前缀：`/api/v1/llm-configs`，标签：`LLM 配置`。读操作需登录，写操作需 **founder 或 chief_researcher**。

### 5.1 LLM 配置列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/llm-configs` |
| 鉴权 | JWT |
| 描述 | 获取所有 LLM 配置，API key 脱敏显示 |

**响应**：`LLMConfigResponse[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 配置 ID |
| name | string | 配置名（如 Agnes、OpenAI） |
| provider | string | 提供商标识 |
| access_mode | string | 访问模式：api_only/local_deploy/proxy |
| upstream_protocol | string | 上游协议：chat_completions/completions/anthropic |
| base_url | string | 基础 URL |
| api_key_masked | string | 脱敏 API key（前 6 位…后 4 位） |
| test_model | string | 测试模型 |
| fast_model | string\|null | 快速筛查模型 |
| deep_model | string\|null | 深度洞察模型 |
| temperature | float | 温度（0~2） |
| max_tokens | int | 最大 token 数 |
| timeout_sec | int | 超时秒数 |
| is_active | boolean | 是否激活 |
| description | string\|null | 描述 |
| last_test_at | datetime\|null | 最近测试时间 |
| last_test_success | boolean\|null | 最近测试是否成功 |
| last_test_message | string\|null | 最近测试信息 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

**关键逻辑**：按创建时间倒序；API key 解密后脱敏（保留前 6 位和后 4 位）。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/llm-configs" \
  -H "Authorization: Bearer <token>"
```

### 5.2 获取当前激活配置

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/llm-configs/active` |
| 鉴权 | JWT |
| 描述 | 获取当前激活的 LLM 配置，无激活时返回默认提示 |

**响应**：`StandardResponse`

- 有激活配置时：`data` 为 `LLMConfigResponse` 对象
- 无激活配置时：`success=false`，`data={use_default:true, mock_mode:true}`

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/llm-configs/active" \
  -H "Authorization: Bearer <token>"
```

### 5.3 创建 LLM 配置

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/llm-configs` |
| 鉴权 | JWT + founder/chief_researcher |
| 描述 | 创建新的 LLM 配置，API key 经 Fernet 加密存储 |

**请求体**：`LLMConfigCreate`

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| name | string | 是 | - | 配置名（唯一） |
| provider | string | 否 | openai_compatible | 提供商标识 |
| access_mode | string | 否 | api_only | api_only/local_deploy/proxy |
| upstream_protocol | string | 否 | chat_completions | chat_completions/completions/anthropic |
| base_url | string | 是 | - | 基础 URL |
| api_key | string | 是 | - | API 密钥（明文传入） |
| test_model | string | 是 | - | 测试模型名 |
| fast_model | string | 否 | null | 快速筛查模型 |
| deep_model | string | 否 | null | 深度洞察模型 |
| temperature | float | 否 | 0.7 | 温度 0~2 |
| max_tokens | int | 否 | 2000 | 1~32000 |
| timeout_sec | int | 否 | 60 | 1~600 |
| description | string | 否 | null | 描述 |
| is_active | boolean | 否 | false | 是否激活 |

**响应**：`LLMConfigResponse`

**关键逻辑**：名称重复返回 409；枚举值非法返回 422；设为激活时其他配置自动置为非激活。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/llm-configs" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Agnes",
    "provider":"openai_compatible",
    "access_mode":"api_only",
    "upstream_protocol":"chat_completions",
    "base_url":"https://apihub.agnes-ai.com/v1",
    "api_key":"sk-xxxxxxxxxxxx",
    "test_model":"agnes-2.0-flash",
    "fast_model":"agnes-2.0-flash",
    "deep_model":"agnes-2.0-pro",
    "is_active":true
  }'
```

### 5.4 更新 LLM 配置

| 项 | 值 |
| --- | --- |
| 方法路径 | `PUT /api/v1/llm-configs/{config_id}` |
| 鉴权 | JWT + founder/chief_researcher |
| 描述 | 部分更新 LLM 配置 |

**路径参数**：`config_id` UUID

**请求体**：`LLMConfigUpdate`（所有字段均可选，仅传需要更新的字段）

字段同 5.3，全部可选。

**响应**：`LLMConfigResponse`

**关键逻辑**：配置不存在返回 404；名称冲突返回 409；设为激活时其他配置自动失活；传入 `api_key` 自动加密。

**示例**

```bash
curl -X PUT "http://localhost:8000/api/v1/llm-configs/3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"temperature":0.5,"max_tokens":4000}'
```

### 5.5 删除 LLM 配置

| 项 | 值 |
| --- | --- |
| 方法路径 | `DELETE /api/v1/llm-configs/{config_id}` |
| 鉴权 | JWT + founder/chief_researcher |
| 描述 | 删除指定 LLM 配置 |

**响应**：`StandardResponse`

**关键逻辑**：配置不存在返回 404；不能删除当前激活的配置（400），需先切换到其他配置。

**示例**

```bash
curl -X DELETE "http://localhost:8000/api/v1/llm-configs/3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 5.6 激活配置

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/llm-configs/{config_id}/activate` |
| 鉴权 | JWT + founder/chief_researcher |
| 描述 | 激活指定 LLM 配置，其他配置自动置为非激活 |

**响应**：`StandardResponse`，`data={name:"<配置名>"}`

**关键逻辑**：配置不存在返回 404；同一时间仅一个配置可激活。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/llm-configs/3fa85f64-5717-4562-b3fc-2c963f66afa6/activate" \
  -H "Authorization: Bearer <token>"
```

### 5.7 测试 LLM 配置连通性

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/llm-configs/test` |
| 鉴权 | JWT + founder/chief_researcher |
| 描述 | 发送一条 ping 消息测试 LLM 配置连通性，不传 config_id 时测试当前激活配置 |

**请求体**：`LLMTestRequest`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| config_id | UUID | 否 | 不传则测试当前激活配置 |
| custom_message | string | 否 | 自定义测试消息，默认 `ping` |

**响应**：`LLMTestResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| success | boolean | 是否成功 |
| message | string | 结果信息 |
| model | string\|null | 实际响应的模型名 |
| response_text | string\|null | LLM 响应文本（前 500 字符） |
| duration_sec | float\|null | 耗时（秒） |

**关键逻辑**：通过 httpx 调用上游 `chat/completions` 或 `completions` 接口；测试结果（时间/成功/消息）写回配置记录；anthropic 协议暂不支持。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/llm-configs/test" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"config_id":"3fa85f64-5717-4562-b3fc-2c963f66afa6","custom_message":"你好"}'
```

---

## 6. 项目管理模块

模块前缀：`/api/v1/projects`，标签：`项目管理`。所有端点需 JWT。

### 6.1 项目列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/projects` |
| 鉴权 | JWT |
| 描述 | 获取项目列表，按创建时间倒序 |

**查询参数**

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| skip | int | 0 | 跳过记录数 |
| limit | int | 50 | 每页数量（1~200） |

**响应**：`ProjectResponse[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 项目 ID |
| name | string | 项目名 |
| patient_pseudonym | string\|null | 患者化名 |
| cancer_type | string\|null | 癌种 |
| stage | string\|null | 分期 |
| description | string\|null | 描述 |
| status | string | 项目状态 |
| owner_id | UUID | 创建者 ID |
| created_at | datetime | 创建时间 |

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/projects?skip=0&limit=20" \
  -H "Authorization: Bearer <token>"
```

### 6.2 创建项目

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/projects` |
| 鉴权 | JWT |
| 描述 | 创建新项目，当前用户作为 owner |

**请求体**：`ProjectCreate`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| name | string | 是 | 项目名 |
| patient_pseudonym | string | 否 | 患者化名 |
| cancer_type | string | 否 | 癌种 |
| stage | string | 否 | 分期 |
| description | string | 否 | 描述 |

**响应**：`ProjectResponse`

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/projects" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"肺癌 P001","cancer_type":"NSCLC","stage":"IIIA"}'
```

### 6.3 项目详情

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/projects/{project_id}` |
| 鉴权 | JWT |
| 描述 | 获取项目详情 |

**路径参数**：`project_id` UUID

**响应**：`ProjectResponse`

**关键逻辑**：项目不存在返回 404。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/projects/3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 6.4 更新项目状态

| 项 | 值 |
| --- | --- |
| 方法路径 | `PATCH /api/v1/projects/{project_id}/status` |
| 鉴权 | JWT |
| 描述 | 更新项目状态 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| status | string | 是 | 新状态值（如 active/completed/archived） |

**响应**：`StandardResponse`

**关键逻辑**：项目不存在返回 404。

**示例**

```bash
curl -X PATCH "http://localhost:8000/api/v1/projects/3fa85f64-5717-4562-b3fc-2c963f66afa6/status?status=completed" \
  -H "Authorization: Bearer <token>"
```

---

## 7. 靶点发现模块

模块前缀：`/api/v1/targets`，标签：`靶点发现`。所有端点需 JWT。

### 7.1 靶点发现

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/targets/discover` |
| 鉴权 | JWT |
| 描述 | 从数据集中发现靶点，流程：突变→注释→通路→证据分级 |

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| project_id | UUID | 是 | - | 项目 ID |
| dataset_id | UUID | 否 | null | 指定数据集分析 |
| tier | string | 否 | fast_screen | 分析层级：fast_screen/deep_insight |

**响应**：`StandardResponse`，`data` 为发现的靶点列表和分析元信息。

**关键逻辑**：调用 `TargetIdentifier.discover`，结合 MyGene.info 注释与通路富集，输出按证据等级分级的靶点。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/targets/discover?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6&tier=deep_insight" \
  -H "Authorization: Bearer <token>"
```

### 7.2 靶点列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/targets` |
| 鉴权 | JWT |
| 描述 | 获取靶点列表，按置信度倒序 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 否 | 按项目过滤 |
| evidence_grade | string | 否 | 按证据等级过滤 |

**响应**：`TargetResponse[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 靶点 ID |
| project_id | UUID | 项目 ID |
| gene_symbol | string | 基因符号（如 EGFR） |
| gene_name | string\|null | 基因全名 |
| evidence_grade | string | 证据等级 |
| confidence_score | float\|null | 置信度 |
| source | string\|null | 来源 |
| annotation | dict\|null | 注释信息 |
| pathway | dict\|null | 通路信息 |
| approved_drugs | list\|null | 已获批药物 |
| evidence_chain | dict\|null | 证据链 |
| analysis_tier | string\|null | 分析层级 |
| created_at | datetime | 创建时间 |

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/targets?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6&evidence_grade=LEVEL_I" \
  -H "Authorization: Bearer <token>"
```

### 7.3 靶点详情

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/targets/{target_id}` |
| 鉴权 | JWT |
| 描述 | 获取靶点详情 |

**响应**：`TargetResponse`

**关键逻辑**：靶点不存在返回 404。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/targets/3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 7.4 老药新用扫描

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/targets/{target_id}/repurpose` |
| 鉴权 | JWT |
| 描述 | 扫描 ChEMBL 数据库，针对靶点查找已获批候选药物 |

**响应**：`StandardResponse`，`data` 含 `candidates` 候选药物列表。

**关键逻辑**：靶点不存在返回 404；找到候选药物时自动将证据等级升为 LEVEL_I，并写回 `approved_drugs` 字段。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/targets/3fa85f64-5717-4562-b3fc-2c963f66afa6/repurpose" \
  -H "Authorization: Bearer <token>"
```

### 7.5 构建证据链

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/targets/{target_id}/evidence` |
| 鉴权 | JWT |
| 描述 | 为靶点构建完整证据链（文献/临床/实验） |

**响应**：`StandardResponse`，`data` 为证据链结构。

**关键逻辑**：靶点不存在返回 404；调用 `EvidenceChainBuilder.build`，结果写回 `evidence_chain` 字段。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/targets/3fa85f64-5717-4562-b3fc-2c963f66afa6/evidence" \
  -H "Authorization: Bearer <token>"
```

---

## 8. 分子设计模块

模块前缀：`/api/v1/molecules`，标签：`分子设计`。所有端点需 JWT。

### 8.1 分子列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/molecules` |
| 鉴权 | JWT |
| 描述 | 获取分子列表，按创建时间倒序 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| target_id | UUID | 否 | 按靶点过滤 |

**响应**：`MoleculeResponse[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 分子 ID |
| smiles | string | SMILES 结构式 |
| name | string\|null | 名称 |
| chembl_id | string\|null | ChEMBL ID |
| molecular_weight | float\|null | 分子量 |
| logp | float\|null | logP |
| properties | dict\|null | 属性字典 |
| docking_result | dict\|null | 对接结果 |
| is_approved | boolean\|null | 是否已获批 |
| designed_by | string\|null | 设计者/来源 |

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/molecules?target_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 8.2 分子设计

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/molecules/design` |
| 鉴权 | JWT |
| 描述 | 分子设计（第二阶段），基于 DeepChem 性质预测 |

**请求体**：`DesignRequest`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| target_id | string | 否 | 靶点 ID |
| smiles | string | 否 | 起点 SMILES |
| constraints | dict | 否 | 设计约束 |

**响应**：`StandardResponse`，`data` 为设计结果。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/molecules/design" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"target_id":"3fa85f64-5717-4562-b3fc-2c963f66afa6","constraints":{"max_mw":500}}'
```

### 8.3 分子对接

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/molecules/{molecule_id}/dock` |
| 鉴权 | JWT |
| 描述 | 分子对接（第二阶段），调用 DiffDock NIM |

**路径参数**：`molecule_id` UUID

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| protein_pdb | string | 是 | 蛋白质 PDB 内容或 ID |

**响应**：`StandardResponse`，`data` 为对接结果（构象、打分等）。

**关键逻辑**：分子不存在返回 404；调用 `get_diffdock_client().dock`，结果写回 `docking_result` 字段。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/molecules/3fa85f64-5717-4562-b3fc-2c963f66afa6/dock?protein_pdb=1XYZ" \
  -H "Authorization: Bearer <token>"
```

### 8.4 类药性评估

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/molecules/assess` |
| 鉴权 | JWT |
| 描述 | 基于 Lipinski 五规则的类药性评估（RDKit） |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| smiles | string | 是 | 分子 SMILES |

**响应**：`StandardResponse`，`data` 为评估指标（MW、logP、HBD、HBA、违规数等）。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/molecules/assess?smiles=CCO" \
  -H "Authorization: Bearer <token>"
```

---

## 9. 治疗方案模块

模块前缀：`/api/v1/treatments`，标签：`治疗方案`。所有端点需 JWT。

### 9.1 治疗方案列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/treatments` |
| 鉴权 | JWT |
| 描述 | 获取治疗方案列表，按创建时间倒序 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 否 | 按项目过滤 |
| status | string | 否 | 按状态过滤 |

**响应**：对象数组

```json
[
  {
    "id": "uuid",
    "name": "方案 A",
    "therapy_type": "targeted",
    "status": "active",
    "efficacy_score": 0.85,
    "risk_score": 0.32
  }
]
```

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/treatments?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 9.2 创建治疗方案

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/treatments` |
| 鉴权 | JWT |
| 描述 | 创建治疗方案，关联靶点/分子/假设 |

**请求体**：`TreatmentCreate`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | string | 是 | 项目 ID |
| name | string | 是 | 方案名 |
| therapy_type | string | 是 | 治疗类型（targeted/immuno/combo 等） |
| target_ids | string[] | 否 | 关联靶点 ID 列表 |
| molecule_ids | string[] | 否 | 关联分子 ID 列表 |
| hypothesis_id | string | 否 | 关联假设 ID |
| config | dict | 否 | 方案配置 |

**响应**：`StandardResponse`，`data={id:"<uuid>"}`

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/treatments" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"3fa85f64-5717-4562-b3fc-2c963f66afa6","name":"EGFR 抑制剂组合","therapy_type":"targeted","target_ids":["uuid1"],"molecule_ids":["uuid2"]}'
```

### 9.3 多疗法组合优化

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/treatments/optimize` |
| 鉴权 | JWT |
| 描述 | 多疗法组合优化（第三阶段），基于强化学习 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 是 | 项目 ID |

**响应**：`StandardResponse`，`data` 为优化后的组合方案及打分。

**关键逻辑**：调用 `TreatmentPlanner.optimize`。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/treatments/optimize?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 9.4 疗效监测

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/treatments/{treatment_id}/monitor` |
| 鉴权 | JWT |
| 描述 | 实时疗效监测（第三阶段） |

**路径参数**：`treatment_id` UUID

**响应**：`StandardResponse`，`data` 为疗效指标。

**关键逻辑**：调用 `EfficacyMonitor.check`。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/treatments/3fa85f64-5717-4562-b3fc-2c963f66afa6/monitor" \
  -H "Authorization: Bearer <token>"
```

---

## 10. 实验模块（干湿闭环）

模块前缀：`/api/v1/experiments`，标签：`干湿闭环`。所有端点需 JWT。

### 10.1 实验列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/experiments` |
| 鉴权 | JWT |
| 描述 | 获取实验列表，按创建时间倒序 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 否 | 按项目过滤 |
| exp_type | string | 否 | 按实验类型过滤 |
| status | string | 否 | 按状态过滤 |

**响应**：对象数组

```json
[
  {
    "id": "uuid",
    "name": "结合实验",
    "exp_type": "binding",
    "status": "completed",
    "success": true,
    "iteration": 2,
    "feedback_applied": true
  }
]
```

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/experiments?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6&status=completed" \
  -H "Authorization: Bearer <token>"
```

### 10.2 创建实验

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/experiments` |
| 鉴权 | JWT |
| 描述 | 创建实验记录，关联项目/靶点/分子/治疗方案 |

**请求体**：`ExperimentCreate`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | string | 是 | 项目 ID |
| name | string | 是 | 实验名 |
| exp_type | string | 是 | 实验类型（binding/cell/vivo 等） |
| target_id | string | 否 | 靶点 ID |
| molecule_id | string | 否 | 分子 ID |
| treatment_id | string | 否 | 治疗方案 ID |
| config | dict | 否 | 实验配置 |
| lab_source | string | 否 | 实验室来源 |

**响应**：`StandardResponse`，`data={id:"<uuid>"}`

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/experiments" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"uuid","name":"细胞活性测试","exp_type":"cell","molecule_id":"uuid","lab_source":"LabA"}'
```

### 10.3 提交实验结果

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/experiments/{experiment_id}/result` |
| 鉴权 | JWT |
| 描述 | 提交湿实验结果，触发干湿闭环反馈（更新模型权重） |

**路径参数**：`experiment_id` UUID

**请求体**：`ExperimentResultUpdate`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| result | dict | 是 | 结果数据 |
| success | boolean | 是 | 是否成功 |
| notes | string | 否 | 备注 |

**响应**：`StandardResponse`，`data` 为反馈结果。

**关键逻辑**：实验不存在返回 404；状态置为 `COMPLETED`；调用 `FeedbackLoop.apply_feedback` 触发模型权重更新。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/experiments/3fa85f64-5717-4562-b3fc-2c963f66afa6/result" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"result":{"ic50":0.12},"success":true,"notes":"nM 级抑制"}'
```

### 10.4 LIMS 数据导入

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/experiments/lims-import` |
| 鉴权 | JWT |
| 描述 | 从 LIMS 系统批量导入实验数据 |

**请求体**：`dict`（自由结构，由 LIMSImporter 解析）

**响应**：`StandardResponse`，`data` 含 `count` 等导入统计。

**关键逻辑**：调用 `LimsImporter.import_data`。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/experiments/lims-import" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"uuid","source":"lims-prod","date_from":"2026-01-01"}'
```

### 10.5 干湿闭环状态

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/experiments/loop-status` |
| 鉴权 | JWT |
| 描述 | 查看指定项目的干湿闭环迭代状态 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 是 | 项目 ID |

**响应**：`StandardResponse`

```json
{
  "total_experiments": 12,
  "completed": 10,
  "successful": 7,
  "feedback_applied": 6,
  "max_iteration": 3
}
```

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/experiments/loop-status?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

---

## 11. 多假设并行模块

模块前缀：`/api/v1/hypotheses`，标签：`多假设并行`。所有端点需 JWT。

### 11.1 假设列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/hypotheses` |
| 鉴权 | JWT |
| 描述 | 获取假设列表，按创建时间倒序 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 否 | 按项目过滤 |
| status | string | 否 | 按状态过滤 |

**响应**：`HypothesisResponse[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 假设 ID |
| project_id | UUID | 项目 ID |
| name | string | 假设名 |
| description | string\|null | 描述 |
| mechanism | string\|null | 机制 |
| strategy | string\|null | 策略 |
| status | string | 状态 |
| analysis_result | dict\|null | 分析结果 |
| target_list | list\|null | 靶点列表 |
| forced_deep_analysis | boolean\|null | 是否强制深度分析 |
| created_at | datetime | 创建时间 |

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/hypotheses?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 11.2 创建假设

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/hypotheses` |
| 鉴权 | JWT |
| 描述 | 创建平行宇宙假设，支持多线并行探索 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 是 | 项目 ID |

**请求体**：`HypothesisCreate`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| name | string | 是 | 假设名 |
| description | string | 否 | 描述 |
| mechanism | string | 否 | 机制 |
| strategy | string | 否 | 策略 |
| analysis_config | dict | 否 | 分析配置 |

**响应**：`HypothesisResponse`

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/hypotheses?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"EGFR 旁路假设","mechanism":"绕过 EGFR 主通路"}'
```

### 11.3 假设对比看板

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/hypotheses/compare` |
| 鉴权 | JWT |
| 描述 | 并排对比不同假设的靶点/分子/疗效差异 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 是 | 项目 ID |

**响应**：`StandardResponse`

```json
{
  "hypotheses": [
    {
      "id": "uuid",
      "name": "假设 A",
      "status": "completed",
      "targets": ["EGFR", "KRAS"],
      "result_summary": {...},
      "forced": false
    }
  ]
}
```

**关键逻辑**：仅返回 `COMPLETED` 或 `ANALYZING` 状态的假设。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/hypotheses/compare?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 11.4 假设详情

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/hypotheses/{hypothesis_id}` |
| 鉴权 | JWT |
| 描述 | 获取假设详情 |

**响应**：`HypothesisResponse`

**关键逻辑**：假设不存在返回 404。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/hypotheses/3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 11.5 执行并行分析

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/hypotheses/{hypothesis_id}/analyze` |
| 鉴权 | JWT |
| 描述 | 执行假设分析，多线并行，可由创始人强制深度分析 |

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| tier | string | 否 | fast_screen | 分析层级 |
| force_deep | boolean | 否 | false | 创始人强制深度分析 |
| force_reason | string | 否 | - | 强制分析理由 |

**响应**：`StandardResponse`，`data` 为分析结果（含 targets 列表）。

**关键逻辑**：假设不存在返回 404；`force_deep=true` 时自动将 tier 切换为 `deep_insight` 并标记 `forced_deep_analysis`；状态置为 `ANALYZING`，完成后置为 `COMPLETED`。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/hypotheses/3fa85f64-5717-4562-b3fc-2c963f66afa6/analyze?tier=deep_insight&force_deep=true&force_reason=候选靶点需复核" \
  -H "Authorization: Bearer <token>"
```

### 11.6 合并假设

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/hypotheses/{hypothesis_id}/merge` |
| 鉴权 | JWT |
| 描述 | 将当前假设合并到目标假设 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| target_hypothesis_id | UUID | 是 | 合并目标假设 ID |

**响应**：`StandardResponse`

**关键逻辑**：任一假设不存在返回 404；当前假设状态置为 `MERGED`。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/hypotheses/3fa85f64-5717-4562-b3fc-2c963f66afa6/merge?target_hypothesis_id=another-uuid" \
  -H "Authorization: Bearer <token>"
```

---

## 12. 数据接入模块

模块前缀：`/api/v1/data`，标签：`数据接入`。所有端点需 JWT。

### 12.1 数据集列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/data` |
| 鉴权 | JWT |
| 描述 | 获取数据集列表，按创建时间倒序 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 否 | 按项目过滤 |
| data_type | string | 否 | 按数据类型过滤 |

**响应**：`DatasetResponse[]`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 数据集 ID |
| project_id | UUID | 项目 ID |
| name | string | 数据集名 |
| data_type | string | 数据类型（rna_seq/scrna_seq/wes/fasta/gene_report） |
| source | string\|null | 来源 |
| file_format | string\|null | 文件格式 |
| file_size | int\|null | 文件大小（字节） |
| parse_status | string | 解析状态（pending/parsing/completed/failed） |
| quality_metrics | dict\|null | 质量指标 |
| parsed_summary | dict\|null | 解析摘要 |
| created_at | datetime | 创建时间 |

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/data?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 12.2 上传数据文件

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/data/upload` |
| 鉴权 | JWT |
| 描述 | 上传多组学数据文件（multipart/form-data） |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 是 | 项目 ID |
| name | string | 是 | 数据集名 |
| data_type | string | 是 | 数据类型 |
| source | string | 否 | 来源（默认为文件名） |

**请求体**：`multipart/form-data`，字段 `file` 为二进制文件。

**响应**：`DatasetResponse`

**关键逻辑**：文件保存到 `/data/uploads/{project_id}/{filename}`（生产环境应存 MinIO）；解析状态初始为 `PENDING`。

**支持的扩展名映射**

| 扩展名 | 数据类型 |
| --- | --- |
| csv / tsv | rna_seq |
| h5 / mtx | scrna_seq |
| vcf | wes |
| fasta / fa | fasta |
| pdf / png / jpg | gene_report |

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/data/upload?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6&name=RNA-seq P001&data_type=rna_seq" \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/data.csv"
```

```javascript
const form = new FormData();
form.append("file", fileInput.files[0]);
await fetch(
  "http://localhost:8000/api/v1/data/upload?project_id=uuid&name=RNA-seq&data_type=rna_seq",
  { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form }
);
```

### 12.3 数据集详情

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/data/{dataset_id}` |
| 鉴权 | JWT |
| 描述 | 获取数据集详情 |

**响应**：`DatasetResponse`

**关键逻辑**：数据集不存在返回 404。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/data/3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 12.4 触发数据解析

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/data/{dataset_id}/parse` |
| 鉴权 | JWT |
| 描述 | 触发数据集解析，调用对应 parser |

**响应**：`StandardResponse`，`data` 含 `summary` 和 `quality_metrics`。

**关键逻辑**：数据集不存在返回 404；状态置为 `PARSING`，成功后置为 `COMPLETED`，异常置为 `FAILED` 并返回 500。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/data/3fa85f64-5717-4562-b3fc-2c963f66afa6/parse" \
  -H "Authorization: Bearer <token>"
```

### 12.5 数据质量报告

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/data/{dataset_id}/quality` |
| 鉴权 | JWT |
| 描述 | 获取数据集质量报告 |

**响应**：`StandardResponse`

```json
{
  "quality_metrics": {...},
  "parse_status": "completed",
  "parsed_summary": {...}
}
```

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/data/3fa85f64-5717-4562-b3fc-2c963f66afa6/quality" \
  -H "Authorization: Bearer <token>"
```

---

## 13. 工作流模块

模块前缀：`/api/v1/workflows`，标签：`工作流`。所有端点需 JWT。

### 13.1 工作流运行列表

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/workflows` |
| 鉴权 | JWT |
| 描述 | 获取工作流运行列表，按创建时间倒序 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | UUID | 否 | 按项目过滤 |
| status | string | 否 | 按状态过滤 |

**响应**：对象数组

```json
[
  {
    "id": "uuid",
    "pipeline_name": "scrna_pipeline",
    "status": "completed",
    "run_id": "nf-abc123",
    "duration_sec": 360
  }
]
```

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/workflows?project_id=3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 13.2 触发工作流

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/workflows/run` |
| 鉴权 | JWT |
| 描述 | 触发 Nextflow 工作流执行 |

**请求体**：`WorkflowRunRequest`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | string | 是 | 项目 ID |
| pipeline_name | string | 是 | 管道名：scrna_pipeline/rna_seq_pipeline/variant_annotation |
| params | dict | 否 | 运行参数 |

**响应**：`StandardResponse`，`data` 为运行结果。

**关键逻辑**：调用 `NextflowRunner.run`；运行记录状态初始为 `SUBMITTED`。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/workflows/run" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"uuid","pipeline_name":"rna_seq_pipeline","params":{"threads":8}}'
```

### 13.3 工作流详情

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/workflows/{workflow_id}` |
| 鉴权 | JWT |
| 描述 | 获取工作流运行详情 |

**响应**：`StandardResponse`

```json
{
  "id": "uuid",
  "pipeline_name": "scrna_pipeline",
  "status": "completed",
  "run_id": "nf-abc",
  "trace_url": "https://...",
  "output_path": "/data/output/...",
  "params": {...},
  "error": null,
  "duration_sec": 360
}
```

**关键逻辑**：工作流不存在返回 404。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/workflows/3fa85f64-5717-4562-b3fc-2c963f66afa6" \
  -H "Authorization: Bearer <token>"
```

### 13.4 可用管道

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/workflows/pipelines/available` |
| 鉴权 | JWT |
| 描述 | 列出系统支持的 Nextflow 管道 |

**响应**：`StandardResponse`

```json
{
  "pipelines": [
    {"name":"scrna_pipeline","description":"单细胞测序数据处理（Scanpy）","phase":"P0"},
    {"name":"rna_seq_pipeline","description":"RNA-seq 定量与差异表达","phase":"P0"},
    {"name":"variant_annotation","description":"WES/WGS 变异注释","phase":"P2"}
  ]
}
```

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/workflows/pipelines/available" \
  -H "Authorization: Bearer <token>"
```

---

## 14. 自然语言问答模块

模块前缀：`/api/v1/chat`，标签：`自然语言问答`。所有端点需 JWT。

### 14.1 自然语言问答

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/chat` |
| 鉴权 | JWT |
| 描述 | 自然语言问答，AI 自动执行分析并返回报告，支持分级路由 |

**请求体**：`ChatRequest`

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| message | string | 是 | - | 用户问题 |
| project_id | string | 否 | null | 项目上下文 |
| tier | string | 否 | fast_screen | 分析层级：fast_screen/deep_insight |

**响应**：`ChatResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| answer | string | AI 回答 |
| tier | string | 实际使用的层级 |
| cost_usd | float | 本次调用成本（美元） |
| duration_sec | float | 耗时（秒） |
| model | string | 模型名 |
| references | dict[]\|null | 参考文献 |
| code | string\|null | AI 生成的分析代码 |

**关键逻辑**：调用 `LLMOrchestrator.route`；fast_screen 限制 <$5/<5min，deep_insight 限制 <$20/<30min。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message":"EGFR 突变患者的潜在靶点有哪些？","project_id":"uuid","tier":"deep_insight"}'
```

### 14.2 自然语言驱动数据分析

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/chat/analyze` |
| 鉴权 | JWT |
| 描述 | 自然语言→文献检索→提出假设→设计分析框架→运行分析→返回报告 |

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| message | string | 是 | - | 分析问题 |
| project_id | string | 是 | - | 项目 ID |
| tier | string | 否 | deep_insight | 分析层级 |

**响应**：`StandardResponse`，`data` 包含结论、交互式图表、AI 生成的 Python 代码。

**关键逻辑**：调用 `LLMOrchestrator.full_analysis`，是 Sid 团队核心能力的复现。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/chat/analyze?message=分析 KRAS 突变与耐药关系&project_id=uuid&tier=deep_insight" \
  -H "Authorization: Bearer <token>"
```

### 14.3 分析层级说明

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/chat/tiers` |
| 鉴权 | JWT |
| 描述 | 返回分级分析策略说明 |

**响应**：`StandardResponse`

```json
{
  "tiers": [
    {
      "name":"fast_screen",
      "label":"快速筛查",
      "tech_stack":"统计分析 + 规则引擎 + 小模型",
      "use_case":"靶点初筛、批量数据扫描",
      "max_cost_usd":5.0,
      "max_duration_sec":300
    },
    {
      "name":"deep_insight",
      "label":"深度洞察",
      "tech_stack":"LLM + RAG + 网络分析 + 分子建模",
      "use_case":"候选靶点深度分析、分子设计",
      "max_cost_usd":20.0,
      "max_duration_sec":1800
    }
  ]
}
```

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/chat/tiers" \
  -H "Authorization: Bearer <token>"
```

---

## 15. 知识库模块

模块前缀：`/api/v1/knowledge`，标签：`知识库`。所有端点需 JWT。

### 15.1 基因查询

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/knowledge/gene` |
| 鉴权 | JWT |
| 描述 | 查询基因信息，集成 NCBI/Ensembl/UniProt 等 30+ 数据源 |

**请求体**：`GeneQuery`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| gene_symbol | string | 是 | 基因符号（如 EGFR、B7H3、FAP） |

**响应**：`StandardResponse`

**关键逻辑**：调用 `get_gene_client().query`，底层数据源为 MyGene.info。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge/gene" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"gene_symbol":"EGFR"}'
```

### 15.2 变异注释

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/knowledge/variant` |
| 鉴权 | JWT |
| 描述 | 批量变异注释，一次搞定 ClinVar/COSMIC/dbSNP/gnomAD |

**请求体**：`VariantQuery`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| variants | string[] | 是 | 变异列表（如 `["chr7:55259515:T>A"]`） |

**响应**：`StandardResponse`

**关键逻辑**：调用 `get_variant_client().query_batch`，底层数据源为 MyVariant.info。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge/variant" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"variants":["chr7:55259515:T>A","chr12:25245350:C>T"]}'
```

### 15.3 ChEMBL 活性分子查询

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/knowledge/chembl/activity` |
| 鉴权 | JWT |
| 描述 | 查询靶点对应的已知活性分子 |

**请求体**：`ChemblQuery`

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| target_gene | string | 是 | - | 靶点基因 |
| activity_type | string | 否 | IC50 | 活性类型（IC50/Ki/Kd 等） |
| limit | int | 否 | 50 | 返回数量 |

**响应**：`StandardResponse`

**关键逻辑**：调用 `get_chembl_client().get_active_molecules`，底层数据源为 ChEMBL。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge/chembl/activity" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"target_gene":"EGFR","activity_type":"IC50","limit":20}'
```

### 15.4 ChEMBL 已获批药物查询

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/knowledge/chembl/approved` |
| 鉴权 | JWT |
| 描述 | 药物重定位：查找已获批药物 |

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| target_gene | string | 是 | 靶点基因 |

**响应**：`StandardResponse`

**关键逻辑**：调用 `get_chembl_client().find_approved_drugs`。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge/chembl/approved?target_gene=EGFR" \
  -H "Authorization: Bearer <token>"
```

### 15.5 临床试验匹配

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/knowledge/clinical-trials` |
| 鉴权 | JWT |
| 描述 | ClinicalTrials.gov 试验匹配 |

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| gene_symbol | string | 是 | - | 基因符号 |
| cancer_type | string | 否 | "" | 癌种（用于精准匹配） |

**响应**：`StandardResponse`

**关键逻辑**：调用 `query_clinical_trials`，底层数据源为 ClinicalTrials.gov API v2。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge/clinical-trials?gene_symbol=EGFR&cancer_type=NSCLC" \
  -H "Authorization: Bearer <token>"
```

---

## 16. 报告导出模块

模块前缀：`/api/v1/reports`，标签：`报告导出`。所有端点需 JWT。

### 16.1 导出 CDISC SDTM

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/reports/{project_id}/sdtm` |
| 鉴权 | JWT |
| 描述 | 导出 CDISC SDTM 格式数据（FDA 认可的临床试验数据标准） |

**路径参数**：`project_id` UUID

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| format | string | 否 | json | 输出格式：json（含域预览）或 csv（纯 CSV 下载） |

**响应**

- `format=json`：`StandardResponse`，`data` 含 `csv`、`domains`、`metadata`、`record_counts`
- `format=csv`：`text/csv` 文件下载，`Content-Disposition: attachment; filename=sdtm_{project_id}.csv`

**关键逻辑**：调用 `SDTMExporter.export` 与 `to_csv`；csv 模式直接返回 `PlainTextResponse`。

**示例**

```bash
# JSON 模式
curl -X POST "http://localhost:8000/api/v1/reports/3fa85f64-5717-4562-b3fc-2c963f66afa6/sdtm?format=json" \
  -H "Authorization: Bearer <token>"

# CSV 下载
curl -X POST "http://localhost:8000/api/v1/reports/3fa85f64-5717-4562-b3fc-2c963f66afa6/sdtm?format=csv" \
  -H "Authorization: Bearer <token>" -o sdtm.csv
```

### 16.2 导出 CDISC ADaM

| 项 | 值 |
| --- | --- |
| 方法路径 | `POST /api/v1/reports/{project_id}/adam` |
| 鉴权 | JWT |
| 描述 | 导出 CDISC ADaM 格式数据，用于统计分析 |

**路径参数**：`project_id` UUID

**响应**：`StandardResponse`

**关键逻辑**：调用 `SDTMExporter.export_adam`。

**示例**

```bash
curl -X POST "http://localhost:8000/api/v1/reports/3fa85f64-5717-4562-b3fc-2c963f66afa6/adam" \
  -H "Authorization: Bearer <token>"
```

### 16.3 项目报告摘要

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/reports/{project_id}/summary` |
| 鉴权 | JWT |
| 描述 | 生成项目综合报告摘要，聚合数据集/靶点/假设/实验统计 |

**响应**：`StandardResponse`

```json
{
  "project_id": "uuid",
  "datasets": {"total": 5, "by_type": {"rna_seq": 3, "wes": 2}},
  "targets": {"total": 12, "by_grade": {"LEVEL_I": 3, "LEVEL_II": 9}},
  "hypotheses": {"total": 4, "completed": 2},
  "experiments": {"total": 8, "successful": 5}
}
```

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/reports/3fa85f64-5717-4562-b3fc-2c963f66afa6/summary" \
  -H "Authorization: Bearer <token>"
```

---

## 17. 全局看板模块

模块前缀：`/api/v1/dashboard`，标签：`全局看板`。所有端点需 JWT。

### 17.1 全局看板聚合统计

| 项 | 值 |
| --- | --- |
| 方法路径 | `GET /api/v1/dashboard/overview` |
| 鉴权 | JWT |
| 描述 | 跨项目全局统计，用于 dashboard 全局看板 |

**响应**：`StandardResponse`

```json
{
  "global": {
    "projects": 12,
    "datasets": 38,
    "targets": 96,
    "molecules": 124,
    "hypotheses": 18,
    "experiments": 64,
    "treatments": 22,
    "completed_hypotheses": 10,
    "successful_experiments": 45,
    "hypothesis_completion_rate": 0.56,
    "experiment_success_rate": 0.70
  },
  "by_cancer_type": {"NSCLC": 5, "乳腺癌": 4, "未分类": 3},
  "by_status": {"active": 8, "completed": 3, "unknown": 1},
  "projects": [
    {
      "id": "uuid",
      "name": "肺癌 P001",
      "patient_pseudonym": "P001",
      "cancer_type": "NSCLC",
      "stage": "IIIA",
      "status": "active",
      "created_at": "2026-06-01T08:00:00",
      "counts": {
        "datasets": 3, "targets": 8, "molecules": 12,
        "hypotheses": 2, "experiments": 5, "treatments": 1
      }
    }
  ],
  "recent_experiments": [
    {
      "id": "uuid",
      "name": "结合实验",
      "exp_type": "binding",
      "status": "completed",
      "success": true,
      "iteration": 2,
      "project_id": "uuid",
      "project_name": "肺癌 P001",
      "created_at": "2026-07-04T10:00:00"
    }
  ]
}
```

**关键逻辑**：
- 全局聚合统计项目/数据集/靶点/分子/假设/实验/治疗方案总数；
- `by_cancer_type` 按癌种分组项目数；
- `by_status` 按项目状态分组；
- `projects` 每个项目的明细统计（含各资源计数）；
- `recent_experiments` 最近 10 条跨项目实验；
- 分子通过 Target 关联项目（Molecule 无 project_id 字段）。

**示例**

```bash
curl -X GET "http://localhost:8000/api/v1/dashboard/overview" \
  -H "Authorization: Bearer <token>"
```

---

## 18. 错误码对照表

| HTTP 状态码 | 错误标识 | 触发模块 | 触发场景 |
| --- | --- | --- | --- |
| 400 | bad_request | 通用 | 参数错误、业务校验失败 |
| 400 | email_exists | 认证 | 邮箱已注册 |
| 400 | invalid_role | 用户管理 | 角色枚举非法 |
| 400 | cannot_modify_self_role | 用户管理 | 修改自己的角色 |
| 400 | cannot_promote_to_founder | 用户管理 | 将用户提升为 founder |
| 400 | cannot_disable_self | 用户管理 | 禁用自己 |
| 400 | cannot_disable_founder | 用户管理 | 禁用 founder 账户 |
| 400 | cannot_delete_active_config | LLM 配置 | 删除当前激活的 LLM 配置 |
| 401 | unauthorized | 认证 | Token 缺失/失效，邮箱或密码错误 |
| 403 | forbidden | 通用 | 账户禁用、角色权限不足 |
| 404 | not_found | 通用 | 资源不存在（用户/项目/靶点/分子/实验/假设/数据集/工作流/LLM 配置） |
| 409 | conflict | LLM 配置 | 配置名称重复 |
| 422 | validation_error | 通用 | Pydantic 校验失败、枚举值非法（access_mode/upstream_protocol） |
| 500 | internal_error | 通用 | 内部异常（如数据解析失败、上游服务异常） |

### 18.1 常见错误响应示例

**401 Unauthorized**

```json
{"detail": "邮箱或密码错误"}
```

**404 Not Found**

```json
{"detail": "项目不存在"}
```

**422 Unprocessable Entity**（FastAPI 默认格式）

```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**500 Internal Server Error**

```json
{"detail": "解析失败: <异常信息>"}
```

---

## 附录 A：HTTP 状态码汇总

| 状态码 | 名称 | 用途 |
| --- | --- | --- |
| 200 | OK | 请求成功 |
| 201 | Created | 资源创建成功（部分接口返回 200） |
| 400 | Bad Request | 请求参数错误 |
| 401 | Unauthorized | 未认证 |
| 403 | Forbidden | 无权限 |
| 404 | Not Found | 资源不存在 |
| 409 | Conflict | 资源冲突 |
| 422 | Unprocessable Entity | 实体校验失败 |
| 500 | Internal Server Error | 服务器内部错误 |

## 附录 B：数据类型约定

| 类型 | 说明 |
| --- | --- |
| UUID | 36 字符 UUID 字符串，如 `3fa85f64-5717-4562-b3fc-2c963f66afa6` |
| datetime | ISO 8601 格式，如 `2026-07-05T08:00:00` |
| boolean | `true` / `false` |
| dict | 自由结构 JSON 对象 |
| list | JSON 数组 |

## 附录 C：模块端点统计

| 模块 | 端点数 |
| --- | --- |
| 认证 | 3 |
| 用户管理 | 3 |
| 审计日志 | 1 |
| LLM 配置 | 7 |
| 项目管理 | 4 |
| 靶点发现 | 5 |
| 分子设计 | 4 |
| 治疗方案 | 4 |
| 干湿闭环 | 5 |
| 多假设并行 | 6 |
| 数据接入 | 5 |
| 工作流 | 4 |
| 自然语言问答 | 3 |
| 知识库 | 5 |
| 报告导出 | 3 |
| 全局看板 | 1 |
| **总计** | **63** |

---

> 本文档由精准药物设计团队维护，如有疑问请联系后端组。文档版本 v1.0.0，最后更新于 2026-07-05。
