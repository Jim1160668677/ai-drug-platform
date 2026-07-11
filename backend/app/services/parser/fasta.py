"""FASTA 解析器 — BioPython 解析序列"""
import os
from typing import Any, Dict

from app.services.parser.base import Parser


class FastaParser(Parser):
    """FASTA 序列文件解析器"""

    async def parse(self, dataset, db=None) -> Dict[str, Any]:
        path = dataset.storage_path
        if not path or not os.path.exists(path):
            return {
                "summary": {"error": f"文件不存在: {path}"},
                "quality_metrics": {},
            }

        try:
            from Bio import SeqIO
        except ImportError as e:
            return {
                "summary": {"error": f"BioPython 未安装: {e}"},
                "quality_metrics": {},
            }

        sequences = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for record in SeqIO.parse(f, "fasta"):
                    sequences.append({
                        "id": record.id,
                        "description": record.description,
                        "length": len(record.seq),
                        "gc_content": self._gc_content(str(record.seq)),
                    })
        except Exception as e:
            return {
                "summary": {"error": f"FASTA 解析失败: {e}"},
                "quality_metrics": {},
            }

        if not sequences:
            return {
                "summary": {"error": "FASTA 文件无有效序列"},
                "quality_metrics": {},
            }

        lengths = [s["length"] for s in sequences]
        gc_values = [s["gc_content"] for s in sequences]
        n50 = self._compute_n50(lengths)

        total_length = sum(lengths)
        avg_length = total_length / len(sequences) if sequences else 0
        avg_gc = sum(gc_values) / len(gc_values) if gc_values else 0

        length_bins = {"<500": 0, "500-2000": 0, "2000-10000": 0, ">10000": 0}
        for L in lengths:
            if L < 500:
                length_bins["<500"] += 1
            elif L < 2000:
                length_bins["500-2000"] += 1
            elif L < 10000:
                length_bins["2000-10000"] += 1
            else:
                length_bins[">10000"] += 1

        return {
            "summary": {
                "sequence_count": len(sequences),
                "total_length": total_length,
                "avg_length": round(avg_length, 2),
                "min_length": min(lengths),
                "max_length": max(lengths),
                "gc_content": round(avg_gc, 4),
                "top_sequences_by_length": sorted(
                    [{"id": s["id"], "length": s["length"], "gc": s["gc_content"]} for s in sequences],
                    key=lambda x: x["length"],
                    reverse=True,
                )[:10],
            },
            "quality_metrics": {
                "n50": n50,
                "length_distribution": length_bins,
                "data_type": "fasta",
            },
        }

    def _gc_content(self, seq: str) -> float:
        if not seq:
            return 0.0
        gc = seq.upper().count("G") + seq.upper().count("C")
        return gc / len(seq)

    def _compute_n50(self, lengths: list) -> int:
        if not lengths:
            return 0
        sorted_lengths = sorted(lengths, reverse=True)
        total = sum(sorted_lengths)
        cumulative = 0
        for L in sorted_lengths:
            cumulative += L
            if cumulative >= total / 2:
                return L
        return sorted_lengths[-1]
