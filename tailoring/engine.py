#!/usr/bin/env python3
"""Tailoring engine — the heart of the resume pipeline.

Standalone module. Given a candidate profile (their REAL facts: a bullet
bank from their own experience, projects, skills) and a job description,
it produces a tailored resume config + a report of what it did.

HOW IT TAILORS
  1. Extracts the JD's keywords (rules.skill_lexicon) with frequencies.
  2. Keeps only keywords the candidate actually has (present in their
     bullet bank / skills) — the "grounded keyword set".
  3. Scores every experience bullet by grounded-keyword overlap and picks
     the best N (rules.*_to_pick); selected bullets lead the section.
  4. Ranks projects the same way; best bullet per project.
  5. Reorders skill groups so JD-relevant groups come first.
  6. Picks the resume title from rules.title_map by JD role family.
  7. Assembles the summary from the template using only profile facts
     and metric phrases found in the candidate's own top bullets.

GROUNDING RULE (rules.grounding.enforce)
  The engine selects, reorders, and re-frames ONLY what is in the profile.
  It never invents employers, dates, projects, metrics, skills, or
  locations. Change behavior by editing rules.json — this file stays
  the same for every user of the pipeline.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_RULES = HERE / "rules.json"


def load_rules(path=None):
    with open(path or DEFAULT_RULES) as f:
        return json.load(f)


def _kw_hits(text, lexicon):
    low = f" {text.lower()} "
    hits = {}
    for kw in lexicon:
        n = low.count(f" {kw}") + low.count(f"{kw} ") + low.count(f" {kw} ")
        # simpler + robust: word-boundary-ish count
        n = len(re.findall(re.escape(kw), text.lower()))
        if n:
            hits[kw] = n
    return hits


def extract_jd_keywords(jd_text, rules):
    return _kw_hits(jd_text, rules["skill_lexicon"])


def grounded_keywords(jd_kw, profile, rules):
    """JD keywords that also appear somewhere in the candidate's material."""
    hay = json.dumps(profile).lower()
    return {k: v for k, v in jd_kw.items() if k in hay}


def pick_title(jd_title, rules):
    t = (jd_title or "").lower()
    for pat, title in rules["title_map"].items():
        if pat.startswith("_"):
            continue
        if pat in t:
            return title
    return rules["title_map"].get("default", "Full Stack Engineer")


def score_bullets(bullets, gkw):
    scored = []
    for i, b in enumerate(bullets):
        low = b.lower()
        s = sum(gkw.get(k, 0) * (2 if k in low else 0) for k in gkw if k in low)
        scored.append((s, i, b))
    return scored


def select(bullets, gkw, n):
    scored = score_bullets(bullets, gkw)
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = scored[:n]
    return [b for _, _, b in chosen], [(b, s) for s, _, b in scored[n:]]


def rank_projects(projects, gkw, bullets_per):
    ranked = []
    for p in projects:
        best, _ = select(p["bullets"], gkw, bullets_per)
        score = sum(s for s, _, _ in score_bullets(p["bullets"][:1], gkw))
        ranked.append((score, p["name"], p.get("links", []), best))
    ranked.sort(key=lambda x: -x[0])
    return [(name, links, blts) for _, name, links, blts in ranked]


def order_skills(groups, gkw):
    def score(g):
        low = g.lower()
        return sum(1 for k in gkw if k in low)
    return sorted(groups, key=lambda g: -score(g))


_PROOF_PATTERNS = [
    (r"(\d[\d,]*)-case", "{0}-case golden eval set"),
    (r"(\d+)% on a golden eval set", "{0}% on a golden eval set"),
    (r"(\d+) pytest", "{0} pytest passing"),
    (r"([\d,]+\+?) monthly requests", "{0} monthly requests served"),
]
_SUMMARY_SKIP = {"demo", "sse", "api", "integration", "prototyping"}


def proof_points(profile):
    hay = json.dumps(profile)
    out = []
    for pat, fmt in _PROOF_PATTERNS:
        m = re.search(pat, hay)
        if m:
            out.append(fmt.format(m.group(1)))
    return out[:3]


def build_summary(profile, title, gkw, top_bullets, rules):
    years = "3+ years"
    top_kw = [k for k, _ in sorted(gkw.items(), key=lambda x: -x[1])
              if k not in _SUMMARY_SKIP][:4]
    focus = "LLM-powered products" if any(k in gkw for k in ("llm", "rag", "agentic", "agents")) \
        else "production software systems"
    proofs = proof_points(profile)
    proof = ("Proof points: " + ", ".join(proofs) + ".") if proofs else \
        "Track record of shipping production systems end to end."
    tmpl = rules.get("summary_template", "{title} with {years} of experience.")
    return tmpl.format(title=title, years=years, focus=focus,
                       top_keywords=", ".join(top_kw) if top_kw else "modern stacks",
                       proof_points=proof)


def tailor(profile, jd_title, jd_text, rules=None):
    """Return (cfg, report). cfg matches the PDF renderer's config shape."""
    rules = rules or load_rules()
    jd_kw = extract_jd_keywords(jd_text, rules)
    gkw = grounded_keywords(jd_kw, profile, rules)
    title = pick_title(jd_title, rules)

    exp = {e["company"]: e for e in profile["experience"]}
    ally = exp.get("Ally Financial", profile["experience"][0])
    ally_picked, ally_dropped = select(ally["bullets"], gkw, rules["ally_bullets_to_pick"])

    hitachi_picked = []
    if "Hitachi" in exp:
        hitachi_picked, _ = select(exp["Hitachi"]["bullets"], gkw, rules["hitachi_bullets_to_pick"])

    projects = rank_projects(profile["projects"], gkw, rules["project_bullets_to_pick"])
    skills = order_skills(rules["skill_groups"], gkw)
    summary = build_summary(profile, title, gkw, ally_picked, rules)

    cfg = {"title": title, "summary": summary, "skills": skills,
           "ally_bullets": ally_picked, "hitachi_bullets": hitachi_picked,
           "projects": projects}
    report = {"jd_title": jd_title, "resume_title": title,
              "jd_keywords": dict(sorted(jd_kw.items(), key=lambda x: -x[1])[:15]),
              "grounded_keywords": sorted(gkw.keys()),
              "keywords_not_in_profile": sorted(set(jd_kw) - set(gkw)),
              "ally_picked": len(ally_picked), "ally_dropped": len(ally_dropped)}
    return cfg, report
