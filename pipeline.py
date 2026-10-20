#!/usr/bin/env python3
"""Primary CLI entry point for the fictional-profile Synthetic Demo.

All generation goes through the synthetic pipeline's strict validation and
labeled PDF/DOCX renderer. Real candidate profiles are rejected by its
synthetic/profiles/ isolation gate.

Usage:
    python3 pipeline.py --profile synthetic/profiles/alex-carter.json \
        --jd-file jd.txt --jd-title "Database Developer"

For a pre-recorded model response, pass --llm-file response.json.
"""
from synthetic.synthetic_pipeline import main

if __name__ == "__main__":
    main()
