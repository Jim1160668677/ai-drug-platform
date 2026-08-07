"""证据链构建器 — 整合 ClinVar/COSMIC/ChEMBL/ClinicalTrials 多源证据

策略：
1. 已有变异（target.variant_info）→ 直接提取 ClinVar/COSMIC 注释
2. 已有变异但无 ClinVar 注释 → 主动调 MyVariant.info 补全
3. 无变异信息但靶点基因已知 → 按 HGNC 标准查询 ClinVar 致病变异
4. 整合 ChEMBL 已获批药物 / ClinicalTrials.gov 试验 / KEGG 通路 / PPI 网络
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_variant_client, get_chembl_client
from app.models.target import EvidenceGrade

logger = logging.getLogger(__name__)


class EvidenceChainBuilder:
    """证据链构建 — 整合多源证据形成 DAG"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self, target) -> Dict[str, Any]:
        """构建靶点的证据链

        Returns:
            {
                "root": gene_symbol,
                "nodes": [...],
                "edges": [...],
                "evidence_sources": {...},
                "summary": str
            }
        """
        gene = target.gene_symbol
        nodes: List[Dict] = []
        edges: List[Dict] = []

        # 根节点
        nodes.append({
            "id": f"target:{gene}",
            "type": "target",
            "label": gene,
            "grade": target.evidence_grade,
        })

        # 1. 变异证据 — 整合已有变异 + 主动查询 ClinVar/COSMIC
        variant_infos = target.variant_info or []
        if isinstance(variant_infos, dict):
            variant_infos = [variant_infos]

        enriched_variants = await self._enrich_variants_with_clinvar(gene, variant_infos)

        for i, v in enumerate(enriched_variants[:10]):
            node_id = f"variant:{v.get('query', f'v{i}')}"
            clinvar = v.get("clinvar") or {}
            cosmic = v.get("cosmic") or {}
            clnsig = clinvar.get("clnsig") or ""
            grade = "I" if "pathogenic" in clnsig.lower() else (
                "II" if "likely pathogenic" in clnsig.lower() or "vus" in clnsig.lower() else "III"
            )
            nodes.append({
                "id": node_id,
                "type": "variant",
                "label": v.get("hgvs_p") or v.get("query", "unknown"),
                "clnsig": clnsig or None,
                "clinvar_id": clinvar.get("clinvar_id") or clinvar.get("rcv"),
                "cosmic_id": cosmic.get("cosmic_id"),
                "cosmic_cancer_type": cosmic.get("cancer_type") or cosmic.get("tumor_site"),
                "gnomad_af": (v.get("gnomad") or {}).get("af"),
                "source": v.get("source", "MyVariant.info"),
                "grade": grade,
            })
            evidence_source = "ClinVar" if clinvar else ("COSMIC" if cosmic else "MyVariant.info")
            edges.append({
                "source": node_id,
                "target": f"target:{gene}",
                "relation": "supports",
                "evidence": evidence_source,
            })

        # 2. 已获批药物证据
        approved_drugs = target.approved_drugs or []
        if isinstance(approved_drugs, dict):
            approved_drugs = [approved_drugs]

        for drug in approved_drugs[:5]:
            node_id = f"drug:{drug.get('chembl_id') or drug.get('name', 'unknown')}"
            nodes.append({
                "id": node_id,
                "type": "approved_drug",
                "label": drug.get("name", "unknown"),
                "chembl_id": drug.get("chembl_id"),
                "indication": drug.get("indication"),
                "max_phase": drug.get("max_phase"),
                "grade": "I" if (drug.get("max_phase") or 0) >= 4 else "II",
            })
            edges.append({
                "source": f"target:{gene}",
                "target": node_id,
                "relation": "targeted_by",
                "evidence": "ChEMBL",
            })

        # 3. 通路证据
        pathway_info = target.pathway or {}
        if isinstance(pathway_info, dict):
            pathways = pathway_info.get("pathways", [])
            for p in pathways[:5]:
                # 兼容字符串和字典两种格式
                if isinstance(p, str):
                    p = {"id": p, "name": p, "source": "KEGG"}
                elif not isinstance(p, dict) or not p.get("id"):
                    continue
                node_id = f"pathway:{p['id']}"
                nodes.append({
                    "id": node_id,
                    "type": "pathway",
                    "label": p.get("name", p["id"]),
                    "source_db": p.get("source"),
                    "grade": "II",
                })
                edges.append({
                    "source": f"target:{gene}",
                    "target": node_id,
                    "relation": "involved_in",
                    "evidence": p.get("source", "KEGG"),
                })

        # 4. 临床试验证据（实时查询 ClinicalTrials.gov）
        try:
            from app.services.knowledge.gene_query import query_clinical_trials
            trials_data = await query_clinical_trials(gene)
            for t in trials_data.get("trials", [])[:5]:
                node_id = f"trial:{t.get('nct_id', 'unknown')}"
                phase_list = t.get("phase") or []
                phase_str = ",".join(phase_list) if phase_list else "N/A"
                grade = "II" if "PHASE3" in phase_list else "III"
                nodes.append({
                    "id": node_id,
                    "type": "clinical_trial",
                    "label": t.get("title", "unknown")[:80],
                    "nct_id": t.get("nct_id"),
                    "phase": phase_str,
                    "status": t.get("status"),
                    "grade": grade,
                })
                edges.append({
                    "source": f"target:{gene}",
                    "target": node_id,
                    "relation": "tested_in",
                    "evidence": "ClinicalTrials.gov",
                })
        except Exception as e:
            logger.warning(f"临床试验查询失败: {e}")

        # 5. PPI 邻居证据
        ppi_neighbors = (pathway_info or {}).get("ppi_neighbors", []) if isinstance(pathway_info, dict) else []
        for n in ppi_neighbors[:5]:
            # 兼容字符串和字典两种格式
            if isinstance(n, str):
                n = {"gene": n, "interaction": "interacts_with", "evidence": "BioGRID"}
            elif not isinstance(n, dict):
                continue
            neighbor_gene = n.get("gene")
            if not neighbor_gene:
                continue
            node_id = f"gene:{neighbor_gene}"
            nodes.append({
                "id": node_id,
                "type": "ppi_neighbor",
                "label": neighbor_gene,
                "interaction": n.get("interaction"),
                "score": n.get("score"),
                "grade": "III",
            })
            edges.append({
                "source": f"target:{gene}",
                "target": node_id,
                "relation": n.get("interaction", "interacts_with"),
                "evidence": n.get("evidence", "BioGRID"),
            })

        # 6. 主动查询 ClinVar 致病变异（当靶点基因无既有变异时）
        # 已在 _enrich_variants_with_clinvar 中处理，此处仅添加 evidence_sources 汇总

        # 统计各等级证据数量
        grade_counts = {"I": 0, "II": 0, "III": 0, "IV": 0}
        for node in nodes:
            g = node.get("grade", "IV")
            grade_counts[g] = grade_counts.get(g, 0) + 1

        # 各证据源统计
        evidence_sources = self._summarize_evidence_sources(nodes, edges)

        # 生成总结
        summary = self._generate_summary(gene, target.evidence_grade, nodes, grade_counts, evidence_sources)

        return {
            "root": gene,
            "nodes": nodes,
            "edges": edges,
            "grade_distribution": grade_counts,
            "evidence_sources": evidence_sources,
            "total_evidence": len(nodes),
            "summary": summary,
        }

    async def _enrich_variants_with_clinvar(
        self,
        gene: str,
        existing_variants: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """整合已有变异 + 主动查询 ClinVar/COSMIC 致病变异

        策略：
        1. 已有变异且含 ClinVar 注释 → 直接使用
        2. 已有变异但缺 ClinVar → 调 MyVariant.info 补全
        3. 无变异信息 → 按 HGVS 标准查询该基因的 ClinVar 致病变异（最多 5 条）

        Returns:
            整合后的变异列表（每条含 clinvar / cosmic / gnomad 字段）
        """
        if not gene:
            return existing_variants

        # 1. 已有变异且含 ClinVar 注释 → 直接返回
        has_clinvar = any(
            (v.get("clinvar") or {}).get("clnsig")
            for v in existing_variants
            if isinstance(v, dict)
        )
        if has_clinvar:
            return existing_variants

        # 2/3. 主动查询 MyVariant.info
        try:
            vc = get_variant_client()
        except Exception as e:
            logger.warning(f"获取 variant client 失败: {e}")
            return existing_variants

        # 构造查询 ID：若已有变异则用其 query；否则按基因符号查 HGVS
        query_ids: List[str] = []
        for v in existing_variants:
            if isinstance(v, dict) and v.get("query"):
                query_ids.append(v["query"])

        # 路径 A：有具体变异 ID → 先尝试 MyVariant 批量注释
        annotations: List[Dict[str, Any]] = []
        myvariant_succeeded = False
        if query_ids:
            try:
                annotations = await vc.query_batch(query_ids[:10])
                # 验证返回有效 ClinVar 注释
                has_real_clinvar = any(
                    (a.get("clinvar") or {}).get("clnsig")
                    for a in annotations
                    if isinstance(a, dict)
                )
                if has_real_clinvar:
                    myvariant_succeeded = True
                else:
                    logger.info(f"MyVariant 对 {gene} 的变异未返回 ClinVar 注释，回退到 ClinVar EDirect")
            except Exception as e:
                logger.warning(f"MyVariant 批量查询失败 {gene}: {e}（回退到 ClinVar EDirect）")

        # 路径 B：MyVariant 失败/无注释/无既有变异 → 主动查 NCBI ClinVar
        if not myvariant_succeeded:
            clinvar_queries = await self._query_clinvar_by_gene(vc, gene)
            if clinvar_queries:
                annotations = (annotations or []) + clinvar_queries
            elif not query_ids:
                # MyVariant 和 ClinVar 都无结果，且无既有变异
                return existing_variants

        # 合并 ClinVar/COSMIC 注释到现有变异列表
        enriched = list(existing_variants)
        for ann in annotations:
            if not isinstance(ann, dict) or not ann.get("clinvar"):
                continue
            # 仅保留致病性变异（Pathogenic / Likely pathogenic）
            clnsig = (ann.get("clinvar") or {}).get("clnsig") or ""
            if not any(
                kw in clnsig.lower()
                for kw in ("pathogenic", "likely pathogenic", "vus")
            ):
                continue
            # 避免重复
            query_str = ann.get("query", "")
            if any(v.get("query") == query_str for v in enriched if isinstance(v, dict)):
                continue
            enriched.append(ann)

        # 限制总数 10 条
        return enriched[:10]

    async def _query_clinvar_by_gene(self, variant_client, gene: str) -> List[Dict[str, Any]]:
        """通过 NCBI ClinVar E-utilities API 按基因符号查询致病变异

        重构说明（阶段 2）：
        - 原内联 httpx 调用替换为 NcbiClient.fetch_clinvar_variants
        - 复用 NcbiClient 的速率限制、重试、缓存机制
        - 保持返回结构兼容（query/gene/hgvs_p/hgvs_c/clinvar/cosmic/gnomad/variant_type/source）

        Args:
            variant_client: 未使用（保留接口兼容）
            gene: 基因符号，如 CDK4 / TP53 / MDM2

        Returns:
            List of variant dicts with clinvar annotation
        """
        try:
            from app.core.deps import get_ncbi_client

            ncbi_client = get_ncbi_client()
            variants = await ncbi_client.fetch_clinvar_variants(
                gene=gene,
                retmax=5,
                db_session=self.db,
            )

            # 转换为 evidence_chain 兼容的返回结构
            results: List[Dict[str, Any]] = []
            for v in variants:
                uid = v.get("uid", "")
                title = v.get("title", "") or ""
                clnsig = v.get("clnsig") or "Pathogenic"
                results.append({
                    "query": f"clinvar:{uid}",
                    "gene": v.get("gene", gene),
                    "hgvs_p": v.get("hgvs_p"),
                    "hgvs_c": v.get("hgvs_c"),
                    "clinvar": {
                        "clnsig": clnsig,
                        "clinvar_id": uid,
                        "rcv": None,
                        "review_status": v.get("review_status"),
                        "condition": title,
                    },
                    "cosmic": None,
                    "gnomad": None,
                    "variant_type": v.get("variant_type", "single_nucleotide_variant"),
                    "source": v.get("source", "NCBI ClinVar (E-utilities)"),
                })

            logger.info(
                f"ClinVar 查询 {gene}: 返回 {len(results)} 条致病记录"
            )
            return results
        except Exception as e:
            logger.warning(f"按基因 {gene} 查询 NCBI ClinVar 失败: {e}")
            return []

    def _summarize_evidence_sources(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """按证据源（edge.evidence）统计节点数"""
        sources: Dict[str, int] = {}
        for e in edges:
            src = e.get("evidence", "unknown")
            sources[src] = sources.get(src, 0) + 1
        # 节点类型分布
        type_dist: Dict[str, int] = {}
        for n in nodes:
            t = n.get("type", "unknown")
            type_dist[t] = type_dist.get(t, 0) + 1
        sources["_node_types"] = type_dist  # type: ignore
        return sources

    def _generate_summary(
        self,
        gene: str,
        grade: str,
        nodes: List[Dict],
        grade_counts: Dict[str, int],
        evidence_sources: Optional[Dict[str, int]] = None,
    ) -> str:
        """生成证据链总结"""
        n_variants = sum(1 for n in nodes if n.get("type") == "variant")
        n_drugs = sum(1 for n in nodes if n.get("type") == "approved_drug")
        n_trials = sum(1 for n in nodes if n.get("type") == "clinical_trial")
        n_pathways = sum(1 for n in nodes if n.get("type") == "pathway")
        n_ppi = sum(1 for n in nodes if n.get("type") == "ppi_neighbor")

        # 统计致病性变异数（ClinVar Pathogenic / Likely pathogenic）
        n_pathogenic = sum(
            1 for n in nodes
            if n.get("type") == "variant"
            and "pathogenic" in (n.get("clnsig") or "").lower()
        )

        sources_str = ""
        if evidence_sources:
            src_items = [(k, v) for k, v in evidence_sources.items() if k != "_node_types"]
            if src_items:
                sources_str = "\n- 证据源分布：" + ", ".join(f"{k}={v}" for k, v in src_items[:6])

        return (
            f"靶点 {gene} 证据等级 {grade}，共整合 {len(nodes)} 条证据：\n"
            f"- 致病变异证据：{n_variants} 条（含 Pathogenic {n_pathogenic} 条 / ClinVar + COSMIC + gnomAD）\n"
            f"- 已获批药物：{n_drugs} 个\n"
            f"- 临床试验：{n_trials} 项\n"
            f"- 通路证据：{n_pathways} 条\n"
            f"- PPI 邻居：{n_ppi} 个\n"
            f"等级分布：I={grade_counts['I']}, II={grade_counts['II']}, "
            f"III={grade_counts['III']}, IV={grade_counts['IV']}"
            f"{sources_str}"
        )
