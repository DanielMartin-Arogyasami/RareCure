"""Module 3: Drugs. Async httpx + thread-safe TTLCache + OncoKB cache.

[FIX 2] httpx.AsyncClient with asyncio.Semaphore(10) for concurrent API calls.
[FIX 3] TTLCache with threading.Lock on all dict mutations.
[C1] OncoKB downloaded once, queried from memory.
[FIX 4] Specific exceptions with logger.exception.
"""
import asyncio
import logging
import threading
import time
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from rarecure.config import API, DRUG, API_SEMAPHORE_LIMIT, ONCOKB_API_KEY
from rarecure.models import DrugMatch, DrugReport, EvidenceTier, AnnotatedVariant, VariantTier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# [FIX 3] Thread-safe TTLCache with explicit locking
# ---------------------------------------------------------------------------
class TTLCache:
    """Cache with TTL expiry, max size, and thread-safe mutations."""

    def __init__(self, maxsize=2000, ttl_seconds=3600):
        self._cache: dict = {}
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._lock = threading.Lock()  # [FIX 3] Actual lock

    def get(self, key):
        with self._lock:
            if key in self._cache:
                val, ts = self._cache[key]
                if time.time() - ts < self._ttl:
                    return val
                del self._cache[key]
        return None

    def set(self, key, value):
        with self._lock:
            if len(self._cache) >= self._maxsize:
                oldest = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest]
            self._cache[key] = (value, time.time())


_dgidb_cache = TTLCache(maxsize=2000, ttl_seconds=3600)
_civic_cache = TTLCache(maxsize=500, ttl_seconds=3600)

# [C1] OncoKB one-time cache
_ONCOKB = None
_ONCOKB_LOCK = threading.Lock()


def _oncokb_cache():
    global _ONCOKB
    with _ONCOKB_LOCK:
        if _ONCOKB is not None:
            return _ONCOKB
        logger.info("Loading OncoKB (one-time)...")
        try:
            headers = {"Accept": "application/json"}
            if ONCOKB_API_KEY:
                headers["Authorization"] = f"Bearer {ONCOKB_API_KEY}"

            r = httpx.get(
                f"{API.ONCOKB}/utils/allAnnotatedVariants",
                timeout=60,
                headers=headers)
            r.raise_for_status()
            _ONCOKB = {}
            for e in r.json():
                g = e.get("gene", {}).get("hugoSymbol", "")
                if g:
                    _ONCOKB.setdefault(g, []).append(e)
            logger.info(f"OncoKB: {len(_ONCOKB)} genes")
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.exception("OncoKB cache load failed")
            _ONCOKB = {}
    return _ONCOKB


# ---------------------------------------------------------------------------
# [FIX 2] Async API fetchers with semaphore
# ---------------------------------------------------------------------------
_semaphore = asyncio.Semaphore(API_SEMAPHORE_LIMIT)


async def _dgidb_fetch_async(client: httpx.AsyncClient, genes: list[str]) -> list[dict]:
    """Fetch DGIdb interactions with semaphore rate limiting."""
    async with _semaphore:
        r = await client.get(
            f"{API.DGIDB}/interactions.json",
            params={"genes": ",".join(genes)},
            timeout=30)
        r.raise_for_status()
    out = []
    for m in r.json().get("matchedTerms", []):
        g = m.get("geneName", "")
        for ix in m.get("interactions", []):
            out.append({
                "gene": g,
                "drug_name": ix.get("drugName", "").strip(),
                "interaction_types": ix.get("interactionTypes", []),
                "source_db": "DGIdb"})
    return out


_CIVIC_QUERY = """
query($gene: String!) {
  gene(entrezSymbol: $gene) {
    name
    variants(first: 50) {
      nodes {
        name
        singleVariantMolecularProfile {
          evidenceItems(first: 50) {
            nodes {
              evidenceLevel
              evidenceDirection
              significance
              disease { name }
              therapies { name }
            }
          }
        }
      }
    }
  }
}
"""

_CIVIC_LEVEL_MAP = {
    "A": "A", "B": "B", "C": "C", "D": "D", "E": "E",
}


async def _civic_fetch_async(client: httpx.AsyncClient, gene: str) -> list[dict]:
    """Fetch CIViC evidence via GraphQL with semaphore rate limiting."""
    async with _semaphore:
        r = await client.post(
            API.CIVIC,
            json={"query": _CIVIC_QUERY, "variables": {"gene": gene}},
            headers={"Content-Type": "application/json"},
            timeout=30)
        r.raise_for_status()
    data = r.json()
    gene_data = (data.get("data") or {}).get("gene")
    if not gene_data:
        return []
    out = []
    for var in (gene_data.get("variants") or {}).get("nodes", []):
        mp = var.get("singleVariantMolecularProfile") or {}
        for ev in (mp.get("evidenceItems") or {}).get("nodes", []):
            for th in ev.get("therapies") or []:
                n = (th.get("name") or "").strip()
                if n:
                    raw_level = str(ev.get("evidenceLevel") or "").upper()
                    out.append({
                        "gene": gene, "drug_name": n,
                        "variant": var.get("name", ""),
                        "evidence_level": _CIVIC_LEVEL_MAP.get(raw_level, raw_level),
                        "disease": (ev.get("disease") or {}).get("name", ""),
                        "source_db": "CIViC"})
    return out


async def _fetch_all_drugs_async(genes: list[str]) -> list[dict]:
    """[FIX 2] Run DGIdb batch + CIViC per-gene concurrently."""
    async with httpx.AsyncClient(
        headers={"Accept": "application/json", "User-Agent": "RareCure/1.0"}
    ) as client:
        tasks = []
        # DGIdb: one batch call
        tasks.append(_dgidb_fetch_async(client, genes))
        # CIViC: concurrent per-gene (capped at 30)
        for g in genes[:30]:
            tasks.append(_civic_fetch_async(client, g))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_raw = []
    for r in results:
        if isinstance(r, Exception):
            logger.exception(f"Async drug fetch failed: {r}")
        elif isinstance(r, list):
            all_raw.extend(r)
    return all_raw


def query_dgidb(genes: list[str]) -> list[dict]:
    """Sync wrapper with TTLCache."""
    key = tuple(sorted(set(genes)))
    cached = _dgidb_cache.get(key)
    if cached is not None:
        return cached
    try:
        result = asyncio.run(_dgidb_fetch_async_standalone(genes))
        _dgidb_cache.set(key, result)
        return result
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.exception(f"DGIdb failed for {genes[:5]}")
        return []


async def _dgidb_fetch_async_standalone(genes):
    async with httpx.AsyncClient(
        headers={"Accept": "application/json", "User-Agent": "RareCure/1.0"}
    ) as client:
        return await _dgidb_fetch_async(client, genes)


def query_civic(gene: str) -> list[dict]:
    """Sync wrapper with TTLCache."""
    cached = _civic_cache.get(gene)
    if cached is not None:
        return cached
    try:
        result = asyncio.run(_civic_fetch_async_standalone(gene))
        _civic_cache.set(gene, result)
        return result
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.exception(f"CIViC failed for {gene}")
        return []


async def _civic_fetch_async_standalone(gene):
    async with httpx.AsyncClient(
        headers={"Accept": "application/json", "User-Agent": "RareCure/1.0"}
    ) as client:
        return await _civic_fetch_async(client, gene)


def query_oncokb(gene, variant=None):
    results = []
    for e in _oncokb_cache().get(gene, []):
        ov = e.get("variant", {}).get("name", "")
        if variant and variant.lower() not in ov.lower():
            continue
        for tx in e.get("treatments", []):
            for d in tx.get("drugs", []):
                results.append({
                    "gene": gene,
                    "drug_name": d.get("drugName", "").strip(),
                    "variant": ov,
                    "oncokb_level": tx.get("level", ""),
                    "indication": tx.get("levelAssociatedCancerType", {}).get("name", ""),
                    "source_db": "OncoKB"})
    return results


# ---------------------------------------------------------------------------
# Classification, dedup, public API
# ---------------------------------------------------------------------------
def _classify(raw, ct):
    src = raw.get("source_db", "")
    if src == "OncoKB":
        l = raw.get("oncokb_level", "")
        if l in ("1", "R1"):   return EvidenceTier.TIER_1
        if l in ("2", "R2"):   return EvidenceTier.TIER_2
        if l in ("3A", "3B"):  return EvidenceTier.TIER_3
        return EvidenceTier.TIER_4
    if src == "CIViC":
        l = raw.get("evidence_level", "")
        m = ct.lower() in raw.get("disease", "").lower() or "sarcoma" in raw.get("disease", "").lower()
        if l == "A" and m:                return EvidenceTier.TIER_1
        if l == "A" or (l == "B" and m):  return EvidenceTier.TIER_2
        if l in ("B", "C"):              return EvidenceTier.TIER_3
        return EvidenceTier.TIER_4
    return EvidenceTier.TIER_4


def _dedup(matches):
    seen = {}
    for m in matches:
        k = m.drug_name.lower().strip()
        if k not in seen or m.evidence_score >= seen[k].evidence_score:
            if k in seen:
                if seen[k].evidence_tier != m.evidence_tier:
                    m.conflict_note = "Evidence conflict. Highest retained."
                m.source_databases = sorted(set(seen[k].source_databases) | set(m.source_databases))
            seen[k] = m
    return sorted(seen.values(), key=lambda x: x.evidence_score, reverse=True)


def match_drugs(variants, cancer_type, patient_id="unknown"):
    """Main entry. Uses async internally for concurrent API calls."""
    genes = list(set(v.gene for v in variants if v.tier.value <= 3))
    if not genes:
        return DrugReport(
            patient_id=patient_id, total_genes_queried=0,
            total_matches=0, matches=[], no_match_flag=True)

    logger.info(f"Querying {len(genes)} genes: {genes[:10]}")

    # [FIX 2] Concurrent DGIdb + CIViC via async
    try:
        raw = asyncio.run(_fetch_all_drugs_async(genes))
    except RuntimeError:
        # Already in an event loop (e.g. Jupyter) -- fall back to sync
        logger.warning("Event loop already running, falling back to sync")
        raw = query_dgidb(genes)
        for g in genes[:30]:
            raw.extend(query_civic(g))

    # OncoKB from local cache (no async needed)
    for v in [v for v in variants if v.tier.value <= 2][:20]:
        raw.extend(query_oncokb(v.gene, v.hgvsp))

    matches = []
    for r in raw:
        if not r.get("drug_name"):
            continue
        tier = _classify(r, cancer_type)
        sc = DRUG.EVIDENCE_SCORES.get(f"tier_{tier.value}", 0.25)
        matches.append(DrugMatch(
            drug_name=r["drug_name"], gene=r["gene"],
            variant=r.get("variant"),
            mechanism_of_action=(r.get("interaction_types") or [None])[0] if r.get("interaction_types") else None,
            evidence_tier=tier, evidence_score=sc,
            source_databases=[r["source_db"]],
            oncokb_level=r.get("oncokb_level"),
            civic_level=r.get("evidence_level"),
            fda_approved_indication=r.get("indication")))
    matches = _dedup(matches)
    return DrugReport(
        patient_id=patient_id, total_genes_queried=len(genes),
        total_matches=len(matches), matches=matches,
        no_match_flag=len(matches) == 0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test = [
        AnnotatedVariant(gene="NTRK1", variant_classification="Missense_Mutation", tier=VariantTier.KNOWN_ACTIONABLE),
        AnnotatedVariant(gene="TP53", variant_classification="Missense_Mutation", tier=VariantTier.LIKELY_ACTIONABLE),
        AnnotatedVariant(gene="CDKN2A", variant_classification="Nonsense_Mutation", tier=VariantTier.LIKELY_ACTIONABLE),
    ]
    rpt = match_drugs(test, "sarcoma", "TEST")
    print(f"\nMatches: {rpt.total_matches} from {rpt.total_genes_queried} genes")
    for m in rpt.matches[:15]:
        print(f"  [{m.evidence_tier.name}] {m.drug_name:30s} | {m.gene:8s} | {m.evidence_score:.2f}")
