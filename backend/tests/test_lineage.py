"""数据血缘追踪服务单元测试

覆盖：
- 记录血缘关系
- 上游/下游查询
- 多层级 DAG 构建
- depth 深度控制
- 循环依赖安全
- 跨项目隔离
"""
import pytest

from app.services.lineage.tracker import LineageTracker


@pytest.fixture
async def tracker(async_db_session):
    return LineageTracker(async_db_session)


@pytest.fixture
async def project_id():
    """模拟项目 ID（不需要真实 Project 记录，因为血缘表用字符串外键）"""
    import uuid
    return str(uuid.uuid4())


class TestRecordLineage:
    """测试记录血缘关系"""

    @pytest.mark.asyncio
    async def test_record_single_relation(self, tracker, project_id):
        lineage = await tracker.record(
            project_id=project_id,
            source_type="dataset",
            source_id="ds-001",
            target_type="target",
            target_id="tgt-001",
            transformation="discover",
        )
        assert lineage.source_type == "dataset"
        assert lineage.source_id == "ds-001"
        assert lineage.target_type == "target"
        assert lineage.target_id == "tgt-001"
        assert lineage.transformation == "discover"
        assert lineage.id is not None

    @pytest.mark.asyncio
    async def test_record_with_meta(self, tracker, project_id):
        lineage = await tracker.record(
            project_id=project_id,
            source_type="dataset",
            source_id="ds-001",
            target_type="target",
            target_id="tgt-001",
            transformation="discover",
            meta={"algorithm": "DESeq2", "threshold": 0.05},
        )
        assert lineage.transformation_meta == {"algorithm": "DESeq2", "threshold": 0.05}

    @pytest.mark.asyncio
    async def test_record_with_created_by(self, tracker, project_id):
        lineage = await tracker.record(
            project_id=project_id,
            source_type="dataset",
            source_id="ds-001",
            target_type="target",
            target_id="tgt-001",
            transformation="discover",
            created_by="user-001",
        )
        assert lineage.created_by == "user-001"


class TestGetUpstream:
    """测试上游查询"""

    @pytest.mark.asyncio
    async def test_direct_upstream(self, tracker, project_id):
        """dataset → target：查询 target 的上游应返回 dataset"""
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-001",
            target_type="target", target_id="tgt-001",
            transformation="discover",
        )
        result = await tracker.get_upstream(project_id, "target", "tgt-001", depth=3)
        assert len(result) == 1
        assert result[0]["node_type"] == "dataset"
        assert result[0]["node_id"] == "ds-001"
        assert result[0]["depth"] == 1

    @pytest.mark.asyncio
    async def test_multi_level_upstream(self, tracker, project_id):
        """dataset → target → molecule：查询 molecule 的上游应返回 target 和 dataset"""
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-001",
            target_type="target", target_id="tgt-001",
            transformation="discover",
        )
        await tracker.record(
            project_id=project_id,
            source_type="target", source_id="tgt-001",
            target_type="molecule", target_id="mol-001",
            transformation="design",
        )
        result = await tracker.get_upstream(project_id, "molecule", "mol-001", depth=3)
        assert len(result) == 2
        # depth=1 是直接上游 target
        depth_1 = [r for r in result if r["depth"] == 1]
        assert len(depth_1) == 1
        assert depth_1[0]["node_type"] == "target"
        # depth=2 是间接上游 dataset
        depth_2 = [r for r in result if r["depth"] == 2]
        assert len(depth_2) == 1
        assert depth_2[0]["node_type"] == "dataset"

    @pytest.mark.asyncio
    async def test_no_upstream(self, tracker, project_id):
        """无上游节点返回空列表"""
        result = await tracker.get_upstream(project_id, "dataset", "ds-999", depth=3)
        assert result == []


class TestGetDownstream:
    """测试下游查询"""

    @pytest.mark.asyncio
    async def test_direct_downstream(self, tracker, project_id):
        """dataset → target：查询 dataset 的下游应返回 target"""
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-001",
            target_type="target", target_id="tgt-001",
            transformation="discover",
        )
        result = await tracker.get_downstream(project_id, "dataset", "ds-001", depth=3)
        assert len(result) == 1
        assert result[0]["node_type"] == "target"
        assert result[0]["node_id"] == "tgt-001"

    @pytest.mark.asyncio
    async def test_multi_level_downstream(self, tracker, project_id):
        """dataset → target → molecule → treatment"""
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-001",
            target_type="target", target_id="tgt-001",
            transformation="discover",
        )
        await tracker.record(
            project_id=project_id,
            source_type="target", source_id="tgt-001",
            target_type="molecule", target_id="mol-001",
            transformation="design",
        )
        await tracker.record(
            project_id=project_id,
            source_type="molecule", source_id="mol-001",
            target_type="treatment", target_id="trt-001",
            transformation="optimize",
        )
        result = await tracker.get_downstream(project_id, "dataset", "ds-001", depth=5)
        assert len(result) == 3
        depths = sorted(r["depth"] for r in result)
        assert depths == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_depth_limit(self, tracker, project_id):
        """depth=1 只返回直接下游"""
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-001",
            target_type="target", target_id="tgt-001",
            transformation="discover",
        )
        await tracker.record(
            project_id=project_id,
            source_type="target", source_id="tgt-001",
            target_type="molecule", target_id="mol-001",
            transformation="design",
        )
        result = await tracker.get_downstream(project_id, "dataset", "ds-001", depth=1)
        assert len(result) == 1
        assert result[0]["node_type"] == "target"


class TestGetDAG:
    """测试完整 DAG 查询"""

    @pytest.mark.asyncio
    async def test_dag_structure(self, tracker, project_id):
        """dataset → target → molecule：以 target 为中心"""
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-001",
            target_type="target", target_id="tgt-001",
            transformation="discover",
        )
        await tracker.record(
            project_id=project_id,
            source_type="target", source_id="tgt-001",
            target_type="molecule", target_id="mol-001",
            transformation="design",
        )
        dag = await tracker.get_dag(project_id, "target", "tgt-001", depth=3)

        assert dag["node_count"] == 3  # center + upstream + downstream
        assert dag["edge_count"] >= 2

        # 中心节点
        center = [n for n in dag["nodes"] if n["direction"] == "center"]
        assert len(center) == 1
        assert center[0]["type"] == "target"

        # 上游节点
        upstream_nodes = [n for n in dag["nodes"] if n["direction"] == "upstream"]
        assert len(upstream_nodes) == 1
        assert upstream_nodes[0]["type"] == "dataset"

        # 下游节点
        downstream_nodes = [n for n in dag["nodes"] if n["direction"] == "downstream"]
        assert len(downstream_nodes) == 1
        assert downstream_nodes[0]["type"] == "molecule"

    @pytest.mark.asyncio
    async def test_dag_no_relations(self, tracker, project_id):
        """无关系的节点 DAG 只含中心节点"""
        dag = await tracker.get_dag(project_id, "dataset", "ds-999", depth=3)
        assert dag["node_count"] == 1
        assert dag["edge_count"] == 0


class TestCrossProjectIsolation:
    """测试跨项目隔离"""

    @pytest.mark.asyncio
    async def test_isolation(self, tracker, project_id):
        """项目 A 的血缘不泄露到项目 B"""
        project_b = "project-b-uuid"
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-A",
            target_type="target", target_id="tgt-A",
            transformation="discover",
        )
        # 项目 B 查询不应看到项目 A 的数据
        result = await tracker.get_upstream(project_b, "target", "tgt-A", depth=3)
        assert result == []

    @pytest.mark.asyncio
    async def test_same_node_id_different_projects(self, tracker, project_id):
        """相同节点 ID 在不同项目中独立"""
        project_b = "project-b-uuid"
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="ds-shared",
            target_type="target", target_id="tgt-shared",
            transformation="discover",
        )
        # 项目 B 无此关系
        result_b = await tracker.get_upstream(project_b, "target", "tgt-shared", depth=3)
        assert result_b == []
        # 项目 A 有此关系
        result_a = await tracker.get_upstream(project_id, "target", "tgt-shared", depth=3)
        assert len(result_a) == 1


class TestCycleSafety:
    """测试循环依赖安全"""

    @pytest.mark.asyncio
    async def test_cycle_does_not_infinite_loop(self, tracker, project_id):
        """A → B → A 循环不应导致无限循环"""
        await tracker.record(
            project_id=project_id,
            source_type="dataset", source_id="A",
            target_type="target", target_id="B",
            transformation="step1",
        )
        await tracker.record(
            project_id=project_id,
            source_type="target", source_id="B",
            target_type="dataset", target_id="A",
            transformation="step2",
        )
        # 应正常返回，不死循环
        result = await tracker.get_downstream(project_id, "dataset", "A", depth=5)
        assert len(result) <= 5  # 不会无限增长
