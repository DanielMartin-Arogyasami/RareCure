"""
RareCure Publication Figure Generator
Generates high-DPI, publication-ready multi-panel figures for academic submission.
"""

import os
import json
from pathlib import Path
from collections import Counter
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# --- Configuration & Paths ---
ROOT_DIR = Path(__file__).parent.parent
RESULTS_DIR = ROOT_DIR / "results"
OUTPUT_PNG = RESULTS_DIR / "figure_1_clinical_utility.png"
OUTPUT_PDF = RESULTS_DIR / "figure_1_clinical_utility.pdf"

# --- Publication Aesthetics ---
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 10,
    "axes.titlesize": 14,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "figure.titlesize": 16,
    "figure.dpi": 300,
    "axes.spines.top": False,
    "axes.spines.right": False
})

# Custom Clinical Color Palette
COLORS = {
    "High Evidence (Tier 1-2)": "#2A7B9B",  # Trust/Clinical Blue
    "Investigational (Tier 3-4)": "#E3A654", # Preclinical Amber
    "Guideline Fallback": "#8C9B9D",         # Neutral Grey
    "Tier 1": "#1D5469",
    "Tier 2": "#3A9CBF",
    "Tier 3": "#E68C35",
    "Tier 4": "#F2C288",
}

def load_patient_data():
    """Parses the raw JSONs to extract exact clinical outcomes."""
    patients = []
    top_genes = Counter()
    
    files = [f for f in RESULTS_DIR.glob("*.json") if f.name not in ["paper_statistics.json", "batch_summary.json"]]
    
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        
        # Determine Fallback status
        warnings = data.get("warnings", [])
        is_fallback = any("common" in w.lower() or "fallback" in w.lower() or "clinical" in w.lower() for w in warnings)
        
        t1 = data.get("tier_1", [])
        t2 = data.get("tier_2", [])
        t3 = data.get("tier_3", [])
        t4 = data.get("tier_4", [])
        
        # Categorize the highest level of evidence
        if is_fallback:
            category = "Guideline Fallback"
            highest_tier = "Fallback"
        elif t1 or t2:
            category = "High Evidence (Tier 1-2)"
            highest_tier = "Tier 1" if t1 else "Tier 2"
        elif t3 or t4:
            category = "Investigational (Tier 3-4)"
            highest_tier = "Tier 3" if t3 else "Tier 4"
        else:
            category = "Guideline Fallback"
            highest_tier = "Fallback"

        patients.append({
            "id": data.get("patient_id", "Unknown"),
            "category": category,
            "highest_tier": highest_tier
        })
        
        # Track targeted genes (only for actual genomic matches)
        if not is_fallback:
            for t in t1 + t2 + t3 + t4:
                if t.get("gene"):
                    top_genes[t.get("gene")] += 1
                    
    return pd.DataFrame(patients), top_genes

def main():
    print("Aggregating N=260 cohort data for publication figures...")
    df, top_genes = load_patient_data()
    
    if df.empty:
        print("Error: No patient data found in results directory.")
        return

    # Create a 1x3 composite figure layout
    fig = plt.figure(figsize=(16, 5.5))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1.2, 1.2])
    
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    ax3 = fig.add_subplot(gs[2])

    # ==========================================
    # PANEL A: Total Actionability (Donut Chart)
    # ==========================================
    cat_counts = df["category"].value_counts()
    
    # Ensure specific order
    order = ["High Evidence (Tier 1-2)", "Investigational (Tier 3-4)", "Guideline Fallback"]
    sizes = [cat_counts.get(c, 0) for c in order]
    colors = [COLORS[c] for c in order]
    
    wedges, texts, autotexts = ax1.pie(
        sizes, 
        colors=colors,
        labels=order,
        autopct='%1.1f%%',
        startangle=90,
        pctdistance=0.75,
        explode=(0.05, 0.05, 0.05),
        wedgeprops=dict(width=0.4, edgecolor='w', linewidth=2)
    )
    
    for text in texts:
        text.set_fontsize(11)
    for autotext in autotexts:
        autotext.set_fontsize(10)
        autotext.set_weight('bold')
        autotext.set_color('white')

    ax1.set_title("A. Cohort Treatment Routing", pad=20, weight='bold')

    # ==========================================
    # PANEL B: Highest Evidence Level (Bar Chart)
    # ==========================================
    tier_order = ["Tier 1", "Tier 2", "Tier 3", "Tier 4", "Fallback"]
    tier_counts = df["highest_tier"].value_counts().reindex(tier_order, fill_value=0)
    
    tier_colors = [COLORS.get(t, COLORS["Guideline Fallback"]) for t in tier_order]
    
    bars = ax2.bar(tier_order, tier_counts.values, color=tier_colors, width=0.6)
    ax2.set_title("B. Highest Level of Evidence Reached", pad=20, weight='bold')
    ax2.set_ylabel("Number of Patients")
    ax2.grid(axis='y', linestyle='--', alpha=0.6)
    
    # Add value labels on top of bars
    for bar in bars:
        height = bar.get_height()
        ax2.annotate(f'{int(height)}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom', weight='bold')

    # ==========================================
    # PANEL C: Top Targetable Alterations (H-Bar)
    # ==========================================
    # Get top 10 genes
    top_10 = top_genes.most_common(10)
    if top_10:
        genes, counts = zip(*top_10)
        
        # Reverse to have the highest at the top of the plot
        genes = list(genes)[::-1]
        counts = list(counts)[::-1]
        
        y_pos = np.arange(len(genes))
        ax3.barh(y_pos, counts, color="#2E4053", height=0.6)
        
        ax3.set_yticks(y_pos)
        ax3.set_yticklabels(genes, style='italic') # Genes should be italicized in medical papers
        ax3.set_xlabel("Total Biomarker Matches")
        ax3.set_title("C. Most Frequently Targeted Alterations", pad=20, weight='bold')
        ax3.grid(axis='x', linestyle='--', alpha=0.6)
    else:
        ax3.text(0.5, 0.5, "No targetable genes found.", ha='center', va='center')
        ax3.set_title("C. Top Actionable Targets", pad=20, weight='bold')

    # --- Final Layout Adjustments ---
    plt.tight_layout(pad=3.0)
    
    # Save high-res outputs
    plt.savefig(OUTPUT_PDF, format='pdf', bbox_inches='tight')
    plt.savefig(OUTPUT_PNG, format='png', bbox_inches='tight', dpi=300)
    
    print(f"\nSUCCESS! Publication figures generated.")
    print(f"📄 PDF format (for journal submission): {OUTPUT_PDF}")
    print(f"🖼️ PNG format (for slides/docs): {OUTPUT_PNG}")

if __name__ == "__main__":
    main()