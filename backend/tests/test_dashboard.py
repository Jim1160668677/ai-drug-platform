"""全局看板模块测试"""
import io
import pytest


@pytest.mark.asyncio
async def test_dashboard_overview_empty(client, auth_headers):
    """空数据时看板返回零值"""
    resp = await client.get("/api/v1/dashboard/overview", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "global" in data
    assert data["global"]["projects"] == 0
    assert data["global"]["datasets"] == 0
    assert data["global"]["targets"] == 0
    assert data["global"]["hypothesis_completion_rate"] == 0
    assert data["global"]["experiment_success_rate"] == 0
    assert data["projects"] == []
    assert data["recent_experiments"] == []


@pytest.mark.asyncio
async def test_dashboard_overview_with_data(client, auth_headers, test_project):
    """有数据时看板聚合正确"""
    project_id = test_project["id"]

    # 上传数据
    csv_content = b"gene,s1,s2\nEGFR,25,22\nKRAS,15,14\nTP53,30,28\n"
    await client.post(
        "/api/v1/data/upload",
        params={"project_id": project_id, "name": "Dash RNA", "data_type": "rna_seq"},
        files={"file": ("dash.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )

    # 发现靶点
    await client.post(
        "/api/v1/targets/discover",
        params={"project_id": project_id, "tier": "fast_screen"},
        headers=auth_headers,
    )

    # 创建假设并分析
    create_resp = await client.post(
        "/api/v1/hypotheses",
        params={"project_id": project_id},
        json={"name": "Dash H1"},
        headers=auth_headers,
    )
    hyp_id = create_resp.json()["id"]
    await client.post(
        f"/api/v1/hypotheses/{hyp_id}/analyze",
        params={"tier": "fast_screen"},
        headers=auth_headers,
    )

    # 查询看板
    resp = await client.get("/api/v1/dashboard/overview", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]

    # 全局聚合
    g = data["global"]
    assert g["projects"] >= 1
    assert g["datasets"] >= 1
    assert g["targets"] >= 3  # EGFR/KRAS/TP53
    assert g["hypotheses"] >= 1
    assert g["completed_hypotheses"] >= 1
    assert g["hypothesis_completion_rate"] > 0

    # 按癌种分组
    assert "NSCLC" in data["by_cancer_type"]
    assert data["by_cancer_type"]["NSCLC"] >= 1

    # 按状态分组
    assert "active" in data["by_status"]

    # 项目明细
    projects = data["projects"]
    assert len(projects) >= 1
    p = next(p for p in projects if p["id"] == project_id)
    assert p["name"] == "Test NSCLC Project"
    assert p["cancer_type"] == "NSCLC"
    assert p["counts"]["datasets"] >= 1
    assert p["counts"]["targets"] >= 3
    assert p["counts"]["hypotheses"] >= 1

    # 最近实验
    assert isinstance(data["recent_experiments"], list)
