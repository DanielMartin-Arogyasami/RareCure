#!/usr/bin/env python3
"""
RareCure Batch Runner

Process all TCGA-SARC patients through the pipeline.

    cd RareCure
    export ANTHROPIC_API_KEY="sk-..."
    python scripts/batch_run.py --max-patients 3 --clinical-only

Options:
  --max-patients N    Process only first N patients (for testing)
  --skip-existing     Skip patients with existing result JSONs
  --clinical-only     Run Mode B only (no genomic data, faster)
  --output-dir DIR    Where to save JSONs (default: results/)
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from rarecure.config import RESULTS_DIR
from rarecure.models import PatientProfile, InputMode
from rarecure.pipeline import RareCurePipeline
from rarecure.llm_client import get_llm_client

logger = logging.getLogger(__name__)

# Column variants to handle GDC TSV format changes
COLUMN_VARIANTS = {
    "patient_id": ["submitter_id", "case_submitter_id", "bcr_patient_barcode", "case_id"],
    "diagnosis": ["primary_diagnosis", "diagnoses.0.primary_diagnosis", "disease_type"],
    "stage": ["ajcc_pathologic_stage", "diagnoses.0.ajcc_pathologic_stage", "tumor_stage", "clinical_stage"],
    "gender": ["gender", "demographic.gender", "sex"],
    "age_at_dx": ["age_at_diagnosis", "diagnoses.0.age_at_diagnosis", "age_at_index"],
    "site": ["site_of_resection_or_biopsy", "diagnoses.0.site_of_resection_or_biopsy", "tissue_or_organ_of_origin"],
}

def _find_column(df, field_name):
    for variant in COLUMN_VARIANTS.get(field_name, []):
        if variant in df.columns:
            return variant
    return None

def _normalize_diagnosis(raw):
    if pd.isna(raw) or not raw:
        return "sarcoma"
    raw = str(raw).strip().lower()
    mappings = {
        "leiomyosarcoma": "leiomyosarcoma",
        "undifferentiated pleomorphic sarcoma": "undifferentiated_pleomorphic_sarcoma",
        "dedifferentiated liposarcoma": "liposarcoma",
        "myxofibrosarcoma": "myxofibrosarcoma",
        "synovial sarcoma": "synovial_sarcoma",
        "mpnst": "mpnst",
        "gastrointestinal stromal tumor": "gastrointestinal_stromal_tumor",
        "spindle cell sarcoma": "spindle_cell_sarcoma",
        "osteosarcoma": "osteosarcoma",
        "chondrosarcoma": "chondrosarcoma",
        "rhabdomyosarcoma": "rhabdomyosarcoma",
    }
    for key, val in mappings.items():
        if key in raw:
            return val
    return raw.replace(" ", "_").replace(",", "").replace("-", "_")

def _age_from_days(days_val):
    if pd.isna(days_val): return 55
    try:
        days = float(days_val)
        return max(18, min(90, int(abs(days) / 365.25)))
    except (ValueError, TypeError):
        return 55

def load_clinical_data(clinical_path):
    logger.info(f"Loading clinical data: {clinical_path}")
    df = pd.read_csv(clinical_path, sep="\t", low_memory=False)

    pid_col = _find_column(df, "patient_id")
    dx_col = _find_column(df, "diagnosis")
    stage_col = _find_column(df, "stage")
    gender_col = _find_column(df, "gender")
    age_col = _find_column(df, "age_at_dx")
    site_col = _find_column(df, "site")

    patients = {}
    for _, row in df.iterrows():
        pid = str(row[pid_col]).strip()
        if not pid or pid == "nan": continue
        pid_short = pid[:12]

        patients[pid_short] = {
            "patient_id": pid_short,
            "cancer_type": _normalize_diagnosis(row.get(dx_col) if dx_col else None),
            "stage": str(row.get(stage_col, "")).strip() if stage_col and pd.notna(row.get(stage_col)) else None,
            "sex": "F" if str(row.get(gender_col, "")).strip().lower() in ("female", "f") else "M",
            "age": _age_from_days(row.get(age_col) if age_col else None),
            "primary_site": str(row.get(site_col, "")).strip() if site_col and pd.notna(row.get(site_col)) else None,
        }
    return patients

def load_hla_data(hla_path):
    hla_path = Path(hla_path)
    if not hla_path.exists():
        return {}
    df = pd.read_csv(hla_path, sep="\t", low_memory=False)

    pid_col = next((c for c in df.columns if c.lower() in ["patient", "barcode", "sample"]), df.columns[0])
    hla_cols = [c for c in df.columns if any(x in c.lower() for x in ["hla-a", "hla-b", "hla-c", ".a.", ".b.", ".c."])]

    hla_lookup = {}
    for _, row in df.iterrows():
        pid = str(row[pid_col]).strip()[:12]
        alleles = []
        for col in hla_cols:
            val = row.get(col)
            if pd.notna(val) and str(val).strip():
                allele = str(val).strip()
                if not allele.startswith("HLA-"): allele = f"HLA-{allele}"
                alleles.append(allele)
        if alleles:
            hla_lookup[pid] = alleles
    return hla_lookup
def build_profiles(clinical_data, maf_patient_ids, mode):
    profiles = []
    
    # [FIX] Use ALL clinical patients as the master list. 
    # Do not filter by maf_patient_ids here.
    patient_ids = sorted(clinical_data.keys())
    
    input_mode = InputMode.GENOMIC if mode == "genomic" else InputMode.CLINICAL

    for pid in patient_ids:
        clin = clinical_data.get(pid, {})
        
        profiles.append(PatientProfile(
            patient_id=pid,
            input_mode=input_mode,
            age=clin.get("age", 55),
            sex=clin.get("sex", "M"),
            cancer_type=clin.get("cancer_type", "sarcoma"),
            stage=clin.get("stage"),
            lines_exhausted=0,
            current_status="historical TCGA cohort",
            # We keep the path; the pipeline will handle the barcode matching internally
            maf_path=str(ROOT / "data" / "tcga" / "TCGA-SARC.maf.gz") if input_mode == InputMode.GENOMIC else None,
        ))
    
    print(f"Successfully queued {len(profiles)} patients for processing.")
    return profiles
def run_batch(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "batch_summary.csv"

    clinical_data = load_clinical_data(ROOT / "data" / "tcga" / "clinical.tsv")
    hla_lookup = load_hla_data(ROOT / "data" / "hla" / "thorsson_hla_calls.tsv")

    maf_path = ROOT / "data" / "tcga" / "TCGA-SARC.maf.gz"
    maf_patient_ids = set()
    if not args.clinical_only and maf_path.exists():
        for chunk in pd.read_csv(maf_path, sep="\t", comment="#", low_memory=False, chunksize=100_000, usecols=["Tumor_Sample_Barcode"]):
            for barcode in chunk["Tumor_Sample_Barcode"].unique():
                maf_patient_ids.add(str(barcode)[:12])
    elif not args.clinical_only:
        logger.warning(f"MAF not found. Forcing clinical-only mode.")
        args.clinical_only = True

    mode = "clinical" if args.clinical_only else "genomic"
    profiles = build_profiles(clinical_data, maf_patient_ids, mode)

    if args.max_patients:
        profiles = profiles[:args.max_patients]

    pipeline = RareCurePipeline(hla_lookup=hla_lookup)
    results_summary = []
    success_count, fail_count, skip_count = 0, 0, 0
    total_start = time.time()

    print(f"\nProcessing {len(profiles)} patients ({mode} mode)")
    for patient in tqdm(profiles, desc="Patients", unit="pt"):
        result_path = output_dir / f"{patient.patient_id}.json"
        if args.skip_existing and result_path.exists():
            skip_count += 1
            continue

        row = {"patient_id": patient.patient_id, "cancer_type": patient.cancer_type, "mode": mode}
        try:
            plan = pipeline.run(patient)

            result_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

            row.update({
                "status": "success", "total_options": plan.total_options,
                "tier_1_count": len(plan.tier_1), "tier_2_count": len(plan.tier_2),
                "trial_count": sum(1 for t in (plan.tier_1 + plan.tier_2 + plan.tier_3 + plan.tier_4) if t.treatment_type == "trial"),
                "runtime_seconds": plan.runtime_seconds, "api_cost_usd": plan.api_cost_usd,
                "scoring_clamped": plan.scoring_weights.clamped,
                "top_drug": plan.tier_1[0].treatment_name if plan.tier_1 else (plan.tier_2[0].treatment_name if plan.tier_2 else "none"),
                "error": "",
            })
            success_count += 1
        except Exception as e:
            row.update({"status": "failed", "error": f"{type(e).__name__}: {str(e)[:100]}"})
            fail_count += 1
            logger.exception(f"FAILED: {patient.patient_id}")

        results_summary.append(row)
        if len(results_summary) % 10 == 0:
            pd.DataFrame(results_summary).to_csv(summary_path, index=False, encoding="utf-8")

    summary_df = pd.DataFrame(results_summary)
    summary_df.to_csv(summary_path, index=False)

    total_elapsed = time.time() - total_start
    llm = get_llm_client()

    print(f"\nBATCH COMPLETE: {success_count} succeeded, {fail_count} failed, {skip_count} skipped.")
    print(f"Time: {total_elapsed/60:.1f}m | Cost: ${llm.total_cost_usd:.4f}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-patients", type=int, help="Process first N patients")
    ap.add_argument("--skip-existing", action="store_true", help="Skip existing JSONs")
    ap.add_argument("--clinical-only", action="store_true", help="Run Mode B only")
    ap.add_argument("--output-dir", type=str, default=str(RESULTS_DIR), help="Output dir")
    run_batch(ap.parse_args())
