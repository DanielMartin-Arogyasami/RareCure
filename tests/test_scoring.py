"""Tests M6."""
import pytest
from rarecure.models import (DrugMatch, EvidenceTier, PatientProfile, TreatmentOutcome, PriorTreatment)
from rarecure.scoring import filter_failed, _novelty, score_drug, clamp_weights, ScoringWeights


@pytest.fixture
def w():
    return ScoringWeights(
        evidence_strength=0.2, access_feasibility=0.2,
        expected_response=0.2, safety_profile=0.2, cost=0.2, rationale="t")

@pytest.fixture
def pt():
    return PatientProfile(
        patient_id="T", input_mode="clinical", age=50, sex="M",
        cancer_type="sarcoma", lines_exhausted=3,
        prior_treatments=[PriorTreatment(
            drug_name="doxorubicin", mechanism="cytotoxic",
            outcome=TreatmentOutcome.PROGRESSIVE_DISEASE)])


class TestFilter:
    def test_removes(self, pt):
        d = [DrugMatch(drug_name="doxorubicin", gene="X", evidence_tier=EvidenceTier.TIER_1,
                       evidence_score=1.0, source_databases=["t"])]
        assert len(filter_failed(d, pt)) == 0
    def test_keeps(self, pt):
        d = [DrugMatch(drug_name="pazopanib", gene="X", evidence_tier=EvidenceTier.TIER_2,
                       evidence_score=0.75, source_databases=["t"])]
        assert len(filter_failed(d, pt)) == 1


class TestCap:
    def test_max1(self, w, pt):
        d = DrugMatch(drug_name="X", gene="Y", evidence_tier=EvidenceTier.TIER_1,
                      evidence_score=1.0, source_databases=["t"], mechanism_of_action="novel")
        assert score_drug(d, w, pt).composite_score <= 1.0


class TestClamp:
    def test_clamps_extreme(self):
        raw = {"evidence_strength": 0.90, "access_feasibility": 0.02,
               "expected_response": 0.03, "safety_profile": 0.03, "cost": 0.02}
        clamped, was = clamp_weights(raw)
        assert was is True
        assert clamped["evidence_strength"] <= 0.85  # Clamped then renormalized
    def test_passthrough(self):
        raw = {"evidence_strength": 0.30, "access_feasibility": 0.20,
               "expected_response": 0.25, "safety_profile": 0.15, "cost": 0.10}
        _, was = clamp_weights(raw)
        assert was is False
    def test_sums_to_one(self):
        raw = {"evidence_strength": 0.80, "access_feasibility": 0.05,
               "expected_response": 0.05, "safety_profile": 0.05, "cost": 0.05}
        clamped, _ = clamp_weights(raw)
        assert abs(sum(clamped.values()) - 1.0) < 0.001
