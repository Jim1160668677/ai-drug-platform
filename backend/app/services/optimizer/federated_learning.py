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
            aggregated = self._aggregate(submissions, job["current_round"])
            job["rounds_history"][-1]["aggregated"] = aggregated
            job["aggregated_weights"] = aggregated["aggregated_weights"]
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
    ) -> Dict[str, Any]:
        """FedAvg 聚合 — 加权平均 + MAD 拜占庭剔除 + 学习率衰减

        Args:
            submissions: 客户端提交列表
            round_num: 当前轮次
        Returns:
            {aggregated_weights, total_samples, num_clients, byzantine_filtered}
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

        return {
            "aggregated_weights": aggregated,
            "total_samples": total_samples,
            "num_clients": len(submissions),
            "byzantine_filtered": byzantine_filtered,
            "learning_rate": round(lr, 6),
            "round": round_num,
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

    async def list_clients(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出注册的客户端"""
        clients = list(self._clients.values())
        if status:
            clients = [c for c in clients if c.get("status") == status]
        return clients


# 别名 — 保留旧类名兼容
FederatedLearner = FederatedLearningService
