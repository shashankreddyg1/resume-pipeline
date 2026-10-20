# Synthetic Resume Transformation Engine — LLM Testing Framework

**This is a synthetic test-data generation and LLM evaluation framework.
It does not produce resumes for real people or real job applications.**

It transforms *fictional* candidate profiles toward a target job
description with an LLM, then validates, renders, and scores the result —
so prompts, schemas, and renderers can be tested end-to-end without ever
touching real candidate data.

Every rendered resume carries a code-enforced banner:

> **SYNTHETIC TEST RESUME — NOT FOR REAL-WORLD APPLICATIONS**

plus a per-page footer and synthetic-prefixed document metadata. The
labeling lives in `render_synthetic.py`, not in the prompt — the model
cannot remove it, and certifications render with
"(synthetic — unverified)" appended.

## Architecture

```
Fictional Profile → Target JD → LLM Role Transformation →
Strict JSON Validation → Synthetic Resume Renderer → Final Resume
        │                                                    │
        └──── original.json preserved ────┐                  │
                                          ▼                  │
                              comparison.md (evaluation) ◄───┘
```

| File | Role |
|---|---|
| `synthetic_pipeline.py` | Orchestrator CLI. Enforces isolation, builds the prompt, calls the LLM, gates on validation, renders, and writes the comparison report. Appends a JSON **key contract** (schema v2) to the prompt at run time. |
| `validate.py` | Strict schema validator. Rejects malformed JSON, missing/wrong-typed fields, unresolved `{placeholders}`, serialized JSON inside text fields, unknown keys, bullet counts outside the expansion ranges, under-detailed projects — and any payload whose `generation_metadata.is_synthetic` is not `true`. Metadata is validated but **never rendered**. |
| `render_synthetic.py` | Dedicated renderer for the whole-resume JSON (PDF + DOCX). Reuses only the production renderer's formatting styles; inserts the synthetic banner, footer, and metadata in code. |
| `compare.py` | Original-vs-transformed evaluation: role changes per employer, employer/industry preservation, per-bullet similarity (kept / edited / rewritten), transformation "aggressiveness", skills coverage, invented projects/certifications. |
| `profiles/` | Fictional test profiles only (e.g. Alex Carter, Data Engineer at the fictional Northwind Retail). |
| `runs/` | One directory per run: `original.json`, `transformed.json`, `comparison.md`, rendered resumes, plus `prompt-used.txt` / `llm-raw.txt` for debugging. Failed validations are saved as `transformed-invalid.json` and never rendered. |
| `../tailoring/llm_prompt_custom.txt` | The transformation prompts (v2 universal engine + automatic experience/project expansion addendum). |

## Transformation behavior under test

- **Universal role transformation** — any fictional source role → any
  target role from the JD, no predefined role mappings.
- **Automatic expansion** — bullet counts scale with seniority/recency
  (most recent role 6–8, previous 4–6, junior/earlier 3–5), enforced by
  the validator against the original profile.
- **Automatic project generation** — 2–3 projects per run, each with
  name, business objective, architecture, tech stack, outcome, and
  3–5 detailed bullets, enforced by the validator.
- **Industry preservation** — fictional employers keep their industries;
  employer-associated content stays in-domain.
- **Career realism checks** — the comparison report surfaces seniority
  jumps (e.g. a junior role transformed into a senior title) so prompt
  adherence can be measured run over run.

## Isolation (enforced in code)

- Input profiles are accepted **only** from `synthetic/profiles/`; the
  CLI refuses any other path before any LLM call.
- The production pipeline (`../pipeline.py`, `../render.py`,
  `../tailoring/llm_prompt.txt`) is a separate, fact-preserving system
  and is never used or modified by this framework.

## Setup

```bash
pip install -r ../requirements.txt   # reportlab (+ python-docx for DOCX)
export GEMINI_API_KEY=<your key>     # or run inside the Muse Vault connector setup
```

## Testing workflow

```bash
python3 synthetic_pipeline.py \
  --profile synthetic/profiles/alex-carter.json \
  --jd-file <job-description.txt> \
  --jd-title "Staff+ Software Engineer, VectorDB"
```

Then inspect the run directory: `comparison.md` for transformation
quality, `transformed.json` for the validated payload, and the rendered
`resume-synthetic.pdf` / `.docx` — banner included, always.
