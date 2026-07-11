"""靶点发现模块测试"""
import io
import pytest


@pytest.mark.asyncio
async def test_discover_targets(client, auth_headers, test_project):
    """测试靶点发现"""
    project_id = test_project["id"]

    # 上传含 EGFR 的 RNA-seq 数据
    csv_content = b"gene,s1,s2,s3\nEGFR,25.5,22.1,28.3\nKRAS,15.2,14.8,16.1\nTP53,30.1,28.5,32.0\nB7H3,12.3,11.5,13.1\nFAP,8.2,7.5,9.0\n"
    await client.post(
        "/api/v1/data/upload",
        params={"project_id": project_id, "name": "Discover Data", "data_type": "rna_seq"},
        files={"file": ("discover.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )

    # 触发靶点发现
    resp = await client.post(
        "/api/v1/targets/discover",
        params={"project_id": project_id, "tier": "fast_screen"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "targets" in data
    assert data["count"] >= 0
    assert data["tier"] == "fast_screen"


@pytest.mark.asyncio
async def test_list_targets(client, auth_headers, test_project):
    """测试靶点列表"""
    resp = await client.get(
        "/api/v1/targets",
        params={"project_id": test_project["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    # PagedResponse 信封
    assert body["success"] is True
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_repurpose(client, auth_headers, test_project):
    """测试老药新用"""
    project_id = test_project["id"]

    # 先发现靶点（确保有靶点数据）
    csv_content = b"gene,s1,s2\nEGFR,25,22\nKRAS,15,14\nTP53,30,28\n"
    await client.post(
        "/api/v1/data/upload",
        params={"project_id": project_id, "name": "Repurpose Data", "data_type": "rna_seq"},
        files={"file": ("repurpose.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )

    discover_resp = await client.post(
        "/api/v1/targets/discover",
        params={"project_id": project_id, "tier": "fast_screen"},
        headers=auth_headers,
    )

    # 获取靶点列表
    targets_resp = await client.get(
        "/api/v1/targets",
        params={"project_id": project_id},
        headers=auth_headers,
    )
    targets = targets_resp.json()["data"]

    if targets:
        target_id = targets[0]["id"]
        # 老药新用
        resp = await client.post(
            f"/api/v1/targets/{target_id}/repurpose",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "candidates" in data


@pytest.mark.asyncio
async def test_evidence_chain(client, auth_headers, test_project):
    """测试证据链构建"""
    project_id = test_project["id"]

    # 确保有靶点
    csv_content = b"gene,s1,s2\nEGFR,25,22\nTP53,30,28\n"
    await client.post(
        "/api/v1/data/upload",
        params={"project_id": project_id, "name": "Evidence Data", "data_type": "rna_seq"},
        files={"file": ("evidence.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/targets/discover",
        params={"project_id": project_id, "tier": "fast_screen"},
        headers=auth_headers,
    )

    targets_resp = await client.get(
        "/api/v1/targets",
        params={"project_id": project_id},
        headers=auth_headers,
    )
    targets = targets_resp.json()["data"]

    if targets:
        target_id = targets[0]["id"]
        resp = await client.post(
            f"/api/v1/targets/{target_id}/evidence",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data is not None
