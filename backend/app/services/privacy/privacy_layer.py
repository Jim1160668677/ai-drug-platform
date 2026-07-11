"""隐私保护层 — P3 PySyft 集成框架

设计来源：repowiki/zh/content/安全与合规/隐私计算框架.md
P0/P1：内存态实现（域/数据集/计算请求/审批）。
P3：可替换为 PySyft Domain 进行差分隐私、安全多方计算、隐私域封装。

注：本模块从 services/knowledge/privacy_layer.py 迁移而来，旧路径保留 re-export。
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class PrivacyLayer:
    """隐私保护层 — 隐私域/数据集/计算请求/审批

    P3 阶段：使用 PySyft 进行差分隐私、安全多方计算、隐私域封装。
    P0/P1 阶段：内存态实现，提供完整 API 框架，便于上层集成与测试。
    """

    def __init__(self) -> None:
        self._pysyft_available = self._check_pysyft()
        # 内存态存储
        self._domains: Dict[str, Dict[str, Any]] = {}
        self._datasets: Dict[str, Dict[str, Any]] = {}
        self._requests: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}

    def _check_pysyft(self) -> bool:
        """检查 PySyft 是否可用"""
        try:
            import syft  # noqa: F401
            return True
        except ImportError:
            return False

    # ---------- 隐私域 ----------
    def create_domain(
        self,
        name: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建隐私域（内存态）

        Args:
            name: 隐私域名称
            schema: 数据模式（列名 -> 类型描述）
        Returns:
            {domain_id, name, schema, status}
        """
        if self._pysyft_available and not settings.USE_MOCK:
            try:
                import syft as sy
                domain = sy.Domain(name=name)
                domain_id = str(domain.id)
                logger.info("PySyft 创建隐私域: %s (id=%s)", name, domain_id)
                self._domains[domain_id] = {
                    "name": name,
                    "schema": schema or {},
                    "backend": "pysyft",
                    "ref": domain,
                }
                return {"domain_id": domain_id, "name": name, "schema": schema or {}, "status": "pysyft"}
            except Exception as e:
                logger.warning("PySyft 创建域失败，降级内存态: %s", e)

        domain_id = f"dom_{uuid.uuid4().hex[:12]}"
        self._domains[domain_id] = {
            "name": name,
            "schema": schema or {},
            "backend": "memory",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("内存态创建隐私域: %s (id=%s)", name, domain_id)
        return {"domain_id": domain_id, "name": name, "schema": schema or {}, "status": "memory"}

    def register_dataset(
        self,
        domain_id: str,
        dataset_id: str,
        columns: List[str],
    ) -> Dict[str, Any]:
        """注册数据集到隐私域

        Args:
            domain_id: 隐私域 ID
            dataset_id: 数据集 ID（外部唯一标识）
            columns: 列名列表
        Returns:
            {domain_id, dataset_id, columns, registered}
        Raises:
            KeyError: 域不存在
        """
        if domain_id not in self._domains:
            raise KeyError(f"隐私域不存在: {domain_id}")

        self._datasets[dataset_id] = {
            "domain_id": domain_id,
            "columns": list(columns),
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "注册数据集 %s 到域 %s（%d 列）",
            dataset_id, domain_id, len(columns),
        )
        return {
            "domain_id": domain_id,
            "dataset_id": dataset_id,
            "columns": list(columns),
            "registered": True,
        }

    # ---------- 计算请求 ----------
    def submit_compute(
        self,
        domain_id: str,
        dataset_id: str,
        code: str,
    ) -> Dict[str, Any]:
        """提交隐私计算请求

        Args:
            domain_id: 隐私域 ID
            dataset_id: 数据集 ID
            code: 计算代码（Python 字符串）
        Returns:
            {request_id, status, message}
        Raises:
            KeyError: 域或数据集不存在
        """
        if domain_id not in self._domains:
            raise KeyError(f"隐私域不存在: {domain_id}")
        if dataset_id not in self._datasets:
            raise KeyError(f"数据集未注册: {dataset_id}")

        request_id = f"req_{uuid.uuid4().hex[:12]}"
        self._requests[request_id] = {
            "domain_id": domain_id,
            "dataset_id": dataset_id,
            "code": code,
            "status": "pending_approval",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "approved_by": None,
            "approved_at": None,
        }
        logger.info("提交计算请求 %s（域=%s 数据集=%s）", request_id, domain_id, dataset_id)
        return {
            "request_id": request_id,
            "status": "pending_approval",
            "message": "请求已提交，等待审批",
        }

    def approve(
        self,
        request_id: str,
        approved_by: str,
    ) -> Dict[str, Any]:
        """审批计算请求

        Args:
            request_id: 请求 ID
            approved_by: 审批人
        Returns:
            {request_id, status, result}
        Raises:
            KeyError: 请求不存在
            ValueError: 请求状态不允许审批
        """
        if request_id not in self._requests:
            raise KeyError(f"计算请求不存在: {request_id}")
        req = self._requests[request_id]
        if req["status"] != "pending_approval":
            raise ValueError(f"请求状态不允许审批: {req['status']}")

        req["status"] = "approved"
        req["approved_by"] = approved_by
        req["approved_at"] = datetime.now(timezone.utc).isoformat()

        # 执行计算（内存态降级：返回占位结果）
        result = self._execute_compute(req)
        self._results[request_id] = result
        req["status"] = "completed"

        logger.info("审批通过请求 %s（审批人=%s）", request_id, approved_by)
        return {"request_id": request_id, "status": "completed", "result": result}

    def get_result(self, request_id: str) -> Dict[str, Any]:
        """获取计算结果

        Args:
            request_id: 请求 ID
        Returns:
            {request_id, status, result}
        Raises:
            KeyError: 请求不存在
        """
        if request_id not in self._requests:
            raise KeyError(f"计算请求不存在: {request_id}")
        req = self._requests[request_id]
        result = self._results.get(request_id)
        return {
            "request_id": request_id,
            "status": req["status"],
            "result": result,
        }

    # ---------- 兼容旧 API ----------
    async def encrypt_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """隐私域封装 — 脱敏处理（兼容旧 API）

        Args:
            data: 原始数据（可能含患者标识）
        Returns:
            {encrypted, data, method}
        """
        if not self._pysyft_available or settings.USE_MOCK:
            sanitized = self._simple_anonymize(data)
            return {
                "encrypted": False,
                "data": sanitized,
                "method": "simple_anonymization",
                "note": "P3 启用 PySyft 后将支持差分隐私和安全计算",
            }

        try:
            import syft as sy
            domain = sy.Domain(name="precision_drug")
            dataset = sy.Dataset(data=data)
            domain.load_dataset(dataset)
            return {
                "encrypted": True,
                "data": {"domain_id": str(domain.id), "protected": True},
                "method": "pysyft_domain",
            }
        except Exception as e:
            logger.warning("PySyft 封装失败: %s", e)
            return {
                "encrypted": False,
                "data": self._simple_anonymize(data),
                "method": "fallback_anonymization",
                "error": str(e),
            }

    async def federated_query(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """联邦查询 — 跨中心隐私保护查询（兼容旧 API）

        Args:
            query: {targets, centers, aggregation}
        Returns:
            {status, participating_centers, privacy_budget}
        """
        if not self._pysyft_available or settings.USE_MOCK:
            return {
                "status": "framework_only",
                "message": "联邦查询需 P3 启用 PySyft",
                "query": query,
                "privacy_budget": None,
            }
        try:
            return {
                "status": "framework_ready",
                "message": "PySyft 可用，联邦查询框架已加载",
                "query": query,
                "privacy_budget": {"epsilon": 1.0, "delta": 1e-5},
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ---------- 内部方法 ----------
    def _execute_compute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """执行计算（内存态降级实现）

        P0/P1：不实际执行用户代码，返回占位结果。
        P3：通过 PySyft 沙箱执行。
        """
        dataset_id = request["dataset_id"]
        dataset = self._datasets.get(dataset_id, {})
        return {
            "executed": False,
            "method": "memory_stub",
            "dataset_id": dataset_id,
            "columns": dataset.get("columns", []),
            "message": "P0 内存态：未实际执行代码，返回元数据占位",
            "code_preview": (request["code"] or "")[:200],
        }

    def _simple_anonymize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """简单脱敏 — 去除直接标识符"""
        if not isinstance(data, dict):
            return data
        sensitive_keys = {"name", "email", "phone", "ssn", "patient_id", "mrn"}
        sanitized: Dict[str, Any] = {}
        for k, v in data.items():
            if k.lower() in sensitive_keys:
                sanitized[k] = f"[REDACTED_{k}]"
            elif isinstance(v, dict):
                sanitized[k] = self._simple_anonymize(v)
            else:
                sanitized[k] = v
        return sanitized


__all__ = ["PrivacyLayer"]
