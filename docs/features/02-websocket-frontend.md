# 功能 2：WebSocket 前端接入

## 1. 功能描述

WebSocket 前端接入模块实现后端长任务（分子设计、靶点发现、联邦学习等）的实时进度推送，替代传统轮询模式，显著降低服务端压力并提供更流畅的用户体验。

### 核心能力

- **实时进度推送**：任务执行过程中每 1-3 秒推送进度更新
- **多任务订阅**：单个连接可同时订阅多个任务的进度
- **断线重连**：前端自动检测断线并指数退避重连
- **JWT 鉴权**：连接时携带 token，服务端校验用户身份和项目权限
- **消息类型区分**：progress / completed / failed / log 四种消息类型

## 2. 技术实现

### 2.1 架构设计

```
前端 useWebSocket hook
        ↓ ws://api/ws?token=xxx
后端 ConnectionManager（管理连接池）
        ↓ 订阅任务 channel
任务执行器 → broadcast(task_id, message) → 推送到所有订阅者
```

### 2.2 核心文件

| 文件路径 | 职责 |
|---------|------|
| `backend/app/api/v1/endpoints/ws.py` | WebSocket 端点，连接管理与消息广播 |
| `backend/app/core/ws_manager.py` | 连接池管理器，频道订阅机制 |
| `frontend/lib/api/ws.ts` | 前端 WebSocket 客户端封装 |
| `frontend/hooks/useWebSocket.ts` | React hook，自动重连与状态管理 |

### 2.3 消息协议

```typescript
// 服务端 → 客户端
interface WSMessage {
  type: 'progress' | 'completed' | 'failed' | 'log';
  task_id: string;
  progress: number;       // 0-100
  message: string;
  timestamp: string;      // ISO 8601
  data?: Record<string, any>;
}

// 客户端 → 服务端
interface WSCommand {
  action: 'subscribe' | 'unsubscribe';
  task_id: string;
}
```

### 2.4 关键方法

- `ConnectionManager.connect(websocket, user_id)`：建立连接并注册
- `ConnectionManager.subscribe(task_id, websocket)`：订阅任务频道
- `ConnectionManager.broadcast(task_id, message)`：向频道所有订阅者推送
- `useWebSocket(taskId)`：前端 hook，返回 `{ progress, status, lastMessage }`

## 3. 测试结果

| 测试文件 | 用例数 | 通过 | 覆盖场景 |
|---------|-------|------|---------|
| `test_ws_manager.py` | 18 | 18 ✅ | 连接管理、订阅/退订、广播、鉴权失败、断线清理 |

**关键测试场景**：
- 单连接订阅多任务
- 多连接订阅同一任务（广播正确性）
- 未订阅任务的消息隔离
- 无效 token 连接拒绝
- 连接断开后自动从订阅池移除

## 4. 使用指南

### 4.1 前端使用

```typescript
import { useWebSocket } from '@/hooks/useWebSocket';

function MoleculeDesignProgress({ taskId }: { taskId: string }) {
  const { progress, status, lastMessage } = useWebSocket(taskId);

  if (status === 'connecting') return <div>连接中...</div>;
  if (status === 'completed') return <div>设计完成</div>;
  if (status === 'failed') return <div>失败: {lastMessage?.message}</div>;

  return (
    <div>
      <ProgressBar value={progress} />
      <p>{lastMessage?.message}</p>
    </div>
  );
}
```

### 4.2 后端推送

```python
from app.core.ws_manager import ws_manager

# 在任务执行过程中推送进度
await ws_manager.broadcast(
    task_id=str(task.id),
    message={
        "type": "progress",
        "task_id": str(task.id),
        "progress": 65,
        "message": "正在生成第 3 个候选分子...",
        "timestamp": datetime.utcnow().isoformat(),
    }
)
```

### 4.3 鉴权流程

1. 前端从 localStorage 读取 `ai_drug_token`
2. 连接 URL 携带 `?token=xxx`
3. 服务端 `ws.py` 在 `accept()` 前校验 JWT
4. 校验失败返回 4001 关闭码并拒绝连接

### 4.4 断线重连策略

- 首次重连：立即
- 第 2 次：延迟 1 秒
- 第 3 次：延迟 2 秒
- 第 4+ 次：延迟 5 秒（上限）
- 最大重连次数：10 次
