"""结构化 JSON 日志扩展 — Phase F

扩展现有 loguru 日志，支持：
- JSON 格式输出（通过 LOG_JSON_FORMAT=true 启用）
- request_id 自动注入（复用 contextvars）
- 敏感字段脱敏（api_key / password / token / secret）

设计原则：
- 与现有 setup_logging() 共存，不破坏现有日志格式
- 生产环境推荐启用 JSON 格式，便于 ELK/Loki 采集
- 开发环境保持人类可读的彩色格式
- 脱敏在日志层完成，业务代码无感

使用方式：
    # 在 setup_logging() 中调用
    from app.core.observability.logging_ext import setup_json_logging
    setup_json_logging(logger)
"""
import json
import logging
import re
from typing import Any, Dict

from app.core.middleware import get_request_id

# 需要脱敏的字段名（正则匹配，大小写不敏感）
_SENSITIVE_FIELDS = re.compile(
    r"(api[_-]?key|password|passwd|secret|token|authorization|bearer|credential)",
    re.IGNORECASE,
)

# 脱敏后的显示值
_MASKED_VALUE = "***REDACTED***"


def _mask_sensitive(data: Any) -> Any:
    """递归脱敏字典中的敏感字段

    Args:
        data: 原始数据（dict/list/其他）
    Returns:
        脱敏后的数据（深拷贝）
    """
    if isinstance(data, dict):
        masked: Dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(k, str) and _SENSITIVE_FIELDS.search(k):
                masked[k] = _MASKED_VALUE
            else:
                masked[k] = _mask_sensitive(v)
        return masked
    if isinstance(data, list):
        return [_mask_sensitive(item) for item in data]
    return data


def _json_serializer(record) -> str:
    """loguru JSON 序列化器

    将日志记录序列化为 JSON 字符串，包含：
    - timestamp: ISO 格式时间戳
    - level: 日志级别
    - logger: logger 名
    - function: 函数名
    - line: 行号
    - request_id: 当前请求 ID（若存在）
    - message: 日志消息
    - extra: 额外字段（已脱敏）
    """
    try:
        subset = {
            "timestamp": record["time"].isoformat(),
            "level": record["level"].name,
            "logger": record["name"],
            "function": record["function"],
            "line": record["line"],
            "request_id": get_request_id() or "-",
            "message": record["message"],
        }
        # 合并 extra 字段（已脱敏）
        extra = {k: v for k, v in record["extra"].items() if k not in ("__name__",)}
        if extra:
            subset["extra"] = _mask_sensitive(extra)
        # 异常信息
        if record["exception"]:
            subset["exception"] = "".join(
                record["exception"].format()
            )
        return json.dumps(subset, ensure_ascii=False, default=str) + "\n"
    except Exception as e:
        # 序列化失败不能影响主流程
        return json.dumps({
            "level": "ERROR",
            "message": f"log serialization failed: {e}",
            "raw": str(record.get("message", "")),
        }) + "\n"


def setup_json_logging(logger) -> None:
    """为 loguru 添加 JSON 格式 sink

    Args:
        logger: loguru.logger 实例
    """
    import sys
    from app.core.config import settings

    # JSON 格式开关（默认开发环境关闭，生产环境开启）
    json_enabled = getattr(settings, "LOG_JSON_FORMAT", False)
    if not json_enabled:
        return

    # JSON 输出到 stdout（替换原有的彩色格式）
    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format="{message}",  # 占位，实际用 serialize
        serialize=False,
        # 使用自定义 sink
    )
    # 用自定义 sink 替代默认序列化
    logger.add(
        _json_sink,
        level=settings.LOG_LEVEL,
    )

    # JSON 文件输出
    from pathlib import Path
    log_dir = Path(getattr(settings, "LOG_FILE_PATH", "logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.jsonl",
            level=settings.LOG_LEVEL,
            rotation="00:00",
            retention="30 days",
            compression="zip",
            format="{message}",
        )
    except Exception:
        pass

    logger.info("JSON 结构化日志已启用")


def _json_sink(message) -> None:
    """loguru 自定义 sink — 输出 JSON 行

    loguru 的 add() 调用此 sink 时传入 Message 对象，
    其 record 属性包含完整日志记录。
    """
    import sys
    sys.stdout.write(_json_serializer(message.record))
