"""Tests M3. Mock-based."""
import pytest
from unittest.mock import patch
from rarecure.models import AnnotatedVariant, VariantTier, EvidenceTier
from rarecure.drug_match import match_drugs, _classify, _dedup, DrugMatch, TTLCache


class TestClassify:
    def test_oncokb_1(self):
        assert _classify({"source_db": "OncoKB", "oncokb_level": "1"}, "sarcoma") == EvidenceTier.TIER_1
    def test_oncokb_3a(self):
        assert _classify({"source_db": "OncoKB", "oncokb_level": "3A"}, "sarcoma") == EvidenceTier.TIER_3
    def test_civic_a(self):
        assert _classify({"source_db": "CIViC", "evidence_level": "A", "disease": "Sarcoma"}, "sarcoma") == EvidenceTier.TIER_1
    def test_dgidb(self):
        assert _classify({"source_db": "DGIdb"}, "sarcoma") == EvidenceTier.TIER_4


class TestDedup:
    def test_highest(self):
        r = _dedup([
            DrugMatch(drug_name="A", gene="X", evidence_tier=EvidenceTier.TIER_3, evidence_score=0.5, source_databases=["DGIdb"]),
            DrugMatch(drug_name="A", gene="X", evidence_tier=EvidenceTier.TIER_1, evidence_score=1.0, source_databases=["OncoKB"])])
        assert len(r) == 1 and r[0].evidence_score == 1.0
    def test_merges(self):
        r = _dedup([
            DrugMatch(drug_name="B", gene="Y", evidence_tier=EvidenceTier.TIER_2, evidence_score=0.75, source_databases=["DGIdb"]),
            DrugMatch(drug_name="B", gene="Y", evidence_tier=EvidenceTier.TIER_2, evidence_score=0.75, source_databases=["CIViC"])])
        assert set(r[0].source_databases) == {"CIViC", "DGIdb"}


class TestTTLCache:
    def test_set_get(self):
        c = TTLCache(maxsize=10, ttl_seconds=60)
        c.set("k", "v")
        assert c.get("k") == "v"
    def test_eviction(self):
        c = TTLCache(maxsize=2, ttl_seconds=60)
        c.set("a", 1); c.set("b", 2); c.set("c", 3)
        assert c.get("c") == 3
    def test_miss(self):
        c = TTLCache(maxsize=10, ttl_seconds=60)
        assert c.get("missing") is None


class TestMatch:
    @patch("rarecure.drug_match.asyncio.run")
    def test_actionable(self, mock_run):
        mock_run.return_value = [{"gene": "NTRK1", "drug_name": "LAROTRECTINIB",
                                   "interaction_types": ["inhibitor"], "source_db": "DGIdb"}]
        r = match_drugs(
            [AnnotatedVariant(gene="NTRK1", variant_classification="Missense_Mutation", tier=VariantTier.KNOWN_ACTIONABLE)],
            "sarcoma", "T1")
        assert r.total_matches > 0
    def test_passenger(self):
        r = match_drugs(
            [AnnotatedVariant(gene="TTN", variant_classification="Missense_Mutation", tier=VariantTier.LIKELY_PASSENGER)],
            "sarcoma", "T2")
        assert r.no_match_flag


@pytest.mark.integration
class TestLive:
    def test_dgidb(self):
        from rarecure.drug_match import query_dgidb
        assert len(query_dgidb(["NTRK1"])) > 0
