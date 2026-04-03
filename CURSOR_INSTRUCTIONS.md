# Cursor AI — Remaining Build Tasks

Base code working with async I/O, thread-safe caching, weight clamping,
ontology expansion, and specific exceptions. Complete these:

1. Verify: python -m rarecure.drug_match / trial_match / scoring
2. scripts/download_tcga.py — GDC API data download
3. scripts/batch_run.py — process 265 TCGA-SARC patients (use async pipeline)
4. Implement rarecure/neoantigen.py — pVACtools wrapper
5. Implement rarecure/rag_engine.py — PubMed RAG

   CRITICAL for Task 5: Do NOT use E-utilities for bulk indexing.
   Use NCBI FTP baseline XMLs (ftp.ncbi.nlm.nih.gov/pubmed/baseline/)
   for bulk ingestion. E-utilities is for targeted queries only.
   Rate limit: max 3 req/sec without API key, 10 with key.
   Use config.PUBMED_FTP_BASELINE and config.PUBMED_RATE_LIMIT.

6. scripts/index_pubmed.py — bulk FTP download + chunk + embed + ChromaDB
7. Wire RAG evidence into pipeline.py scoring
8. scripts/analyze_results.py — paper stats with Clopper-Pearson CIs
9. scripts/generate_report.py — markdown + PDF reports
10. Expand test suite with mocks for all modules
11. notebooks/validation.ipynb
12. pyproject.toml with mypy + ruff
