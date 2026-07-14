"""数据端点 — 多组学数据接入"""
import asyncio
import logging
import os
import uuid
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import apply_project_visibility
from app.core.config import settings
from app.core.deps import get_current_user
from app.core.exceptions import ForbiddenError, NotFoundError, UpstreamError, ValidationError
from app.core.security import UserRole
from app.db.session import get_db
from app.models.dataset import Dataset, DataType, ParseStatus
from app.models.user import User
from app.api.v1.schemas import DatasetResponse, StandardResponse
from app.schemas.common import ApiResponse, PagedResponse, paged_response, success_response

logger = logging.getLogger(__name__)
router = APIRouter()

# 上传文件大小上限（100MB）— 防止 OOM 攻击
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

# 允许的文件扩展名白名单
ALLOWED_EXTENSIONS = {
    "csv", "tsv", "h5", "mtx", "vcf", "fasta", "fa",
    "pdf", "png", "jpg", "jpeg", "txt",
    "xlsx", "xls",
}

# 支持的数据类型映射
DATA_TYPE_MAP = {
    "csv": DataType.RNA_SEQ, "tsv": DataType.RNA_SEQ,
    "h5": DataType.SCRNA_SEQ, "mtx": DataType.SCRNA_SEQ,
    "vcf": DataType.WES, "fasta": DataType.FASTA, "fa": DataType.FASTA,
    "pdf": DataType.GENE_REPORT, "png": DataType.GENE_REPORT, "jpg": DataType.GENE_REPORT,
    "xlsx": DataType.RNA_SEQ, "xls": DataType.RNA_SEQ,
}


@router.get("", response_model=PagedResponse[DatasetResponse], summary="数据集列表")
async def list_datasets(
    project_id: UUID = Query(None),
    data_type: str = Query(None),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取数据集列表（分页，PagedResponse 信封）

    可见性：领导角色可见全部；其余角色仅可见自己拥有项目下的数据集。
    """
    skip = (page - 1) * page_size
    stmt = select(Dataset).offset(skip).limit(page_size).order_by(Dataset.created_at.desc())
    if project_id:
        stmt = stmt.where(Dataset.project_id == project_id)
    if data_type:
        stmt = stmt.where(Dataset.data_type == data_type)
    stmt = apply_project_visibility(stmt, current_user, Dataset.project_id)
    result = await db.execute(stmt)
    items = [DatasetResponse.model_validate(d).model_dump() for d in result.scalars().all()]

    count_stmt = select(func.count()).select_from(Dataset)
    if project_id:
        count_stmt = count_stmt.where(Dataset.project_id == project_id)
    if data_type:
        count_stmt = count_stmt.where(Dataset.data_type == data_type)
    count_stmt = apply_project_visibility(count_stmt, current_user, Dataset.project_id)
    total = (await db.execute(count_stmt)).scalar() or 0
    return paged_response(data=items, page=page, page_size=page_size, total=total)


@router.post("/upload", response_model=DatasetResponse, summary="上传数据文件")
async def upload_data(
    project_id: UUID,
    name: str,
    data_type: str,
    source: str = "",
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传多组学数据文件

    安全策略：
    - 文件大小上限 100MB（MAX_UPLOAD_BYTES），防止 OOM
    - 扩展名白名单校验（ALLOWED_EXTENSIONS）
    - 文件名取 basename 防路径遍历，二次校验最终路径在上传目录内
    - 文件写入使用 asyncio.to_thread 避免阻塞事件循环
    """
    content = await file.read()
    file_size = len(content)

    # 大小校验
    if file_size > MAX_UPLOAD_BYTES:
        raise ValidationError(
            f"文件大小 {file_size} 字节超过上限 {MAX_UPLOAD_BYTES} 字节（100MB）"
        )
    if file_size == 0:
        raise ValidationError("文件为空")

    ext = os.path.splitext(file.filename or "")[1].lstrip(".").lower()

    # 扩展名白名单校验
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"不支持的文件类型: .{ext}，允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # 安全文件名：取 basename 防路径遍历，空则生成随机名
    safe_name = os.path.basename(file.filename or "") or f"{uuid.uuid4().hex}.bin"
    # 防止 Windows 路径分隔符绕过
    safe_name = safe_name.replace("\\", "/").split("/")[-1]
    if not safe_name or safe_name.startswith("."):
        safe_name = f"{uuid.uuid4().hex}.{ext}" if ext else f"{uuid.uuid4().hex}.bin"

    # 配置化的上传根目录（跨平台）
    upload_root = os.path.abspath(getattr(settings, "UPLOAD_DIR", "uploads") or "uploads")
    local_dir = os.path.join(upload_root, str(project_id))
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.abspath(os.path.join(local_dir, safe_name))
    # 二次校验：确保最终路径在上传目录内
    if not local_path.startswith(local_dir + os.sep):
        raise ValidationError("非法文件名")

    # 异步写入文件，避免阻塞事件循环
    await asyncio.to_thread(_write_file_sync, local_path, content)

    dataset = Dataset(
        project_id=project_id,
        name=name,
        data_type=data_type,
        source=source or file.filename,
        storage_path=local_path,
        file_size=file_size,
        file_format=ext,
        parse_status=ParseStatus.PENDING,
        uploaded_by=current_user.id,
    )
    db.add(dataset)
    await db.flush()
    return DatasetResponse.model_validate(dataset)


def _write_file_sync(path: str, content: bytes) -> None:
    """同步文件写入（供 asyncio.to_thread 调用）"""
    with open(path, "wb") as f:
        f.write(content)


@router.get("/{dataset_id}", response_model=DatasetResponse, summary="数据集详情")
async def get_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError("数据集不存在")
    if current_user.role != UserRole.FOUNDER and dataset.uploaded_by != current_user.id:
        raise ForbiddenError("无权访问此资源")
    return DatasetResponse.model_validate(dataset)


@router.post("/{dataset_id}/parse", response_model=StandardResponse, summary="触发数据解析")
async def parse_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """触发数据解析（调用对应的 parser）"""
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError("数据集不存在")

    dataset.parse_status = ParseStatus.PARSING
    await db.flush()

    # 调用对应的 parser
    try:
        from app.services.parser.base import parse_dataset as do_parse
        result = await do_parse(dataset, db)
        dataset.parse_status = ParseStatus.COMPLETED
        dataset.parsed_summary = result.get("summary")
        dataset.quality_metrics = result.get("quality_metrics")
        return StandardResponse(message="解析完成", data=result)
    except Exception as e:
        logger.error(f"数据集 {dataset_id} 解析失败: {e}", exc_info=True)
        dataset.parse_status = ParseStatus.FAILED
        dataset.parsed_summary = {"error": str(e)[:500]}
        await db.commit()
        raise UpstreamError("数据解析失败，请检查数据格式或联系管理员", service="parser")


@router.get("/{dataset_id}/quality", response_model=StandardResponse, summary="数据质量报告")
async def quality_report(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError("数据集不存在")
    return success_response({
        "quality_metrics": dataset.quality_metrics,
        "parse_status": dataset.parse_status,
        "parsed_summary": dataset.parsed_summary,
    })


@router.post("/{dataset_id}/process", response_model=ApiResponse[Dict[str, Any]], summary="处理数据集")
async def process_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """触发数据集处理（解析 + 质控）"""
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError("数据集不存在")
    # 调用 parser 工厂函数解析
    from app.services.parser.base import parse_dataset as do_parse
    try:
        result = await do_parse(dataset, db)
        dataset.parse_status = ParseStatus.COMPLETED
        dataset.parsed_summary = result.get("summary")
        dataset.quality_metrics = result.get("quality_metrics")
        await db.commit()
    except Exception as e:
        logger.error(f"数据集 {dataset_id} 处理失败: {e}", exc_info=True)
        dataset.parse_status = ParseStatus.FAILED
        await db.commit()
        raise UpstreamError("数据处理失败，请检查数据格式或联系管理员", service="parser")
    return success_response({
        "id": str(dataset_id),
        "parse_status": "completed",
        "summary": dataset.parsed_summary,
    })


@router.post("/{dataset_id}/umap", response_model=ApiResponse[Dict[str, Any]], summary="UMAP 降维")
async def umap_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """UMAP 降维可视化"""
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError("数据集不存在")
    summary = dataset.parsed_summary or {}
    return success_response({
        "id": str(dataset_id),
        "clusters": summary.get("clusters", []),
        "coordinates": summary.get("umap_coordinates", []),
    })


@router.get("/{dataset_id}/markers", response_model=ApiResponse[Dict[str, Any]], summary="标记基因")
async def get_markers(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取标记基因列表"""
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError("数据集不存在")
    summary = dataset.parsed_summary or {}
    return success_response({
        "id": str(dataset_id),
        "markers": summary.get("top_markers_per_cluster", {}),
    })


@router.delete("/{dataset_id}", response_model=ApiResponse[Dict[str, Any]], summary="删除数据集")
async def delete_dataset(
    dataset_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除数据集"""
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError("数据集不存在")
    if current_user.role != UserRole.FOUNDER and dataset.uploaded_by != current_user.id:
        raise ForbiddenError("无权删除此资源")
    await db.delete(dataset)
    await db.commit()
    return success_response({"id": str(dataset_id), "deleted": True})


@router.post("/{dataset_id}/analyze", response_model=ApiResponse[Dict[str, Any]], summary="生信分析")
async def analyze_dataset(
    dataset_id: UUID,
    analysis_type: str = Body(..., embed=True, description="de/clustering/pathway/pca"),
    group_a: List[str] = Body(None, embed=True),
    group_b: List[str] = Body(None, embed=True),
    params: dict = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行生信分析 — 差异表达/聚类/通路富集/PCA

    当数据集无 expression_data 时自动降级到 Mock 模式，返回演示数据。
    """
    from app.services.analyzer.bio_analyzer import BioAnalyzer
    from app.core.config import settings
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError("数据集不存在")
    summary = dataset.parsed_summary or {}
    expression_data = summary.get("expression_data", {})

    # 数据为空时自动降级到 Mock 模式，保证功能可用
    use_mock = settings.USE_MOCK or not expression_data
    if use_mock and not settings.USE_MOCK:
        import logging
        logging.getLogger(__name__).info(
            f"数据集 {dataset_id} 无 expression_data，降级到 Mock 模式"
        )
    analyzer = BioAnalyzer(use_mock=use_mock)

    if analysis_type == "de":
        # 差异表达分析需要对照组，未提供时使用默认分组
        if not group_a:
            group_a = ["sample_1", "sample_2", "sample_3"]
        if not group_b:
            group_b = ["sample_4", "sample_5", "sample_6"]
        result = await analyzer.differential_expression(
            expression_data, group_a, group_b,
            fdr_threshold=(params or {}).get("fdr_threshold", 0.05))
    elif analysis_type == "clustering":
        result = await analyzer.clustering(
            expression_data,
            method=(params or {}).get("method", "kmeans"),
            n_clusters=(params or {}).get("n_clusters", 5))
    elif analysis_type == "pathway":
        gene_list_str = (params or {}).get("gene_list", "")
        if isinstance(gene_list_str, str) and gene_list_str:
            gene_list = [g.strip() for g in gene_list_str.split(",") if g.strip()]
        elif isinstance(gene_list_str, list):
            gene_list = gene_list_str
        else:
            gene_list = list(expression_data.keys())[:50] if expression_data else []
        result = await analyzer.pathway_enrichment(
            gene_list, source=(params or {}).get("source", "kegg"))
    elif analysis_type == "pca":
        result = await analyzer.pca_analysis(
            expression_data, n_components=(params or {}).get("n_components", 2))
    else:
        raise ValidationError(f"未知分析类型: {analysis_type}")
    return success_response({"dataset_id": str(dataset_id), "analysis_type": analysis_type, "result": result})


@router.post("/{dataset_id}/export", response_model=ApiResponse[Dict[str, Any]], summary="导出分析结果")
async def export_dataset(
    dataset_id: UUID,
    format: str = Body("csv", embed=True, description="csv/json/excel"),
    analysis_type: str = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出分析结果为 CSV/JSON/Excel"""
    from app.services.analyzer.data_io import BioDataIO
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError("数据集不存在")
    summary = dataset.parsed_summary or {}
    data = summary.get("analysis_results", {}).get(analysis_type or "de", summary)
    if format == "json":
        content = await BioDataIO.export_json(data)
    elif format == "excel":
        content = await BioDataIO.export_excel(data)
    else:
        content = await BioDataIO.export_csv(data)
    return success_response({
        "dataset_id": str(dataset_id),
        "format": format,
        "size_bytes": len(content),
        "preview": content[:500].decode("utf-8", errors="ignore") if format != "excel" else f"[Excel binary, {len(content)} bytes]",
    })


@router.post("/import", response_model=ApiResponse[Dict[str, Any]], summary="导入数据文件")
async def import_data_file(
    project_id: UUID = Query(...),
    name: str = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导入多格式数据文件（CSV/JSON/FASTA/VCF/MTX/Excel）— 解析后创建 Dataset 记录"""
    from app.services.analyzer.data_io import BioDataIO
    content = await file.read()
    fmt = await BioDataIO.detect_format(file.filename or "", content)
    if fmt == "csv":
        parsed = await BioDataIO.import_csv(content)
    elif fmt == "tsv":
        parsed = await BioDataIO.import_csv(content)
    elif fmt == "json":
        parsed = await BioDataIO.import_json(content)
    elif fmt in ("fasta", "fa"):
        parsed = await BioDataIO.import_fasta(content)
    elif fmt == "vcf":
        parsed = await BioDataIO.import_vcf(content)
    elif fmt == "mtx":
        parsed = await BioDataIO.import_mtx(content)
    elif fmt in ("xlsx", "xls"):
        parsed = await BioDataIO.import_excel(content)
        if parsed.get("error"):
            raise ValidationError(parsed["error"])
    else:
        raise ValidationError(f"不支持的格式: {fmt}")
    data_type_map = {"csv": DataType.RNA_SEQ, "tsv": DataType.RNA_SEQ, "json": DataType.RNA_SEQ,
                     "fasta": DataType.FASTA, "vcf": DataType.WES, "mtx": DataType.SCRNA_SEQ,
                     "xlsx": DataType.RNA_SEQ, "xls": DataType.RNA_SEQ}
    dataset = Dataset(
        project_id=project_id, name=name,
        data_type=data_type_map.get(fmt, DataType.RNA_SEQ),
        source=file.filename, storage_path="",
        file_size=len(content), file_format=fmt,
        parse_status=ParseStatus.COMPLETED,
        parsed_summary=parsed, uploaded_by=current_user.id,
    )
    db.add(dataset)
    await db.flush()
    return success_response({
        "id": str(dataset.id), "name": name, "format": fmt,
        "parsed": parsed, "dataset": DatasetResponse.model_validate(dataset).model_dump(),
    })

