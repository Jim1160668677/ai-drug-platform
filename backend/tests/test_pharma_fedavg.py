"""PharmaFedAvg 与 FLClient/ClientRegistry 单元测试

覆盖：
- ``app.services.optimizer.pharma_fedavg.PharmaFedAvg`` —— 拜占庭容错的 FedAvg 聚合器
- ``app.services.optimizer.fl_client.FLClient`` —— 联邦学习客户端
- ``app.services.optimizer.fl_client.ClientRegistry`` —— 内存态客户端注册中心
"""
import time
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services.optimizer.pharma_fedavg import PharmaFedAvg
from app.services.optimizer.fl_client import (
    FLClient,
    ClientRegistry,
    _DEFAULT_HEARTBEAT_TIMEOUT_SEC,
)


# =====================================================================
# PharmaFedAvg
# =====================================================================


class TestPharmaFedAvgInit:
    """PharmaFedAvg 初始化测试"""

    def test_init_uses_settings_default_when_none(self):
        """mad_threshold=None 时应从 settings.FL_MAD_THRESHOLD 读取"""
        agg = PharmaFedAvg()
        assert agg._mad_threshold == settings.FL_MAD_THRESHOLD

    def test_init_uses_custom_threshold(self):
        """显式传入 mad_threshold 时应覆盖默认值"""
        agg = PharmaFedAvg(mad_threshold=5.5)
        assert agg._mad_threshold == 5.5

    def test_init_threshold_zero_is_respected(self):
        """显式传入 0 不应被视为 None（边界条件）"""
        agg = PharmaFedAvg(mad_threshold=0.0)
        assert agg._mad_threshold == 0.0


class TestPharmaFedAvgAggregate:
    """PharmaFedAvg.aggregate 主流程测试"""

    def test_aggregate_empty_client_list_returns_no_clients(self):
        """空客户端列表应返回 status=no_clients"""
        agg = PharmaFedAvg()
        result = agg.aggregate(client_weights=[])

        assert result["status"] == "no_clients"
        assert result["aggregated_weights"] == {}
        assert result["total_samples"] == 0
        assert result["num_clients"] == 0
        assert result["num_byzantine_filtered"] == 0
        assert result["strategy"] == "FedAvg+MAD"

    def test_aggregate_simple_two_clients_weighted(self):
        """两个客户端的正常加权平均（不触发剔除）"""
        agg = PharmaFedAvg()
        result = agg.aggregate(
            client_weights=[
                {"weights": {"layer1": 1.0}, "num_samples": 100},
                {"weights": {"layer1": 3.0}, "num_samples": 300},
            ]
        )
        # (1*100 + 3*300) / 400 = 2.5
        assert result["status"] == "aggregated"
        assert result["num_clients"] == 2
        assert result["num_byzantine_filtered"] == 0
        assert result["total_samples"] == 400
        assert abs(result["aggregated_weights"]["layer1"] - 2.5) < 1e-6
        assert result["strategy"] == "FedAvg+MAD"
        assert result["mad_threshold"] == settings.FL_MAD_THRESHOLD

    def test_aggregate_with_explicit_sample_counts(self):
        """显式传入 sample_counts 覆盖客户端内嵌 num_samples"""
        agg = PharmaFedAvg()
        result = agg.aggregate(
            client_weights=[
                {"weights": {"l1": 0.0}, "num_samples": 999},
                {"weights": {"l1": 10.0}, "num_samples": 999},
            ],
            sample_counts=[1, 1],  # 等权重 → 平均 = 5.0
        )
        assert abs(result["aggregated_weights"]["l1"] - 5.0) < 1e-6
        assert result["total_samples"] == 2

    def test_aggregate_with_direct_dict_format(self):
        """支持直接以 {layer: value} dict 作为客户端项（无 weights 键）"""
        agg = PharmaFedAvg()
        result = agg.aggregate(
            client_weights=[
                {"l1": 2.0, "l2": 4.0},
                {"l1": 4.0, "l2": 8.0},
            ],
            sample_counts=[10, 10],
        )
        # 等权重平均
        assert abs(result["aggregated_weights"]["l1"] - 3.0) < 1e-6
        assert abs(result["aggregated_weights"]["l2"] - 6.0) < 1e-6

    def test_aggregate_with_override_mad_threshold(self):
        """aggregate() 调用时的 mad_threshold 优先级高于初始化值"""
        agg = PharmaFedAvg(mad_threshold=99.0)
        result = agg.aggregate(
            client_weights=[
                {"weights": {"l1": 0.0}, "num_samples": 1},
                {"weights": {"l1": 1.0}, "num_samples": 1},
            ],
            mad_threshold=3.0,
        )
        assert result["mad_threshold"] == 3.0
        assert result["status"] == "aggregated"

    def test_aggregate_all_filtered_returns_all_filtered_status(self):
        """构造可被全部剔除的场景，验证 status=all_filtered"""
        # 使用极小的 MAD 阈值 + 5 个客户端其中 4 个完全相同、1 个偏离
        # 但要让所有客户端都被剔除需要每层都判定为拜占庭 ——
        # 这里通过 mock _filter_byzantine 返回空列表来验证 status 分支
        agg = PharmaFedAvg()
        with patch.object(
            agg, "_filter_byzantine", return_value=([], 3)
        ):
            result = agg.aggregate(
                client_weights=[
                    {"weights": {"l1": 1.0}, "num_samples": 1},
                    {"weights": {"l1": 2.0}, "num_samples": 1},
                    {"weights": {"l1": 3.0}, "num_samples": 1},
                ]
            )
        assert result["status"] == "all_filtered"
        assert result["aggregated_weights"] == {}
        assert result["total_samples"] == 0
        assert result["num_clients"] == 0
        assert result["num_byzantine_filtered"] == 3
        assert result["mad_threshold"] == settings.FL_MAD_THRESHOLD

    def test_aggregate_filters_byzantine_client(self):
        """3+ 客户端时，明显偏离中位数的客户端应被剔除"""
        agg = PharmaFedAvg(mad_threshold=2.0)
        # 5 个客户端，4 个值接近 1.0，1 个偏离到 100.0
        result = agg.aggregate(
            client_weights=[
                {"weights": {"l1": 1.0}, "num_samples": 10},
                {"weights": {"l1": 1.1}, "num_samples": 10},
                {"weights": {"l1": 0.9}, "num_samples": 10},
                {"weights": {"l1": 1.0}, "num_samples": 10},
                {"weights": {"l1": 100.0}, "num_samples": 10},
            ]
        )
        assert result["num_byzantine_filtered"] == 1
        assert result["num_clients"] == 4
        assert result["status"] == "aggregated"
        # 剔除 100.0 后，剩余 4 个值平均接近 1.0
        assert abs(result["aggregated_weights"]["l1"] - 1.0) < 0.05

    def test_aggregate_two_clients_skips_filtering(self):
        """<=2 客户端时应跳过拜占庭剔除，全部保留"""
        agg = PharmaFedAvg(mad_threshold=0.001)
        result = agg.aggregate(
            client_weights=[
                {"weights": {"l1": 0.0}, "num_samples": 1},
                {"weights": {"l1": 1000.0}, "num_samples": 1},
            ]
        )
        assert result["num_byzantine_filtered"] == 0
        assert result["num_clients"] == 2
        # 等权重平均 = 500
        assert abs(result["aggregated_weights"]["l1"] - 500.0) < 1e-6

    def test_aggregate_default_num_samples_when_missing(self):
        """当 num_samples 与 sample_counts 均未提供时默认为 1"""
        agg = PharmaFedAvg()
        result = agg.aggregate(
            client_weights=[
                {"weights": {"l1": 2.0}},
                {"weights": {"l1": 4.0}},
            ]
        )
        # 等权重 → 平均 = 3.0；total_samples = 1+1=2
        assert abs(result["aggregated_weights"]["l1"] - 3.0) < 1e-6
        assert result["total_samples"] == 2

    def test_aggregate_returns_strategy_field(self):
        """聚合结果应始终包含 strategy 字段"""
        agg = PharmaFedAvg()
        result = agg.aggregate(client_weights=[])
        assert result["strategy"] == "FedAvg+MAD"


class TestPharmaFedAvgComputeMad:
    """PharmaFedAvg._compute_mad 测试"""

    def test_compute_mad_empty_list(self):
        agg = PharmaFedAvg()
        result = agg._compute_mad([])
        assert result == {"median": 0.0, "mad": 0.0, "scaled_mad": 0.0}

    def test_compute_mad_single_value(self):
        agg = PharmaFedAvg()
        result = agg._compute_mad([5.5])
        assert result["median"] == 5.5
        assert result["mad"] == 0.0
        assert result["scaled_mad"] == 0.0

    def test_compute_mad_two_values(self):
        agg = PharmaFedAvg()
        result = agg._compute_mad([1.0, 3.0])
        # median = 2.0, abs devs = [1, 1], mad = 1.0, scaled = 1.4826
        assert result["median"] == 2.0
        assert result["mad"] == 1.0
        assert abs(result["scaled_mad"] - 1.4826) < 1e-6

    def test_compute_mad_multiple_values(self):
        agg = PharmaFedAvg()
        # 1, 2, 3, 4, 100 —— median = 3, abs devs = [2,1,0,1,97]
        # sorted abs devs = [0,1,1,2,97], mad = median = 1.0
        result = agg._compute_mad([1.0, 2.0, 3.0, 4.0, 100.0])
        assert result["median"] == 3.0
        assert result["mad"] == 1.0
        assert abs(result["scaled_mad"] - 1.0 * 1.4826) < 1e-6

    def test_compute_mad_identical_values_zero_scaled(self):
        """所有值相同时 scaled_mad 应为 0（用于跳过该层判断）"""
        agg = PharmaFedAvg()
        result = agg._compute_mad([7.0, 7.0, 7.0, 7.0])
        assert result["median"] == 7.0
        assert result["mad"] == 0.0
        assert result["scaled_mad"] == 0.0

    def test_compute_mad_returns_floats(self):
        """返回值应为 float 类型（即使输入是 int）"""
        agg = PharmaFedAvg()
        result = agg._compute_mad([1, 2, 3])
        assert isinstance(result["median"], float)
        assert isinstance(result["mad"], float)
        assert isinstance(result["scaled_mad"], float)


class TestPharmaFedAvgFilterByzantine:
    """PharmaFedAvg._filter_byzantine 测试"""

    def test_filter_no_clients(self):
        agg = PharmaFedAvg()
        filtered, num = agg._filter_byzantine([], 3.0)
        assert filtered == []
        assert num == 0

    def test_filter_single_client_kept(self):
        agg = PharmaFedAvg()
        clients = [{"weights": {"l1": 1.0}, "num_samples": 1}]
        filtered, num = agg._filter_byzantine(clients, 3.0)
        assert filtered == clients
        assert num == 0

    def test_filter_two_clients_kept(self):
        """<=2 客户端时全部保留"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": 0.0}, "num_samples": 1},
            {"weights": {"l1": 1e6}, "num_samples": 1},
        ]
        filtered, num = agg._filter_byzantine(clients, 0.001)
        assert len(filtered) == 2
        assert num == 0

    def test_filter_identical_values_skips_layer(self):
        """所有客户端同层值相同时该层应跳过判断（scaled_mad=0）"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": 5.0}, "num_samples": 1},
            {"weights": {"l1": 5.0}, "num_samples": 1},
            {"weights": {"l1": 5.0}, "num_samples": 1},
        ]
        filtered, num = agg._filter_byzantine(clients, 0.001)
        assert len(filtered) == 3
        assert num == 0

    def test_filter_byzantine_detected(self):
        """明显偏离的客户端应被剔除

        注意：需至少 3 个不同值才能让 MAD 非零；4 个相同 + 1 个偏离时
        MAD=0 会被跳过。这里用 [1.0, 1.1, 0.9, 1.0, 100.0]：
        median=1.0, abs_devs=[0,0.1,0.1,0,99], mad=0.1, scaled=0.148,
        cutoff=3*0.148=0.44 → 仅 100.0 被剔除。
        """
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": 1.0}, "num_samples": 1},
            {"weights": {"l1": 1.1}, "num_samples": 1},
            {"weights": {"l1": 0.9}, "num_samples": 1},
            {"weights": {"l1": 1.0}, "num_samples": 1},
            {"weights": {"l1": 100.0}, "num_samples": 1},
        ]
        filtered, num = agg._filter_byzantine(clients, 3.0)
        assert num == 1
        assert len(filtered) == 4
        # 被剔除的是值 100.0 的客户端
        for c in filtered:
            assert c["weights"]["l1"] != 100.0

    def test_filter_handles_none_weights(self):
        """weights 字段为 None 时应被替换为 {}，不抛异常"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": None, "num_samples": 1},
            {"weights": {"l1": 1.0}, "num_samples": 1},
            {"weights": {"l1": 1.0}, "num_samples": 1},
        ]
        filtered, num = agg._filter_byzantine(clients, 3.0)
        assert len(filtered) == 3
        assert num == 0

    def test_filter_handles_non_numeric_weights(self):
        """非数值类型权重应被当作 0.0，不抛异常"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": "invalid"}, "num_samples": 1},
            {"weights": {"l1": 1.0}, "num_samples": 1},
            {"weights": {"l1": 1.0}, "num_samples": 1},
        ]
        filtered, num = agg._filter_byzantine(clients, 3.0)
        # 应正常完成，不抛异常
        assert len(filtered) <= 3

    def test_filter_handles_none_layer_value(self):
        """权重层值为 None 时应被当作 0.0"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": None}, "num_samples": 1},
            {"weights": {"l1": 1.0}, "num_samples": 1},
            {"weights": {"l1": 1.0}, "num_samples": 1},
        ]
        # 不应抛异常
        filtered, num = agg._filter_byzantine(clients, 3.0)
        assert isinstance(num, int)

    def test_filter_multiple_layers_independent(self):
        """多层权重独立判定拜占庭

        使用 [1.0, 1.1, 0.9, 1.0, 999.0] 确保 MAD 非零。
        """
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": 1.0, "l2": 5.0}, "num_samples": 1},
            {"weights": {"l1": 1.1, "l2": 5.1}, "num_samples": 1},
            {"weights": {"l1": 0.9, "l2": 4.9}, "num_samples": 1},
            {"weights": {"l1": 1.0, "l2": 5.0}, "num_samples": 1},
            {"weights": {"l1": 999.0, "l2": 999.0}, "num_samples": 1},
        ]
        filtered, num = agg._filter_byzantine(clients, 3.0)
        assert num == 1

    def test_filter_returns_copy_of_list(self):
        """返回的 filtered 应是新列表，不应修改原列表"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": 1.0}, "num_samples": 1},
            {"weights": {"l1": 1.0}, "num_samples": 1},
            {"weights": {"l1": 1.0}, "num_samples": 1},
        ]
        filtered, _ = agg._filter_byzantine(clients, 3.0)
        assert filtered is not clients


class TestPharmaFedAvgNormalizeInputs:
    """PharmaFedAvg._normalize_inputs 测试"""

    def test_normalize_with_weights_key(self):
        agg = PharmaFedAvg()
        result = agg._normalize_inputs(
            [{"weights": {"l1": 1.0}, "num_samples": 50}], None
        )
        assert result == [{"weights": {"l1": 1.0}, "num_samples": 50}]

    def test_normalize_direct_dict_format(self):
        agg = PharmaFedAvg()
        result = agg._normalize_inputs([{"l1": 1.0, "l2": 2.0}], None)
        assert result == [{"weights": {"l1": 1.0, "l2": 2.0}, "num_samples": 1}]

    def test_normalize_sample_counts_override(self):
        agg = PharmaFedAvg()
        result = agg._normalize_inputs(
            [{"weights": {"l1": 1.0}, "num_samples": 999}],
            sample_counts=[42],
        )
        assert result[0]["num_samples"] == 42

    def test_normalize_sample_counts_shorter_than_clients(self):
        """sample_counts 短于 client_weights 时，缺位用 num_samples 或默认 1"""
        agg = PharmaFedAvg()
        result = agg._normalize_inputs(
            [
                {"weights": {"l1": 1.0}, "num_samples": 7},
                {"weights": {"l1": 2.0}, "num_samples": 8},
            ],
            sample_counts=[100],  # 仅 1 个
        )
        assert result[0]["num_samples"] == 100
        # 第 2 个客户端应回退到 num_samples=8
        assert result[1]["num_samples"] == 8

    def test_normalize_default_num_samples_is_one(self):
        agg = PharmaFedAvg()
        result = agg._normalize_inputs([{"weights": {"l1": 1.0}}], None)
        assert result[0]["num_samples"] == 1

    def test_normalize_negative_num_samples_becomes_zero(self):
        agg = PharmaFedAvg()
        result = agg._normalize_inputs(
            [{"weights": {"l1": 1.0}, "num_samples": -5}], None
        )
        assert result[0]["num_samples"] == 0

    def test_normalize_non_int_num_samples_falls_back_to_one(self):
        agg = PharmaFedAvg()
        result = agg._normalize_inputs(
            [{"weights": {"l1": 1.0}, "num_samples": "invalid"}], None
        )
        assert result[0]["num_samples"] == 1

    def test_normalize_none_num_samples_falls_back_to_one(self):
        agg = PharmaFedAvg()
        result = agg._normalize_inputs(
            [{"weights": {"l1": 1.0}, "num_samples": None}], None
        )
        assert result[0]["num_samples"] == 1

    def test_normalize_weights_dict_is_copied(self):
        """weights 应被 dict() 复制，避免引用原对象"""
        agg = PharmaFedAvg()
        original = {"l1": 1.0}
        result = agg._normalize_inputs(
            [{"weights": original, "num_samples": 1}], None
        )
        assert result[0]["weights"] == original
        assert result[0]["weights"] is not original

    def test_normalize_empty_weights_key(self):
        """weights 为空 dict 时应保留为空 dict"""
        agg = PharmaFedAvg()
        result = agg._normalize_inputs([{"weights": {}, "num_samples": 1}], None)
        assert result[0]["weights"] == {}

    def test_normalize_none_weights_becomes_empty_dict(self):
        """weights 字段为 None 时应被替换为 {}"""
        agg = PharmaFedAvg()
        result = agg._normalize_inputs(
            [{"weights": None, "num_samples": 1}], None
        )
        assert result[0]["weights"] == {}


class TestPharmaFedAvgWeightedAverage:
    """PharmaFedAvg._weighted_average 测试"""

    def test_weighted_average_basic(self):
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": 1.0}, "num_samples": 10},
            {"weights": {"l1": 3.0}, "num_samples": 30},
        ]
        result = agg._weighted_average(clients)
        # (1*10 + 3*30) / 40 = 2.5
        assert abs(result["weights"]["l1"] - 2.5) < 1e-6
        assert result["_total_samples"] == 40

    def test_weighted_average_all_zero_samples_uses_equal_weight(self):
        """全部样本量为 0 时退化为简单平均"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": 0.0}, "num_samples": 0},
            {"weights": {"l1": 10.0}, "num_samples": 0},
        ]
        result = agg._weighted_average(clients)
        assert abs(result["weights"]["l1"] - 5.0) < 1e-6
        # total_samples 在退化模式下等于客户端数
        assert result["_total_samples"] == 2

    def test_weighted_average_multiple_layers(self):
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": 2.0, "l2": 4.0}, "num_samples": 5},
            {"weights": {"l1": 4.0, "l2": 8.0}, "num_samples": 5},
        ]
        result = agg._weighted_average(clients)
        assert abs(result["weights"]["l1"] - 3.0) < 1e-6
        assert abs(result["weights"]["l2"] - 6.0) < 1e-6

    def test_weighted_average_missing_layer_in_some_clients(self):
        """某些客户端缺失某层时应被当作 0.0"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": 2.0}, "num_samples": 5},
            {"weights": {"l1": 4.0, "l2": 8.0}, "num_samples": 5},
        ]
        result = agg._weighted_average(clients)
        # l1 平均 = (2*0.5 + 4*0.5) = 3.0
        assert abs(result["weights"]["l1"] - 3.0) < 1e-6
        # l2 平均 = (0*0.5 + 8*0.5) = 4.0
        assert abs(result["weights"]["l2"] - 4.0) < 1e-6

    def test_weighted_average_none_layer_value(self):
        """权重层值为 None 时应被当作 0.0"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": None}, "num_samples": 5},
            {"weights": {"l1": 4.0}, "num_samples": 5},
        ]
        result = agg._weighted_average(clients)
        assert abs(result["weights"]["l1"] - 2.0) < 1e-6

    def test_weighted_average_non_numeric_value(self):
        """非数值类型权重应被当作 0.0，不抛异常"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"l1": "bad"}, "num_samples": 5},
            {"weights": {"l1": 4.0}, "num_samples": 5},
        ]
        result = agg._weighted_average(clients)
        assert abs(result["weights"]["l1"] - 2.0) < 1e-6

    def test_weighted_average_none_weights_field(self):
        """weights 字段为 None 时应被当作 {}，不抛异常"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": None, "num_samples": 5},
            {"weights": {"l1": 4.0}, "num_samples": 5},
        ]
        result = agg._weighted_average(clients)
        # 仅 l1 层存在，第 1 个客户端该层视为 0.0
        assert abs(result["weights"]["l1"] - 2.0) < 1e-6

    def test_weighted_average_single_client(self):
        agg = PharmaFedAvg()
        clients = [{"weights": {"l1": 7.5}, "num_samples": 100}]
        result = agg._weighted_average(clients)
        assert abs(result["weights"]["l1"] - 7.5) < 1e-6
        assert result["_total_samples"] == 100

    def test_weighted_average_preserves_layer_order(self):
        """层在结果中的顺序应与首次出现顺序一致"""
        agg = PharmaFedAvg()
        clients = [
            {"weights": {"a": 1.0, "b": 2.0}, "num_samples": 1},
            {"weights": {"c": 3.0}, "num_samples": 1},
        ]
        result = agg._weighted_average(clients)
        assert list(result["weights"].keys()) == ["a", "b", "c"]


# =====================================================================
# FLClient
# =====================================================================


class TestFLClientInit:
    """FLClient 初始化测试"""

    def test_init_with_capabilities(self):
        client = FLClient(
            client_id="hospital-001",
            endpoint="grpc://hospital-001:8080",
            capabilities=["ic50", "scrna"],
        )
        assert client.client_id == "hospital-001"
        assert client.endpoint == "grpc://hospital-001:8080"
        assert client.capabilities == ["ic50", "scrna"]
        assert client._registered is False
        assert client._last_heartbeat == 0.0
        assert client._registry is None

    def test_init_with_none_capabilities(self):
        client = FLClient(
            client_id="c1", endpoint="grpc://c1:8080", capabilities=None
        )
        assert client.capabilities == []

    def test_init_with_no_capabilities_arg(self):
        client = FLClient(client_id="c1", endpoint="grpc://c1:8080")
        assert client.capabilities == []

    def test_init_capabilities_is_copied(self):
        """capabilities 应被复制，避免外部修改影响客户端"""
        caps = ["ic50"]
        client = FLClient(client_id="c1", endpoint="grpc://c1:8080", capabilities=caps)
        caps.append("pdx")
        assert client.capabilities == ["ic50"]


class TestFLClientRegister:
    """FLClient.register 测试"""

    def test_register_first_time(self):
        registry = ClientRegistry()
        client = FLClient(
            client_id="h1",
            endpoint="grpc://h1:8080",
            capabilities=["ic50"],
        )
        result = client.register(registry)

        assert result["status"] == "registered"
        assert result["client_id"] == "h1"
        assert result["endpoint"] == "grpc://h1:8080"
        assert result["capabilities"] == ["ic50"]
        assert client._registered is True
        assert client._registry is registry
        assert client._last_heartbeat > 0.0

    def test_register_re_register_returns_status_from_registry(self):
        """重复注册时应返回 registry.register 给的 status（re_registered）"""
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        client.register(registry)
        # 第二次注册同一 client_id
        result = client.register(registry)
        assert result["status"] == "re_registered"


class TestFLClientHeartbeat:
    """FLClient.heartbeat 测试"""

    def test_heartbeat_not_registered(self):
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        result = client.heartbeat()
        assert result["status"] == "not_registered"
        assert result["client_id"] == "h1"
        assert "timestamp" in result
        assert isinstance(result["timestamp"], float)

    def test_heartbeat_registered_returns_alive(self):
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        client.register(registry)

        result = client.heartbeat()
        assert result["status"] == "alive"
        assert result["client_id"] == "h1"
        assert result["timestamp"] > 0.0
        assert result["timestamp"] == client._last_heartbeat

    def test_heartbeat_updates_registry(self):
        """heartbeat 应同时更新 registry 中的心跳时间戳"""
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        client.register(registry)
        old_hb = registry._heartbeats["h1"]

        time.sleep(0.01)
        client.heartbeat()
        new_hb = registry._heartbeats["h1"]
        assert new_hb > old_hb


class TestFLClientSubmitWeights:
    """FLClient.submit_weights 测试"""

    def test_submit_weights_not_registered(self):
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        result = client.submit_weights(weights={"l1": 0.5}, metrics={"loss": 0.1})

        assert result["status"] == "not_registered"
        assert result["client_id"] == "h1"
        assert result["num_layers"] == 0
        assert result["metrics"] == {"loss": 0.1}

    def test_submit_weights_not_registered_no_metrics(self):
        """未注册且 metrics=None 时返回 metrics={}"""
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        result = client.submit_weights(weights={"l1": 0.5}, metrics=None)
        assert result["metrics"] == {}

    def test_submit_weights_registered(self):
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        client.register(registry)

        result = client.submit_weights(
            weights={"l1": 0.5, "l2": 0.3},
            metrics={"loss": 0.1, "num_samples": 100},
        )
        assert result["status"] == "submitted"
        assert result["client_id"] == "h1"
        assert result["num_layers"] == 2
        assert result["metrics"] == {"loss": 0.1, "num_samples": 100}

    def test_submit_weights_registered_no_metrics(self):
        """已注册但 metrics=None 时 metrics 应为空 dict"""
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        client.register(registry)

        result = client.submit_weights(weights={"l1": 0.5}, metrics=None)
        assert result["status"] == "submitted"
        assert result["metrics"] == {}
        assert result["num_layers"] == 1

    def test_submit_weights_records_to_registry(self):
        """权重提交应调用 registry._record_weight_submission"""
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        client.register(registry)

        client.submit_weights(
            weights={"l1": 0.5}, metrics={"num_samples": 42}
        )
        submissions = registry._weights["h1"]
        assert len(submissions) == 1
        assert submissions[0]["weights"] == {"l1": 0.5}
        assert submissions[0]["num_samples"] == 42

    def test_submit_weights_empty_weights(self):
        """空 weights dict 应返回 num_layers=0"""
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        client.register(registry)

        result = client.submit_weights(weights={}, metrics=None)
        assert result["status"] == "submitted"
        assert result["num_layers"] == 0


# =====================================================================
# ClientRegistry
# =====================================================================


class TestClientRegistryInit:
    """ClientRegistry 初始化测试"""

    def test_init_default_timeout(self):
        registry = ClientRegistry()
        assert registry._heartbeat_timeout == _DEFAULT_HEARTBEAT_TIMEOUT_SEC
        assert registry._clients == {}
        assert registry._heartbeats == {}
        assert registry._weights == {}

    def test_init_custom_timeout(self):
        registry = ClientRegistry(heartbeat_timeout_sec=120)
        assert registry._heartbeat_timeout == 120

    def test_init_timeout_zero_is_respected(self):
        """显式传入 0 不应被视为 None"""
        registry = ClientRegistry(heartbeat_timeout_sec=0)
        assert registry._heartbeat_timeout == 0


class TestClientRegistryRegister:
    """ClientRegistry.register 测试"""

    def test_register_new_client(self):
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        result = registry.register(client)

        assert result["status"] == "registered"
        assert result["client_id"] == "h1"
        assert result["active_count"] == 1
        assert "h1" in registry._clients
        assert "h1" in registry._heartbeats
        assert registry._heartbeats["h1"] > 0.0
        assert registry._weights["h1"] == []

    def test_register_re_register_same_id(self):
        registry = ClientRegistry()
        client1 = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(client1)

        client2 = FLClient(client_id="h1", endpoint="grpc://h1:9090")
        result = registry.register(client2)

        assert result["status"] == "re_registered"
        assert result["active_count"] == 1
        # 客户端实例被覆盖
        assert registry._clients["h1"] is client2
        assert registry._clients["h1"].endpoint == "grpc://h1:9090"

    def test_register_multiple_clients(self):
        registry = ClientRegistry()
        c1 = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        c2 = FLClient(client_id="h2", endpoint="grpc://h2:8080")
        r1 = registry.register(c1)
        r2 = registry.register(c2)

        assert r1["active_count"] == 1
        assert r2["active_count"] == 2
        assert len(registry._clients) == 2

    def test_register_weights_list_preserved_on_re_register(self):
        """重复注册时已存在的权重提交记录应被保留（setdefault）"""
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(client)
        registry._record_weight_submission("h1", {"l1": 1.0}, {})

        # 重新注册
        client2 = FLClient(client_id="h1", endpoint="grpc://h1:9090")
        registry.register(client2)
        assert len(registry._weights["h1"]) == 1


class TestClientRegistryListClients:
    """ClientRegistry.list_clients 测试"""

    def test_list_clients_empty_registry(self):
        registry = ClientRegistry()
        assert registry.list_clients() == []

    def test_list_clients_no_filter(self):
        registry = ClientRegistry()
        c1 = FLClient(client_id="h1", endpoint="grpc://h1:8080", capabilities=["ic50"])
        c2 = FLClient(client_id="h2", endpoint="grpc://h2:8080")
        registry.register(c1)
        registry.register(c2)

        result = registry.list_clients()
        assert len(result) == 2
        ids = {r["client_id"] for r in result}
        assert ids == {"h1", "h2"}
        for r in result:
            assert r["status"] == "active"
            assert "endpoint" in r
            assert "capabilities" in r
            assert "last_heartbeat" in r
            assert r["weight_submissions"] == 0

    def test_list_clients_filter_active(self):
        registry = ClientRegistry(heartbeat_timeout_sec=0)
        c1 = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(c1)

        # timeout=0 时所有客户端立即失活
        result = registry.list_clients(status="active")
        assert result == []

    def test_list_clients_filter_inactive(self):
        registry = ClientRegistry(heartbeat_timeout_sec=0)
        c1 = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(c1)

        result = registry.list_clients(status="inactive")
        assert len(result) == 1
        assert result[0]["status"] == "inactive"

    def test_list_clients_capabilities_copied(self):
        """返回的 capabilities 应为副本"""
        registry = ClientRegistry()
        client = FLClient(
            client_id="h1", endpoint="grpc://h1:8080", capabilities=["ic50"]
        )
        registry.register(client)

        result = registry.list_clients()
        assert result[0]["capabilities"] == ["ic50"]
        assert result[0]["capabilities"] is not client.capabilities

    def test_list_clients_includes_weight_submissions_count(self):
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(client)
        registry._record_weight_submission("h1", {"l1": 1.0}, {})
        registry._record_weight_submission("h1", {"l1": 2.0}, {})

        result = registry.list_clients()
        assert result[0]["weight_submissions"] == 2


class TestClientRegistryUpdateHeartbeat:
    """ClientRegistry.update_heartbeat 测试"""

    def test_update_heartbeat_unknown_client(self):
        registry = ClientRegistry()
        result = registry.update_heartbeat("unknown-id")

        assert result["status"] == "not_found"
        assert result["client_id"] == "unknown-id"
        assert result["timestamp"] == 0.0

    def test_update_heartbeat_known_client(self):
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(client)
        old_hb = registry._heartbeats["h1"]

        time.sleep(0.01)
        result = registry.update_heartbeat("h1")

        assert result["status"] == "updated"
        assert result["client_id"] == "h1"
        assert result["timestamp"] > old_hb
        assert registry._heartbeats["h1"] == result["timestamp"]


class TestClientRegistryGetActiveClients:
    """ClientRegistry.get_active_clients 测试"""

    def test_get_active_clients_empty(self):
        registry = ClientRegistry()
        assert registry.get_active_clients() == []

    def test_get_active_clients_all_active(self):
        registry = ClientRegistry()
        c1 = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        c2 = FLClient(client_id="h2", endpoint="grpc://h2:8080")
        registry.register(c1)
        registry.register(c2)

        active = registry.get_active_clients()
        assert len(active) == 2
        assert {c.client_id for c in active} == {"h1", "h2"}

    def test_get_active_clients_excludes_expired(self):
        """超时的客户端应被排除"""
        registry = ClientRegistry(heartbeat_timeout_sec=0)
        c1 = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(c1)

        active = registry.get_active_clients()
        assert active == []

    def test_get_active_clients_partial_expiry(self):
        """部分客户端失活时只返回活跃的"""
        registry = ClientRegistry(heartbeat_timeout_sec=60)
        c1 = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        c2 = FLClient(client_id="h2", endpoint="grpc://h2:8080")
        registry.register(c1)
        registry.register(c2)

        # 让 h1 失活
        registry._heartbeats["h1"] = time.time() - 120

        active = registry.get_active_clients()
        assert len(active) == 1
        assert active[0].client_id == "h2"


class TestClientRegistryRecordWeightSubmission:
    """ClientRegistry._record_weight_submission 测试"""

    def test_record_submission_appends_to_list(self):
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(client)

        registry._record_weight_submission("h1", {"l1": 1.0}, {"loss": 0.5})
        registry._record_weight_submission("h1", {"l1": 2.0}, {"loss": 0.3})

        submissions = registry._weights["h1"]
        assert len(submissions) == 2
        assert submissions[0]["weights"] == {"l1": 1.0}
        assert submissions[1]["weights"] == {"l1": 2.0}
        assert submissions[0]["metrics"] == {"loss": 0.5}
        assert submissions[1]["metrics"] == {"loss": 0.3}

    def test_record_submission_creates_list_if_missing(self):
        """对未注册的 client_id 也能记录（setdefault 行为）"""
        registry = ClientRegistry()
        registry._record_weight_submission("ghost", {"l1": 1.0}, {})
        assert "ghost" in registry._weights
        assert len(registry._weights["ghost"]) == 1

    def test_record_submission_includes_metadata(self):
        registry = ClientRegistry()
        registry._record_weight_submission("h1", {"l1": 1.0}, {"num_samples": 50})

        sub = registry._weights["h1"][0]
        assert sub["num_samples"] == 50
        assert sub["submitted_at"] > 0.0
        assert isinstance(sub["submission_id"], str)
        assert len(sub["submission_id"]) > 0

    def test_record_submission_default_num_samples(self):
        """metrics 中无 num_samples 时默认为 1"""
        registry = ClientRegistry()
        registry._record_weight_submission("h1", {"l1": 1.0}, {})

        sub = registry._weights["h1"][0]
        assert sub["num_samples"] == 1

    def test_record_submission_num_samples_none(self):
        """metrics 中 num_samples=None 时默认为 1"""
        registry = ClientRegistry()
        registry._record_weight_submission(
            "h1", {"l1": 1.0}, {"num_samples": None}
        )

        sub = registry._weights["h1"][0]
        assert sub["num_samples"] == 1

    def test_record_submission_weights_copied(self):
        """weights 应被 dict() 复制，避免引用原对象"""
        registry = ClientRegistry()
        original = {"l1": 1.0}
        registry._record_weight_submission("h1", original, {})

        sub = registry._weights["h1"][0]
        assert sub["weights"] == original
        assert sub["weights"] is not original

    def test_record_submission_metrics_copied(self):
        """metrics 应被 dict() 复制"""
        registry = ClientRegistry()
        original_metrics = {"loss": 0.1}
        registry._record_weight_submission("h1", {"l1": 1.0}, original_metrics)

        sub = registry._weights["h1"][0]
        assert sub["metrics"] == original_metrics
        assert sub["metrics"] is not original_metrics

    def test_record_submission_unique_submission_ids(self):
        """每次提交应有不同的 submission_id"""
        registry = ClientRegistry()
        registry._record_weight_submission("h1", {"l1": 1.0}, {})
        registry._record_weight_submission("h1", {"l1": 2.0}, {})

        ids = [s["submission_id"] for s in registry._weights["h1"]]
        assert len(set(ids)) == 2


class TestClientRegistryCollectWeights:
    """ClientRegistry.collect_weights 测试"""

    def test_collect_weights_no_clients(self):
        registry = ClientRegistry()
        assert registry.collect_weights() == []

    def test_collect_weights_no_active_clients(self):
        """无活跃客户端时应返回空列表"""
        registry = ClientRegistry(heartbeat_timeout_sec=0)
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(client)
        registry._record_weight_submission("h1", {"l1": 1.0}, {"num_samples": 10})

        result = registry.collect_weights()
        assert result == []

    def test_collect_weights_active_client_no_submission(self):
        """活跃客户端但无权重提交时不应出现在结果中"""
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(client)

        result = registry.collect_weights()
        assert result == []

    def test_collect_weights_single_client(self):
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(client)
        registry._record_weight_submission(
            "h1", {"l1": 1.0}, {"num_samples": 10, "loss": 0.5}
        )

        result = registry.collect_weights()
        assert len(result) == 1
        assert result[0]["client_id"] == "h1"
        assert result[0]["weights"] == {"l1": 1.0}
        assert result[0]["num_samples"] == 10
        assert result[0]["metrics"] == {"num_samples": 10, "loss": 0.5}

    def test_collect_weights_returns_latest_submission(self):
        """多次提交时应只返回最新一次"""
        registry = ClientRegistry()
        client = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        registry.register(client)
        registry._record_weight_submission("h1", {"l1": 1.0}, {"num_samples": 10})
        time.sleep(0.01)
        registry._record_weight_submission("h1", {"l1": 99.0}, {"num_samples": 20})

        result = registry.collect_weights()
        assert len(result) == 1
        assert result[0]["weights"] == {"l1": 99.0}
        assert result[0]["num_samples"] == 20

    def test_collect_weights_multiple_clients(self):
        registry = ClientRegistry()
        c1 = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        c2 = FLClient(client_id="h2", endpoint="grpc://h2:8080")
        registry.register(c1)
        registry.register(c2)
        registry._record_weight_submission("h1", {"l1": 1.0}, {"num_samples": 10})
        registry._record_weight_submission("h2", {"l1": 2.0}, {"num_samples": 20})

        result = registry.collect_weights()
        assert len(result) == 2
        ids = {r["client_id"] for r in result}
        assert ids == {"h1", "h2"}

    def test_collect_weights_excludes_inactive_clients(self):
        """失活客户端的权重提交不应被收集"""
        registry = ClientRegistry(heartbeat_timeout_sec=60)
        c1 = FLClient(client_id="h1", endpoint="grpc://h1:8080")
        c2 = FLClient(client_id="h2", endpoint="grpc://h2:8080")
        registry.register(c1)
        registry.register(c2)
        registry._record_weight_submission("h1", {"l1": 1.0}, {"num_samples": 10})
        registry._record_weight_submission("h2", {"l1": 2.0}, {"num_samples": 20})

        # 让 h1 失活
        registry._heartbeats["h1"] = time.time() - 120

        result = registry.collect_weights()
        assert len(result) == 1
        assert result[0]["client_id"] == "h2"


# =====================================================================
# 集成场景：FLClient + ClientRegistry + PharmaFedAvg
# =====================================================================


class TestFedAvgIntegration:
    """端到端集成：客户端注册 → 提交权重 → 收集 → 聚合"""

    def test_end_to_end_aggregation_flow(self):
        """模拟多客户端注册、提交权重、聚合的完整流程"""
        registry = ClientRegistry()
        aggregator = PharmaFedAvg()

        clients = [
            FLClient("h1", "grpc://h1:8080", ["ic50"]),
            FLClient("h2", "grpc://h2:8080", ["ic50"]),
            FLClient("h3", "grpc://h3:8080", ["ic50"]),
        ]
        for c in clients:
            c.register(registry)

        # 各客户端提交权重
        clients[0].submit_weights({"l1": 1.0, "l2": 2.0}, {"num_samples": 100})
        clients[1].submit_weights({"l1": 1.5, "l2": 2.5}, {"num_samples": 200})
        clients[2].submit_weights({"l1": 2.0, "l2": 3.0}, {"num_samples": 300})

        # 收集并聚合
        collected = registry.collect_weights()
        assert len(collected) == 3

        result = aggregator.aggregate(client_weights=collected)
        assert result["status"] == "aggregated"
        assert result["num_clients"] == 3
        assert result["total_samples"] == 600
        # l1: (1*100 + 1.5*200 + 2*300) / 600 = (100+300+600)/600 = 1000/600
        expected_l1 = (1.0 * 100 + 1.5 * 200 + 2.0 * 300) / 600
        assert abs(result["aggregated_weights"]["l1"] - expected_l1) < 1e-6

    def test_end_to_end_with_byzantine_client(self):
        """集成场景：包含一个拜占庭客户端应被剔除

        使用 [1.0, 1.1, 0.9, 1.0, 1000.0] 确保 MAD 非零：
        median=1.0, abs_devs=[0,0.1,0.1,0,999], mad=0.1, scaled=0.148,
        cutoff=3*0.148=0.44 → 仅 1000.0 被剔除。
        """
        registry = ClientRegistry()
        aggregator = PharmaFedAvg(mad_threshold=3.0)

        clients = [
            FLClient(f"h{i}", f"grpc://h{i}:8080") for i in range(5)
        ]
        for c in clients:
            c.register(registry)

        # 4 个正常客户端（值略有差异以保证 MAD 非零）+ 1 个拜占庭
        clients[0].submit_weights({"l1": 1.0}, {"num_samples": 10})
        clients[1].submit_weights({"l1": 1.1}, {"num_samples": 10})
        clients[2].submit_weights({"l1": 0.9}, {"num_samples": 10})
        clients[3].submit_weights({"l1": 1.0}, {"num_samples": 10})
        clients[4].submit_weights({"l1": 1000.0}, {"num_samples": 10})

        collected = registry.collect_weights()
        result = aggregator.aggregate(client_weights=collected)

        assert result["status"] == "aggregated"
        assert result["num_byzantine_filtered"] == 1
        assert result["num_clients"] == 4
        # 剔除拜占庭后 l1 应接近 1.0
        assert abs(result["aggregated_weights"]["l1"] - 1.0) < 0.05

    def test_end_to_end_all_clients_inactive(self):
        """所有客户端失活时 collect_weights 返回空，aggregate 返回 no_clients"""
        registry = ClientRegistry(heartbeat_timeout_sec=0)
        client = FLClient("h1", "grpc://h1:8080")
        client.register(registry)
        client.submit_weights({"l1": 1.0}, {"num_samples": 10})

        collected = registry.collect_weights()
        assert collected == []

        aggregator = PharmaFedAvg()
        result = aggregator.aggregate(client_weights=collected)
        assert result["status"] == "no_clients"
