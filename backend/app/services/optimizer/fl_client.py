"""联邦学习客户端 + 注册中心 — 内存态实现

提供：
- ``FLClient``：联邦学习客户端，负责注册、心跳、提交权重
- ``ClientRegistry``：客户端注册中心，内存态维护客户端元数据与活跃状态

设计目标：
- P0/P1 阶段以内存态实现，便于单进程演示与测试
- P3 阶段可平滑替换为 Redis/etcd 后端
- 配置驱动：心跳超时阈值从 ``settings`` 读取（未配置则使用默认值）
- Mock/Real 双模式：心跳与权重提交均可降级为框架态
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


# 默认心跳超时（秒）— 超过该时长未心跳的客户端视为失活
_DEFAULT_HEARTBEAT_TIMEOUT_SEC = 60


class FLClient:
    """联邦学习客户端

    表示参与联邦训练的一个数据持有方（医院/研究中心）。
    通过 ``ClientRegistry`` 维护在线状态，周期性心跳保活，
    训练完成后向聚合器提交本地权重与指标。

    Examples:
        >>> registry = ClientRegistry()
        >>> client = FLClient(
        ...     client_id="hospital-001",
        ...     endpoint="grpc://hospital-001:8080",
        ...     capabilities=["ic50", "scrna"],
        ... )
        >>> client.register(registry)["status"]
        'registered'
    """

    def __init__(
        self,
        client_id: str,
        endpoint: str,
        capabilities: Optional[List[str]] = None,
    ):
        """初始化联邦学习客户端

        Args:
            client_id: 客户端唯一标识
            endpoint: 客户端通信端点（如 ``grpc://host:port``）
            capabilities: 客户端能力列表（如 ``["ic50", "pdx"]``），
                None 时为空列表
        """
        self.client_id = client_id
        self.endpoint = endpoint
        self.capabilities: List[str] = list(capabilities or [])
        self._registered = False
        self._last_heartbeat: float = 0.0
        self._registry: Optional[ClientRegistry] = None
        logger.debug("FLClient 初始化: id=%s endpoint=%s", client_id, endpoint)

    def register(self, registry: "ClientRegistry") -> Dict[str, Any]:
        """注册到客户端注册中心

        Args:
            registry: 目标注册中心实例

        Returns:
            {
                "status": "registered" | "already_registered",
                "client_id": str,
                "endpoint": str,
                "capabilities": List[str],
            }
        """
        self._registry = registry
        result = registry.register(self)
        self._registered = True
        self._last_heartbeat = time.time()
        logger.info("FLClient 注册成功: %s", self.client_id)
        return {
            "status": result.get("status", "registered"),
            "client_id": self.client_id,
            "endpoint": self.endpoint,
            "capabilities": self.capabilities,
        }

    def heartbeat(self) -> Dict[str, Any]:
        """发送心跳保活

        Returns:
            {"status": "alive" | "not_registered",
             "client_id": str, "timestamp": float}
        """
        if self._registry is None:
            logger.warning(
                "FLClient %s 未注册到任何注册中心，心跳无效",
                self.client_id,
            )
            return {
                "status": "not_registered",
                "client_id": self.client_id,
                "timestamp": time.time(),
            }

        self._last_heartbeat = time.time()
        self._registry.update_heartbeat(self.client_id)
        return {
            "status": "alive",
            "client_id": self.client_id,
            "timestamp": self._last_heartbeat,
        }

    def submit_weights(
        self,
        weights: Dict[str, Any],
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """提交本轮训练的本地权重与指标

        Args:
            weights: 本地模型权重 ``{layer_name: value}``
            metrics: 训练指标（如 ``{"loss": 0.3, "num_samples": 100}``），
                None 时为空 dict

        Returns:
            {
                "status": "submitted" | "not_registered",
                "client_id": str,
                "num_layers": int,
                "metrics": Dict,
            }
        """
        if self._registry is None:
            logger.warning(
                "FLClient %s 未注册，权重提交被拒绝",
                self.client_id,
            )
            return {
                "status": "not_registered",
                "client_id": self.client_id,
                "num_layers": 0,
                "metrics": metrics or {},
            }

        # 在真实模式下这里会通过 gRPC 把权重传到聚合器；
        # 当前为 Mock/Real 双模式降级：仅记录到注册中心，便于后续聚合。
        self._registry._record_weight_submission(
            self.client_id, weights, metrics or {}
        )

        logger.info(
            "FLClient %s 提交权重：%d 层，指标=%s",
            self.client_id,
            len(weights),
            list((metrics or {}).keys()),
        )
        return {
            "status": "submitted",
            "client_id": self.client_id,
            "num_layers": len(weights),
            "metrics": metrics or {},
        }


class ClientRegistry:
    """联邦学习客户端注册中心 — 内存态实现

    维护客户端元数据、心跳时间戳与权重提交记录。
    通过心跳超时机制判定客户端是否活跃。

    Note:
        本类为 P0/P1 阶段的内存态实现，进程重启数据丢失。
        P3 阶段应替换为 Redis/etcd 后端。
    """

    def __init__(self, heartbeat_timeout_sec: Optional[int] = None):
        """初始化注册中心

        Args:
            heartbeat_timeout_sec: 心跳超时秒数；None 时使用默认值 60s
        """
        self._clients: Dict[str, FLClient] = {}
        self._heartbeats: Dict[str, float] = {}
        self._weights: Dict[str, List[Dict[str, Any]]] = {}
        self._heartbeat_timeout = (
            heartbeat_timeout_sec
            if heartbeat_timeout_sec is not None
            else _DEFAULT_HEARTBEAT_TIMEOUT_SEC
        )

    def register(self, client: FLClient) -> Dict[str, Any]:
        """注册客户端

        重复注册将覆盖原记录（按 client_id）。

        Args:
            client: 待注册的客户端实例

        Returns:
            {"status": "registered" | "re_registered",
             "client_id": str, "active_count": int}
        """
        is_re_register = client.client_id in self._clients
        self._clients[client.client_id] = client
        self._heartbeats[client.client_id] = time.time()
        self._weights.setdefault(client.client_id, [])
        status = "re_registered" if is_re_register else "registered"
        logger.info(
            "ClientRegistry: 客户端 %s %s，当前总数=%d",
            client.client_id,
            status,
            len(self._clients),
        )
        return {
            "status": status,
            "client_id": client.client_id,
            "active_count": len(self.get_active_clients()),
        }

    def list_clients(
        self, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """列出客户端

        Args:
            status: 过滤状态，``"active"`` 仅活跃，``"inactive"`` 仅失活，
                None 表示全部

        Returns:
            客户端元数据列表，每项形如
            ``{"client_id", "endpoint", "capabilities", "status",
               "last_heartbeat", "weight_submissions"}``
        """
        now = time.time()
        result: List[Dict[str, Any]] = []
        for cid, client in self._clients.items():
            last_hb = self._heartbeats.get(cid, 0.0)
            is_active = (now - last_hb) < self._heartbeat_timeout
            client_status = "active" if is_active else "inactive"
            if status is not None and client_status != status:
                continue
            result.append(
                {
                    "client_id": cid,
                    "endpoint": client.endpoint,
                    "capabilities": list(client.capabilities),
                    "status": client_status,
                    "last_heartbeat": last_hb,
                    "weight_submissions": len(self._weights.get(cid, [])),
                }
            )
        return result

    def update_heartbeat(self, client_id: str) -> Dict[str, Any]:
        """更新客户端心跳时间戳

        Args:
            client_id: 客户端 ID

        Returns:
            {"status": "updated" | "not_found",
             "client_id": str, "timestamp": float}
        """
        if client_id not in self._clients:
            logger.warning(
                "ClientRegistry: 心跳更新失败，未知客户端 %s",
                client_id,
            )
            return {
                "status": "not_found",
                "client_id": client_id,
                "timestamp": 0.0,
            }
        now = time.time()
        self._heartbeats[client_id] = now
        return {
            "status": "updated",
            "client_id": client_id,
            "timestamp": now,
        }

    def get_active_clients(self) -> List[FLClient]:
        """获取当前所有活跃客户端

        Returns:
            活跃客户端实例列表
        """
        now = time.time()
        active: List[FLClient] = []
        for cid, client in self._clients.items():
            last_hb = self._heartbeats.get(cid, 0.0)
            if (now - last_hb) < self._heartbeat_timeout:
                active.append(client)
        return active

    # -------- 内部辅助方法 --------

    def _record_weight_submission(
        self,
        client_id: str,
        weights: Dict[str, Any],
        metrics: Dict[str, Any],
    ) -> None:
        """记录客户端的权重提交（供聚合器后续拉取）"""
        self._weights.setdefault(client_id, []).append(
            {
                "weights": dict(weights),
                "metrics": dict(metrics),
                "num_samples": int(metrics.get("num_samples", 1) or 1),
                "submitted_at": time.time(),
                "submission_id": uuid.uuid4().hex,
            }
        )

    def collect_weights(self) -> List[Dict[str, Any]]:
        """收集所有活跃客户端最新一次权重提交

        Returns:
            ``[{"client_id", "weights", "num_samples", "metrics"}, ...]``
        """
        active_ids = {c.client_id for c in self.get_active_clients()}
        collected: List[Dict[str, Any]] = []
        for cid, submissions in self._weights.items():
            if cid not in active_ids or not submissions:
                continue
            latest = submissions[-1]
            collected.append(
                {
                    "client_id": cid,
                    "weights": latest["weights"],
                    "num_samples": latest["num_samples"],
                    "metrics": latest["metrics"],
                }
            )
        return collected
