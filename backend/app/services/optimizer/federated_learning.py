"""联邦学习服务 — 多中心数据隐私保护的联邦模型训练

设计来源：repowiki/zh/content/服务端开发指南/服务层设计/优化器服务层.md

内存态实现：job 管理 + 客户端注册 + FedAvg 聚合
生产环境：可替换为 Flower（pip install flwr）+ Redis 持久化
"""
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class FederatedLearningService:
    """联邦学习服务 — 内存态 job 管理

    功能：
    1. 创建/列表/详情/停止 FL 训练任务
    2. 客户端注册与心跳
    3. FedAvg 加权聚合（含 MAD 拜占庭剔除）
    4. 学习率衰减

    Usage:
        service = FederatedLearningService()
        job = await service.create_job(project_id, target_id, num_rounds=10)
    """

    def __init__(
        self,
        num_rounds_default: Optional[int] = None,
        min_clients: Optional[int] = None,
        mad_threshold: Optional[float] = None,
    ):
        self.num_rounds_default = num_rounds_default or settings.FL_NUM_ROUNDS_DEFAULT
        self.min_clients = min_clients or settings.FL_MIN_CLIENTS_DEFAULT
        self.mad_threshold = mad_threshold or settings.FL_MAD_THRESHOLD
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._clients: Dict[str, Dict[str, Any]] = {}
        self._flower_available = self._check_flower()

    @staticmethod
    def _check_flower() -> bool:
        try:
            import flwr  # noqa: F401
            return True
        except ImportError:
            return False

    async def create_job(
        self,
        project_id: str,
        target_id: Optional[str] = None,
        num_rounds: Optional[int] = None,
        min_clients: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建联邦学习任务

        Args:
            project_id: 项目 ID
            target_id: 关联靶点 ID（可选）
            num_rounds: 训练轮数（默认 10）
            min_clients: 最少客户端数（默认 3）
            config: 额外配置
        Returns:
            {job_id, status, config}
        """
        job_id = f"fl_job_{uuid.uuid4().hex[:12]}"
        rounds = num_rounds or self.num_rounds_default
        clients_min = min_clients or self.min_clients

        job = {
            "job_id": job_id,
            "project_id": project_id,
            "target_id": target_id,
            "status": "pending",  # pending / running / completed / stopped / failed
            "num_rounds": rounds,
            "min_clients": clients_min,
            "current_round": 0,
            "config": config or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "completed_at": None,
            "registered_clients": [],
            "rounds_history": [],
            "aggregated_weights": None,
            "framework": "flower" if self._flower_available else "in_memory",
            "metrics_history": [],  # 每轮聚合后的全局指标记录
            "centers": (config or {}).get("centers", []),  # 多中心列表 [{center_id, name, clients: []}]
            "dp_params": (config or {}).get("dp_params"),  # 差分隐私参数
        }
        self._jobs[job_id] = job
        logger.info(f"FL job created: {job_id} (rounds={rounds}, min_clients={clients_min})")
        return job

    async def list_jobs(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出 FL 任务"""
        jobs = list(self._jobs.values())
        if project_id:
            jobs = [j for j in jobs if j.get("project_id") == project_id]
        if status:
            jobs = [j for j in jobs if j.get("status") == status]
        return jobs

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取任务详情"""
        return self._jobs.get(job_id)

    async def stop_job(self, job_id: str) -> Dict[str, Any]:
        """停止任务"""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": "任务不存在", "job_id": job_id}
        job["status"] = "stopped"
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"FL job stopped: {job_id}")
        return {"job_id": job_id, "status": "stopped"}

    async def register_client(
        self,
        client_id: str,
        endpoint: str,
        capabilities: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """注册联邦学习客户端

        Args:
            client_id: 客户端唯一标识
            endpoint: 客户端地址
            capabilities: 客户端能力描述
        Returns:
            {client_id, status, registered_at}
        """
        self._clients[client_id] = {
            "client_id": client_id,
            "endpoint": endpoint,
            "capabilities": capabilities or {},
            "status": "active",
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "weights_submitted": 0,
        }
        logger.info(f"FL client registered: {client_id} @ {endpoint}")
        return {"client_id": client_id, "status": "registered"}

    async def submit_weights(
        self,
        job_id: str,
        client_id: str,
        weights: Dict[str, Any],
        num_samples: int = 1,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """客户端提交本轮权重

        Args:
            job_id: 任务 ID
            client_id: 客户端 ID
            weights: 模型权重
            num_samples: 本地训练样本数
            metrics: 训练指标
        Returns:
            {job_id, round, status}
        """
        job = self._jobs.get(job_id)
        if not job:
            return {"error": "任务不存在", "job_id": job_id}

        current_round = job["current_round"]
        round_data = {
            "round": current_round,
            "client_id": client_id,
            "weights": weights,
            "num_samples": num_samples,
            "metrics": metrics or {},
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }

        # 找到当前轮次的记录
        if not job["rounds_history"] or job["rounds_history"][-1].get("round") != current_round:
            job["rounds_history"].append({
                "round": current_round,
                "submissions": [],
                "aggregated": None,
            })

        job["rounds_history"][-1]["submissions"].append(round_data)

        # 更新客户端心跳和计数
        if client_id in self._clients:
            self._clients[client_id]["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            self._clients[client_id]["weights_submitted"] += 1

        # 检查是否达到最少客户端数，触发聚合
        submissions = job["rounds_history"][-1]["submissions"]
        if len(submissions) >= job["min_clients"]:
            import time as _time
            t0 = _time.time()
            aggregated = self._aggregate(submissions, job["current_round"], job)
            duration_sec = round(_time.time() - t0, 4)

            # 差分隐私处理（如启用）
            dp_params = job.get("dp_params")
            if dp_params and dp_params.get("enabled"):
                optimizer = DPSGDOptimizer(
                    noise_multiplier=dp_params.get("noise_multiplier", 1.0),
                    max_norm=dp_params.get("max_norm", 1.0),
                )
                aggregated["aggregated_weights"] = optimizer.add_noise(
                    aggregated["aggregated_weights"]
                )
                aggregated["dp_applied"] = True

            # 多中心分层聚合（如配置了 centers）
            centers = job.get("centers")
            if centers:
                aggregated = self._hierarchical_aggregate(
                    submissions, job["current_round"], job, aggregated
                )

            aggregated["duration_sec"] = duration_sec
            job["rounds_history"][-1]["aggregated"] = aggregated
            job["aggregated_weights"] = aggregated["aggregated_weights"]

            # 记录每轮全局指标到 metrics_history
            metrics_entry = {
                "round": job["current_round"],
                "global_loss": aggregated.get("avg_loss"),
                "global_accuracy": aggregated.get("avg_accuracy"),
                "val_metrics": aggregated.get("val_metrics", {}),
                "client_contributions": [
                    {
                        "client_id": s.get("client_id"),
                        "num_samples": s.get("num_samples", 1),
                        "weight": round(
                            s.get("num_samples", 1) / max(aggregated.get("total_samples", 1), 1), 4
                        ),
                    }
                    for s in submissions
                ],
                "byzantine_filtered": aggregated.get("byzantine_filtered", 0),
                "duration_sec": duration_sec,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            job["metrics_history"].append(metrics_entry)

            job["current_round"] += 1

            if job["current_round"] >= job["num_rounds"]:
                job["status"] = "completed"
                job["completed_at"] = datetime.now(timezone.utc).isoformat()
            elif job["status"] == "pending":
                job["status"] = "running"
                job["started_at"] = datetime.now(timezone.utc).isoformat()

        return {
            "job_id": job_id,
            "round": current_round,
            "status": job["status"],
            "current_round": job["current_round"],
        }

    def _aggregate(
        self,
        submissions: List[Dict[str, Any]],
        round_num: int,
        job: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """FedAvg 聚合 — 加权平均 + MAD 拜占庭剔除 + 学习率衰减 + 指标汇总

        Args:
            submissions: 客户端提交列表
            round_num: 当前轮次
            job: 任务对象（可选，用于读取配置）
        Returns:
            {aggregated_weights, total_samples, num_clients, byzantine_filtered,
             learning_rate, round, avg_loss, avg_accuracy, val_metrics}
        """
        if not submissions:
            return {"aggregated_weights": {}, "total_samples": 0, "num_clients": 0}

        # 1. MAD 拜占庭剔除
        byzantine_filtered = 0
        if len(submissions) > 3 and self.mad_threshold > 0:
            valid = self._filter_byzantine(submissions)
            byzantine_filtered = len(submissions) - len(valid)
            submissions = valid

        # 2. 加权平均（按样本数）
        total_samples = sum(s.get("num_samples", 1) for s in submissions)
        if total_samples == 0:
            total_samples = len(submissions)

        aggregated = {}
        first_weights = submissions[0].get("weights") or {}
        for layer in first_weights:
            weighted_sum = 0.0
            for s in submissions:
                w = (s.get("weights") or {}).get(layer, 0)
                n = s.get("num_samples", 1)
                weighted_sum += w * n
            aggregated[layer] = weighted_sum / total_samples

        # 3. 学习率衰减（每轮衰减 0.95）
        lr = 0.01 * (0.95 ** round_num)

        # 4. 汇总客户端训练指标（loss / accuracy）
        losses = []
        accuracies = []
        for s in submissions:
            m = s.get("metrics") or {}
            if "loss" in m:
                losses.append(m["loss"])
            if "accuracy" in m:
                accuracies.append(m["accuracy"])

        avg_loss = round(sum(losses) / len(losses), 6) if losses else None
        avg_accuracy = round(sum(accuracies) / len(accuracies), 4) if accuracies else None

        # 5. 验证集指标（取中位数作为 val_metrics）
        val_metrics: Dict[str, Any] = {}
        for s in submissions:
            m = s.get("metrics") or {}
            for key, val in m.items():
                if key.startswith("val_") and isinstance(val, (int, float)):
                    val_metrics.setdefault(key, []).append(val)
        val_metrics = {k: round(sum(v) / len(v), 4) for k, v in val_metrics.items()}

        return {
            "aggregated_weights": aggregated,
            "total_samples": total_samples,
            "num_clients": len(submissions),
            "byzantine_filtered": byzantine_filtered,
            "learning_rate": round(lr, 6),
            "round": round_num,
            "avg_loss": avg_loss,
            "avg_accuracy": avg_accuracy,
            "val_metrics": val_metrics,
        }

    def _filter_byzantine(self, submissions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """MAD（中位绝对偏差）拜占庭剔除

        剔除权重偏离中位数过大的客户端（|x - median| > MAD_THRESHOLD * MAD）
        """
        import statistics

        if len(submissions) <= 3:
            return submissions

        # 计算每个客户端的权重范数（简化：取所有层的平均绝对值）
        norms = []
        for s in submissions:
            weights = s.get("weights") or {}
            if weights:
                vals = [abs(v) for v in weights.values() if isinstance(v, (int, float))]
                norm = sum(vals) / len(vals) if vals else 0
            else:
                norm = 0
            norms.append(norm)

        if not norms or len(norms) <= 3:
            return submissions

        median = statistics.median(norms)
        abs_devs = [abs(n - median) for n in norms]
        mad = statistics.median(abs_devs)

        if mad == 0:
            return submissions

        valid = []
        for s, norm in zip(submissions, norms):
            # |x - median| / MAD < threshold
            if abs(norm - median) / mad < self.mad_threshold:
                valid.append(s)
            else:
                logger.warning(f"拜占庭客户端剔除: norm={norm:.4f} median={median:.4f} mad={mad:.4f}")

        return valid if valid else submissions

    async def get_metrics_history(self, job_id: str) -> Dict[str, Any]:
        """获取任务的全局指标历史记录

        Args:
            job_id: 任务 ID
        Returns:
            {job_id, rounds, metrics_history, convergence_trend}
        """
        job = self._jobs.get(job_id)
        if not job:
            return {"error": "任务不存在", "job_id": job_id}

        history = job.get("metrics_history", [])
        # 收敛趋势（loss 是否随轮次下降）
        trend = []
        for i in range(1, len(history)):
            prev = history[i - 1].get("global_loss")
            curr = history[i].get("global_loss")
            if prev is not None and curr is not None:
                if curr < prev:
                    trend.append({"round": history[i]["round"], "trend": "decreasing"})
                elif curr > prev:
                    trend.append({"round": history[i]["round"], "trend": "increasing"})
                else:
                    trend.append({"round": history[i]["round"], "trend": "stable"})
            else:
                trend.append({"round": history[i].get("round"), "trend": "unknown"})

        return {
            "job_id": job_id,
            "rounds": len(history),
            "metrics_history": history,
            "convergence_trend": trend,
            "final_loss": history[-1].get("global_loss") if history else None,
            "final_accuracy": history[-1].get("global_accuracy") if history else None,
        }

    async def evaluate_global_model(
        self,
        job_id: str,
        eval_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """评估全局模型性能

        Args:
            job_id: 任务 ID
            eval_metrics: 外部评估指标（可选）
        Returns:
            {job_id, status, aggregated_weights_summary, eval_metrics, rounds_completed}
        """
        job = self._jobs.get(job_id)
        if not job:
            return {"error": "任务不存在", "job_id": job_id}

        weights = job.get("aggregated_weights") or {}
        # 权重摘要
        if weights:
            vals = [v for v in weights.values() if isinstance(v, (int, float))]
            weight_summary = {
                "num_layers": len(weights),
                "mean": round(sum(vals) / len(vals), 6) if vals else 0,
                "min": round(min(vals), 6) if vals else 0,
                "max": round(max(vals), 6) if vals else 0,
            }
        else:
            weight_summary = {"num_layers": 0, "message": "尚未聚合权重"}

        # 合并最近一轮指标
        history = job.get("metrics_history", [])
        last_round = history[-1] if history else {}

        return {
            "job_id": job_id,
            "status": job.get("status"),
            "rounds_completed": job.get("current_round", 0),
            "total_rounds": job.get("num_rounds", 0),
            "aggregated_weights_summary": weight_summary,
            "eval_metrics": eval_metrics or {},
            "last_round_metrics": {
                "global_loss": last_round.get("global_loss"),
                "global_accuracy": last_round.get("global_accuracy"),
                "val_metrics": last_round.get("val_metrics", {}),
                "duration_sec": last_round.get("duration_sec"),
            },
            "dp_applied": bool(job.get("dp_params")),
            "framework": job.get("framework"),
        }

    def _hierarchical_aggregate(
        self,
        submissions: List[Dict[str, Any]],
        round_num: int,
        job: Dict[str, Any],
        base_aggregated: Dict[str, Any],
    ) -> Dict[str, Any]:
        """多中心分层聚合 — 先按中心聚合，再跨中心聚合

        Args:
            submissions: 客户端提交列表
            round_num: 当前轮次
            job: 任务对象
            base_aggregated: 基础聚合结果（已有 FedAvg）
        Returns:
            增强后的聚合结果，包含 centers_breakdown
        """
        centers = job.get("centers") or []
        if not centers:
            return base_aggregated

        # 按 center 分组客户端提交（通过 client_id 匹配 center.clients）
        client_to_center = {}
        for center in centers:
            cid = center.get("center_id", "")
            for c in center.get("clients", []):
                client_to_center[c] = cid

        center_groups: Dict[str, List[Dict[str, Any]]] = {}
        for s in submissions:
            cid = client_to_center.get(s.get("client_id"), "unknown")
            center_groups.setdefault(cid, []).append(s)

        # 每个中心内部聚合
        centers_breakdown = []
        for center in centers:
            cid = center.get("center_id", "")
            group = center_groups.get(cid, [])
            if not group:
                continue
            total_samples = sum(s.get("num_samples", 1) for s in group)
            losses = [s.get("metrics", {}).get("loss") for s in group if s.get("metrics", {}).get("loss") is not None]
            centers_breakdown.append({
                "center_id": cid,
                "name": center.get("name", ""),
                "num_clients": len(group),
                "total_samples": total_samples,
                "avg_loss": round(sum(losses) / len(losses), 6) if losses else None,
                "weight": round(total_samples / max(base_aggregated.get("total_samples", 1), 1), 4),
            })

        base_aggregated["centers_breakdown"] = centers_breakdown
        base_aggregated["hierarchical"] = True
        return base_aggregated

    async def configure_dp(
        self,
        job_id: str,
        enabled: bool = True,
        noise_multiplier: float = 1.0,
        max_norm: float = 1.0,
    ) -> Dict[str, Any]:
        """配置差分隐私参数

        Args:
            job_id: 任务 ID
            enabled: 是否启用 DP
            noise_multiplier: 噪声乘子（越大隐私越强）
            max_norm: 梯度裁剪范数
        Returns:
            {job_id, dp_params}
        """
        job = self._jobs.get(job_id)
        if not job:
            return {"error": "任务不存在", "job_id": job_id}

        job["dp_params"] = {
            "enabled": enabled,
            "noise_multiplier": noise_multiplier,
            "max_norm": max_norm,
        }
        logger.info(f"FL job {job_id} DP 配置: enabled={enabled}, noise={noise_multiplier}, max_norm={max_norm}")
        return {"job_id": job_id, "dp_params": job["dp_params"]}

    async def get_centers(self, job_id: str) -> Dict[str, Any]:
        """获取任务的多中心配置与最新状态

        Args:
            job_id: 任务 ID
        Returns:
            {job_id, centers, last_centers_breakdown}
        """
        job = self._jobs.get(job_id)
        if not job:
            return {"error": "任务不存在", "job_id": job_id}

        centers = job.get("centers") or []
        # 取最近一轮的 centers_breakdown
        last_breakdown = []
        history = job.get("rounds_history", [])
        if history:
            last_round = history[-1]
            aggregated = last_round.get("aggregated") or {}
            last_breakdown = aggregated.get("centers_breakdown", [])

        return {
            "job_id": job_id,
            "centers": centers,
            "last_centers_breakdown": last_breakdown,
        }

    async def list_clients(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出注册的客户端"""
        clients = list(self._clients.values())
        if status:
            clients = [c for c in clients if c.get("status") == status]
        return clients


class DPSGDOptimizer:
    """差分隐私 SGD 优化器 — 梯度裁剪 + 高斯噪声

    实现 DP-SGD（Differentially Private Stochastic Gradient Descent）：
    1. 梯度裁剪：将每个客户端的权重范数裁剪到 max_norm
    2. 高斯噪声：向裁剪后的权重添加 N(0, noise_multiplier * max_norm) 噪声

    依赖 opacus（可选）：pip install opacus
    未安装时降级为 numpy 纯 Python 实现。
    """

    def __init__(
        self,
        noise_multiplier: float = 1.0,
        max_norm: float = 1.0,
    ):
        self.noise_multiplier = noise_multiplier
        self.max_norm = max_norm
        self._opacus_available = self._check_opacus()

    @staticmethod
    def _check_opacus() -> bool:
        try:
            import opacus  # noqa: F401
            return True
        except ImportError:
            return False

    def clip_weights(self, weights: Dict[str, Any]) -> Dict[str, Any]:
        """梯度裁剪 — 将权重范数裁剪到 max_norm

        Args:
            weights: 模型权重 {layer_name: value}
        Returns:
            裁剪后的权重
        """
        vals = [v for v in weights.values() if isinstance(v, (int, float))]
        if not vals:
            return weights

        # 计算 L2 范数
        norm = sum(v * v for v in vals) ** 0.5
        if norm <= self.max_norm:
            return weights

        # 按比例缩放
        scale = self.max_norm / norm
        return {k: v * scale if isinstance(v, (int, float)) else v for k, v in weights.items()}

    def add_noise(
        self,
        weights: Dict[str, Any],
        noise_multiplier: Optional[float] = None,
        max_norm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """向权重添加高斯噪声

        Args:
            weights: 模型权重
            noise_multiplier: 噪声乘子（覆盖默认值）
            max_norm: 裁剪范数（覆盖默认值）
        Returns:
            加噪后的权重
        """
        nm = noise_multiplier or self.noise_multiplier
        mn = max_norm or self.max_norm

        # 先裁剪
        clipped = self.clip_weights(weights) if mn else weights

        # 添加高斯噪声
        try:
            import numpy as np
            noise_scale = nm * mn
            noisy = {}
            for k, v in clipped.items():
                if isinstance(v, (int, float)):
                    noise = float(np.random.normal(0, noise_scale))
                    noisy[k] = round(v + noise, 6)
                else:
                    noisy[k] = v
            return noisy
        except ImportError:
            # 降级：使用 random.gauss
            import random
            noise_scale = nm * mn
            noisy = {}
            for k, v in clipped.items():
                if isinstance(v, (int, float)):
                    noise = random.gauss(0, noise_scale)
                    noisy[k] = round(v + noise, 6)
                else:
                    noisy[k] = v
            return noisy

    def get_privacy_spent(self, steps: int, target_delta: float = 1e-5) -> Dict[str, Any]:
        """估算隐私预算消耗（基于 RDP 简化估算）

        Args:
            steps: 训练步数
            target_delta: 目标 delta
        Returns:
            {epsilon, delta, steps, noise_multiplier}
        """
        try:
            from opacus.privacy_analysis import compute_rdp, get_privacy_spent
            # 简化：假设采样率 q=0.01
            q = 0.01
            orders = [1 + x / 10.0 for x in range(1, 100)] + list(range(12, 64))
            rdp = compute_rdp(q, self.noise_multiplier, steps, orders)
            eps, _, opt_order = get_privacy_spent(target_delta, [(rdp, 0)], orders)
            return {
                "epsilon": round(eps, 4),
                "delta": target_delta,
                "steps": steps,
                "noise_multiplier": self.noise_multiplier,
                "opt_order": opt_order,
                "source": "opacus",
            }
        except (ImportError, Exception):
            # 降级估算：epsilon ≈ noise_multiplier * sqrt(2 * ln(1.25/delta)) / sqrt(steps)
            import math
            eps = self.noise_multiplier * (2 * math.log(1.25 / target_delta)) ** 0.5 / max(steps ** 0.5, 1)
            return {
                "epsilon": round(eps, 4),
                "delta": target_delta,
                "steps": steps,
                "noise_multiplier": self.noise_multiplier,
                "source": "approx",
            }


class RedisFLStorage:
    """Redis 持久化存储 — 用于 FL 任务和客户端数据的持久化

    生产环境使用 Redis 持久化 FL 状态，避免进程重启丢失。
    未安装 redis 或连接失败时降级为内存字典。

    Usage:
        storage = RedisFLStorage(redis_url="redis://localhost:6379/0")
        await storage.save_job(job)
        job = await storage.load_job(job_id)
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self._redis = None
        self._fallback: Dict[str, Any] = {}
        self._available = self._check_redis()

    @staticmethod
    def _check_redis() -> bool:
        try:
            import redis  # noqa: F401
            return True
        except ImportError:
            return False

    async def _get_client(self):
        if not self._available:
            return None
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
                await self._redis.ping()
            except Exception as e:
                logger.warning(f"Redis 连接失败，降级内存: {e}")
                self._available = False
                return None
        return self._redis

    async def save_job(self, job: Dict[str, Any]) -> bool:
        """保存任务"""
        import json
        client = await self._get_client()
        job_id = job.get("job_id", "")
        if client:
            try:
                await client.set(f"fl:job:{job_id}", json.dumps(job, default=str))
                return True
            except Exception as e:
                logger.warning(f"Redis 保存任务失败，降级内存: {e}")
        self._fallback[f"fl:job:{job_id}"] = job
        return True

    async def load_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """加载任务"""
        import json
        client = await self._get_client()
        if client:
            try:
                data = await client.get(f"fl:job:{job_id}")
                if data:
                    return json.loads(data)
                return None
            except Exception as e:
                logger.warning(f"Redis 加载任务失败，降级内存: {e}")
        return self._fallback.get(f"fl:job:{job_id}")

    async def list_jobs(self, pattern: str = "fl:job:*") -> List[Dict[str, Any]]:
        """列出所有任务"""
        import json
        client = await self._get_client()
        if client:
            try:
                keys = await client.keys(pattern)
                jobs = []
                for key in keys:
                    data = await client.get(key)
                    if data:
                        jobs.append(json.loads(data))
                return jobs
            except Exception as e:
                logger.warning(f"Redis 列出任务失败，降级内存: {e}")
        return list(self._fallback.values())

    async def save_client(self, client_data: Dict[str, Any]) -> bool:
        """保存客户端"""
        import json
        client = await self._get_client()
        client_id = client_data.get("client_id", "")
        if client:
            try:
                await client.set(f"fl:client:{client_id}", json.dumps(client_data, default=str))
                return True
            except Exception as e:
                logger.warning(f"Redis 保存客户端失败，降级内存: {e}")
        self._fallback[f"fl:client:{client_id}"] = client_data
        return True

    async def close(self):
        """关闭连接"""
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass


# 别名 — 保留旧类名兼容
FederatedLearner = FederatedLearningService
