#!/usr/bin/env python3
"""
RareCure Results Analyzer

Computes all paper statistics from batch results.
    python scripts/analyze_results.py
"""

import json
import logging
import sys
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
RESULTS_DIR = ROOT / "results"
FIGURES_DIR = ROOT / "paper" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

def clopper_pearson(successes, total, alpha=0.05):
    """Exact binomial CI (Clopper-Pearson method)."""
    if total == 0: return 0.0, 0.0, 0.0
    proportion = successes / total
    ci = stats.binomtest(successes, total).proportion_ci(confidence_level=1 - alpha, method="exact")
    return proportion * 100, ci.low * 100, ci.high * 100

def load_results(results_dir):
    results = []
    for f in sorted(results_dir.glob("*.json")):
        if f.name in ("paper_statistics.json", "batch_summary.json"): continue
        try:
            results.append(json.loads(f.read_text()))
        except Exception as e:
            logger.warning(f"Skipping {f.name}: {e}")
    return results

def analyze(results):
    s = {}
    N = len(results)
    if N == 0: return s, {}
    s["N"] = N

    # Tier 1/2 Match Rate
    n_t1t2 = sum(1 for r in results if r.get("tier_1") or r.get("tier_2"))
    pct, ci_low, ci_high = clopper_pearson(n_t1t2, N)
    s.update({"N_T1T2": n_t1t2, "PCT_T1T2": f"{pct:.1f}", "CI_LOW": f"{ci_low:.1f}", "CI_HIGH": f"{ci_high:.1f}"})

    # Trial Match Rate
    def trial_count(r):
        return sum(1 for t in r.get("tier_1", []) + r.get("tier_2", []) + r.get("tier_3", []) + r.get("tier_4", [])
                   if t.get("treatment_type") == "trial")
    n_trial = sum(1 for r in results if trial_count(r) > 0)
    pct_t, ci_t_low, ci_t_high = clopper_pearson(n_trial, N)
    s.update({"N_TRIAL": n_trial, "PCT_TRIAL": f"{pct_t:.1f}", "CI_TRIAL_LOW": f"{ci_t_low:.1f}", "CI_TRIAL_HIGH": f"{ci_t_high:.1f}"})

    # Medians
    drug_counts = [r.get("total_options", 0) for r in results]
    s.update({"MEDIAN_DRUGS": f"{np.median(drug_counts):.0f}", "IQR_DRUGS": f"{np.percentile(drug_counts, 25):.0f}-{np.percentile(drug_counts, 75):.0f}"})

    # Subtype-stratified rates
    subtype_data = {}
    for r in results:
        parts = r.get("patient_summary", "").split(", ")
        cancer = parts[1] if len(parts) >= 2 else "unknown"
        has_t12 = bool(r.get("tier_1") or r.get("tier_2"))
        subtype_data.setdefault(cancer, {"total": 0, "t12": 0})
        subtype_data[cancer]["total"] += 1
        subtype_data[cancer]["t12"] += int(has_t12)

    # Cost & Clamping
    costs = [r.get("api_cost_usd", 0) for r in results]
    n_clamped = sum(1 for r in results if r.get("scoring_weights", {}).get("clamped"))
    s.update({
        "TOTAL_COST": f"{sum(costs):.2f}",
        "COST_PER": f"{np.median(costs):.4f}",
        "N_CLAMPED": n_clamped,
        "PCT_CLAMPED": f"{n_clamped / N * 100:.1f}"
    })

    return s, subtype_data

def generate_figures(subtype_data):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    subtypes_for_plot = {k: v for k, v in subtype_data.items() if v["total"] >= 5}
    if subtypes_for_plot:
        names = list(subtypes_for_plot.keys())
        rates = [v["t12"] / v["total"] * 100 for v in subtypes_for_plot.values()]
        totals = [v["total"] for v in subtypes_for_plot.values()]

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.barh(names, rates, color="#4C72B0", alpha=0.8)
        ax.set_xlabel("Patients with Tier 1/2 Match (%)")
        ax.set_title("Actionable Findings by Sarcoma Subtype")
        for i, (rate, total) in enumerate(zip(rates, totals)):
            ax.text(rate + 1, i, f"n={total}", va="center", fontsize=9)
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "fig2_subtypes.png", dpi=150)
        plt.close()

def main():
    print("RareCure Results Analyzer\n" + "=" * 40)
    results = load_results(RESULTS_DIR)
    if not results:
        print("No result JSONs found. Run batch_run.py first.")
        sys.exit(1)

    statistics, subtype_data = analyze(results)
    stats_path = RESULTS_DIR / "paper_statistics.json"
    stats_path.write_text(json.dumps(statistics, indent=2))

    print(f"Loaded {statistics['N']} patient results.")
    print(f"Tier 1/2 match: {statistics['PCT_T1T2']}% (95% CI: {statistics['CI_LOW']}-{statistics['CI_HIGH']}%)")
    print(f"Total API cost: ${statistics['TOTAL_COST']}")
    print(f"Clamped weight runs: {statistics['PCT_CLAMPED']}%\n")

    generate_figures(subtype_data)
    print(f"Statistics saved: {stats_path}")

if __name__ == "__main__":
    main()
