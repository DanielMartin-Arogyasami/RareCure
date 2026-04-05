import os
import json
from pathlib import Path

# Define root and results directory
ROOT = Path(__file__).parent.parent
RESULTS_DIR = ROOT / "results"

def analyze_results():
    print("RareCure Results Analyzer")
    print("========================================")

    if not RESULTS_DIR.exists():
        print(f"Error: {RESULTS_DIR} does not exist.")
        return

    results = []
    skipped = 0

    # 1. Load all patient JSONs
    for file_path in RESULTS_DIR.glob("*.json"):
        # Ignore the summary stats files
        if file_path.name in ["paper_statistics.json", "batch_summary.json"]:
            continue
        
        try:
            # [FIXED] Added encoding="utf-8" to handle clinical characters without crashing
            data = json.loads(file_path.read_text(encoding="utf-8"))
            results.append(data)
        except Exception as e:
            print(f"Skipping {file_path.name}: {e}")
            skipped += 1

    total_patients = len(results)
    if total_patients == 0:
        print("No patient results found to analyze.")
        return

    print(f"Loaded {total_patients} patient results. (Skipped: {skipped})")

    # 2. Initialize counters
    total_actionable = 0
    genomic_matches = 0
    fallback_matches = 0
    total_api_cost = 0.0
    clamped_runs = 0

    # 3. Process the data
    for p in results:
        # Cost and Clamping stats
        total_api_cost += p.get("api_cost_usd", 0.0)
        if p.get("scoring_weights", {}).get("clamped", False):
            clamped_runs += 1

        # Actionability Stats (Does the patient have a Tier 1 or Tier 2 drug?)
        has_tier_1_2 = len(p.get("tier_1", [])) > 0 or len(p.get("tier_2", [])) > 0
        
        if has_tier_1_2:
            total_actionable += 1
            # [ROBUST FIX] Check system warnings for fallback triggers
        warnings = p.get("warnings", [])
        
        # If any warning mentions "common", "fallback", or "clinical", it used the safety net
        is_fallback = any(
            "common" in w.lower() or "fallback" in w.lower() or "clinical" in w.lower() 
            for w in warnings
        )
        
        if is_fallback:
            fallback_matches += 1
        else:
            genomic_matches += 1

    # 4. Calculate percentages
    tar_pct = (total_actionable / total_patients) * 100
    bmr_pct = (genomic_matches / total_patients) * 100
    gcr_pct = (fallback_matches / total_patients) * 100
    clamp_pct = (clamped_runs / total_patients) * 100

    # 5. Print formatted output for the academic paper
    print(f"\n--- Clinical Efficacy ---")
    print(f"Total Actionability Rate (TAR): {tar_pct:.1f}% ({total_actionable}/{total_patients} patients)")
    print(f"  ├─ Biomarker-Driven Matches:  {bmr_pct:.1f}% ({genomic_matches} patients)")
    print(f"  └─ Guideline Concordance:     {gcr_pct:.1f}% ({fallback_matches} patients)")
    
    print(f"\n--- System Performance ---")
    print(f"Recorded API Cost (Ignore for paper): ${total_api_cost:.2f}")
    print(f"Clamped weight runs: {clamp_pct:.1f}%")

    # 6. Save statistics for figure generation scripts
    stats_output = {
        "total_patients": total_patients,
        "total_actionable": total_actionable,
        "genomic_matches": genomic_matches,
        "fallback_matches": fallback_matches,
        "tar_pct": tar_pct,
        "bmr_pct": bmr_pct,
        "gcr_pct": gcr_pct,
        "total_api_cost_usd": total_api_cost,
        "clamped_runs": clamped_runs
    }

    stats_path = RESULTS_DIR / "paper_statistics.json"
    stats_path.write_text(json.dumps(stats_output, indent=2), encoding="utf-8")
    print(f"\nStatistics saved: {stats_path}")

if __name__ == "__main__":
    analyze_results()