"""EvidenceCollector 三级输出 + token 预算裁剪测试"""
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import pytest

from app.services.intelligence.evidence_collector import EvidenceCollector


@pytest.fixture
def fake_db_bundle():
    """构造一个 11 类数据都有的"大项目"假 EvidenceBundle"""
    from app.services.intelligence.evidence_collector import EvidenceBundle, EvidenceSource

    text = (
        "# 项目前期分析数据汇总\n\n"
        "## 已发现靶点\n"
        + "\n".join(f"- 靶点{i}: 基因{i} 置信度 0.9{i}" for i in range(1, 21))
        + "\n\n## 候选分子\n"
        + "\n".join(f"- C{i}CC(=O)O{i}: 评分 0.8{i}" for i in range(1, 21))
        + "\n\n## 治疗方案\n"
        + "\n".join(f"- 治疗{i}: 疗效 0.9{i} 风险 0.1{i}" for i in range(1, 11))
        + "\n\n## 实验记录\n- exp1 结果显著\n- exp2 部分响应\n"
        + "## 数据集\n- RNA-seq 数据集A\n## 已有研究假设\n- hyp1 假设一描述\n"
        + "## 个人基因组风险评估\n- 风险评分 0.85 (等级: high, 核心位点: 12, 辅助位点: 34)\n"
        + "  主要关联疾病特征: 乳腺癌, 卵巢癌\n"
        + "## 基因组数据上传\n- snp_chip: completed, SNPs 匹配数: 650000\n"
        + "## 验证结果\n- in_silico: 通过 18/20 (90%)\n"
        + "## 计算任务结果\n- docking_vina: completed 亲和力: -9.2\n"
        + "## 知情同意记录\n- 已授予: general_research\n"
    )
    structured = {
        "targets": [{"gene_symbol": f"T{i}"} for i in range(1, 21)],
        "molecules": [{"smiles": f"C{i}"} for i in range(1, 21)],
    }
    sources = [EvidenceSource(f"src{i}", i, f"s{i}") for i in range(1, 12)]
    return EvidenceBundle(text=text, sources=sources, structured=structured, project_id="test")


class TestEvidenceLevels:
    def test_level_summary_only_top_items(self, fake_db_bundle):
        """LEVEL=概要: 只保留 Top3 靶点+Top3 分子 + 其它模块数量统计"""
        with patch.object(EvidenceCollector, "collect_project_evidence_bundle", return_value=fake_db_bundle):
            collector = EvidenceCollector()
            out = asyncio.run(collector.collect_project_evidence_with_budget(
                "dummy",
                level="summary",
                token_budget_chars=1500,
            ))
            for i in range(4, 21):
                assert f"靶点{i}" not in out, f"概要级不应有靶点{i} 详情"
            assert "Top 20" in out or "20 个靶点" in out or "20" in out
            assert len(out) <= 1500 * 1.1

    def test_level_compact_respects_budget(self, fake_db_bundle):
        """LEVEL=精简: 预算紧时要自动裁剪到 budget 以内"""
        with patch.object(EvidenceCollector, "collect_project_evidence_bundle", return_value=fake_db_bundle):
            collector = EvidenceCollector()
            out = asyncio.run(collector.collect_project_evidence_with_budget(
                "dummy", level="compact", token_budget_chars=3000,
            ))
            assert len(out) <= 3000 * 1.1
            assert "靶点1" in out
            assert "治疗1" in out or "治疗方案" in out

    def test_level_full_keeps_everything(self, fake_db_bundle):
        """LEVEL=全量: 保留全部（budget 也允许时）"""
        with patch.object(EvidenceCollector, "collect_project_evidence_bundle", return_value=fake_db_bundle):
            collector = EvidenceCollector()
            out = asyncio.run(collector.collect_project_evidence_with_budget(
                "dummy", level="full", token_budget_chars=50000,
            ))
            assert "靶点19" in out and "靶点20" in out
            assert "知情同意" in out

    def test_invalid_level_falls_back_to_compact(self, fake_db_bundle):
        """level 传入非法值 → 默认 compact（不抛异常）"""
        with patch.object(EvidenceCollector, "collect_project_evidence_bundle", return_value=fake_db_bundle):
            collector = EvidenceCollector()
            out = asyncio.run(collector.collect_project_evidence_with_budget(
                "dummy", level="INVALID", token_budget_chars=2500,
            ))
            assert isinstance(out, str)
            assert len(out) <= 2500 * 1.1
