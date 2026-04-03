"""RareCure Configuration."""
import os
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
RESULTS_DIR = ROOT_DIR / "results"
CHROMA_DIR = ROOT_DIR / "chroma_db"
RESULTS_DIR.mkdir(exist_ok=True)
CHROMA_DIR.mkdir(exist_ok=True)


class LLMProvider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    LOCAL_LLAMA = "local_llama"


LLM_PROVIDER = LLMProvider(os.getenv("RARECURE_LLM_PROVIDER", "claude"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 4096
CLAUDE_TEMPERATURE = 0.3
LOCAL_LLAMA_ENDPOINT = os.getenv("LOCAL_LLAMA_ENDPOINT", "http://localhost:8080/v1")
LOCAL_LLAMA_MODEL = "meta-llama/Llama-3.1-70B-Instruct"


@dataclass(frozen=True)
class APIEndpoints:
    DGIDB: str = "https://dgidb.org/api/v2"
    CIVIC: str = "https://civicdb.org/api"
    ONCOKB: str = "https://www.oncokb.org/api/v1"
    CHEMBL: str = "https://www.ebi.ac.uk/chembl/api/data"
    CLINICAL_TRIALS: str = "https://clinicaltrials.gov/api/v2"
    PUBMED: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    # Bulk indexing: use FTP baseline, NOT sequential E-utilities
    PUBMED_FTP_BASELINE: str = "https://ftp.ncbi.nlm.nih.gov/pubmed/baseline/"


API = APIEndpoints()
ONCOKB_API_KEY = os.getenv("ONCOKB_API_KEY", "")

# Concurrency controls
API_SEMAPHORE_LIMIT: int = 10  # Max concurrent HTTP requests
PUBMED_RATE_LIMIT: float = 0.34  # Seconds between requests (3/sec without key)


@dataclass(frozen=True)
class NeoantigenConfig:
    BINDING_AFFINITY_THRESHOLD_NM: float = 500.0
    DIFFERENTIAL_AGRETOPICITY_MIN: float = 1.0
    VAF_THRESHOLD: float = 0.05
    DEFAULT_EXPRESSION_PERCENTILE: float = 0.5
    PEPTIDE_LENGTHS: list = field(default_factory=lambda: [8, 9, 10, 11])
    FALLBACK_HLA_ALLELES: list = field(default_factory=lambda: [
        "HLA-A*02:01", "HLA-A*01:01", "HLA-A*03:01", "HLA-A*24:02",
        "HLA-B*07:02", "HLA-B*08:01", "HLA-B*44:02"])


NEO = NeoantigenConfig()


@dataclass(frozen=True)
class DrugMatchConfig:
    EVIDENCE_SCORES: dict = field(default_factory=lambda: {
        "tier_1": 1.0, "tier_2": 0.75, "tier_3": 0.5, "tier_4": 0.25})


DRUG = DrugMatchConfig()


@dataclass(frozen=True)
class TrialMatchConfig:
    PHASE_SCORES: dict = field(default_factory=lambda: {
        "PHASE3": 1.0, "PHASE2_3": 0.85, "PHASE2": 0.7,
        "PHASE1_2": 0.55, "PHASE1": 0.4, "EARLY_PHASE1": 0.3})
    RELEVANCE_WEIGHTS: dict = field(default_factory=lambda: {
        "phase": 0.30, "genomic_match": 0.35,
        "histology_match": 0.20, "geographic_proximity": 0.15})
    MAX_RESULTS_PER_QUERY: int = 50
    STATUS_FILTER: list = field(default_factory=lambda: ["RECRUITING", "NOT_YET_RECRUITING"])


TRIAL = TrialMatchConfig()


@dataclass(frozen=True)
class RAGConfig:
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64
    TOP_K: int = 5
    SIMILARITY_THRESHOLD: float = 0.65
    COLLECTION_NAME: str = "rarecure_pubmed"


RAG = RAGConfig()


@dataclass(frozen=True)
class ScoringConfig:
    WEIGHT_DIMENSIONS: list = field(default_factory=lambda: [
        "evidence_strength", "access_feasibility",
        "expected_response", "safety_profile", "cost"])
    NOVELTY_BONUS: float = 0.15
    N_WEIGHT_REPEATS: int = 5
    COST_REFERENCE_MAX_USD: float = 200000.0
    ACCESS_SCORES: dict = field(default_factory=lambda: {
        "fda_approved": 1.0, "offlabel_nccn": 0.8, "trial_local": 0.7,
        "trial_travel": 0.5, "compassionate": 0.3, "ind": 0.2})
    DEFAULT_RESPONSE_RATE: float = 0.3
    WEIGHT_CLAMPS: dict = field(default_factory=lambda: {
        "evidence_strength": (0.05, 0.60),
        "access_feasibility": (0.05, 0.40),
        "expected_response": (0.05, 0.50),
        "safety_profile":    (0.03, 0.40),
        "cost":              (0.02, 0.35),
    })


SCORING = ScoringConfig()

CODING_VARIANT_TYPES = frozenset([
    "Missense_Mutation", "Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins",
    "Splice_Site", "In_Frame_Del", "In_Frame_Ins", "Nonstop_Mutation",
    "Translation_Start_Site"])

COMMON_GENES_BY_CANCER = {
    "sarcoma": ["TP53", "RB1", "CDKN2A", "MDM2", "CDK4", "PDGFRA", "KIT"],
    "osteosarcoma": ["TP53", "RB1", "CDKN2A", "MDM2", "ATRX", "DLG2"],
    "pancreatic": ["KRAS", "TP53", "CDKN2A", "SMAD4", "BRCA2", "ARID1A"],
    "default": ["TP53", "KRAS", "BRAF", "NTRK1", "NTRK2", "NTRK3", "RET", "ALK", "ROS1"],
}

CANCER_ONTOLOGY = {
    "spindle_cell_sarcoma": ["soft tissue sarcoma", "sarcoma", "solid tumor"],
    "leiomyosarcoma": ["soft tissue sarcoma", "sarcoma", "solid tumor"],
    "undifferentiated_pleomorphic_sarcoma": ["soft tissue sarcoma", "sarcoma", "solid tumor"],
    "osteosarcoma": ["bone sarcoma", "sarcoma", "solid tumor"],
    "chondrosarcoma": ["bone sarcoma", "sarcoma", "solid tumor"],
    "synovial_sarcoma": ["soft tissue sarcoma", "sarcoma", "solid tumor"],
    "liposarcoma": ["soft tissue sarcoma", "sarcoma", "solid tumor"],
    "rhabdomyosarcoma": ["soft tissue sarcoma", "sarcoma", "solid tumor"],
    "angiosarcoma": ["vascular sarcoma", "sarcoma", "solid tumor"],
    "gastrointestinal_stromal_tumor": ["GIST", "sarcoma", "solid tumor"],
    "pancreatic_adenocarcinoma": ["pancreatic cancer", "GI cancer", "solid tumor"],
    "default": ["solid tumor", "advanced cancer"],
}

try:
    from config_local import *  # noqa
except ImportError:
    pass
