from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional


class InputMode(str, Enum):
    GENOMIC = "genomic"
    CLINICAL = "clinical"


class EvidenceTier(int, Enum):
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3
    TIER_4 = 4


class VariantTier(int, Enum):
    KNOWN_ACTIONABLE = 1
    LIKELY_ACTIONABLE = 2
    UNCERTAIN = 3
    LIKELY_PASSENGER = 4


class HLAMode(str, Enum):
    PERSONALIZED = "personalized"
    ESTIMATED = "estimated"


class AccessPathway(str, Enum):
    FDA_APPROVED = "fda_approved"
    OFF_LABEL_NCCN = "offlabel_nccn"
    CLINICAL_TRIAL_LOCAL = "trial_local"
    CLINICAL_TRIAL_TRAVEL = "trial_travel"
    COMPASSIONATE_USE = "compassionate"
    INDIVIDUAL_IND = "ind"


class EvidenceLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class TreatmentOutcome(str, Enum):
    COMPLETE_RESPONSE = "complete_response"
    PARTIAL_RESPONSE = "partial_response"
    STABLE_DISEASE = "stable_disease"
    PROGRESSIVE_DISEASE = "progressive_disease"
    UNKNOWN = "unknown"


class PriorTreatment(BaseModel):
    drug_name: str
    mechanism: Optional[str] = None
    outcome: TreatmentOutcome = TreatmentOutcome.UNKNOWN
    duration_months: Optional[float] = None


class PatientProfile(BaseModel):
    patient_id: str
    input_mode: InputMode
    age: int
    sex: str
    ecog_ps: Optional[int] = None
    cancer_type: str
    cancer_subtype: Optional[str] = None
    primary_site: Optional[str] = None
    stage: Optional[str] = None
    metastatic_sites: list[str] = Field(default_factory=list)
    prior_treatments: list[PriorTreatment] = Field(default_factory=list)
    lines_exhausted: int = 0
    current_status: Optional[str] = None
    tmb_status: Optional[str] = None
    msi_status: Optional[str] = None
    pdl1_status: Optional[str] = None
    preference: str = "maximize_survival"
    geography: str = "United States"
    max_travel_willing: Optional[str] = None
    maf_path: Optional[str] = None
    hla_alleles: Optional[list[str]] = None
    hla_mode: HLAMode = HLAMode.ESTIMATED
    rna_expression_path: Optional[str] = None


class AnnotatedVariant(BaseModel):
    gene: str
    chromosome: Optional[str] = None
    position: Optional[int] = None
    variant_classification: str
    hgvsp: Optional[str] = None
    vaf: Optional[float] = None
    sift_score: Optional[float] = None
    polyphen_score: Optional[float] = None
    tier: VariantTier = VariantTier.UNCERTAIN


class VariantReport(BaseModel):
    patient_id: str
    total_variants_raw: int
    total_variants_coding: int
    variants: list[AnnotatedVariant]
    actionable_genes: list[str]
    zero_variant_flag: bool = False


class NeoantigenCandidate(BaseModel):
    gene: str
    mutation: str
    peptide_sequence: str
    peptide_length: int
    hla_allele: str
    binding_affinity_nm: float
    immunogenicity_score: float = 0.0


class NeoantigenReport(BaseModel):
    patient_id: str
    hla_mode: HLAMode
    hla_alleles_used: list[str]
    total_candidates_unfiltered: int
    total_candidates_filtered: int
    candidates: list[NeoantigenCandidate]
    hla_mode_warning: Optional[str] = None


class DrugMatch(BaseModel):
    drug_name: str
    gene: str
    variant: Optional[str] = None
    mechanism_of_action: Optional[str] = None
    evidence_tier: EvidenceTier
    evidence_score: float
    source_databases: list[str]
    oncokb_level: Optional[str] = None
    civic_level: Optional[str] = None
    fda_approved_indication: Optional[str] = None
    conflict_note: Optional[str] = None


class DrugReport(BaseModel):
    patient_id: str
    total_genes_queried: int
    total_matches: int
    matches: list[DrugMatch]
    no_match_flag: bool = False


class TrialMatch(BaseModel):
    nct_id: str
    title: str
    phase: str
    status: str
    conditions: list[str]
    interventions: list[str]
    eligibility_met: bool
    eligibility_notes: Optional[str] = None
    relevance_score: float
    genomic_match: bool = False
    locations: list[str] = Field(default_factory=list)
    contact_info: Optional[str] = None
    url: Optional[str] = None


class TrialReport(BaseModel):
    patient_id: str
    query_terms_used: list[str]
    total_retrieved: int
    total_eligible: int
    trials: list[TrialMatch]


class EvidenceSummary(BaseModel):
    treatment_name: str
    rationale: str
    evidence_level: EvidenceLevel
    primary_reference_pmid: Optional[str] = None
    source_chunks_used: int
    insufficient_evidence: bool = False


class ScoringWeights(BaseModel):
    evidence_strength: float
    access_feasibility: float
    expected_response: float
    safety_profile: float
    cost: float
    rationale: str
    clamped: bool = False


class ScoredTreatment(BaseModel):
    treatment_name: str
    treatment_type: str
    evidence_tier: EvidenceTier
    access_pathway: AccessPathway
    evidence_score: float
    access_score: float
    response_score: float
    safety_score: float
    cost_score: float
    novelty_bonus: float = 0.0
    composite_score: float
    rank_within_tier: int
    mechanism: Optional[str] = None
    evidence_summary: Optional[EvidenceSummary] = None
    action_item: str
    source_module: str
    gene: Optional[str] = None
    variant: Optional[str] = None


class TreatmentPlan(BaseModel):
    patient_id: str
    input_mode: InputMode
    patient_summary: str
    scoring_weights: ScoringWeights
    scoring_weights_stability_cv: Optional[float] = None
    tier_1: list[ScoredTreatment] = Field(default_factory=list)
    tier_2: list[ScoredTreatment] = Field(default_factory=list)
    tier_3: list[ScoredTreatment] = Field(default_factory=list)
    tier_4: list[ScoredTreatment] = Field(default_factory=list)
    neoantigen_candidates: list[NeoantigenCandidate] = Field(default_factory=list)
    total_options: int = 0
    runtime_seconds: float = 0.0
    api_cost_usd: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    pipeline_version: str = "1.0.0"
