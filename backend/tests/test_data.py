"""数据接入模块测试"""
import io
import pytest


@pytest.mark.asyncio
async def test_upload_csv(client, auth_headers, test_project):
    """测试上传 CSV 文件"""
    project_id = test_project["id"]
    csv_content = b"gene,sample1,sample2,sample3\nEGFR,10.5,12.3,8.7\nKRAS,5.1,4.8,6.2\nTP53,15.2,14.1,13.8\n"

    resp = await client.post(
        "/api/v1/data/upload",
        params={"project_id": project_id, "name": "Test RNA-seq", "data_type": "rna_seq", "source": "test"},
        files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test RNA-seq"
    assert data["data_type"] == "rna_seq"
    assert data["parse_status"] == "pending"


@pytest.mark.asyncio
async def test_list_datasets(client, auth_headers, test_project):
    """测试数据集列表"""
    resp = await client.get(
        "/api/v1/data",
        params={"project_id": test_project["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    # PagedResponse 信封
    assert body["success"] is True
    assert isinstance(body["data"], list)
    assert "meta" in body
    assert "total" in body["meta"]
    assert "page" in body["meta"]


@pytest.mark.asyncio
async def test_parse_dataset(client, auth_headers, test_project):
    """测试数据解析"""
    project_id = test_project["id"]
    csv_content = b"gene,s1,s2\nEGFR,10,12\nKRAS,5,6\nTP53,15,14\nB7H3,8,9\n"

    # 上传
    upload_resp = await client.post(
        "/api/v1/data/upload",
        params={"project_id": project_id, "name": "Parse Test", "data_type": "rna_seq"},
        files={"file": ("parse.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    dataset_id = upload_resp.json()["id"]

    # 解析
    parse_resp = await client.post(
        f"/api/v1/data/{dataset_id}/parse",
        headers=auth_headers,
    )
    assert parse_resp.status_code == 200
    data = parse_resp.json()
    assert data["success"] is True
    assert "summary" in data["data"] or "quality_metrics" in data["data"]


@pytest.mark.asyncio
async def test_quality_report(client, auth_headers, test_project):
    """测试质量报告"""
    project_id = test_project["id"]
    csv_content = b"gene,s1,s2\nEGFR,10,12\nKRAS,5,6\n"

    upload_resp = await client.post(
        "/api/v1/data/upload",
        params={"project_id": project_id, "name": "Quality Test", "data_type": "rna_seq"},
        files={"file": ("quality.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    dataset_id = upload_resp.json()["id"]

    # 先解析
    await client.post(f"/api/v1/data/{dataset_id}/parse", headers=auth_headers)

    # 查质量报告
    resp = await client.get(f"/api/v1/data/{dataset_id}/quality", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "quality_metrics" in data
    assert "parse_status" in data
