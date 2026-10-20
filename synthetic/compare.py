#!/usr/bin/env python3
"""Original-vs-transformed comparison for synthetic runs.

Evaluates how aggressively the LLM transformed the fictional profile:
role changes per employer, employer preservation (industry context),
per-bullet similarity (kept / edited / rewritten), new skills, new
projects, and certifications introduced. Output: Markdown report.
"""
import difflib


def _role(e):
    return e.get("title") or e.get("role", "")


def _bullet_change(orig_bullets, new_bullets):
    """Classify each ORIGINAL bullet by its best match in the new set."""
    kept = edited = rewritten = 0
    for ob in orig_bullets:
        best = max((difflib.SequenceMatcher(None, ob, nb).ratio()
                    for nb in new_bullets), default=0.0)
        if best >= 0.85:
            kept += 1
        elif best >= 0.5:
            edited += 1
        else:
            rewritten += 1
    return kept, edited, rewritten


def compare(original, transformed, jd_title="", jd_keywords=None):
    L = [f"# Synthetic transformation — comparison report",
         f"\nTarget role: **{jd_title}**\n"]
    o_exp = {e["company"]: e for e in original.get("experience", [])}
    t_exp = {e["company"]: e for e in transformed.get("experience", [])}

    L.append("## Role transformation by employer\n")
    L.append("| Employer | Original role | Transformed role |")
    L.append("|---|---|---|")
    for co, oe in o_exp.items():
        te = t_exp.get(co)
        L.append(f"| {co} | {_role(oe)} | {_role(te) if te else '— MISSING —'} |")
    for co, te in t_exp.items():
        if co not in o_exp:
            L.append(f"| {co} | — NEW EMPLOYER (not in original) — | {_role(te)} |")

    missing = [c for c in o_exp if c not in t_exp]
    added = [c for c in t_exp if c not in o_exp]
    L.append(f"\nEmployers preserved: "
             f"{'YES — all original employers kept, none added' if not missing and not added else 'NO'}"
             + (f" (missing: {', '.join(missing)})" if missing else "")
             + (f" (added: {', '.join(added)})" if added else ""))

    L.append("\n## Bullet transformation (per employer)\n")
    L.append("| Employer | Orig bullets | New bullets | Kept ≈ | Edited | Rewritten/new |")
    L.append("|---|---|---|---|---|---|")
    tot_o = tot_r = 0
    for co, oe in o_exp.items():
        te = t_exp.get(co)
        if not te:
            L.append(f"| {co} | {len(oe.get('bullets', []))} | 0 | 0 | 0 | all |")
            tot_o += len(oe.get("bullets", []))
            tot_r += len(oe.get("bullets", []))
            continue
        k, ed, rw = _bullet_change(oe.get("bullets", []), te.get("bullets", []))
        L.append(f"| {co} | {len(oe['bullets'])} | {len(te['bullets'])} | {k} | {ed} | {rw} |")
        tot_o += len(oe["bullets"])
        tot_r += rw
    if tot_o:
        L.append(f"\n**Aggressiveness: {tot_r}/{tot_o} original bullets "
                 f"({100 * tot_r // tot_o}%) were rewritten beyond recognition "
                 f"or replaced.**")

    skills = transformed.get("technical_skills", [])
    L.append(f"\n## Skills\nTransformed resume lists {len(skills)} skills: "
             f"{', '.join(skills)}")
    if jd_keywords:
        hit = [k for k in jd_keywords
               if any(k.lower() in s.lower() for s in skills)]
        L.append(f"\nJD keyword coverage in skills: {len(hit)}/{len(jd_keywords)}"
                 f" ({', '.join(hit)})")

    o_proj = {p.get("name") for p in original.get("projects", [])}
    t_proj = {p.get("name") for p in transformed.get("projects", [])}
    new_proj = [p for p in t_proj if p and p not in o_proj]
    L.append(f"\n## Projects\nOriginal: {len(o_proj)} · Transformed: {len(t_proj)}"
             + (f" · New/invented: {', '.join(new_proj)}" if new_proj else ""))

    certs = transformed.get("certifications", [])
    L.append(f"\n## Certifications\n{len(certs)} in transformed resume"
             + (" (rendered as synthetic — unverified)" if certs else ""))

    o_edu = {(e.get("school"), e.get("degree"))
             for e in original.get("education", [])}
    t_edu = {(e.get("school"), e.get("degree"))
             for e in transformed.get("education", [])}
    L.append(f"\n## Education\nPreserved unchanged: {'YES' if o_edu == t_edu else 'NO — changed'}")
    return "\n".join(L) + "\n"
