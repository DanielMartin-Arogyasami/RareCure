"""RareCure environment, TCGA data layout, and external API diagnostics.

Run from repo root:

    python scripts/diagnostic.py
    python -m rarecure.diagnostic
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pandas as pd
import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

from rarecure.config import DATA_DIR, RESULTS_DIR, ROOT_DIR

PID_COL_CANDIDATES = [
    "submitter_id", "case_submitter_id", "bcr_patient_barcode", "case_id",
]


def _find_pid_col(df: pd.DataFrame) -> str | None:
    for c in PID_COL_CANDIDATES:
        if c in df.columns:
            return c
    return None


def run_data_diagnostics() -> None:
    print("--- Data layout ---\n")
    tcga = DATA_DIR / "tcga"
    clin = tcga / "clinical.tsv"
    maf = tcga / "TCGA-SARC.maf.txt"
    hla_paths = [
        DATA_DIR / "hla" / "thorsson_hla_calls.tsv",
        DATA_DIR / "HLA" / "thorsson_hla_calls.tsv",
    ]

    print(f"ROOT_DIR: {ROOT_DIR}")
    print(f"DATA_DIR: {DATA_DIR}")
    print(f"RESULTS_DIR: {RESULTS_DIR}\n")

    if clin.exists():
        sz = clin.stat().st_size // 1024
        print(f"[ OK ] clinical.tsv: {clin} ({sz} KB)")
        try:
            df = pd.read_csv(clin, sep="\t", low_memory=False)
            pid = _find_pid_col(df)
            print(f"       rows={len(df)}, cols={len(df.columns)}")
            if pid:
                n = df[pid].astype(str).str.strip().str[:12].nunique()
                print(f"       patient_id column={pid!r}, unique_12char={n}")
            else:
                print("       [WARN] no known patient_id column (see batch_run COLUMN_VARIANTS)")
        except Exception as e:
            print(f"       [FAIL] read error: {e}")
    else:
        print(f"[ -- ] clinical.tsv missing: {clin}")

    if maf.exists():
        sz = maf.stat().st_size // (1024 * 1024)
        print(f"[ OK ] MAF: {maf} ({sz} MB)")
        try:
            chunk = next(
                pd.read_csv(
                    maf, sep="\t", comment="#", low_memory=False,
                    chunksize=50_000, usecols=["Tumor_Sample_Barcode"]))
            n = chunk["Tumor_Sample_Barcode"].astype(str).str[:12].nunique()
            print(f"       sample barcodes (first chunk, unique 12-char): {n}")
        except Exception as e:
            print(f"       [WARN] MAF peek failed: {e}")
    else:
        print(f"[ -- ] MAF missing: {maf}")

    hla_ok = next((p for p in hla_paths if p.exists()), None)
    if hla_ok:
        print(f"[ OK ] HLA: {hla_ok}")
    else:
        print(f"[ -- ] HLA TSV missing (tried hla/ and HLA/)")

    if RESULTS_DIR.exists():
        skip = {"paper_statistics.json", "batch_summary.json"}
        all_json = [p for p in RESULTS_DIR.glob("*.json") if p.name not in skip]
        tcga_json = [p for p in all_json if p.name.startswith("TCGA-")]
        other = [p for p in all_json if not p.name.startswith("TCGA-")]
        print(f"\n[ OK ] results/: {len(tcga_json)} TCGA patient JSON, {len(other)} other")
        summ = RESULTS_DIR / "batch_summary.csv"
        if summ.exists():
            print(f"       batch_summary.csv: {summ.stat().st_size // 1024} KB")
    else:
        print("\n[ -- ] results/ missing")


async def run_api_diagnostics() -> None:
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    oncokb_key = os.getenv("ONCOKB_API_KEY")

    headers = {
        "User-Agent": "RareCureResearch/1.0 (Educational Project)",
        "Accept": "application/json",
    }

    print("\n--- API connectivity ---\n")

    async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
        if not anthropic_key:
            print("[FAIL] ANTHROPIC: key missing in .env")
        else:
            try:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01"},
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                print("[ OK ] ANTHROPIC" if r.status_code == 200 else f"[FAIL] ANTHROPIC: {r.status_code}")
            except Exception as e:
                print(f"[FAIL] ANTHROPIC: {e}")

        if not oncokb_key:
            print("[FAIL] ONCOKB: key missing in .env")
        else:
            try:
                r = await client.get(
                    "https://www.oncokb.org/api/v1/info",
                    headers={"Authorization": f"Bearer {oncokb_key}"},
                )
                print("[ OK ] ONCOKB" if r.status_code == 200 else f"[FAIL] ONCOKB: {r.status_code}")
            except Exception as e:
                print(f"[FAIL] ONCOKB: {e}")

        try:
            r = await client.get("https://dgidb.org/api/v2/interactions.json?genes=TP53")
            print("[ OK ] DGIDB" if r.status_code == 200 else f"[FAIL] DGIDB: {r.status_code}")
        except Exception as e:
            print(f"[FAIL] DGIDB: {e}")

        try:
            r = await client.post(
                "https://civicdb.org/api/graphql",
                json={"query": '{ gene(entrezSymbol: "TP53") { name } }'},
                headers={"Content-Type": "application/json"},
            )
            gene = (r.json().get("data") or {}).get("gene")
            print("[ OK ] CIVIC GraphQL" if r.status_code == 200 and gene else f"[FAIL] CIVIC: {r.status_code}")
        except Exception as e:
            print(f"[FAIL] CIVIC: {e}")

    try:
        r = requests.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={"query.cond": "sarcoma", "pageSize": "1", "format": "json"},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; RareCure/1.0)"},
            timeout=20,
        )
        ok = r.status_code == 200 and r.json().get("studies")
        print("[ OK ] CLINICALTRIALS.GOV (requests)" if ok else f"[FAIL] CLINICALTRIALS.GOV: {r.status_code}")
    except Exception as e:
        print(f"[FAIL] CLINICALTRIALS.GOV: {e}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RareCure data + API diagnostics")
    ap.add_argument("--data-only", action="store_true", help="Skip API checks")
    ap.add_argument("--apis-only", action="store_true", help="Skip data checks")
    args = ap.parse_args(argv)

    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    print("RareCure diagnostic\n" + "=" * 40)

    if not args.apis_only:
        run_data_diagnostics()
    if not args.data_only:
        asyncio.run(run_api_diagnostics())

    print("\n--- Done ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
