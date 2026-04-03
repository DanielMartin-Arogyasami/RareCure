"""Pipeline. [C3] deepcopy [FIX 4] specific exceptions [H3] gene fallback."""
import logging
import time
import json
from copy import deepcopy
from pathlib import Path
from typing import Optional
import httpx
import requests
from rarecure.config import SCORING, COMMON_GENES_BY_CANCER
from rarecure.models import (
    PatientProfile, InputMode, TreatmentPlan, EvidenceTier,
    AnnotatedVariant, VariantTier, VariantReport, DrugReport,
    TrialReport, NeoantigenReport, ScoringWeights,
)
from rarecure.ingest_maf import ingest_maf
from rarecure.neoantigen import predict_neoantigens, get_hla_alleles
from rarecure.drug_match import match_drugs
from rarecure.trial_match import match_trials
from rarecure.rag_engine import get_rag_engine
from rarecure.scoring import generate_weights, filter_failed, score_drug, score_trial
from rarecure.llm_client import get_llm_client

logger = logging.getLogger(__name__)


class RareCurePipeline:
    def __init__(self, hla_lookup=None):
        self.hla_lookup = hla_lookup

    def run(self, patient_in: PatientProfile) -> TreatmentPlan:
        patient = deepcopy(patient_in)
        start = time.time()
        warnings = []
        logger.info(f"Pipeline: {patient.patient_id} ({patient.input_mode})")

        # M1: Variants [FIX 4]
        vr: Optional[VariantReport] = None
        if patient.input_mode == InputMode.GENOMIC and patient.maf_path:
            try:
                logger.info("M1: Variants...")
                rpts = ingest_maf(patient.maf_path, patient.patient_id)
                vr = rpts.get(patient.patient_id)
                if vr and vr.zero_variant_flag:
                    warnings.append("No coding variants.")
                    patient.input_mode = InputMode.CLINICAL
            except (FileNotFoundError, KeyError, ValueError) as e:
                logger.exception("M1 failed")
                warnings.append(f"M1: {type(e).__name__}: {e}")
                patient.input_mode = InputMode.CLINICAL

        # M2: Neoantigens [FIX 4]
        neo: Optional[NeoantigenReport] = None
        if patient.input_mode == InputMode.GENOMIC and vr and vr.variants:
            try:
                logger.info("M2: Neoantigens...")
                al, mode = get_hla_alleles(
                    patient.patient_id, patient.hla_alleles, self.hla_lookup)
                patient.hla_mode = mode
                neo = predict_neoantigens(vr.variants, al, mode, patient.patient_id)
                if neo.hla_mode_warning:
                    warnings.append(neo.hla_mode_warning)
            except (KeyError, ValueError) as e:
                logger.exception("M2 failed")
                warnings.append(f"M2: {type(e).__name__}: {e}")

        # M3: Drugs [FIX 4]
        dr = DrugReport(
            patient_id=patient.patient_id, total_genes_queried=0,
            total_matches=0, matches=[], no_match_flag=True)
        try:
            logger.info("M3: Drugs...")
            if vr and vr.variants:
                dr = match_drugs(vr.variants, patient.cancer_type, patient.patient_id)
            else:
                ck = next(
                    (k for k in COMMON_GENES_BY_CANCER if k in patient.cancer_type.lower()),
                    "default")
                common = [
                    AnnotatedVariant(
                        gene=g, variant_classification="Unknown",
                        tier=VariantTier.UNCERTAIN)
                    for g in COMMON_GENES_BY_CANCER[ck]]
                dr = match_drugs(common, patient.cancer_type, patient.patient_id)
                warnings.append(f"Used common {ck} genes.")
        except (httpx.RequestError, httpx.HTTPStatusError, KeyError, ValueError) as e:
            logger.exception("M3 failed")
            warnings.append(f"M3: {type(e).__name__}: {e}")
        if dr.no_match_flag:
            warnings.append("No drug matches.")

        # M4: Trials [FIX 4]
        tr = TrialReport(
            patient_id=patient.patient_id, query_terms_used=[],
            total_retrieved=0, total_eligible=0, trials=[])
        try:
            logger.info("M4: Trials...")
            tr = match_trials(patient, vr.actionable_genes if vr else [])
        except (requests.RequestException, httpx.RequestError, httpx.HTTPStatusError, KeyError) as e:
            logger.exception("M4 failed")
            warnings.append(f"M4: {type(e).__name__}: {e}")

        # M6: Scoring [FIX 4]
        eq = 0.2
        weights = ScoringWeights(
            evidence_strength=eq, access_feasibility=eq,
            expected_response=eq, safety_profile=eq, cost=eq,
            rationale="default")
        cv = 0.0
        try:
            logger.info("M6: Scoring...")
            weights, cv = generate_weights(patient)
        except (ValueError, KeyError, TypeError) as e:
            logger.exception("M6 failed")
            warnings.append(f"M6 equal weights: {type(e).__name__}: {e}")

        filt = filter_failed(dr.matches, patient)
        sd = [score_drug(d, weights, patient) for d in filt]
        st = [score_trial(t, weights, patient) for t in tr.trials if t.eligibility_met]
        all_s = sorted(sd + st, key=lambda x: x.composite_score, reverse=True)
        tiers = {1: [], 2: [], 3: [], 4: []}
        for s in all_s:
            tiers[s.evidence_tier.value].append(s)
        for lst in tiers.values():
            for i, item in enumerate(lst):
                item.rank_within_tier = i + 1

        llm = get_llm_client()
        return TreatmentPlan(
            patient_id=patient.patient_id,
            input_mode=patient.input_mode,
            patient_summary=(
                f"{patient.age}{patient.sex}, "
                f"{patient.cancer_type.replace('_', ' ')}, "
                f"stage {patient.stage or '?'}, "
                f"{patient.lines_exhausted} lines"),
            scoring_weights=weights,
            scoring_weights_stability_cv=cv,
            tier_1=tiers[1], tier_2=tiers[2],
            tier_3=tiers[3], tier_4=tiers[4],
            neoantigen_candidates=neo.candidates if neo else [],
            total_options=len(all_s),
            runtime_seconds=round(time.time() - start, 2),
            api_cost_usd=round(llm.total_cost_usd, 6),
            warnings=warnings)


def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="RareCure")
    ap.add_argument("--patient-json", type=str)
    ap.add_argument("--cancer-type", default="spindle_cell_sarcoma")
    ap.add_argument("--age", type=int, default=55)
    ap.add_argument("--sex", default="M")
    ap.add_argument("--output", default="treatment_plan.json")
    a = ap.parse_args()
    if a.patient_json:
        pt = PatientProfile(**json.loads(Path(a.patient_json).read_text()))
    else:
        pt = PatientProfile(
            patient_id="CLI", input_mode=InputMode.CLINICAL,
            age=a.age, sex=a.sex, cancer_type=a.cancer_type,
            stage="IV", lines_exhausted=2,
            current_status="partial response",
            geography="United States")
    plan = RareCurePipeline().run(pt)
    Path(a.output).write_text(plan.model_dump_json(indent=2))
    print(f"\nSaved: {a.output} | {plan.total_options} options | "
          f"{plan.runtime_seconds}s | ${plan.api_cost_usd:.4f}")
    for nm, lst in [("T1", plan.tier_1), ("T2", plan.tier_2),
                    ("T3", plan.tier_3), ("T4", plan.tier_4)]:
        if lst:
            print(f"\n{nm} ({len(lst)}):")
            for t in lst[:5]:
                print(f"  #{t.rank_within_tier} {t.treatment_name:30s} | "
                      f"{t.composite_score:.3f} | {t.access_pathway.value}")
    if plan.warnings:
        print("\nWarnings:")
        for w in plan.warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
