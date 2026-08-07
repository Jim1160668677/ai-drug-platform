"""Shared: identify metadata columns in CSV/TSV data matrices.

Used by ProteomicsParser / MetabolomicsParser / RnaSeqParser.

Main API:
- is_metadata_column(name, dtype=None)
- split_metadata_columns(df) -> (numeric_data_matrix, metadata_columns)

Design:
1. String columns (gene_id/gene_name/protein_name etc.) must be excluded,
   otherwise pandas 2.x df.mean(axis=1, numeric_only=False) raises TypeError.
2. Numeric metadata columns (pubchem_cid/mz/rt/length/IsoPct etc.) must be excluded,
   otherwise they pollute statistics.
"""
from __future__ import annotations

import re
from typing import Set, Tuple

import pandas as pd

_STRING_METADATA_COLUMNS: Set[str] = {
    "gene_id", "gene_name", "gene_symbol", "symbol", "name", "description",
    "transcript_id", "transcript_id(s)", "transcript_name",
    "protein_id", "protein_name", "protein_symbol", "uniprot_id",
    "metabolite", "metabolite_name", "compound_name", "compound_id",
    "kegg_id", "hmdb_id", "pubchem_cid", "chebi_id", "inchi", "smiles",
    "snp_id", "rsid", "variant_id",
    "desc", "source", "category", "group", "batch",
    "sample_id", "patient_id", "tissue", "tumor_type", "stage", "grade",
}

_NUMERIC_METADATA_COLUMNS: Set[str] = {
    "length", "effective_length", "isopct",
    "mz", "rt", "retention_time", "retention_index", "ccs",
    "peptide_count", "unique_peptides", "coverage", "mol_weight", "pi",
    "chr", "chrom", "chromosome", "pos", "position", "start", "end", "strand",
}

_NUMERIC_METADATA_PATTERNS = [
    re.compile(r"^(length|effective_length)(_\w+)?$", re.I),
    re.compile(r"^(mz|rt|retention_time|retention_index)(_\w+)?$", re.I),
    re.compile(r"^isopct(_\w+)?$", re.I),
    re.compile(r"^pubchem_cid$", re.I),
    re.compile(r"^coverage(_pct|_percent)?$", re.I),
]


def is_metadata_column(name, dtype=None):
    if name is None:
        return False
    lower = str(name).lower().strip()
    if lower in _STRING_METADATA_COLUMNS:
        return True
    if lower in _NUMERIC_METADATA_COLUMNS:
        return True
    for pat in _NUMERIC_METADATA_PATTERNS:
        if pat.match(lower):
            return True
    if dtype is not None and (dtype == object or pd.api.types.is_string_dtype(dtype)):
        for kw in ("id", "name", "desc", "symbol", "type", "group", "category", "source"):
            if kw in lower:
                return True
    return False


def split_metadata_columns(df):
    if df is None or len(df.columns) == 0:
        return df, pd.DataFrame(index=df.index if df is not None else None)
    metadata_cols = []
    data_cols = []
    for col in df.columns:
        if is_metadata_column(str(col), df[col].dtype):
            metadata_cols.append(col)
        else:
            data_cols.append(col)
    data_matrix = df[data_cols].select_dtypes(include=["number"])
    metadata = df[metadata_cols] if metadata_cols else pd.DataFrame(index=df.index)
    return data_matrix, metadata
