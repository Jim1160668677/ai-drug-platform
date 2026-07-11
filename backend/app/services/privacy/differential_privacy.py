"""差分隐私机制 — 拉普拉斯/高斯/随机响应

设计来源：repowiki/zh/content/安全与合规/差分隐私机制.md
P0/P1 阶段：纯 Python 实现（仅依赖 random 标准库）。
P3 阶段：可替换为 PySyft / Opacus 后端。
"""
import logging
import math
import random
from typing import Any, List

from app.core.config import settings

logger = logging.getLogger(__name__)


class PrivacyBudget:
    """隐私预算管理 — (ε, δ) 跟踪与消耗

    差分隐私要求总 ε 在生命周期内有限。本类提供预算账户，
    超出时拒绝进一步查询。

    Attributes:
        epsilon: 总 ε 预算
        delta: 总 δ 预算（用于 (ε, δ)-DP）
        _consumed: 已消耗的 ε 量
    """

    def __init__(self, epsilon: float, delta: float = 0.0) -> None:
        """初始化隐私预算

        Args:
            epsilon: 总 ε 预算（>0）
            delta: 总 δ 预算（>=0），默认 0 即纯 DP
        Raises:
            ValueError: 参数非法
        """
        if epsilon <= 0:
            raise ValueError(f"epsilon 必须为正数，收到 {epsilon}")
        if delta < 0:
            raise ValueError(f"delta 不能为负，收到 {delta}")
        self.epsilon = epsilon
        self.delta = delta
        self._consumed = 0.0

    def consume(self, amount: float) -> float:
        """消耗一定量的 ε 预算

        Args:
            amount: 待消耗量（>0）
        Returns:
            剩余预算
        Raises:
            ValueError: 超出剩余预算
        """
        if amount <= 0:
            raise ValueError(f"消耗量必须为正，收到 {amount}")
        if self._consumed + amount > self.epsilon + 1e-12:
            raise ValueError(
                f"隐私预算不足：已消耗 {self._consumed}，请求 {amount}，"
                f"总额 {self.epsilon}"
            )
        self._consumed += amount
        logger.debug(
            "消耗隐私预算 ε=%.4f（累计 %.4f / %.4f）",
            amount, self._consumed, self.epsilon,
        )
        return self.remaining()

    def remaining(self) -> float:
        """返回剩余 ε 预算"""
        return max(0.0, self.epsilon - self._consumed)

    def is_exhausted(self) -> bool:
        """预算是否耗尽"""
        return self.remaining() <= 1e-12


class DifferentialPrivacy:
    """差分隐私机制集合 — 纯 Python 实现

    P0/P1：使用 random 标准库采样，避免 numpy 依赖。
    P3：可替换为 PySyft/Opacus 后端。
    """

    def __init__(self) -> None:
        self._backend = "stdlib"
        self._rng = random.Random()
        # 固定种子时使用 settings.USE_MOCK 决定可复现性
        if settings.USE_MOCK:
            self._rng.seed(42)
            logger.info("差分隐私：Mock 模式，使用固定种子 42 以便复现")

    # ---------- 拉普拉斯机制 ----------
    def laplace(
        self,
        value: float,
        sensitivity: float,
        epsilon: float,
    ) -> float:
        """拉普拉斯机制 — 数值型查询加噪

        noise ~ Laplace(0, sensitivity / ε)
        返回 value + noise

        Args:
            value: 原始查询结果
            sensitivity: 查询的 L1 全局敏感度
            epsilon: 单次查询的 ε
        Returns:
            加噪后的值
        Raises:
            ValueError: 参数非法
        """
        if epsilon <= 0:
            raise ValueError(f"epsilon 必须为正，收到 {epsilon}")
        if sensitivity < 0:
            raise ValueError(f"sensitivity 不能为负，收到 {sensitivity}")

        scale = sensitivity / epsilon
        noise = self._sample_laplace(0.0, scale)
        result = value + noise
        logger.debug(
            "laplace: value=%.4f sens=%.4f eps=%.4f noise=%.4f -> %.4f",
            value, sensitivity, epsilon, noise, result,
        )
        return result

    # ---------- 高斯机制 ----------
    def gaussian(
        self,
        value: float,
        sensitivity: float,
        epsilon: float,
        delta: float,
    ) -> float:
        """高斯机制 — (ε, δ)-DP

        σ = sqrt(2 * ln(1.25/δ)) * sensitivity / ε
        noise ~ N(0, σ²)
        返回 value + noise

        Args:
            value: 原始查询结果
            sensitivity: 查询的 L2 全局敏感度
            epsilon: ε 参数
            delta: δ 参数
        Returns:
            加噪后的值
        Raises:
            ValueError: 参数非法
        """
        if epsilon <= 0:
            raise ValueError(f"epsilon 必须为正，收到 {epsilon}")
        if not (0 < delta < 1):
            raise ValueError(f"delta 必须在 (0, 1) 区间，收到 {delta}")
        if sensitivity < 0:
            raise ValueError(f"sensitivity 不能为负，收到 {sensitivity}")

        sigma = math.sqrt(2 * math.log(1.25 / delta)) * sensitivity / epsilon
        noise = self._sample_gaussian(0.0, sigma)
        result = value + noise
        logger.debug(
            "gaussian: value=%.4f sens=%.4f eps=%.4f delta=%.2e sigma=%.4f -> %.4f",
            value, sensitivity, epsilon, delta, sigma, result,
        )
        return result

    # ---------- 随机响应 ----------
    def randomized_response(
        self,
        value: Any,
        categories: List[Any],
        epsilon: float,
    ) -> Any:
        """随机响应 — 类别型数据的本地差分隐私

        k = len(categories)
        p = e^ε / (e^ε + k - 1)  # 讲真话概率
        以概率 p 报告真实值，否则在其他 k-1 个类别中均匀随机

        Args:
            value: 真实类别（必须在 categories 中）
            categories: 所有可能类别列表
            epsilon: 隐私参数
        Returns:
            加噪后的类别
        Raises:
            ValueError: 参数非法
        """
        if epsilon <= 0:
            raise ValueError(f"epsilon 必须为正，收到 {epsilon}")
        if not categories:
            raise ValueError("categories 不能为空")
        if len(categories) == 1:
            return categories[0]
        if value not in categories:
            raise ValueError(f"value={value!r} 不在 categories 中")

        k = len(categories)
        p_true = math.exp(epsilon) / (math.exp(epsilon) + k - 1)

        if self._rng.random() < p_true:
            return value
        # 在其他类别中均匀采样
        others = [c for c in categories if c != value]
        return self._rng.choice(others)

    # ---------- 内部采样原语 ----------
    @staticmethod
    def _sample_laplace(loc: float, scale: float) -> float:
        """从 Laplace(loc, scale) 采样

        使用逆 CDF：U ~ Uniform(-0.5, 0.5)
        X = loc - scale * sign(U) * ln(1 - 2|U|)
        """
        if scale <= 0:
            return loc
        u = random.random() - 0.5
        return loc - scale * math.copysign(math.log(1 - 2 * abs(u)), u)

    @staticmethod
    def _sample_gaussian(loc: float, sigma: float) -> float:
        """从 N(loc, σ²) 采样 — Box-Muller"""
        if sigma <= 0:
            return loc
        u1 = random.random()
        u2 = random.random()
        # 避免 log(0)
        while u1 <= 1e-300:
            u1 = random.random()
        z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        return loc + sigma * z
