# 功能 6：数据血缘追踪

## 1. 功能描述

### 业务价值
追踪数据从原始数据集到治疗方案的完整流转链路，支持数据可追溯性审计，满足 v3.0 文档第 11 章数据安全要求。

### 用户场景
- 研究人员查询某个靶点的数据来源（上游）
- 审计人员追踪某个治疗方案依赖的全部数据（完整 DAG）
- 数据管理者验证数据流转链路的完整性

### 需求来源
v3.0 文档第 11 章数据安全与隐私保护要求可追溯性。

## 2. 实现方法

### 技术方案
- **关系表存储**：DataLineage 模型记录 source → target 的转换关系
- **BFS 迭代遍历**：兼容 SQLite + PostgreSQL，支持上游/下游/DAG 查询
- **深度控制**：最大遍历深度 10，防止无限循环
- **跨项目隔离**：project_id 字段确保项目间数据不泄露

### 数据链路
```
dataset → target → molecule → treatment
  (parse)  (discover)  (design)  (optimize)
```

### 文件清单
| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/models/data_lineage.py` | 新建 | DataLineage ORM 模型 |
| `backend/app/services/lineage/tracker.py` | 新建 | LineageTracker 服务（BFS 遍历） |
| `backend/app/api/v1/endpoints/lineage.py` | 新建 | 4 个查询端点 |
| `backend/app/models/__init__.py` | 修改 | 注册 DataLineage |
| `backend/app/db/session.py` | 修改 | 模型导入同步 |
| `backend/tests/conftest.py` | 修改 | 测试 fixture 同步 |
| `backend/app/api/v1/router.py` | 修改 | 路由注册 |
| `backend/tests/test_lineage.py` | 新建 | 14 个测试用例 |
| `frontend/lib/api/lineage.ts` | 新建 | API 客户端 |
| `frontend/lib/api/index.ts` | 修改 | 统一导出 |
| `frontend/app/workbench/lineage/page.tsx` | 新建 | 血缘可视化页面 |
| `frontend/components/layout/Sidebar.tsx` | 修改 | 新增导航入口 |

### API 端点
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/lineage` | 记录血缘关系 |
| GET | `/api/v1/lineage/upstream` | 查询上游链路 |
| GET | `/api/v1/lineage/downstream` | 查询下游链路 |
| GET | `/api/v1/lineage/dag` | 获取完整 DAG |

## 3. 测试结果

| 指标 | 结果 |
|------|------|
| 测试用例数 | 14 |
| 通过率 | 100% |

### 测试覆盖
- 记录血缘关系（单条 + meta + created_by）
- 上游查询（直接 + 多层级 + 空结果）
- 下游查询（直接 + 多层级 + depth 限制）
- DAG 结构（节点 + 边 + 中心/上游/下游方向）
- 跨项目隔离
- 循环依赖安全

## 4. 使用指南

### API 调用
```bash
# 记录血缘
POST /api/v1/lineage
{"project_id": "...", "source_type": "dataset", "source_id": "...",
 "target_type": "target", "target_id": "...", "transformation": "discover"}

# 查询 DAG
GET /api/v1/lineage/dag?project_id=...&node_type=target&node_id=...&depth=3
```

### 前端使用
侧边栏点击"数据血缘"进入页面，选择节点类型、输入节点 ID、调整深度，点击"查询"查看 DAG 可视化图（PlotlyChart 散点图 + 连线）。
