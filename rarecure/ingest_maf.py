"""Module 1: Variants. [C4] Chunked MAF reading."""
import logging
from pathlib import Path
import pandas as pd
from rarecure.config import CODING_VARIANT_TYPES
from rarecure.models import AnnotatedVariant, VariantReport, VariantTier

logger = logging.getLogger(__name__)
COLS = [
    "Hugo_Symbol", "Chromosome", "Start_Position", "Variant_Classification",
    "HGVSp_Short", "SIFT", "PolyPhen", "t_alt_count", "t_ref_count",
    "Tumor_Sample_Barcode",
]


def _vaf(r):
    a, rf = r.get("t_alt_count"), r.get("t_ref_count")
    if pd.notna(a) and pd.notna(rf) and (a + rf) > 0:
        return float(a) / (float(a) + float(rf))
    return None


def _sc(v):
    if pd.isna(v):
        return None
    s = str(v)
    if "(" in s:
        try:
            return float(s.split("(")[1].rstrip(")"))
        except (ValueError, IndexError):
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _tier(si, pp, vc):
    if vc in ("Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins"):
        return VariantTier.LIKELY_ACTIONABLE
    sd = si is not None and si < 0.05
    pd_ = pp is not None and pp > 0.85
    if sd and pd_:
        return VariantTier.LIKELY_ACTIONABLE
    if sd or pd_:
        return VariantTier.UNCERTAIN
    return VariantTier.LIKELY_PASSENGER


def ingest_maf(maf_path, patient_id=None, id_fn=None):
    maf_path = Path(maf_path)
    logger.info(f"MAF (chunked): {maf_path}")
    ext = id_fn or (lambda x: str(x)[:12])
    pvars = {}
    for chunk in pd.read_csv(
        maf_path, sep="\t", comment="#", low_memory=False,
        chunksize=100_000, usecols=lambda c: c in COLS
    ):
        chunk = chunk[chunk["Variant_Classification"].isin(CODING_VARIANT_TYPES)]
        if patient_id:
            chunk = chunk[chunk["Tumor_Sample_Barcode"].str.startswith(patient_id)]
        for _, row in chunk.iterrows():
            pid = ext(row["Tumor_Sample_Barcode"])
            si, pp = _sc(row.get("SIFT")), _sc(row.get("PolyPhen"))
            v = AnnotatedVariant(
                gene=row["Hugo_Symbol"],
                chromosome=str(row.get("Chromosome", "")),
                position=int(row["Start_Position"]) if pd.notna(row.get("Start_Position")) else None,
                variant_classification=row["Variant_Classification"],
                hgvsp=row.get("HGVSp_Short") if pd.notna(row.get("HGVSp_Short")) else None,
                vaf=_vaf(row), sift_score=si, polyphen_score=pp,
                tier=_tier(si, pp, row["Variant_Classification"]))
            pvars.setdefault(pid, []).append(v)
    reports = {}
    for pid, vs in pvars.items():
        act = list(set(v.gene for v in vs if v.tier.value <= 2))
        reports[pid] = VariantReport(
            patient_id=pid, total_variants_raw=len(vs),
            total_variants_coding=len(vs), variants=vs,
            actionable_genes=act, zero_variant_flag=len(vs) == 0)
    logger.info(f"Processed {len(reports)} patients")
    return reports


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python -m rarecure.ingest_maf <maf>")
        exit(1)
    for pid, r in list(ingest_maf(sys.argv[1]).items())[:3]:
        print(f"{pid}: {r.total_variants_coding} coding, {len(r.actionable_genes)} actionable")
