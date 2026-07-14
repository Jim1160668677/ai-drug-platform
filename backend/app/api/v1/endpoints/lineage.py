"""数据血缘端点 — 数据流转追溯"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.api.v1.schemas import StandardResponse
from app.schemas.common import ApiResponse, success_response

router = APIRouter()


class LineageRecordRequest(BaseModel):
    """记录血缘关系请求"""
    project_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    transformation: str
    transformation_meta: Optional[dict] = None


@router.post("", response_model=StandardResponse, summary="记录血缘关系")
async def record_lineage(
    req: LineageRecordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录一条数据血缘关系"""
    from app.services.lineage.tracker import LineageTracker

    tracker = LineageTracker(db)
    lineage = await tracker.record(
        project_id=req.project_id,
        source_type=req.source_type,
        source_id=req.source_id,
        target_type=req.target_type,
        target_id=req.target_id,
        transformation=req.transformation,
        meta=req.transformation_meta,
        created_by=str(current_user.id),
    )
    return StandardResponse(
        message="血缘关系已记录",
        data={
            "id": str(lineage.id),
            "source_type": lineage.source_type,
            "source_id": lineage.source_id,
            "target_type": lineage.target_type,
            "target_id": lineage.target_id,
            "transformation": lineage.transformation,
        },
    )


@router.get("/upstream", response_model=ApiResponse[List[Dict[str, Any]]], summary="查询上游链路")
async def get_upstream(
    project_id: str = Query(..., description="项目 ID"),
    node_type: str = Query(..., description="节点类型"),
    node_id: str = Query(..., description="节点 ID"),
    depth: int = Query(3, ge=1, le=10, description="遍历深度"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询节点的上游链路（谁产生了这个节点）"""
    from app.services.lineage.tracker import LineageTracker

    tracker = LineageTracker(db)
    result = await tracker.get_upstream(project_id, node_type, node_id, depth)
    return success_response(result)


@router.get("/downstream", response_model=ApiResponse[List[Dict[str, Any]]], summary="查询下游链路")
async def get_downstream(
    project_id: str = Query(..., description="项目 ID"),
    node_type: str = Query(..., description="节点类型"),
    node_id: str = Query(..., description="节点 ID"),
    depth: int = Query(3, ge=1, le=10, description="遍历深度"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询节点的下游链路（这个节点产生了什么）"""
    from app.services.lineage.tracker import LineageTracker

    tracker = LineageTracker(db)
    result = await tracker.get_downstream(project_id, node_type, node_id, depth)
    return success_response(result)


@router.get("/dag", response_model=ApiResponse[Dict[str, Any]], summary="获取完整 DAG")
async def get_dag(
    project_id: str = Query(..., description="项目 ID"),
    node_type: str = Query(..., description="节点类型"),
    node_id: str = Query(..., description="节点 ID"),
    depth: int = Query(3, ge=1, le=10, description="遍历深度"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取以指定节点为中心的完整 DAG（上游 + 下游）"""
    from app.services.lineage.tracker import LineageTracker

    tracker = LineageTracker(db)
    result = await tracker.get_dag(project_id, node_type, node_id, depth)
    return success_response(result)
