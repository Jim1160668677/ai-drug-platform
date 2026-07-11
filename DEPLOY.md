# 部署指南

## 一、环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | 后端运行时（推荐 Anaconda 3.11） |
| Node.js | 18+ | 前端构建 |
| Docker | 24+ | 容器化部署 |
| Docker Compose | 2.20+ | 多服务编排 |

## 二、开发环境部署（本地）

### 2.1 后端

```bash
# 1. 创建 Anaconda 环境
conda env create -f environment.yml
conda activate precision-drug-design

# 2. 配置环境变量
cd backend
cp ../.env.example .env
# 编辑 .env，设置 USE_MOCK=true（开发默认 Mock 模式）

# 3. 启动后端
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

验证：访问 http://localhost:8000/health 返回 `{"status":"healthy",...}`

### 2.2 前端

```bash
cd frontend
npm install
npm run dev
```

验证：访问 http://localhost:3000 显示登录页

### 2.3 默认账户

```
邮箱：sid@ai-drug.com
密码：demo123456
角色：founder（最高权限）
```

## 三、Docker Compose 一键部署

### 3.1 启动全部服务

```bash
cp .env.example .env
make up
```

启动后访问：
- 前端：http://localhost
- API 文档：http://localhost/docs
- MinIO 控制台：http://localhost:9001
- Neo4j：http://localhost:7474

### 3.2 初始化数据

```bash
make migrate   # 数据库迁移
make seed      # 灌入样本数据
```

### 3.3 切换真实 API

编辑 `.env`：
```env
USE_MOCK=false
OPENAI_API_KEY=sk-...
NVIDIA_NIM_API_KEY=...
```

重启：`make down && make up`

## 四、生产环境部署

### 4.1 配置要求

- 修改 `JWT_SECRET_KEY` 为随机强密钥
- 设置 `USE_MOCK=false`
- 配置 PostgreSQL 强密码
- 启用 HTTPS（通过 nginx 反向代理）
- 限制 CORS_ORIGINS 为实际域名

### 4.2 构建生产镜像

```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
```

## 五、服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 | 3000 | Next.js dev / nginx 生产 |
| 后端 API | 8000 | FastAPI + uvicorn |
| PostgreSQL | 5432 | 主数据库 |
| Redis | 6379 | 缓存与任务队列 |
| ChromaDB | 8001 | 向量检索 |
| Neo4j | 7474/7687 | 图数据库 HTTP/Bolt |
| MinIO | 9000/9001 | 对象存储 API/控制台 |
| nginx | 80 | 反向代理 |

## 六、常见问题

### Q: 后端启动报 `ModuleNotFoundError: aiosqlite`
```bash
pip install aiosqlite==0.20.0
```

### Q: bcrypt 报 `password cannot be longer than 72 bytes`
```bash
pip install "bcrypt<4.0"
```

### Q: 前端 API 请求 404
检查 `.env` 中 `NEXT_PUBLIC_API_BASE_URL` 是否指向后端（默认 `http://localhost:8000/api/v1`）。
