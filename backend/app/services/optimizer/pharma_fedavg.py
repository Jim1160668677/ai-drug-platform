"""制药联邦学习 FedAvg 聚合器 — 拜占庭容错的加权平均

在多中心药物研发联邦学习中，对客户端提交的模型权重进行：
1. 中位绝对偏差（MAD）拜占庭客户端检测与剔除
2. 按样本量加权平均（FedAvg）聚合

设计目标：
- 不依赖 numpy（避免容器体积膨胀），仅使用标准库 `statistics`
- 配置驱动：MAD 阈值来自 `settings.FL_MAD_THRESHOLD`
- Mock/Real 双模式：当无客户端或全部被剔除时降级返回空聚合
"""
import logging
import statistics
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)


class PharmaFedAvg:
    """制药联邦学习 FedAvg 聚合器

    P3 阶段组件：多中心联邦训练的中央聚合器。
    使用 MAD（Median Absolute Deviation）剔除拜占庭/恶意客户端后，
    按样本量加权平均得到全局权重。

    Examples:
        >>> agg = PharmaFedAvg()
        >>> result = agg.aggregate(
        ...     client_weights=[
        ...         {"weights": {"layer1": 0.1}, "num_samples": 100},
        ...         {"weights": {"layer1": 0.2}, "num_samples": 200},
        ...     ],
        ...     sample_counts=[100, 200],
        ... )
        >>> "aggregated_weights" in result
        True
    """

    def __init__(self, mad_threshold: Optional[float] = None):
        """初始化聚合器

        Args:
            mad_threshold: MAD 阈值，None 时从 settings.FL_MAD_THRESHOLD 读取
        """
        self._mad_threshold = (
            mad_threshold if mad_threshold is not None else settings.FL_MAD_THRESHOLD
        )

    def aggregate(
        self,
        client_weights: List[Dict[str, Any]],
        sample_counts: Optional[Sequence[int]] = None,
        mad_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """对客户端权重执行拜占庭容错的 FedAvg 加权聚合

        Args:
            client_weights: 每个客户端的权重包，形如
                ``{"weights": {layer: value}, "num_samples": int}``
                或直接 ``{layer: value}`` 的 dict。
            sample_counts: 各客户端样本量；None 时从 client_weights 中
                提取 ``num_samples``，再不行则等权重处理。
            mad_threshold: 本次聚合使用的 MAD 阈值；None 时使用初始化值。

        Returns:
            {
                "aggregated_weights": {layer: value},
                "total_samples": int,
                "num_clients": int,
                "num_byzantine_filtered": int,
                "strategy": "FedAvg+MAD",
                "status": "aggregated" | "no_clients" | "all_filtered",
            }
        """
        if not client_weights:
            logger.warning("FedAvg 聚合收到空客户端列表")
            return {
                "aggregated_weights": {},
                "total_samples": 0,
                "num_clients": 0,
                "num_byzantine_filtered": 0,
                "strategy": "FedAvg+MAD",
                "status": "no_clients",
            }

        # 解析阈值
        threshold = (
            mad_threshold if mad_threshold is not None else self._mad_threshold
        )

        # 标准化为 [{weights, num_samples}] 形式
        normalized = self._normalize_inputs(client_weights, sample_counts)

        # 拜占庭剔除
        filtered, num_filtered = self._filter_byzantine(normalized, threshold)

        if not filtered:
            logger.warning(
                "FedAvg 聚合：所有客户端均被 MAD 阈值 %.2f 剔除（共 %d 个）",
                threshold,
                len(normalized),
            )
            return {
                "aggregated_weights": {},
                "total_samples": 0,
                "num_clients": 0,
                "num_byzantine_filtered": num_filtered,
                "strategy": "FedAvg+MAD",
                "status": "all_filtered",
                "mad_threshold": threshold,
            }

        # 加权平均
        aggregated = self._weighted_average(filtered)

        logger.info(
            "FedAvg 聚合完成：%d/%d 客户端通过 MAD 过滤，总样本量=%d",
            len(filtered),
            len(normalized),
            aggregated["_total_samples"],
        )

        return {
            "aggregated_weights": aggregated["weights"],
            "total_samples": aggregated["_total_samples"],
            "num_clients": len(filtered),
            "num_byzantine_filtered": num_filtered,
            "strategy": "FedAvg+MAD",
            "status": "aggregated",
            "mad_threshold": threshold,
        }

    def _compute_mad(self, weights: Sequence[float]) -> Dict[str, float]:
        """计算一组标量的中位绝对偏差（MAD）

        MAD = median(|x_i - median(X)|)

        使用修正因子 1.4826 将 MAD 转换为正态分布等价标准差估计，
        以便与阈值（如 3.0σ）直接比较。

        Args:
            weights: 一维浮点数序列

        Returns:
            {"median": float, "mad": float, "scaled_mad": float}
            当输入少于 2 个值时，mad 与 scaled_mad 均为 0。
        """
        n = len(weights)
        if n == 0:
            return {"median": 0.0, "mad": 0.0, "scaled_mad": 0.0}
        if n == 1:
            return {"median": float(weights[0]), "mad": 0.0, "scaled_mad": 0.0}

        median_val = statistics.median(weights)
        abs_devs = [abs(w - median_val) for w in weights]
        mad_val = statistics.median(abs_devs)
        # 1.4826 是正态分布下 MAD 的一致性修正因子
        scaled_mad = mad_val * 1.4826

        return {
            "median": float(median_val),
            "mad": float(mad_val),
            "scaled_mad": float(scaled_mad),
        }

    def _filter_byzantine(
        self,
        client_weights: List[Dict[str, Any]],
        mad_threshold: float,
    ) -> tuple[List[Dict[str, Any]], int]:
        """基于 MAD 拜占庭剔除

        对每个权重层独立计算 MAD，将任意一层偏离中位数超过
        ``mad_threshold * scaled_mad`` 的客户端视为拜占庭客户端并剔除。

        当某层 scaled_mad 为 0（所有客户端该层值相同）时，跳过该层判断，
        以避免除零和误判。

        Args:
            client_weights: 标准化后的客户端权重包列表
            mad_threshold: MAD 阈值（σ 倍数）

        Returns:
            (filtered_clients, num_filtered)
        """
        if len(client_weights) <= 2:
            # 客户端数过少时无法稳健剔除，全部保留
            return list(client_weights), 0

        # 收集所有层名
        all_layers: List[str] = []
        seen = set()
        for c in client_weights:
            for layer in (c.get("weights") or {}).keys():
                if layer not in seen:
                    seen.add(layer)
                    all_layers.append(layer)

        byzantine_idx = set()
        for layer in all_layers:
            values = []
            for c in client_weights:
                w = (c.get("weights") or {}).get(layer)
                try:
                    values.append(float(w) if w is not None else 0.0)
                except (TypeError, ValueError):
                    values.append(0.0)

            stats = self._compute_mad(values)
            if stats["scaled_mad"] == 0:
                continue  # 该层无差异，跳过

            median_val = stats["median"]
            cutoff = mad_threshold * stats["scaled_mad"]
            for i, v in enumerate(values):
                if i in byzantine_idx:
                    continue
                if abs(v - median_val) > cutoff:
                    byzantine_idx.add(i)
                    logger.info(
                        "MAD 剔除客户端 #%d（layer=%s, value=%.4f, "
                        "median=%.4f, cutoff=%.4f）",
                        i,
                        layer,
                        v,
                        median_val,
                        cutoff,
                    )

        filtered = [c for i, c in enumerate(client_weights) if i not in byzantine_idx]
        return filtered, len(byzantine_idx)

    # -------- 内部辅助方法 --------

    def _normalize_inputs(
        self,
        client_weights: List[Dict[str, Any]],
        sample_counts: Optional[Sequence[int]],
    ) -> List[Dict[str, Any]]:
        """将多种输入格式标准化为 [{"weights": {...}, "num_samples": int}]"""
        normalized: List[Dict[str, Any]] = []
        for i, cw in enumerate(client_weights):
            # 情况 1：{"weights": ..., "num_samples": ...}
            if "weights" in cw:
                weights = cw.get("weights") or {}
                n = cw.get("num_samples")
            else:
                # 情况 2：直接是 {layer: value} 的权重 dict
                weights = cw
                n = None

            # 样本量优先级：显式传入 > 内嵌 num_samples > 默认 1
            if sample_counts is not None and i < len(sample_counts):
                n = sample_counts[i]
            if n is None:
                n = 1
            try:
                n = int(n)
                if n < 0:
                    n = 0
            except (TypeError, ValueError):
                n = 1

            normalized.append({"weights": dict(weights), "num_samples": n})
        return normalized

    def _weighted_average(
        self, clients: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """按样本量加权平均

        Args:
            clients: 标准化后的客户端列表

        Returns:
            {"weights": {layer: value}, "_total_samples": int}
        """
        total_samples = sum(c["num_samples"] for c in clients)
        if total_samples <= 0:
            # 全部样本量为 0 时退化为简单平均
            total_samples = len(clients)
            equal_weight = 1.0 / len(clients)
            sample_weighted = [equal_weight] * len(clients)
        else:
            sample_weighted = [c["num_samples"] / total_samples for c in clients]

        # 收集所有层
        all_layers: List[str] = []
        seen = set()
        for c in clients:
            for layer in (c.get("weights") or {}).keys():
                if layer not in seen:
                    seen.add(layer)
                    all_layers.append(layer)

        weights: Dict[str, Any] = {}
        for layer in all_layers:
            weighted_sum = 0.0
            for c, w in zip(clients, sample_weighted):
                v = (c.get("weights") or {}).get(layer, 0.0)
                try:
                    v = float(v) if v is not None else 0.0
                except (TypeError, ValueError):
                    v = 0.0
                weighted_sum += v * w
            weights[layer] = weighted_sum

        return {"weights": weights, "_total_samples": total_samples}
