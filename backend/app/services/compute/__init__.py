"""计算引擎模块 — 集成 ESMFold/Uni-Mol/Vina/scGPT/MHCflurry 等 GitHub 开源项目

所有引擎统一遵循 *_USE_MOCK 配置开关：
- 真实模式：调用实际引擎（需 GPU + 模型文件）
- Mock 模式：返回伪造但合理的结果（测试环境默认）
"""
try:
    from .esmfold_predictor import ESMFoldPredictor
    from .unimol_docking import UniMolDocking
    from .vina_docking import VinaDocking
    from .scgpt_engine import ScGPTEngine
    from .mhcflurry_predictor import MHCflurryPredictor
    from .protenix_predictor import ProtenixPredictor
    from .registry import (
        get_esmfold, get_unimol, get_vina, get_scgpt, get_mhcflurry,
        get_protenix, list_available, reset_instances,
    )
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"部分计算引擎导入失败（已降级）: {e}")

__all__ = [
    "ESMFoldPredictor", "UniMolDocking", "VinaDocking",
    "ScGPTEngine", "MHCflurryPredictor", "ProtenixPredictor",
    "get_esmfold", "get_unimol", "get_vina", "get_scgpt", "get_mhcflurry",
    "get_protenix", "list_available", "reset_instances",
]
