"""SDTM 校验器 — 参考 Pinnacle 21 Community 核心规则集

设计来源：v3.0 文档第 8 章 v3.0 开源工具集成策略

纯 Python 实现，不依赖 Java/P21 CLI，覆盖 FDA 常见校验规则：
- CG0001: USUBJID 必须唯一
- CG0002: DOMAIN 必填
- CG0003: STUDYID 跨域一致
- CG0004: USUBJID 跨域引用完整（所有域的 USUBJID 必须在 DM 中存在）
- CG0005: --SEQ 必须连续（如果存在）
- CG0006: 必填变量非空（域特定）
- CG0007: 变量名 ≤ 8 字符
- CG0008: 日期格式 ISO 8601
"""
import re
from datetime import datetime
from typing import Any, Dict, List


# 域特定必填变量
_REQUIRED_VARS = {
    "DM": ["STUDYID", "DOMAIN", "USUBJID"],
    "VS": ["STUDYID", "DOMAIN", "USUBJID", "VSTEST"],
    "RS": ["STUDYID", "DOMAIN", "USUBJID", "RSTEST"],
    "EX": ["STUDYID", "DOMAIN", "USUBJID", "EXTRT"],
    "SV": ["STUDYID", "DOMAIN", "USUBJID", "VISITNUM"],
}

# 日期变量后缀（用于 ISO 8601 校验）
_DATE_VAR_SUFFIXES = ("DTC", "DTM", "STDTC", "ENDTC")

# ISO 8601 日期模式（支持完整日期、部分日期、时间）
_ISO8601_PATTERN = re.compile(
    r"^\d{4}(-\d{2}(-\d{2}(T\d{2}(:\d{2}(:\d{2})?)?(Z|[+-]\d{2}:?\d{2})?)?)?)?$"
)


class SDTMValidator:
    """SDTM 校验器 — 参考 Pinnacle 21 Community 核心规则集"""

    _RULES = [
        {"id": "CG0001", "severity": "error", "description": "USUBJID 必须唯一"},
        {"id": "CG0002", "severity": "error", "description": "DOMAIN 必填"},
        {"id": "CG0003", "severity": "error", "description": "STUDYID 跨域一致"},
        {"id": "CG0004", "severity": "error", "description": "USUBJID 跨域引用完整"},
        {"id": "CG0005", "severity": "warning", "description": "--SEQ 必须连续"},
        {"id": "CG0006", "severity": "warning", "description": "必填变量非空"},
        {"id": "CG0007", "severity": "error", "description": "变量名 ≤ 8 字符"},
        {"id": "CG0008", "severity": "warning", "description": "日期格式 ISO 8601"},
    ]

    def validate(self, sdtm_data: Dict[str, Any]) -> Dict[str, Any]:
        """校验 SDTM 数据

        Args:
            sdtm_data: SDTMExporter.export() 返回的结构 {domains, metadata, record_counts}

        Returns:
            {
                "errors": [{"rule_id", "message", "domain", "record_index"}, ...],
                "warnings": [{"rule_id", "message", "domain", "record_index"}, ...],
                "passed": bool,  # True if no errors
                "rules_checked": int,
                "summary": str,
            }
        """
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        domains: Dict[str, List[Dict]] = sdtm_data.get("domains", {})
        metadata = sdtm_data.get("metadata", {})
        expected_study_id = metadata.get("study_id", "")

        # 收集所有 USUBJID（用于跨域引用检查）
        all_usubjids: Dict[str, set] = {}
        dm_usubjids: set = set()

        for domain_name, records in domains.items():
            if not records:
                continue
            domain_usubjids = set()
            for r in records:
                uid = r.get("USUBJID", "")
                if uid:
                    domain_usubjids.add(uid)
            all_usubjids[domain_name] = domain_usubjids
            if domain_name == "DM":
                dm_usubjids = domain_usubjids

        # CG0001: USUBJID 必须唯一（同域内）
        for domain_name, records in domains.items():
            if not records:
                continue
            seen = set()
            for idx, r in enumerate(records):
                uid = r.get("USUBJID", "")
                if not uid:
                    continue
                if uid in seen:
                    errors.append({
                        "rule_id": "CG0001",
                        "message": f"USUBJID '{uid}' 在域 {domain_name} 中重复",
                        "domain": domain_name,
                        "record_index": idx,
                    })
                seen.add(uid)

        # CG0002: DOMAIN 必填
        for domain_name, records in domains.items():
            if not records:
                continue
            for idx, r in enumerate(records):
                domain_val = r.get("DOMAIN", "")
                if not domain_val:
                    errors.append({
                        "rule_id": "CG0002",
                        "message": f"域 {domain_name} 第 {idx + 1} 条记录缺少 DOMAIN 值",
                        "domain": domain_name,
                        "record_index": idx,
                    })
                elif domain_val != domain_name:
                    errors.append({
                        "rule_id": "CG0002",
                        "message": f"域 {domain_name} 第 {idx + 1} 条记录 DOMAIN 值 '{domain_val}' 与域名不匹配",
                        "domain": domain_name,
                        "record_index": idx,
                    })

        # CG0003: STUDYID 跨域一致
        if expected_study_id:
            for domain_name, records in domains.items():
                if not records:
                    continue
                for idx, r in enumerate(records):
                    study_id = r.get("STUDYID", "")
                    if not study_id:
                        errors.append({
                            "rule_id": "CG0003",
                            "message": f"域 {domain_name} 第 {idx + 1} 条记录缺少 STUDYID",
                            "domain": domain_name,
                            "record_index": idx,
                        })
                    elif study_id != expected_study_id:
                        errors.append({
                            "rule_id": "CG0003",
                            "message": f"域 {domain_name} 第 {idx + 1} 条记录 STUDYID '{study_id}' 与期望值 '{expected_study_id}' 不一致",
                            "domain": domain_name,
                            "record_index": idx,
                        })

        # CG0004: USUBJID 跨域引用完整（非 DM 域的 USUBJID 必须在 DM 中存在）
        if dm_usubjids:
            for domain_name, usubjids in all_usubjids.items():
                if domain_name == "DM":
                    continue
                for uid in usubjids:
                    if uid not in dm_usubjids:
                        errors.append({
                            "rule_id": "CG0004",
                            "message": f"域 {domain_name} 的 USUBJID '{uid}' 在 DM 域中不存在",
                            "domain": domain_name,
                            "record_index": -1,
                        })

        # CG0005: --SEQ 必须连续（如果存在）
        for domain_name, records in domains.items():
            if not records:
                continue
            seq_var = f"{domain_name}SEQ"
            seq_values = []
            for idx, r in enumerate(records):
                if seq_var in r:
                    try:
                        seq_values.append((idx, int(r[seq_var])))
                    except (ValueError, TypeError):
                        warnings.append({
                            "rule_id": "CG0005",
                            "message": f"域 {domain_name} 第 {idx + 1} 条记录 {seq_var} 值 '{r[seq_var]}' 不是有效整数",
                            "domain": domain_name,
                            "record_index": idx,
                        })
            if seq_values:
                expected_seq = 1
                for idx, val in seq_values:
                    if val != expected_seq:
                        warnings.append({
                            "rule_id": "CG0005",
                            "message": f"域 {domain_name} 第 {idx + 1} 条记录 {seq_var}={val}，期望 {expected_seq}",
                            "domain": domain_name,
                            "record_index": idx,
                        })
                    expected_seq = val + 1

        # CG0006: 必填变量非空
        for domain_name, records in domains.items():
            if not records:
                continue
            required = _REQUIRED_VARS.get(domain_name, ["STUDYID", "DOMAIN", "USUBJID"])
            for idx, r in enumerate(records):
                for var in required:
                    val = r.get(var, "")
                    if val == "" or val is None:
                        warnings.append({
                            "rule_id": "CG0006",
                            "message": f"域 {domain_name} 第 {idx + 1} 条记录必填变量 {var} 为空",
                            "domain": domain_name,
                            "record_index": idx,
                        })

        # CG0007: 变量名 ≤ 8 字符
        for domain_name, records in domains.items():
            if not records:
                continue
            for idx, r in enumerate(records):
                for var in r.keys():
                    if len(var) > 8:
                        errors.append({
                            "rule_id": "CG0007",
                            "message": f"域 {domain_name} 第 {idx + 1} 条记录变量名 '{var}' 超过 8 字符",
                            "domain": domain_name,
                            "record_index": idx,
                        })

        # CG0008: 日期格式 ISO 8601
        for domain_name, records in domains.items():
            if not records:
                continue
            for idx, r in enumerate(records):
                for var, val in r.items():
                    if not isinstance(val, str) or not val:
                        continue
                    if var.endswith(_DATE_VAR_SUFFIXES):
                        if not _ISO8601_PATTERN.match(val):
                            warnings.append({
                                "rule_id": "CG0008",
                                "message": f"域 {domain_name} 第 {idx + 1} 条记录 {var}='{val}' 不符合 ISO 8601 格式",
                                "domain": domain_name,
                                "record_index": idx,
                            })

        passed = len(errors) == 0
        total_issues = len(errors) + len(warnings)
        summary = (
            "校验通过，无错误" if passed and not warnings
            else f"校验通过，{len(warnings)} 个警告" if passed
            else f"校验未通过：{len(errors)} 个错误，{len(warnings)} 个警告"
        )

        return {
            "errors": errors,
            "warnings": warnings,
            "passed": passed,
            "rules_checked": len(self._RULES),
            "total_issues": total_issues,
            "summary": summary,
        }
