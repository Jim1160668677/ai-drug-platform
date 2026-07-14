"""生信分析引擎 — 差异表达 / 聚类 / 通路富集 / PCA

Mock 模式下返回预置数据；Real 模式使用 scipy + sklearn + gseapy 计算。
所有方法支持 random_state 可重复性参数，返回 plot_data 可视化数据和 parameters 参数记录。
"""
import logging
import math
import random
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class BioAnalyzer:
    """生信分析核心引擎"""

    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock

    async def differential_expression(
        self,
        expression_data: Dict[str, List[float]],
        group_a: List[str],
        group_b: List[str],
        fdr_threshold: float = 0.05,
        random_state: int = 42,
    ) -> Dict[str, Any]:
        """差异表达分析 — t-test + fold change + FDR 校正

        Args:
            expression_data: {gene: [expr_a1, expr_a2, ..., expr_b1, ...]}
            group_a: 组 A 样本索引（如 ["s1", "s2"]）
            group_b: 组 B 样本索引
            fdr_threshold: FDR 阈值
            random_state: 随机种子（可重复性）
        Returns:
            {genes: [...], volcano_data: [...], plot_data: {...}, parameters: {...}}
        """
        params = {
            "method": "t-test",
            "fdr_threshold": fdr_threshold,
            "random_state": random_state,
            "group_a_size": len(group_a),
            "group_b_size": len(group_b),
        }
        if self.use_mock:
            result = self._mock_de(group_a, group_b)
            result["parameters"] = params
            return result

        # Real 模式：使用 scipy 计算
        try:
            from scipy import stats

            results = []
            for gene, values in expression_data.items():
                a_vals = values[: len(group_a)]
                b_vals = values[len(group_a):]
                if len(a_vals) < 2 or len(b_vals) < 2:
                    continue
                t_stat, pval = stats.ttest_ind(a_vals, b_vals)
                mean_a = np.mean(a_vals) or 0.001
                mean_b = np.mean(b_vals) or 0.001
                log2fc = math.log2(mean_b / mean_a)
                results.append({
                    "gene": gene,
                    "log2fc": round(log2fc, 4),
                    "pvalue": round(pval, 6),
                    "regulation": "up" if log2fc > 0 else "down",
                })

            # BH FDR 校正
            results = self._bh_fdr(results, fdr_threshold)
            formatted = self._format_de_results(results)
            formatted["parameters"] = params
            return formatted
        except Exception as e:
            logger.warning(f"差异表达分析降级到 Mock: {e}")
            result = self._mock_de(group_a, group_b)
            result["parameters"] = {**params, "fallback": "mock", "error": str(e)}
            return result

    async def clustering(
        self,
        expression_data: Dict[str, List[float]],
        method: str = "kmeans",
        n_clusters: int = 5,
        random_state: int = 42,
    ) -> Dict[str, Any]:
        """聚类分析 — K-means / 层次聚类

        Args:
            expression_data: {gene: [expr_values]}
            method: 聚类方法 kmeans/hierarchical
            n_clusters: 簇数量
            random_state: 随机种子（可重复性）
        Returns:
            {clusters: [...], cluster_centers: [...], plot_data: {...}, parameters: {...}}
        """
        params = {
            "method": method,
            "n_clusters": n_clusters,
            "random_state": random_state,
        }
        if self.use_mock:
            result = self._mock_clustering(n_clusters)
            result["parameters"] = params
            return result

        try:
            from sklearn.cluster import KMeans
            from sklearn.decomposition import PCA

            genes = list(expression_data.keys())
            matrix = np.array([expression_data[g] for g in genes])

            # PCA 降维
            pca = PCA(n_components=2, random_state=random_state)
            pca_coords = pca.fit_transform(matrix)

            # 聚类
            kmeans = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
            labels = kmeans.fit_predict(matrix)

            clusters = [
                {"gene": genes[i], "cluster_id": int(labels[i]),
                 "pca_x": round(float(pca_coords[i][0]), 4),
                 "pca_y": round(float(pca_coords[i][1]), 4)}
                for i in range(len(genes))
            ]
            centers = [
                {"x": round(float(c[0]), 4), "y": round(float(c[1]), 4)}
                for c in pca.transform(kmeans.cluster_centers_)
            ]
            # 生成 heatmap 数据（取前 50 个基因）
            top_genes = genes[:50]
            heatmap_values = [
                [round(float(expression_data[g][j]), 4) for j in range(min(len(expression_data[g]), 20))]
                for g in top_genes
            ]
            return {
                "clusters": clusters,
                "cluster_centers": centers,
                "method": method,
                "n_clusters": n_clusters,
                "plot_data": {
                    "scatter": {
                        "points": [{"x": c["pca_x"], "y": c["pca_y"], "cluster": c["cluster_id"], "label": c["gene"]} for c in clusters],
                        "centers": centers,
                    },
                    "heatmap": {
                        "genes": top_genes,
                        "values": heatmap_values,
                    },
                },
                "parameters": params,
            }
        except Exception as e:
            logger.warning(f"聚类分析降级到 Mock: {e}")
            result = self._mock_clustering(n_clusters)
            result["parameters"] = {**params, "fallback": "mock", "error": str(e)}
            return result

    async def pathway_enrichment(
        self,
        gene_list: List[str],
        source: str = "kegg",
        pval_threshold: float = 0.05,
        random_state: int = 42,
    ) -> Dict[str, Any]:
        """通路富集 — GO / KEGG / Enrichr（通过 gseapy）

        Args:
            gene_list: 基因符号列表
            source: 通路来源 kegg/go/enrichr
            pval_threshold: p 值阈值
            random_state: 随机种子（可重复性）
        Returns:
            {pathways: [...], source, plot_data: {...}, parameters: {...}}
        """
        params = {
            "source": source,
            "pval_threshold": pval_threshold,
            "random_state": random_state,
            "input_genes": len(gene_list),
        }
        if self.use_mock:
            result = self._mock_pathway(gene_list, source)
            result["parameters"] = params
            return result

        # Real 模式：尝试调用 gseapy Enrichr API
        try:
            import gseapy

            gene_sets_map = {
                "kegg": "KEGG_2021_Human",
                "go": "GO_Biological_Process_2023",
                "enrichr": "ENCODE_and_ChEA_Consensus_TFs_from_ChIP-X",
            }
            gene_sets = gene_sets_map.get(source, gene_sets_map["kegg"])

            enr = gseapy.enrichr(
                gene_list=gene_list,
                gene_sets=gene_sets,
                organism="human",
                outdir=None,
                cutoff=pval_threshold,
            )

            # 解析 gseapy 结果
            pathways = []
            df = enr.results if hasattr(enr, "results") else enr
            if hasattr(df, "iterrows"):
                for _, row in df.head(20).iterrows():
                    overlap = row.get("Overlap", "0/1")
                    hits, total = overlap.split("/") if "/" in overlap else (0, 1)
                    pathways.append({
                        "id": row.get("Term", "").split("__")[0][:50],
                        "name": row.get("Term", ""),
                        "pvalue": float(row.get("P-value", 1.0)),
                        "genes": row.get("Genes", "").split(";")[:10],
                        "ratio": int(hits) / max(int(total), 1),
                        "adjusted_pvalue": float(row.get("Adjusted P-value", 1.0)),
                    })
            else:
                # gseapy 返回的不是 DataFrame，降级
                raise ValueError("gseapy 返回格式异常")

            result = {
                "pathways": pathways,
                "source": f"gseapy_{source}",
                "input_genes": len(gene_list),
                "plot_data": {
                    "bar_plot": {
                        "labels": [p["name"][:30] for p in pathways[:10]],
                        "values": [-math.log10(max(p["pvalue"], 1e-10)) for p in pathways[:10]],
                        "pvalues": [p["pvalue"] for p in pathways[:10]],
                    },
                },
                "parameters": params,
            }
            return result
        except ImportError:
            logger.warning("gseapy 未安装，降级到 Mock 通路富集")
            result = self._mock_pathway(gene_list, source)
            result["parameters"] = {**params, "fallback": "mock", "error": "gseapy not installed"}
            return result
        except Exception as e:
            logger.warning(f"通路富集降级到 Mock: {e}")
            result = self._mock_pathway(gene_list, source)
            result["parameters"] = {**params, "fallback": "mock", "error": str(e)}
            return result

    async def pca_analysis(
        self,
        expression_data: Dict[str, List[float]],
        n_components: int = 2,
        random_state: int = 42,
    ) -> Dict[str, Any]:
        """PCA 主成分分析

        Args:
            expression_data: {sample: [expr_values]}
            n_components: 主成分数量
            random_state: 随机种子（可重复性）
        Returns:
            {samples: [...], explained_variance: [...], plot_data: {...}, parameters: {...}}
        """
        params = {
            "n_components": n_components,
            "random_state": random_state,
        }
        if self.use_mock:
            result = self._mock_pca()
            result["parameters"] = params
            return result

        try:
            from sklearn.decomposition import PCA

            samples = list(expression_data.keys())
            matrix = np.array([expression_data[s] for s in samples])
            pca = PCA(n_components=n_components, random_state=random_state)
            coords = pca.fit_transform(matrix)
            sample_points = [
                {"sample": samples[i],
                 "pc1": round(float(coords[i][0]), 4),
                 "pc2": round(float(coords[i][1]), 4)}
                for i in range(len(samples))
            ]
            explained = [round(float(v), 4) for v in pca.explained_variance_ratio_]
            return {
                "samples": sample_points,
                "explained_variance": explained,
                "plot_data": {
                    "scatter": {
                        "points": [{"x": s["pc1"], "y": s["pc2"], "label": s["sample"]} for s in sample_points],
                        "x_label": f"PC1 ({explained[0]*100:.1f}%)" if explained else "PC1",
                        "y_label": f"PC2 ({explained[1]*100:.1f}%)" if len(explained) > 1 else "PC2",
                    },
                },
                "parameters": params,
            }
        except Exception as e:
            logger.warning(f"PCA 降级到 Mock: {e}")
            result = self._mock_pca()
            result["parameters"] = {**params, "fallback": "mock", "error": str(e)}
            return result

    # ========== 内部方法 ==========

    @staticmethod
    def _bh_fdr(results: List[dict], threshold: float) -> List[dict]:
        """Benjamini-Hochberg FDR 校正"""
        n = len(results)
        sorted_results = sorted(results, key=lambda x: x["pvalue"])
        for i, r in enumerate(sorted_results):
            r["padj"] = round(min(r["pvalue"] * n / (i + 1), 1.0), 6)
            r["significant"] = r["padj"] < threshold
        return sorted_results

    @staticmethod
    def _format_de_results(results: List[dict]) -> Dict[str, Any]:
        up = [r for r in results if r.get("regulation") == "up" and r.get("significant")]
        down = [r for r in results if r.get("regulation") == "down" and r.get("significant")]
        volcano = [
            {"x": r["log2fc"], "y": -math.log10(max(r["pvalue"], 1e-10)),
             "gene": r["gene"], "significant": r.get("significant", False)}
            for r in results
        ]
        return {
            "genes": results,
            "volcano_data": volcano,
            "plot_data": {
                "volcano_plot": {
                    "points": volcano,
                    "x_label": "log2 Fold Change",
                    "y_label": "-log10(p-value)",
                },
            },
            "summary": {"total": len(results), "up_regulated": len(up), "down_regulated": len(down)},
        }

    @staticmethod
    def _mock_de(group_a: List[str], group_b: List[str]) -> Dict[str, Any]:
        """Mock 差异表达数据"""
        random.seed(42)
        genes = [f"GENE{i:04d}" for i in range(200)]
        results = []
        for g in genes:
            log2fc = round(random.gauss(0, 2), 4)
            pval = round(random.uniform(0, 1), 6)
            results.append({
                "gene": g,
                "log2fc": log2fc,
                "pvalue": pval,
                "padj": round(min(pval * 200 / (results.__len__() + 1), 1.0), 6),
                "regulation": "up" if log2fc > 0 else "down",
                "significant": pval < 0.05,
            })
        formatted = BioAnalyzer._format_de_results(results)
        # Mock 也添加 plot_data（已在 _format_de_results 中添加）
        return formatted

    @staticmethod
    def _mock_clustering(n_clusters: int) -> Dict[str, Any]:
        random.seed(42)
        genes = [f"GENE{i:04d}" for i in range(100)]
        clusters = []
        for g in genes:
            cid = random.randint(0, n_clusters - 1)
            clusters.append({
                "gene": g,
                "cluster_id": cid,
                "pca_x": round(random.gauss(cid * 3, 1), 4),
                "pca_y": round(random.gauss(cid * 2, 1), 4),
            })
        centers = [{"x": i * 3, "y": i * 2} for i in range(n_clusters)]
        # 生成 Mock heatmap 数据
        top_genes = genes[:50]
        heatmap_values = [
            [round(random.gauss(0, 2), 4) for _ in range(20)]
            for _ in top_genes
        ]
        return {
            "clusters": clusters,
            "cluster_centers": centers,
            "method": "kmeans",
            "n_clusters": n_clusters,
            "plot_data": {
                "scatter": {
                    "points": [{"x": c["pca_x"], "y": c["pca_y"], "cluster": c["cluster_id"], "label": c["gene"]} for c in clusters],
                    "centers": centers,
                },
                "heatmap": {
                    "genes": top_genes,
                    "values": heatmap_values,
                },
            },
        }

    @staticmethod
    def _mock_pathway(gene_list: List[str], source: str) -> Dict[str, Any]:
        """Mock 通路富集"""
        pathways = [
            {"id": "hsa00010", "name": "糖酵解/糖异生", "pvalue": 0.001, "genes": gene_list[:5], "ratio": 0.15},
            {"id": "hsa00020", "name": "TCA 循环", "pvalue": 0.003, "genes": gene_list[2:6], "ratio": 0.12},
            {"id": "hsa03010", "name": "核糖体", "pvalue": 0.008, "genes": gene_list[5:10], "ratio": 0.10},
            {"id": "hsa04110", "name": "细胞周期", "pvalue": 0.015, "genes": gene_list[8:12], "ratio": 0.08},
            {"id": "hsa04151", "name": "PI3K-Akt 信号通路", "pvalue": 0.025, "genes": gene_list[10:15], "ratio": 0.07},
        ]
        return {
            "pathways": pathways,
            "source": source,
            "input_genes": len(gene_list),
            "plot_data": {
                "bar_plot": {
                    "labels": [p["name"][:30] for p in pathways],
                    "values": [-math.log10(max(p["pvalue"], 1e-10)) for p in pathways],
                    "pvalues": [p["pvalue"] for p in pathways],
                },
            },
        }

    @staticmethod
    def _mock_pca() -> Dict[str, Any]:
        random.seed(42)
        samples = [f"S{i:03d}" for i in range(20)]
        sample_points = [
            {"sample": s, "pc1": round(random.gauss(0, 3), 4), "pc2": round(random.gauss(0, 2), 4)}
            for s in samples
        ]
        explained = [0.45, 0.22]
        return {
            "samples": sample_points,
            "explained_variance": explained,
            "plot_data": {
                "scatter": {
                    "points": [{"x": s["pc1"], "y": s["pc2"], "label": s["sample"]} for s in sample_points],
                    "x_label": f"PC1 ({explained[0]*100:.1f}%)",
                    "y_label": f"PC2 ({explained[1]*100:.1f}%)",
                },
            },
        }


__all__ = ["BioAnalyzer"]
