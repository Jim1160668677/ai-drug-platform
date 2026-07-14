"""多靶点协同分子设计单元测试"""
import pytest

from app.services.analyzer.molecule_designer import MoleculeDesigner


@pytest.fixture
def designer():
    """MoleculeDesigner 实例 — db 传 None（design_multi_target 不直接使用 db）"""
    return MoleculeDesigner(db=None)


class TestMultiTargetDesign:

    @pytest.mark.asyncio
    async def test_design_multi_target_mock(self, designer):
        """测试 2 靶点多靶点设计返回结构"""
        targets = [
            {"target_id": "t1", "name": "EGFR", "binding_site": "ATP", "weight": 0.6},
            {"target_id": "t2", "name": "KRAS", "binding_site": "GDP", "weight": 0.4},
        ]
        result = await designer.design_multi_target(targets, n_molecules=5)

        assert "designed_molecules" in result
        assert "model_info" in result
        assert len(result["designed_molecules"]) <= 5
        assert len(result["designed_molecules"]) > 0

        # 验证每个分子的结构
        mol = result["designed_molecules"][0]
        assert "smiles" in mol
        assert "properties" in mol
        assert "target_affinities" in mol
        assert "composite_score" in mol
        assert "weighted_affinity" in mol

        # 验证靶点亲和力（列表格式，每个靶点单独成行）
        assert isinstance(mol["target_affinities"], list)
        assert len(mol["target_affinities"]) == 2
        target_ids = [ta["target_id"] for ta in mol["target_affinities"]]
        assert "t1" in target_ids
        assert "t2" in target_ids
        t1_affinity = next(ta["affinity"] for ta in mol["target_affinities"] if ta["target_id"] == "t1")
        assert 0 <= t1_affinity <= 1

    @pytest.mark.asyncio
    async def test_design_multi_target_single_target(self, designer):
        """测试单靶点降级（仍应正常工作）"""
        targets = [
            {"target_id": "t1", "name": "EGFR", "binding_site": "ATP", "weight": 1.0},
        ]
        result = await designer.design_multi_target(targets, n_molecules=3)

        assert len(result["designed_molecules"]) > 0
        mol = result["designed_molecules"][0]
        # 列表格式：单靶点也应是列表
        assert isinstance(mol["target_affinities"], list)
        assert len(mol["target_affinities"]) == 1
        assert mol["target_affinities"][0]["target_id"] == "t1"
        # 单靶点权重归一化后应为 1.0
        assert result["model_info"]["targets"][0]["weight"] == 1.0

    @pytest.mark.asyncio
    async def test_design_multi_target_affinity_calc(self, designer):
        """测试亲和力计算范围"""
        targets = [
            {"target_id": "t1", "name": "Target1", "binding_site": "CCO", "weight": 1.0},
        ]
        result = await designer.design_multi_target(targets, n_molecules=5)

        for mol in result["designed_molecules"]:
            # 列表格式：查找 target_id == "t1" 的亲和力
            ta = next(t for t in mol["target_affinities"] if t["target_id"] == "t1")
            affinity = ta["affinity"]
            assert 0.0 <= affinity <= 1.0, f"亲和力 {affinity} 超出 [0,1] 范围"

    @pytest.mark.asyncio
    async def test_design_multi_target_composite_score(self, designer):
        """测试综合评分排序（降序）"""
        targets = [
            {"target_id": "t1", "name": "T1", "binding_site": "c1ccccc1", "weight": 0.5},
            {"target_id": "t2", "name": "T2", "binding_site": "C(=O)N", "weight": 0.5},
        ]
        result = await designer.design_multi_target(targets, n_molecules=10)

        scores = [m["composite_score"] for m in result["designed_molecules"]]
        assert scores == sorted(scores, reverse=True), "分子未按综合评分降序排列"

    @pytest.mark.asyncio
    async def test_design_multi_target_properties(self, designer):
        """测试理化性质完整性"""
        targets = [
            {"target_id": "t1", "name": "T1", "binding_site": "", "weight": 1.0},
        ]
        result = await designer.design_multi_target(targets, n_molecules=3)

        for mol in result["designed_molecules"]:
            props = mol["properties"]
            assert "mw" in props
            assert "logp" in props
            assert "hbd" in props
            assert "hba" in props
            assert "druglikeness_score" in props

    @pytest.mark.asyncio
    async def test_design_multi_target_with_seed(self, designer):
        """测试带种子分子的多靶点设计"""
        targets = [
            {"target_id": "t1", "name": "T1", "binding_site": "CCO", "weight": 1.0},
        ]
        result = await designer.design_multi_target(
            targets, seed_smiles="CCO", n_molecules=3
        )
        assert result["model_info"]["strategy"] == "optimization"
        assert result["model_info"]["seed_smiles"] == "CCO"

    @pytest.mark.asyncio
    async def test_design_multi_target_weight_normalization(self, designer):
        """测试权重归一化"""
        targets = [
            {"target_id": "t1", "name": "T1", "weight": 3.0},
            {"target_id": "t2", "name": "T2", "weight": 1.0},
        ]
        result = await designer.design_multi_target(targets, n_molecules=2)

        # 归一化后权重之和应为 1.0
        total_weight = sum(t["weight"] for t in result["model_info"]["targets"])
        assert abs(total_weight - 1.0) < 0.001, f"权重归一化后总和 {total_weight} 不等于 1.0"
        # t1 权重应为 0.75
        t1_weight = next(t["weight"] for t in result["model_info"]["targets"] if t["target_id"] == "t1")
        assert abs(t1_weight - 0.75) < 0.001
