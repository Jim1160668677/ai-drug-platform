---
kind: logging_system
name: 基于 loguru 的结构化日志系统
category: logging_system
scope:
    - '**'
source_files:
    - precision-drug-design/backend/app/core/logging.py
    - precision-drug-design/backend/app/main.py
    - precision-drug-design/backend/app/core/config.py
    - precision-drug-design/tests/test_logging.py
---

## 系统概述

后端采用 **loguru** 作为统一日志框架，通过 `backend/app/core/logging.py` 集中配置，支持开发/生产双模式输出、按大小与时间轮转、错误独立归档以及结构化 JSON 输出。

## 核心组件

- **初始化入口**：`backend/app/core/logging.py` 的 `setup_logging()` 在应用启动时调用（`main.py:create_app` 中第一行），负责移除默认 handler 并注册控制台、文件、错误三个 sink。
- **环境感知输出**：
  - 开发环境：彩色控制台 + 完整 backtrace/diagnose 信息，便于调试。
  - 生产环境：`serialize=True` 输出标准 JSON 到 stdout，供外部采集器（如 Docker/容器日志收集）消费。
- **文件轮转策略**：
  - `logs/app_{time:YYYY-MM-DD}.log`：INFO+ 级别，50MB 轮转，保留 30 天，zip 压缩。
  - `logs/error_{time:YYYY-MM-DD}.log`：仅 ERROR 级别，20MB 轮转，保留 90 天。
- **上下文绑定**：`get_logger(name)` 返回已绑定 `module` 字段的 logger；中间件 `EnvelopeMiddleware` 自动注入 `X-Request-ID` 响应头，便于跨请求追踪。
- **配置来源**：`app_log_level` 与 `is_production` 来自 `backend/app/core/config.py` 的 Settings，由 `.env` / 环境变量驱动。

## 使用约定

- 模块内直接 `from loguru import logger` 获取全局实例，或通过 `from backend.app.core.logging import get_logger` 获取带 module 绑定的实例。
- 业务代码中常见用法：`logger.info(...)`, `logger.warning(..., exc)`, `logger.exception(...)`，异常堆栈自动附带。
- 中间件层统一记录 HTTP 请求日志（method/path/status/duration），无需在各路由重复添加。
- 测试覆盖位于 `tests/test_logging.py`，验证 `setup_logging` 幂等性、生产模式分支及 `get_logger` API。

## 架构决策

1. **选择 loguru 而非 stdlib logging**：零样板、异步安全、内置轮转与 JSON 序列化，减少自定义基础设施。
2. **stdout JSON + 文件双写**：容器化部署下由侧车/daemon 抓取 stdout JSON，同时本地文件用于快速排障。
3. **错误单独归档**：ERROR 级别独立文件且更长保留期，满足合规审计需求。
4. **无自定义 Handler/Formatter**：完全依赖 loguru 内置能力，降低维护成本。