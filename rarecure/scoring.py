"""Module 6: Scoring. [FIX 1] deterministic clamps [H4] cap [H5] few-shot."""
import logging
import statistics
from rarecure.config import SCORING
from rarecure.models import (
    PatientProfile, ScoringWeights, DrugMatch, TrialMatch,
    ScoredTreatment, EvidenceTier, AccessPathway, TreatmentOutcome,
)
from rarecure.llm_client import get_llm_client, sanitize_for_prompt

logger = logging.getLogger(__name__)

PROMPT = """Given this patient, determine scoring weights for treatment ranking.

PATIENT: {ct} (stage {st}), {ln} prior lines.
Prior: {pr} | Status: {su} | Pref: {pf} | Geo: {ge}

DIMENSIONS (sum to 1.0): evidence_strength, access_feasibility, expected_response, safety_profile, cost

EXAMPLE 1 - New diagnosis:
{{"evidence_strength":0.40,"access_feasibility":0.20,"expected_response":0.15,"safety_profile":0.15,"cost":0.10,"rationale":"Standard care available."}}

EXAMPLE 2 - Exhausted, progressive:
{{"evidence_strength":0.10,"access_feasibility":0.20,"expected_response":0.40,"safety_profile":0.05,"cost":0.25,"rationale":"No standard options."}}

Return ONLY valid JSON for the patient above."""


def clamp_weights(weights_dict):
    """[FIX 1] Deterministic validator. LLM proposes, clamps enforce."""
    clamps = SCORING.WEIGHT_CLAMPS
    clamped = False
    out = {}
    for dim, val in weights_dict.items():
        if dim in clamps:
            lo, hi = clamps[dim]
            if val < lo:
                out[dim] = lo; clamped = True
            elif val > hi:
                out[dim] = hi; clamped = True
            else:
                out[dim] = val
        else:
            out[dim] = val
    total = sum(out.values())
    if total > 0:
        out = {k: v / total for k, v in out.items()}
    return out, clamped


def _pr(pt):
    if not pt.prior_treatments:
        return "None"
    return "; ".join(f"{t.drug_name}->{t.outcome.value}" for t in pt.prior_treatments)


def generate_weights(patient, n_repeats=SCORING.N_WEIGHT_REPEATS):
    llm = get_llm_client()
    p = PROMPT.format(
        ct=sanitize_for_prompt(patient.cancer_type),
        st=sanitize_for_prompt(patient.stage or "?"),
        ln=patient.lines_exhausted,
        pr=sanitize_for_prompt(_pr(patient)),
        su=sanitize_for_prompt(patient.current_status or "?"),
        pf=sanitize_for_prompt(patient.preference),
        ge=sanitize_for_prompt(patient.geography))
    ws = []
    for i in range(n_repeats):
        try:
            r = llm.complete_json(p)
            dims = SCORING.WEIGHT_DIMENSIONS
            vals = [max(0.01, float(r.get(d, 0.2))) for d in dims]
            t = sum(vals)
            vals = [v / t for v in vals]
            ws.append(dict(zip(dims, vals)) | {"rationale": r.get("rationale", "")})
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Weight gen {i}: {e}")
    if not ws:
        eq = 1.0 / len(SCORING.WEIGHT_DIMENSIONS)
        return ScoringWeights(
            evidence_strength=eq, access_feasibility=eq,
            expected_response=eq, safety_profile=eq, cost=eq,
            rationale="FALLBACK", clamped=False), 0.0
    dims = SCORING.WEIGHT_DIMENSIONS
    med = {d: statistics.median([w[d] for w in ws]) for d in dims}
    t = sum(med.values())
    med = {k: v / t for k, v in med.items()}
    med, was_clamped = clamp_weights(med)  # [FIX 1]
    cvs = []
    for d in dims:
        vs = [w[d] for w in ws]
        if len(vs) > 1 and statistics.mean(vs) > 0:
            cvs.append(statistics.stdev(vs) / statistics.mean(vs))
    if was_clamped:
        logger.info("Weights clamped to configured bounds")
    return (
        ScoringWeights(**med, rationale=ws[0].get("rationale", ""), clamped=was_clamped),
        statistics.mean(cvs) if cvs else 0.0)


def filter_failed(drugs, pt):
    failed = {
        t.drug_name.lower().strip()
        for t in pt.prior_treatments
        if t.outcome == TreatmentOutcome.PROGRESSIVE_DISEASE}
    return [d for d in drugs if d.drug_name.lower().strip() not in failed]


def _novelty(drug, pt):
    if not drug.mechanism_of_action:
        return 0.0
    fm = {
        t.mechanism.lower()
        for t in pt.prior_treatments
        if t.outcome == TreatmentOutcome.PROGRESSIVE_DISEASE and t.mechanism}
    return SCORING.NOVELTY_BONUS if drug.mechanism_of_action.lower() not in fm else 0.0


_ACC = {EvidenceTier.TIER_1: 1.0, EvidenceTier.TIER_2: 0.8,
        EvidenceTier.TIER_3: 0.7, EvidenceTier.TIER_4: 0.2}
_PATH = {EvidenceTier.TIER_1: AccessPathway.FDA_APPROVED,
         EvidenceTier.TIER_2: AccessPathway.OFF_LABEL_NCCN,
         EvidenceTier.TIER_3: AccessPathway.CLINICAL_TRIAL_LOCAL,
         EvidenceTier.TIER_4: AccessPathway.INDIVIDUAL_IND}
_ACT = {EvidenceTier.TIER_1: "Prescribe per indication.",
        EvidenceTier.TIER_2: "Off-label, NCCN may support.",
        EvidenceTier.TIER_3: "Search trials / compassionate use.",
        EvidenceTier.TIER_4: "Preclinical. IND needed."}


def score_drug(drug, weights, patient, evidence=None):
    ev = drug.evidence_score
    acc = _ACC.get(drug.evidence_tier, 0.2)
    resp = SCORING.DEFAULT_RESPONSE_RATE
    safe = 0.6
    cost = 0.5
    nov = _novelty(drug, patient)
    w = (ev * weights.evidence_strength + acc * weights.access_feasibility +
         resp * weights.expected_response + safe * weights.safety_profile +
         cost * weights.cost)
    comp = min(1.0, w * (1.0 + nov))
    return ScoredTreatment(
        treatment_name=drug.drug_name, treatment_type="drug",
        evidence_tier=drug.evidence_tier,
        access_pathway=_PATH.get(drug.evidence_tier, AccessPathway.INDIVIDUAL_IND),
        evidence_score=ev, access_score=acc, response_score=resp,
        safety_score=safe, cost_score=cost, novelty_bonus=nov,
        composite_score=round(comp, 4), rank_within_tier=0,
        mechanism=drug.mechanism_of_action, evidence_summary=evidence,
        action_item=f"{drug.drug_name}: {_ACT.get(drug.evidence_tier, '')}",
        source_module="drug_match", gene=drug.gene, variant=drug.variant)


def score_trial(trial, weights, patient):
    ev = 0.5 if "3" in trial.phase else 0.3
    acc = 0.7 if any(patient.geography.lower() in l.lower() for l in trial.locations) else 0.5
    resp, safe, cost, nov = 0.4, 0.5, 0.8, SCORING.NOVELTY_BONUS
    w = (ev * weights.evidence_strength + acc * weights.access_feasibility +
         resp * weights.expected_response + safe * weights.safety_profile +
         cost * weights.cost)
    comp = min(1.0, w * (1.0 + nov))
    return ScoredTreatment(
        treatment_name=trial.interventions[0] if trial.interventions else trial.title,
        treatment_type="trial", evidence_tier=EvidenceTier.TIER_3,
        access_pathway=(AccessPathway.CLINICAL_TRIAL_LOCAL if acc >= 0.7
                        else AccessPathway.CLINICAL_TRIAL_TRAVEL),
        evidence_score=ev, access_score=acc, response_score=resp,
        safety_score=safe, cost_score=cost, novelty_bonus=nov,
        composite_score=round(comp, 4), rank_within_tier=0,
        action_item=f"Enroll: {trial.url}", source_module="trial_match")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for pid, st, ln, cur, pref in [
        ("A", "IIB", 0, "newly diagnosed", "maximize_survival"),
        ("B", "IV", 2, "partial response", "maximize_survival"),
        ("C", "IV", 4, "progressive, exhausted", "try everything"),
    ]:
        p = PatientProfile(
            patient_id=pid, input_mode="clinical", age=50, sex="M",
            cancer_type="sarcoma", stage=st, lines_exhausted=ln,
            current_status=cur, preference=pref, geography="United States")
        w, cv = generate_weights(p, n_repeats=3)
        print(f"\n{pid}: ev={w.evidence_strength:.2f} acc={w.access_feasibility:.2f} "
              f"resp={w.expected_response:.2f} safe={w.safety_profile:.2f} "
              f"cost={w.cost:.2f} CV={cv:.3f} clamped={w.clamped}")
