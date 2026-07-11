"""VCF 解析器 — cyvcf2 优先，文本解析降级"""
import os
from collections import Counter
from typing import Any, Dict

from app.services.parser.base import Parser


class VcfParser(Parser):
    """VCF 变异文件解析器"""

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {
                "summary": {"error": f"文件不存在: {path}"},
                "quality_metrics": {},
            }

        try:
            return await self._parse_with_cyvcf2(path)
        except ImportError:
            return await self._parse_text(path)
        except Exception as e:
            return {
                "summary": {"error": f"VCF 解析失败: {e}"},
                "quality_metrics": {},
            }

    async def _parse_with_cyvcf2(self, path: str) -> Dict[str, Any]:
        from cyvcf2 import VCF

        vcf = VCF(path)
        total = 0
        snv = 0
        indel = 0
        per_chrom = Counter()
        pass_count = 0
        clinvar_count = 0
        transitions = 0
        transversions = 0

        for variant in vcf:
            total += 1
            chrom = variant.CHROM
            per_chrom[chrom] += 1

            if variant.FILTER is None or variant.FILTER == "PASS":
                pass_count += 1

            # SNV vs INDEL
            ref = variant.REF
            alts = variant.ALT
            if alts and len(ref) == 1 and all(len(a) == 1 for a in alts if a):
                snv += 1
                # Transition vs Transversion
                if alts:
                    alt = alts[0]
                    transitions_pairs = {("A", "G"), ("G", "A"), ("C", "T"), ("T", "C")}
                    if (ref, alt) in transitions_pairs:
                        transitions += 1
                    else:
                        transversions += 1
            else:
                indel += 1

            # ClinVar 注释（CLNSIG 字段）
            try:
                clnsig = variant.INFO.get("CLNSIG")
                if clnsig:
                    clinvar_count += 1
            except Exception:
                pass

        ts_tv = transitions / transversions if transversions > 0 else 0.0

        return {
            "summary": {
                "total_variants": total,
                "snv_count": snv,
                "indel_count": indel,
                "ts_tv_ratio": round(ts_tv, 3),
                "parser": "cyvcf2",
            },
            "quality_metrics": {
                "per_chrom": dict(per_chrom.most_common(25)),
                "pass_rate": round(pass_count / total, 4) if total > 0 else 0,
                "clinvar_annotated": clinvar_count,
                "clinvar_annotation_rate": round(clinvar_count / total, 4) if total > 0 else 0,
                "data_type": "wes",
            },
        }

    async def _parse_text(self, path: str) -> Dict[str, Any]:
        """纯文本 VCF 解析（cyvcf2 不可用时的降级方案）"""
        total = 0
        snv = 0
        indel = 0
        per_chrom = Counter()
        pass_count = 0
        transitions = 0
        transversions = 0

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split("\t")
                if len(parts) < 5:
                    continue
                chrom, _pos, _id, ref, alt = parts[0], parts[1], parts[2], parts[3], parts[4]
                total += 1
                per_chrom[chrom] += 1
                filter_val = parts[6] if len(parts) > 6 else "PASS"
                if filter_val in ("PASS", "."):
                    pass_count += 1

                alts = alt.split(",")
                if len(ref) == 1 and all(len(a) == 1 for a in alts if a not in (".", "*")):
                    snv += 1
                    if alts:
                        transitions_pairs = {("A", "G"), ("G", "A"), ("C", "T"), ("T", "C")}
                        if (ref, alts[0]) in transitions_pairs:
                            transitions += 1
                        else:
                            transversions += 1
                else:
                    indel += 1

        ts_tv = transitions / transversions if transversions > 0 else 0.0
        return {
            "summary": {
                "total_variants": total,
                "snv_count": snv,
                "indel_count": indel,
                "ts_tv_ratio": round(ts_tv, 3),
                "parser": "text",
            },
            "quality_metrics": {
                "per_chrom": dict(per_chrom.most_common(25)),
                "pass_rate": round(pass_count / total, 4) if total > 0 else 0,
                "clinvar_annotated": 0,
                "data_type": "wes",
                "note": "cyvcf2 不可用，使用纯文本解析（无 ClinVar 注释统计）",
            },
        }
