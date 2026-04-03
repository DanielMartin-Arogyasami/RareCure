"""Module 4: Trials. [FIX 2] async httpx [FIX 4] specific exceptions [FIX 5] ontology."""
import asyncio
import logging
import re
import httpx
from rarecure.config import API, TRIAL, CANCER_ONTOLOGY, API_SEMAPHORE_LIMIT
from rarecure.models import TrialMatch, TrialReport, PatientProfile

logger = logging.getLogger(__name__)
_semaphore = asyncio.Semaphore(API_SEMAPHORE_LIMIT)


async def _search_async(client: httpx.AsyncClient, q: str, n: int = 50) -> list[dict]:
    """Single trial search with semaphore rate limiting."""
    async with _semaphore:
        r = await client.get(
            f"{API.CLINICAL_TRIALS}/studies",
            params={
                "query.cond": q,
                "filter.overallStatus": ",".join(TRIAL.STATUS_FILTER),
                "pageSize": min(n, TRIAL.MAX_RESULTS_PER_QUERY),
                "format": "json"},
            timeout=30)
        r.raise_for_status()
    st = r.json().get("studies", [])
    logger.info(f"CT.gov: {len(st)} for '{q}'")
    return st


def _elig(study, pt):
    el = study.get("protocolSection", {}).get("eligibilityModule", {})
    txt = el.get("eligibilityCriteria", "")
    m = re.search(r"(\d+)\s*years?.*(?:or older|and older)", txt, re.I)
    if m and pt.age < int(m.group(1)):
        return False, f"Age<{m.group(1)}"
    sx = el.get("sex", "ALL")
    if sx != "ALL" and ((sx == "FEMALE" and pt.sex == "M") or (sx == "MALE" and pt.sex == "F")):
        return False, "Sex"
    return True, "Eligible"


def _score(study, pt, genes):
    p = study.get("protocolSection", {})
    ph = p.get("designModule", {}).get("phases", [])
    ps = TRIAL.PHASE_SCORES.get((ph[0] if ph else "").upper().replace(" ", ""), 0.3)
    ti = p.get("identificationModule", {}).get("briefTitle", "").lower()
    iv = " ".join(
        i.get("name", "")
        for i in p.get("armsInterventionsModule", {}).get("interventions", [])
    ).lower()
    txt = ti + " " + iv
    gs = 1.0 if any(g.lower() in txt for g in genes) else (
        0.5 if any(k in txt for k in ["tmb", "msi", "ntrk"]) else 0.0)
    co = " ".join(p.get("conditionsModule", {}).get("conditions", [])).lower()
    cn = pt.cancer_type.lower().replace("_", " ")
    hs = 1.0 if cn in co else (0.5 if "sarcoma" in co else (0.3 if "solid tumor" in co else 0.0))
    locs = p.get("contactsLocationsModule", {}).get("locations", [])
    ctry = [l.get("country", "") for l in locs]
    geo = 1.0 if "United States" in ctry else (0.8 if pt.geography in ctry else 0.3)
    w = TRIAL.RELEVANCE_WEIGHTS
    return round(
        ps * w["phase"] + gs * w["genomic_match"] +
        hs * w["histology_match"] + geo * w["geographic_proximity"], 4)


def _expand_queries(cancer_type, genes):
    """[FIX 5] Ontology-aware query expansion."""
    base = cancer_type.replace("_", " ")
    qs = [base]
    for g in genes[:5]:
        qs.append(f"{base} {g}")
    ontology_key = next((k for k in CANCER_ONTOLOGY if k in cancer_type.lower()), "default")
    for parent in CANCER_ONTOLOGY[ontology_key]:
        qs.append(parent)
        for g in genes[:3]:
            qs.append(f"{parent} {g}")
    return list(dict.fromkeys(qs))


async def _search_all_async(queries: list[str]) -> dict[str, dict]:
    """[FIX 2] Concurrent trial searches across all expanded queries."""
    all_st = {}
    async with httpx.AsyncClient(
        headers={"Accept": "application/json", "User-Agent": "RareCure/1.0"}
    ) as client:
        tasks = [_search_async(client, q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            logger.exception(f"Trial search failed: {r}")
            continue
        for s in r:
            nct = s.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "")
            if nct and nct not in all_st:
                all_st[nct] = s
    return all_st


def match_trials(patient, genes=None):
    genes = genes or []
    qs = _expand_queries(patient.cancer_type, genes)
    if patient.tmb_status == "high":
        qs.append("TMB-high solid tumor")
    if patient.msi_status == "MSI-H":
        qs.append("MSI-high")
    qs = list(dict.fromkeys(qs))

    # [FIX 2] Async concurrent search
    try:
        all_st = asyncio.run(_search_all_async(qs))
    except RuntimeError:
        logger.warning("Event loop running, sync fallback")
        all_st = {}
        for q in qs:
            try:
                for s in httpx.get(
                    f"{API.CLINICAL_TRIALS}/studies",
                    params={"query.cond": q,
                            "filter.overallStatus": ",".join(TRIAL.STATUS_FILTER),
                            "pageSize": TRIAL.MAX_RESULTS_PER_QUERY,
                            "format": "json"},
                    timeout=30
                ).json().get("studies", []):
                    nct = s.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "")
                    if nct and nct not in all_st:
                        all_st[nct] = s
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                logger.exception(f"'{q}' failed")

    matches = []
    for nct, s in all_st.items():
        p = s.get("protocolSection", {})
        ok, notes = _elig(s, patient)
        rel = _score(s, patient, genes)
        ti = p.get("identificationModule", {}).get("briefTitle", "")
        loc = p.get("contactsLocationsModule", {}).get("locations", [])
        loc_strs = [f"{l.get('city', '')}, {l.get('state', '')}" for l in loc[:5]]
        matches.append(TrialMatch(
            nct_id=nct, title=ti,
            phase=", ".join(p.get("designModule", {}).get("phases", [])),
            status=p.get("statusModule", {}).get("overallStatus", ""),
            conditions=p.get("conditionsModule", {}).get("conditions", []),
            interventions=[
                i.get("name", "")
                for i in p.get("armsInterventionsModule", {}).get("interventions", [])],
            eligibility_met=ok, eligibility_notes=notes, relevance_score=rel,
            genomic_match=any(g.lower() in ti.lower() for g in genes),
            locations=loc_strs,
            url=f"https://clinicaltrials.gov/study/{nct}"))
    matches.sort(key=lambda m: (m.eligibility_met, m.relevance_score), reverse=True)
    return TrialReport(
        patient_id=patient.patient_id, query_terms_used=qs,
        total_retrieved=len(all_st),
        total_eligible=sum(1 for m in matches if m.eligibility_met),
        trials=matches)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = PatientProfile(
        patient_id="TEST_F", input_mode="clinical", age=55, sex="M",
        cancer_type="spindle_cell_sarcoma", stage="IV",
        lines_exhausted=2, current_status="partial response", geography="India")
    r = match_trials(p, ["TP53", "CDKN2A"])
    print(f"\n{r.total_eligible} eligible / {r.total_retrieved} retrieved")
    print(f"Queries: {r.query_terms_used}")
    for t in r.trials[:10]:
        print(f"  [{'Y' if t.eligibility_met else 'N'}] {t.nct_id} | {t.relevance_score:.3f} | {t.title[:65]}")
