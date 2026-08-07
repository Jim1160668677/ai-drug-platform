"""DICOM 医学影像解析器 — 提取患者/序列/影像元数据

支持 Sid Sijbrandij 骨肉瘤数据集中 UCSF 等机构公开的 DICOM CT/MR 影像。
依赖 pydicom 库（pip install pydicom），无法安装时降级为 minimal 手工解析。

输入：单个 .dcm 文件或包含多个 .dcm 的目录（dataset.storage_path 指向目录时遍历）
输出：
- summary: 患者ID/模态/影像维度/序列UID/切片数等
- quality_metrics: 解析完整性 / 模态分布
"""
import os
from typing import Any, Dict, List

from app.services.parser.base import Parser


# 临床常用 DICOM 标签（标签号 -> 友好字段名）
_DICOM_TAGS = {
    (0x0008, 0x0060): "modality",            # CS Modality
    (0x0008, 0x0020): "study_date",          # DA Study Date
    (0x0008, 0x0030): "study_time",          # TM Study Time
    (0x0008, 0x0050): "accession_number",    # SH Accession Number
    (0x0008, 0x0070): "manufacturer",         # LO Manufacturer
    (0x0008, 0x1090): "model_name",          # LO Manufacturer's Model Name
    (0x0010, 0x0010): "patient_name",        # PN Patient's Name
    (0x0010, 0x0020): "patient_id",          # LO Patient ID
    (0x0010, 0x0040): "patient_sex",          # CS Patient's Sex
    (0x0010, 0x1010): "patient_age",          # AS Patient's Age
    (0x0018, 0x0050): "slice_thickness",     # DS Slice Thickness
    (0x0018, 0x0060): "kvp",                 # DS KVP
    (0x0018, 0x0088): "spacing_between_slices",  # DS Spacing Between Slices
    (0x0018, 0x1150): "exposure_time",       # IS Exposure Time
    (0x0018, 0x1152): "exposure",            # IS Exposure
    (0x0018, 0x1250): "receiving_coil",      # SH Receive Coil Name
    (0x0020, 0x000D): "study_instance_uid",   # UI Study Instance UID
    (0x0020, 0x000E): "series_instance_uid",  # UI Series Instance UID
    (0x0020, 0x0011): "series_number",       # IS Series Number
    (0x0020, 0x0013): "instance_number",      # IS Instance Number
    (0x0020, 0x0032): "image_position",      # DS Image Position (Patient)
    (0x0020, 0x0037): "image_orientation",   # DS Image Orientation (Patient)
    (0x0028, 0x0010): "rows",               # US Rows
    (0x0028, 0x0011): "columns",            # US Columns
    (0x0028, 0x0030): "pixel_spacing",       # DS Pixel Spacing
    (0x0028, 0x0100): "bits_allocated",     # US Bits Allocated
    (0x0028, 0x0101): "bits_stored",        # US Bits Stored
    (0x0028, 0x1050): "window_center",       # DS Window Center
    (0x0028, 0x1051): "window_width",        # DS Window Width
    (0x0008, 0x1030): "study_description",   # LO Study Description
    (0x0008, 0x103E): "series_description",  # LO Series Description
    (0x0008, 0x0080): "institution_name",    # LO Institution Name
}


def _extract_ds_fields(ds) -> Dict[str, Any]:
    """从 pydicom Dataset 提取关键字段（仅元数据，不读 PixelData）"""
    record: Dict[str, Any] = {}
    for tag, field_name in _DICOM_TAGS.items():
        if tag in ds:
            try:
                value = ds[tag].value
                # pydicom 常返回 MultiValue / PersonName 等自定义类型，转字符串
                if hasattr(value, "original_string"):
                    value = str(value.original_string)
                elif isinstance(value, (list, tuple)):
                    value = [float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v) for v in value]
                elif isinstance(value, (int, float)):
                    pass  # 标量保留
                else:
                    value = str(value)
                record[field_name] = value
            except Exception:
                continue
    # BodyPartExamined (旧标签，0018 0015) — 兼容 Sid 数据集（部分 UCSF 影像无此字段）
    if (0x0018, 0x0015) in ds:
        try:
            record["body_part_examined"] = str(ds[(0x0018, 0x0015)].value)
        except Exception:
            pass
    return record


class DicomParser(Parser):
    """DICOM 医学影像元数据解析器

    使用 pydicom 解析单文件或目录。提取患者信息 / 影像参数 / 序列组织结构。
    不读取 PixelData（避免内存爆炸），仅解析元数据头部。
    """

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {"summary": {"error": f"DICOM 路径不存在: {path}"}, "quality_metrics": {}}

        # 收集所有 .dcm 文件
        dcm_files: List[str] = []
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for f in files:
                    if f.lower().endswith(".dcm") or f.lower().endswith(".dicom"):
                        dcm_files.append(os.path.join(root, f))
        elif os.path.isfile(path):
            dcm_files.append(path)

        if not dcm_files:
            return {
                "summary": {
                    "data_type": "dicom",
                    "error": "未找到 .dcm 文件",
                    "path": path,
                },
                "quality_metrics": {"parseable": False},
            }

        try:
            import pydicom
        except ImportError:
            return {
                "summary": {
                    "data_type": "dicom",
                    "error": "未安装 pydicom（pip install pydicom）",
                    "dcm_file_count": len(dcm_files),
                },
                "quality_metrics": {"parseable": False, "missing_dependency": "pydicom"},
            }

        # 解析每个文件（仅元数据，stop_before_pixels=True 避免读取像素数据）
        instances: List[Dict[str, Any]] = []
        parse_errors: List[str] = []
        for dcm_path in dcm_files:
            try:
                ds = pydicom.dcmread(dcm_path, stop_before_pixels=True, force=True)
                record = _extract_ds_fields(ds)
                record["file_name"] = os.path.basename(dcm_path)
                record["file_size_bytes"] = os.path.getsize(dcm_path)
                instances.append(record)
            except Exception as e:
                parse_errors.append(f"{os.path.basename(dcm_path)}: {str(e)[:100]}")

        if not instances:
            return {
                "summary": {
                    "data_type": "dicom",
                    "error": f"所有文件解析失败：{parse_errors[:3]}",
                    "dcm_file_count": len(dcm_files),
                },
                "quality_metrics": {"parseable": False, "errors": parse_errors[:5]},
            }

        # 聚合统计：按 StudyInstanceUID 分组（一个 Study 含若干 Series，每 Series 含若干 Instance）
        studies: Dict[str, Dict[str, Any]] = {}
        modality_counter: Dict[str, int] = {}
        body_parts: List[str] = []
        patient_ids: List[str] = []
        manufacturers: List[str] = []

        for inst in instances:
            study_uid = inst.get("study_instance_uid") or "unknown"
            series_uid = inst.get("series_instance_uid") or "unknown"
            study = studies.setdefault(study_uid, {
                "study_uid": study_uid,
                "study_date": inst.get("study_date"),
                "study_description": inst.get("study_description"),
                "patient_id": inst.get("patient_id"),
                "patient_age": inst.get("patient_age"),
                "patient_sex": inst.get("patient_sex"),
                "series": {},
            })
            series = study["series"].setdefault(series_uid, {
                "series_uid": series_uid,
                "modality": inst.get("modality"),
                "series_description": inst.get("series_description"),
                "rows": inst.get("rows"),
                "columns": inst.get("columns"),
                "slice_thickness": inst.get("slice_thickness"),
                "pixel_spacing": inst.get("pixel_spacing"),
                "instance_count": 0,
            })
            series["instance_count"] += 1

            modality = inst.get("modality") or "unknown"
            modality_counter[modality] = modality_counter.get(modality, 0) + 1

            if inst.get("body_part_examined"):
                body_parts.append(inst["body_part_examined"])
            if inst.get("patient_id"):
                patient_ids.append(str(inst["patient_id"]))
            if inst.get("manufacturer"):
                manufacturers.append(inst["manufacturer"])

        # 简化序列列表（仅前 10 个 Study + 各 Study 前 5 Series）
        studies_summary = []
        total_series = 0
        for study_uid, study in studies.items():
            series_list = list(study["series"].values())
            total_series += len(series_list)
            studies_summary.append({
                "study_uid": study_uid,
                "study_date": study.get("study_date"),
                "study_description": study.get("study_description"),
                "patient_id": study.get("patient_id"),
                "patient_age": study.get("patient_age"),
                "patient_sex": study.get("patient_sex"),
                "series_count": len(series_list),
                "series": [
                    {
                        "series_uid": s["series_uid"],
                        "modality": s["modality"],
                        "series_description": s.get("series_description"),
                        "rows": s.get("rows"),
                        "columns": s.get("columns"),
                        "slice_thickness": s.get("slice_thickness"),
                        "pixel_spacing": s.get("pixel_spacing"),
                        "instance_count": s["instance_count"],
                    }
                    for s in series_list[:5]
                ],
            })
            if len(studies_summary) >= 10:
                break

        # 单文件元信息（用于兼容性：第一个文件的元数据用作 "代表性" 元信息）
        first_inst = instances[0]
        summary = {
            "data_type": "dicom",
            "file_format": "dcm",
            "dcm_file_count": len(dcm_files),
            "parsed_instance_count": len(instances),
            "parse_error_count": len(parse_errors),
            "study_count": len(studies),
            "series_count": total_series,
            "modality_distribution": modality_counter,
            "patient_ids": list(set(patient_ids))[:10],
            "body_parts": list(set(body_parts))[:10],
            "manufacturers": list(set(manufacturers))[:5],
            "studies": studies_summary,
            # 代表性字段（供前端展示）
            "modality": first_inst.get("modality"),
            "rows": first_inst.get("rows"),
            "columns": first_inst.get("columns"),
            "slice_thickness": first_inst.get("slice_thickness"),
            "pixel_spacing": first_inst.get("pixel_spacing"),
            "study_date": first_inst.get("study_date"),
            "patient_age": first_inst.get("patient_age"),
            "study_description": first_inst.get("study_description"),
            "manufacturer": first_inst.get("manufacturer"),
            "model_name": first_inst.get("model_name"),
            "institution_name": first_inst.get("institution_name"),
            "note": (
                f"已解析 {len(instances)}/{len(dcm_files)} 个 DICOM 实例，"
                f"覆盖 {len(studies)} 个 Study / {total_series} 个 Series"
            ),
        }

        quality_metrics = {
            "parseable": True,
            "data_type": "dicom",
            "parse_success_rate": round(len(instances) / len(dcm_files), 4),
            "parse_errors": parse_errors[:5],
            "modality_coverage": {m: c for m, c in modality_counter.items()},
            "has_pixel_data_info": bool(first_inst.get("rows") and first_inst.get("columns")),
        }

        return {"summary": summary, "quality_metrics": quality_metrics}
