import os
import httpx
import requests
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_all_connections():
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    oncokb_key = os.getenv("ONCOKB_API_KEY")

    headers = {
        "User-Agent": "RareCureResearch/1.0 (Educational Project)",
        "Accept": "application/json"
    }

    print("--- RareCure API Diagnostic ---\n")

    async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
        # 1. Anthropic (Claude)
        if not anthropic_key:
            print("[FAIL] ANTHROPIC: Key missing in .env")
        else:
            try:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01"},
                    json={"model": "claude-sonnet-4-20250514", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
                )
                if r.status_code == 200: print("[ OK ] ANTHROPIC: Authenticated")
                else: print(f"[FAIL] ANTHROPIC: {r.status_code} - {r.text[:200]}")
            except Exception as e: print(f"[FAIL] ANTHROPIC: Error - {e}")

        # 2. OncoKB
        if not oncokb_key:
            print("[FAIL] ONCOKB: Key missing in .env")
        else:
            try:
                r = await client.get(
                    "https://www.oncokb.org/api/v1/info",
                    headers={"Authorization": f"Bearer {oncokb_key}"}
                )
                if r.status_code == 200: print("[ OK ] ONCOKB: Authenticated")
                else: print(f"[FAIL] ONCOKB: {r.status_code} - {r.text[:200]}")
            except Exception as e: print(f"[FAIL] ONCOKB: Error - {e}")

        # 3. DGIdb
        try:
            r = await client.get("https://dgidb.org/api/v2/interactions.json?genes=TP53")
            if r.status_code == 200: print("[ OK ] DGIDB: Accessible")
            else: print(f"[FAIL] DGIDB: {r.status_code}")
        except Exception as e: print(f"[FAIL] DGIDB: Error - {e}")

        # 4. CIViC (GraphQL)
        try:
            r = await client.post(
                "https://civicdb.org/api/graphql",
                json={"query": '{ gene(entrezSymbol: "TP53") { name } }'},
                headers={"Content-Type": "application/json"}
            )
            data = r.json()
            gene = (data.get("data") or {}).get("gene")
            if r.status_code == 200 and gene:
                print(f"[ OK ] CIVIC: GraphQL accessible (gene={gene['name']})")
            else: print(f"[FAIL] CIVIC: {r.status_code} - {r.text[:200]}")
        except Exception as e: print(f"[FAIL] CIVIC: Error - {e}")

    # 5. ClinicalTrials.gov (uses requests, not httpx)
    try:
        r = requests.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={"query.cond": "sarcoma", "pageSize": "1", "format": "json"},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; RareCure/1.0)"},
            timeout=15)
        if r.status_code == 200:
            n = len(r.json().get("studies", []))
            print(f"[ OK ] CLINICALTRIALS.GOV: Accessible ({n} study returned)")
        else: print(f"[FAIL] CLINICALTRIALS.GOV: {r.status_code}")
    except Exception as e: print(f"[FAIL] CLINICALTRIALS.GOV: Error - {e}")

    print("\n--- Done ---")

if __name__ == "__main__":
    asyncio.run(test_all_connections())
