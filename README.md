# RareCure
**AI-Orchestrated Treatment Discovery for Rare Solid Tumors**

    cd RareCure && pip install -r requirements.txt && export ANTHROPIC_API_KEY="sk-..."
    python -m rarecure.drug_match
    python -m rarecure.trial_match
    python -m rarecure.scoring
    python -m rarecure.pipeline --patient-json data/sample/patient_f.json
    pytest tests/ -v -m "not integration"

Architecture: Patient -> [Variants] -> [Neoantigens] -> [Drugs] -> [Trials] -> [Evidence] -> [Scoring] -> Plan
MIT License.
