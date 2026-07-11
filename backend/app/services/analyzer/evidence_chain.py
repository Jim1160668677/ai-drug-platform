"""证据链构建器 — 整合 ClinVar/COSMIC/ChEMBL/ClinicalTrials 多源证据"""
import logging
from typing import Any, Dict, List

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

        # 1. 变异证据（来自 target.variant_info）
        variant_infos = target.variant_info or []
        if isinstance(variant_infos, dict):
            variant_infos = [variant_infos]

        for i, v in enumerate(variant_infos[:10]):
            node_id = f"variant:{v.get('query', f'v{i}')}"
            clinvar = v.get("clinvar") or {}
            cosmic = v.get("cosmic") or {}
            nodes.append({
                "id": node_id,
                "type": "variant",
                "label": v.get("hgvs_p") or v.get("query", "unknown"),
                "clnsig": clinvar.get("clnsig"),
                "cosmic_id": cosmic.get("cosmic_id"),
                "grade": "I" if "pathogenic" in (clinvar.get("clnsig") or "").lower() else "III",
            })
            edges.append({
                "source": node_id,
                "target": f"target:{gene}",
                "relation": "supports",
                "evidence": "ClinVar/COSMIC",
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
                "grade": "I",
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

        # 4. 临床试验证据（实时查询）
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

        # 统计各等级证据数量
        grade_counts = {"I": 0, "II": 0, "III": 0, "IV": 0}
        for node in nodes:
            g = node.get("grade", "IV")
            grade_counts[g] = grade_counts.get(g, 0) + 1

        # 生成总结
        summary = self._generate_summary(gene, target.evidence_grade, nodes, grade_counts)

        return {
            "root": gene,
            "nodes": nodes,
            "edges": edges,
            "grade_distribution": grade_counts,
            "total_evidence": len(nodes),
            "summary": summary,
        }

    def _generate_summary(
        self,
        gene: str,
        grade: str,
        nodes: List[Dict],
        grade_counts: Dict[str, int],
    ) -> str:
        """生成证据链总结"""
        n_variants = sum(1 for n in nodes if n.get("type") == "variant")
        n_drugs = sum(1 for n in nodes if n.get("type") == "approved_drug")
        n_trials = sum(1 for n in nodes if n.get("type") == "clinical_trial")
        n_pathways = sum(1 for n in nodes if n.get("type") == "pathway")
        n_ppi = sum(1 for n in nodes if n.get("type") == "ppi_neighbor")

        return (
            f"靶点 {gene} 证据等级 {grade}，共整合 {len(nodes)} 条证据：\n"
            f"- 变异证据：{n_variants} 条（ClinVar/COSMIC）\n"
            f"- 已获批药物：{n_drugs} 个\n"
            f"- 临床试验：{n_trials} 项\n"
            f"- 通路证据：{n_pathways} 条\n"
            f"- PPI 邻居：{n_ppi} 个\n"
            f"等级分布：I={grade_counts['I']}, II={grade_counts['II']}, "
            f"III={grade_counts['III']}, IV={grade_counts['IV']}"
        )
