"""计算引擎单例注册表 — 统一获取与状态查询

提供 5 个计算引擎的懒加载单例获取函数，
以及 list_available() 报告各引擎 Mock/Real 状态。
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 单例实例缓存
_instances: Dict[str, Any] = {}


def get_esmfold(db: Any = None):
    """获取 ESMFold 预测器单例

    Args:
        db: 异步数据库会话（可选）
    Returns:
        ESMFoldPredictor 实例
    """
    if "esmfold" not in _instances:
        from .esmfold_predictor import ESMFoldPredictor
        _instances["esmfold"] = ESMFoldPredictor(db)
        logger.debug("ESMFoldPredictor 实例已创建")
    return _instances["esmfold"]


def get_unimol(db: Any = None):
    """获取 Uni-Mol 对接器单例

    Args:
        db: 异步数据库会话（可选）
    Returns:
        UniMolDocking 实例
    """
    if "unimol" not in _instances:
        from .unimol_docking import UniMolDocking
        _instances["unimol"] = UniMolDocking(db)
        logger.debug("UniMolDocking 实例已创建")
    return _instances["unimol"]


def get_vina(db: Any = None):
    """获取 Vina 对接器单例

    Args:
        db: 异步数据库会话（可选）
    Returns:
        VinaDocking 实例
    """
    if "vina" not in _instances:
        from .vina_docking import VinaDocking
        _instances["vina"] = VinaDocking(db)
        logger.debug("VinaDocking 实例已创建")
    return _instances["vina"]


def get_scgpt(db: Any = None):
    """获取 scGPT 引擎单例

    Args:
        db: 异步数据库会话（可选）
    Returns:
        ScGPTEngine 实例
    """
    if "scgpt" not in _instances:
        from .scgpt_engine import ScGPTEngine
        _instances["scgpt"] = ScGPTEngine(db)
        logger.debug("ScGPTEngine 实例已创建")
    return _instances["scgpt"]


def get_mhcflurry(db: Any = None):
    """获取 MHCflurry 预测器单例

    Args:
        db: 异步数据库会话（可选）
    Returns:
        MHCflurryPredictor 实例
    """
    if "mhcflurry" not in _instances:
        from .mhcflurry_predictor import MHCflurryPredictor
        _instances["mhcflurry"] = MHCflurryPredictor(db)
        logger.debug("MHCflurryPredictor 实例已创建")
    return _instances["mhcflurry"]


def get_protenix(db: Any = None):
    """获取 Protenix 蛋白-配体复合物结构预测器单例

    Args:
        db: 异步数据库会话（可选）
    Returns:
        ProtenixPredictor 实例
    """
    if "protenix" not in _instances:
        from .protenix_predictor import ProtenixPredictor
        _instances["protenix"] = ProtenixPredictor(db)
        logger.debug("ProtenixPredictor 实例已创建")
    return _instances["protenix"]


def list_available() -> Dict[str, str]:
    """报告各引擎 Mock/Real 状态

    Returns:
        {esmfold: "mock"/"real", unimol: ..., vina: ..., scgpt: ..., mhcflurry: ...,
         protenix: "mock"/"real"}
    """
    from app.core.config import settings
    return {
        "esmfold": "mock" if getattr(settings, "ESMFOLD_USE_MOCK", True) else "real",
        "unimol": "mock" if getattr(settings, "UNIMOL_USE_MOCK", True) else "real",
        "vina": "mock" if getattr(settings, "VINA_USE_MOCK", True) else "real",
        "scgpt": "mock" if getattr(settings, "SCGPT_USE_MOCK", True) else "real",
        "mhcflurry": "mock" if getattr(settings, "MHCFLURRY_USE_MOCK", True) else "real",
        "protenix": "mock" if getattr(settings, "PROTENIX_USE_MOCK", True) else "real",
    }


def reset_instances() -> None:
    """重置所有单例（用于测试隔离）

    清空实例缓存，下次获取时将重新创建实例。
    使用 clear() 原地清空，避免 global 重绑定导致外部已导入的 _instances 引用失效。
    """
    _instances.clear()
    logger.debug("所有计算引擎单例已重置")
