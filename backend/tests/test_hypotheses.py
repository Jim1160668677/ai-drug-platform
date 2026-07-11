"""多假设并行模块测试"""
import pytest


@pytest.mark.asyncio
async def test_create_hypothesis(client, auth_headers, test_project):
    """测试创建假设"""
    project_id = test_project["id"]
    resp = await client.post(
        "/api/v1/hypotheses",
        params={"project_id": project_id},
        json={
            "name": "H1: EGFR 通路抑制",
            "description": "通过 EGFR TKI 抑制 EGFR 通路",
            "mechanism": "EGFR 突变导致通路持续激活",
            "strategy": "三代 TKI 单药治疗",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "H1: EGFR 通路抑制"
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_list_hypotheses(client, auth_headers, test_project):
    """测试假设列表"""
    project_id = test_project["id"]
    # 先创建一个
    await client.post(
        "/api/v1/hypotheses",
        params={"project_id": project_id},
        json={"name": "H-List-Test"},
        headers=auth_headers,
    )
    resp = await client.get(
        "/api/v1/hypotheses",
        params={"project_id": project_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    # PagedResponse 信封
    assert body["success"] is True
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1


@pytest.mark.asyncio
async def test_analyze_hypothesis(client, auth_headers, test_project):
    """测试假设分析"""
    project_id = test_project["id"]

    # 上传数据
    import io
    csv_content = b"gene,s1,s2\nEGFR,25,22\nKRAS,15,14\nTP53,30,28\n"
    await client.post(
        "/api/v1/data/upload",
        params={"project_id": project_id, "name": "Hyp Data", "data_type": "rna_seq"},
        files={"file": ("hyp.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )

    # 创建假设
    create_resp = await client.post(
        "/api/v1/hypotheses",
        params={"project_id": project_id},
        json={"name": "H-Analyze-Test", "mechanism": "EGFR activation"},
        headers=auth_headers,
    )
    hyp_id = create_resp.json()["id"]

    # 分析
    resp = await client.post(
        f"/api/v1/hypotheses/{hyp_id}/analyze",
        params={"tier": "fast_screen"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "targets" in data


@pytest.mark.asyncio
async def test_compare_hypotheses(client, auth_headers, test_project):
    """测试假设对比"""
    project_id = test_project["id"]

    # 创建两个假设
    for name in ["H-Compare-1", "H-Compare-2"]:
        await client.post(
            "/api/v1/hypotheses",
            params={"project_id": project_id},
            json={"name": name},
            headers=auth_headers,
        )

    resp = await client.get(
        "/api/v1/hypotheses/compare",
        params={"project_id": project_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "hypotheses" in data
