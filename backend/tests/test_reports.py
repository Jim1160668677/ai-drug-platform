"""报告导出模块测试"""
import io
import pytest


@pytest.mark.asyncio
async def test_sdtm_export(client, auth_headers, test_project):
    """测试 SDTM 导出"""
    project_id = test_project["id"]

    # 上传数据 + 发现靶点（确保有数据可导出）
    csv_content = b"gene,s1,s2\nEGFR,25,22\nTP53,30,28\n"
    await client.post(
        "/api/v1/data/upload",
        params={"project_id": project_id, "name": "SDTM Data", "data_type": "rna_seq"},
        files={"file": ("sdtm.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/targets/discover",
        params={"project_id": project_id, "tier": "fast_screen"},
        headers=auth_headers,
    )

    # 导出 SDTM (CSV 格式)
    resp = await client.post(
        f"/api/v1/reports/{project_id}/sdtm",
        params={"format": "csv"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    content = resp.text
    assert "CDISC" in content or "SDTM" in content
    assert "DM" in content  # DM 域

    # 也验证 JSON 格式（默认）
    resp_json = await client.post(
        f"/api/v1/reports/{project_id}/sdtm",
        headers=auth_headers,
    )
    assert resp_json.status_code == 200
    assert "application/json" in resp_json.headers.get("content-type", "")
    assert "csv" in resp_json.json()["data"]  # JSON 中含 csv 字段


@pytest.mark.asyncio
async def test_adam_export(client, auth_headers, test_project):
    """测试 ADaM 导出"""
    project_id = test_project["id"]

    resp = await client.post(
        f"/api/v1/reports/{project_id}/adam",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "datasets" in data
    assert "ADSL" in data["datasets"]


@pytest.mark.asyncio
async def test_project_summary(client, auth_headers, test_project):
    """测试项目摘要报告"""
    project_id = test_project["id"]

    resp = await client.get(
        f"/api/v1/reports/{project_id}/summary",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "project_id" in data
    assert "datasets" in data
    assert "targets" in data
    assert "hypotheses" in data
    assert "experiments" in data
