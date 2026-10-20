# resume-pipeline

Scraper finds the job → Job Board holds it → this pipeline tailors a
resume for it → a human reviews → ready to apply. Built so more than one
person can use it: each user has their own profile with their own real
resume, city, and experience.

## Quickstart (anywhere)

```bash
git clone https://github.com/shashankreddyg1/resume-pipeline
cd resume-pipeline
pip install -r requirements.txt

# try it with the bundled fictional example profile
python3 pipeline.py --profile profiles/example.json \
  --jd-text "Data Engineer role: Python, SQL, Airflow, ETL, data modeling" \
  --jd-title "Data Engineer" --company Example --yes

# add the AI rewrite stage (free tier key from https://aistudio.google.com)
export GEMINI_API_KEY=<your key>
python3 pipeline.py --profile profiles/example.json \
  --jd-file my_jd.txt --jd-title "Data Engineer" --company Example \
  --llm gemini
```

Your own profile: copy `profiles/example.json`, replace it with YOUR
real details, and run with `--profile profiles/<you>.json`. Personal
profiles are gitignored — your data never ships with the repo.

Tailor from a job-board feed instead of a pasted JD (any JSON with a
`kept` list carrying `jd_text`): pass `--from-board "<company or title>"`
and `--board-file <file>`, or set `RESUME_PIPELINE_BOARD=<file>`.

## Layout
```
pipeline.py            CLI: JD in -> review gate -> PDF out
render.py              Jake's-style ATS-safe PDF renderer (any profile)
tailoring/
  engine.py            THE TAILORING ENGINE (standalone module)
  rules.json           ALL engine behavior — editable, no code changes
profiles/
  shashank.json        one user's facts: bullet bank, projects, skills
outputs/               exported PDFs
```

## ⭐ Your access point: the tailoring engine
**`tailoring/rules.json`** — everything the engine does is controlled
from this one file:
- `title_map` — which resume title each JD role family gets
- `skill_lexicon` — the keyword vocabulary extracted from JDs
- `skill_groups` — the skills section content and order candidates
- `ally_bullets_to_pick` / `hitachi_bullets_to_pick` / `project_bullets_to_pick` — how much of the bank makes the cut
- `summary_template` — how the summary line is assembled
- `grounding` — the engine's core contract (see below)

**`tailoring/engine.py`** — the logic: JD keyword extraction, grounded
keyword filtering, bullet scoring/selection, project ranking, skill
reordering, summary assembly. Import it from anywhere:
`from tailoring.engine import tailor`.

## The grounding contract
The engine ONLY selects, reorders, and re-frames what is in the user's
profile. It never invents employers, dates, projects, metrics, skills,
or locations — and the review gate prints every JD keyword that is NOT
in the profile, so gaps are visible, never papered over. That's what
makes a tailored resume survivable in an interview and a background
check, for every user of this pipeline.

## Run it
```bash
python3 pipeline.py --profile profiles/shashank.json \
  --jd-file jd.txt --jd-title "Applied AI Demo Engineer" \
  --company Anthropic
# review gate prints the summary, picks, and missing keywords;
# confirm to export the PDF (or pass --yes)
```

## Add a new user (e.g. a friend)
1. Copy `profiles/shashank.json` → `profiles/<name>.json`
2. Replace with THEIR real contact, city, bullet bank, projects, education
3. Run the same command with their profile — the engine, rules, and
   renderer are shared; only the facts change.

## LLM rewrite stage (`tailoring/llm.py`)
`--llm gemini` adds an AI rewrite pass AFTER selection: the model
rewrites the picked bullets so the JD's language leads, under a hard
prompt contract (only facts from the original bullet, metrics verbatim,
nothing invented) — and the review gate prints original vs. rewritten
side by side. Providers: `gemini` (Google AI Studio free tier, needs
GEMINI_API_KEY in env), `file` (pre-written rewrites, for tests),
`none` (default). If the LLM is unavailable the pipeline keeps the
deterministic output and says so.

## Status
v1.1 working end-to-end (verified on a live Anthropic posting, 2-page
PDF, with and without the LLM stage). Next step if wanted: feed JDs
straight from the Job Board / scraper output.
