"""日志配置 — 使用 loguru"""
import logging
import sys
from pathlib import Path

from loguru import logger

from app.core.config import settings


def setup_logging() -> None:
    """配置 loguru 日志"""
    logger.remove()

    log_level = "DEBUG" if settings.APP_ENV == "development" else "INFO"

    # 控制台输出
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # 文件输出（本地 logs 目录，兼容 Windows）
    log_dir = Path("logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            level=log_level,
            rotation="00:00",
            retention="30 days",
            compression="zip",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        )
    except Exception as e:
        print(f"[WARNING] 日志目录创建失败，仅使用控制台输出: {e}", file=sys.stderr)

    # 拦截标准库 logging
    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    logger.info(f"日志已配置 | 环境={settings.APP_ENV} | Mock={settings.USE_MOCK}")
