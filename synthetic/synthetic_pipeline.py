#!/usr/bin/env python3
"""Synthetic testing pipeline — SEPARATE from the production pipeline.

Flow: Fictional Profile → Target JD → LLM Role Transformation →
      Strict JSON Validation → Synthetic Resume Renderer → Final Resume

Isolation rules (enforced in code, not by convention):
  - Input profiles are accepted ONLY from synthetic/profiles/.
  - All outputs land in synthetic/runs/<timestamp>-<slug>/ — the original
    profile snapshot, the validated transformed JSON, a comparison
    report, and the rendered PDF/DOCX live side by side for evaluation.
  - The production pipeline (pipeline.py), its renderer (render.py), and
    the active fact-preserving prompt (tailoring/llm_prompt.txt) are
    never touched. This tool reads the synthetic prompt from
    tailoring/llm_prompt_custom.txt.
  - Every rendered resume carries the SYNTHETIC banner enforced by
    render_synthetic.py.

Usage:
  python3 synthetic_pipeline.py --profile synthetic/profiles/alex-carter.json \
      --jd-file <jd.txt> --jd-title "Staff+ Software Engineer, VectorDB" \
      [--llm gemini | --llm-file canned-response.json]
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from tailoring.engine import load_rules, extract_jd_keywords  # noqa: E402
from tailoring.llm import _gemini                              # noqa: E402
from validate import validate, normalize                       # noqa: E402
from compare import compare                                    # noqa: E402
import render_synthetic                                        # noqa: E402

PROFILES_DIR = HERE / "profiles"
RUNS_DIR = HERE / "runs"
PROMPT_FILE = ROOT / "tailoring" / "llm_prompt_custom.txt"

# Appended to the synthetic prompt at run time (the prompt file itself is
# untouched). The user's prompt names resume SECTIONS but not exact JSON
# key shapes, so shapes drift between runs; this contract pins the exact
# schema v2 that validate.py enforces.
KEY_CONTRACT = """

JSON KEY CONTRACT (a strict validator enforces exactly this — any
deviation is rejected and nothing renders):
Return one JSON object with EXACTLY these top-level keys:
- "candidate": {"name": string, "contact": {"location": string,
  "phone": string, "email": string, optional "github", "linkedin",
  "portfolio"}}
- "target_job": {"title": string}
- "professional_summary": string (REQUIRED — never omit it)
- "technical_skills": array of strings
- "professional_experience": array of objects {"company": string,
  "title": string, "dates": string, "location": string,
  "bullets": array of strings} — bullet counts per the expansion rules:
  6-8 for the most recent role, 4-6 for the previous role, 3-5 for
  earlier or junior roles
- "projects": array of 2-3 objects {"name": string, "objective": string,
  "architecture": string, "stack": array of strings, "outcome": string,
  "bullets": array of 3-5 strings}
- "certifications": array of strings (may be empty)
- "education": array of objects {"school": string, "degree": string,
  "dates": string}
- "generation_metadata": object that MUST contain "is_synthetic": true
No other top-level keys."""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "run"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True,
                    help="fictional profile JSON — MUST live in synthetic/profiles/")
    ap.add_argument("--jd-file", required=True)
    ap.add_argument("--jd-title", required=True)
    ap.add_argument("--llm", choices=["gemini"], default="gemini")
    ap.add_argument("--llm-file", default=None,
                    help="use a canned LLM response file instead of calling Gemini")
    args = ap.parse_args()

    # ---- isolation gate -------------------------------------------------
    profile_path = Path(args.profile).resolve()
    if PROFILES_DIR.resolve() not in profile_path.parents:
        sys.exit(f"ISOLATION: profiles are only accepted from {PROFILES_DIR} "
                 f"(got {profile_path}). The synthetic pipeline never reads "
                 f"real candidate data.")
    profile = json.loads(profile_path.read_text())
    jd_text = Path(args.jd_file).read_text()
    if not PROMPT_FILE.exists():
        sys.exit(f"synthetic prompt not found: {PROMPT_FILE}")

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    run_dir = RUNS_DIR / f"{stamp}-{slug(profile['name'])}-{slug(args.jd_title)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "original.json").write_text(json.dumps(profile, indent=1))

    # ---- LLM transformation --------------------------------------------
    rules = load_rules()
    kw = extract_jd_keywords(jd_text, rules)
    kw_list = sorted(kw, key=lambda k: -kw[k])[:15] if isinstance(kw, dict) \
        else list(kw)[:15]
    first = profile["experience"][0]
    original_role = first.get("role") or first.get("title", "")
    industries = profile.get("employer_industries", {})
    industries_text = "; ".join(f"{co}: {ind}" for co, ind in industries.items()) \
        or "Not specified — infer conservatively from each employer's name."
    prompt = (PROMPT_FILE.read_text()
              .replace("{original_resume}", json.dumps(profile, indent=1))
              .replace("{original_role}", original_role)
              .replace("{jd_title}", args.jd_title)
              .replace("{job_description}", jd_text[:8000])
              .replace("{keywords}", ", ".join(kw_list))
              .replace("{employer_industries}", industries_text)) + KEY_CONTRACT
    (run_dir / "prompt-used.txt").write_text(prompt)

    if args.llm_file:
        raw = Path(args.llm_file).read_text()
        note = f"canned response from {args.llm_file}"
    else:
        raw, note = _gemini(prompt)
        if raw is None:
            sys.exit(f"LLM unavailable: {note}")
    (run_dir / "llm-raw.txt").write_text(raw or "")

    txt = (raw or "").strip().removeprefix("```json").removeprefix("```") \
        .removesuffix("```").strip()
    try:
        data = json.loads(txt)
    except Exception as e:
        sys.exit(f"VALIDATION FAILED: LLM output is not valid JSON ({e}). "
                 f"Raw output saved in {run_dir}/llm-raw.txt — nothing rendered.")

    # ---- strict validation gate -----------------------------------------
    errors = validate(data, original=profile)
    if errors:
        (run_dir / "transformed-invalid.json").write_text(json.dumps(data, indent=1))
        print("VALIDATION FAILED — resume NOT rendered:")
        for e in errors:
            print(f"  - {e}")
        print(f"Offending JSON saved to {run_dir}/transformed-invalid.json")
        sys.exit(3)
    (run_dir / "transformed.json").write_text(json.dumps(data, indent=1))
    print(f"[validate] strict schema v2 OK ({note})")
    norm = normalize(data)

    # ---- comparison (original vs transformed, preserved separately) -----
    report = compare(profile, norm, args.jd_title, kw_list)
    (run_dir / "comparison.md").write_text(report)

    # ---- render -----------------------------------------------------------
    pdf = run_dir / "resume-synthetic.pdf"
    docx = run_dir / "resume-synthetic.docx"
    render_synthetic.render_pdf(norm, str(pdf))
    render_synthetic.render_docx(norm, str(docx))
    print(f"[render] {pdf}")
    print(f"[render] {docx}")
    print(f"[run] {run_dir}")


if __name__ == "__main__":
    main()
