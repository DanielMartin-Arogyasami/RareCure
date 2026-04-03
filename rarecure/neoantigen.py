"""Module 2: Neoantigen Prediction (STUB)."""
import logging
from rarecure.config import NEO
from rarecure.models import NeoantigenReport, HLAMode

logger = logging.getLogger(__name__)


def get_hla_alleles(pid, provided=None, lookup=None):
    if provided:
        return provided, HLAMode.PERSONALIZED
    if lookup and pid in lookup:
        return lookup[pid], HLAMode.PERSONALIZED
    logger.warning(f"No HLA for {pid}, Mode B")
    return NEO.FALLBACK_HLA_ALLELES, HLAMode.ESTIMATED


def predict_neoantigens(variants, hla, mode, pid="?", rna=None):
    w = "HLA estimated. Confirm with typing." if mode == HLAMode.ESTIMATED else None
    return NeoantigenReport(
        patient_id=pid, hla_mode=mode, hla_alleles_used=hla,
        total_candidates_unfiltered=0, total_candidates_filtered=0,
        candidates=[], hla_mode_warning=w)
