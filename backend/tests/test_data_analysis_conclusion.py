import pytest
from unittest.mock import MagicMock
from app.services.agent.tools.data_analysis import AnalyzeDatasetTool


class TestLLMConclusion:
    def setup_method(self):
        self.tool = AnalyzeDatasetTool()
        self.ctx = MagicMock()
    
    @pytest.mark.asyncio
    async def test_generate_conclusion_with_data(self):
        analysis_result = {
            "statistics": {"mean": 0.5, "std": 0.1},
            "chart_data": [{"x": 1, "y": 0.5}],
            "count": 10,
        }
        conclusion = await self.tool._generate_llm_conclusion(analysis_result, self.ctx)
        assert isinstance(conclusion, str)
        assert len(conclusion) > 0
        assert "0.50" in conclusion  # mean value
    
    @pytest.mark.asyncio
    async def test_generate_conclusion_empty_data(self):
        analysis_result = {}
        conclusion = await self.tool._generate_llm_conclusion(analysis_result, self.ctx)
        assert "无数据" in conclusion
    
    @pytest.mark.asyncio
    async def test_generate_conclusion_no_stats(self):
        analysis_result = {"chart_data": []}
        conclusion = await self.tool._generate_llm_conclusion(analysis_result, self.ctx)
        assert "统计结果为空" in conclusion
