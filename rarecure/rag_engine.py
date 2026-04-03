"""Module 5: RAG Knowledge Engine (STUB)."""
import logging
from rarecure.models import EvidenceSummary, EvidenceLevel

logger = logging.getLogger(__name__)


class RAGEngine:
    def get_evidence(self, treatment_name, **kw):
        return EvidenceSummary(
            treatment_name=treatment_name,
            rationale=f"Evidence retrieval not implemented for {treatment_name}.",
            evidence_level=EvidenceLevel.D,
            source_chunks_used=0,
            insufficient_evidence=True)


_e = None


def get_rag_engine():
    global _e
    if _e is None:
        _e = RAGEngine()
    return _e
