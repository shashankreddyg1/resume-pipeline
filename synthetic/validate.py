#!/usr/bin/env python3
"""Strict schema validation for synthetic-resume JSON — schema v2.

The v2 transformation prompt returns a whole-resume JSON object shaped:
  candidate{name, contact}, target_job, professional_summary,
  technical_skills, professional_experience, projects, certifications,
  education, generation_metadata{is_synthetic: true, ...}

NOTHING renders until this validator passes. Rejects:
  - non-object / malformed payloads
  - missing required fields, empty required strings/lists, wrong types
  - unresolved template placeholders ({jd_title}, {original_role}, ...)
  - serialized JSON hiding inside a text field
  - unknown top-level keys (strict schema)
  - generation_metadata missing, or is_synthetic not true — a payload
    that does not declare itself synthetic is refused outright.
    (generation_metadata is validated but NEVER rendered.)

Returns a list of human-readable errors; empty list means valid.
"""
import json
import re

PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_ ]*\}")
ALLOWED_TOP = {"candidate", "target_job", "professional_summary",
               "technical_skills", "professional_experience", "projects",
               "certifications", "education", "generation_metadata",
               "is_synthetic"}
FORBIDDEN_KEYS = {"instructions", "system_prompt", "template",
                  "template_variables", "validation", "validation_settings",
                  "schema"}


def _walk_strings(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def _is_str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _bullet_range(orig_index, orig_role):
    """Expansion addendum: most recent role 6-8 bullets, previous 4-6,
    earlier or junior roles 3-5."""
    if orig_index == 0:
        return (6, 8)
    if "junior" in (orig_role or "").lower():
        return (3, 5)
    if orig_index == 1:
        return (4, 6)
    return (3, 5)


def _check_experience(exp, field, errs, original=None):
    if not isinstance(exp, list) or not exp:
        errs.append(f"{field}: required non-empty array")
        return
    orig_by_company = {}
    if original:
        for idx, oe in enumerate(original.get("experience", [])):
            orig_by_company[oe.get("company")] = (
                idx, oe.get("role") or oe.get("title", ""))
    for i, e in enumerate(exp):
        if not isinstance(e, dict):
            errs.append(f"{field}[{i}]: must be an object")
            continue
        if not isinstance(e.get("company"), str) or not e["company"].strip():
            errs.append(f"{field}[{i}].company: required non-empty string")
        role = e.get("title", e.get("role"))
        if not isinstance(role, str) or not role.strip():
            errs.append(f"{field}[{i}]: required 'title' (or 'role') string")
        if not _is_str_list(e.get("bullets")) or not e.get("bullets"):
            errs.append(f"{field}[{i}].bullets: required non-empty array of strings")
        elif e.get("company") in orig_by_company:
            idx, orole = orig_by_company[e["company"]]
            lo, hi = _bullet_range(idx, orole)
            n = len(e["bullets"])
            if not (lo <= n <= hi):
                errs.append(f"{field}[{i}].bullets: {n} bullets for "
                            f"{e['company']} — expansion range is {lo}-{hi}")
        for k in ("dates", "location"):
            if k in e and e[k] is not None and not isinstance(e[k], str):
                errs.append(f"{field}[{i}].{k}: must be a string")


def validate(data, original=None):
    errs = []
    if not isinstance(data, dict):
        return ["top level is not a JSON object"]

    unknown = set(data) - ALLOWED_TOP
    if unknown:
        errs.append(f"unknown top-level keys: {sorted(unknown)}")
    bad = FORBIDDEN_KEYS & set(data)
    if bad:
        errs.append(f"forbidden internal keys present: {sorted(bad)}")

    # ---- synthetic declaration (required, enforced) ----
    meta = data.get("generation_metadata")
    if not isinstance(meta, dict):
        errs.append("generation_metadata: required object")
    elif meta.get("is_synthetic") is not True and data.get("is_synthetic") is not True:
        errs.append("generation_metadata.is_synthetic must be true — "
                    "payload does not declare itself synthetic")

    # ---- candidate ----
    cand = data.get("candidate")
    if not isinstance(cand, dict):
        errs.append("candidate: required object")
    else:
        if not isinstance(cand.get("name"), str) or not cand["name"].strip():
            errs.append("candidate.name: required non-empty string")
        c = cand.get("contact")
        if not isinstance(c, dict):
            errs.append("candidate.contact: required object")
        else:
            if not isinstance(c.get("email"), str) or "@" not in c.get("email", ""):
                errs.append("candidate.contact.email: required string containing '@'")
            for k in ("location", "phone", "github", "linkedin", "portfolio"):
                if k in c and c[k] is not None and not isinstance(c[k], str):
                    errs.append(f"candidate.contact.{k}: must be a string or null")

    # ---- target job ----
    tj = data.get("target_job")
    if isinstance(tj, dict):
        if not isinstance(tj.get("title"), str) or not tj["title"].strip():
            errs.append("target_job.title: required non-empty string")
    elif not isinstance(tj, str) or not tj.strip():
        errs.append("target_job: required string or object with a title")

    # ---- summary / skills ----
    if not isinstance(data.get("professional_summary"), str) \
            or not data["professional_summary"].strip():
        errs.append("professional_summary: required non-empty string")
    if not _is_str_list(data.get("technical_skills")) \
            or not data.get("technical_skills"):
        errs.append("technical_skills: required non-empty array of strings")

    # ---- experience / projects / certifications / education ----
    _check_experience(data.get("professional_experience"),
                      "professional_experience", errs, original=original)

    # Expansion addendum: 2-3 projects, each fully detailed —
    # name, objective, architecture, stack, outcome, 3-5 bullets.
    proj = data.get("projects", [])
    if not isinstance(proj, list) or not (2 <= len(proj) <= 3):
        errs.append("projects: required array of 2-3 generated projects")
    else:
        for i, p in enumerate(proj):
            if not isinstance(p, dict):
                errs.append(f"projects[{i}]: must be an object")
                continue
            for k in ("name", "objective", "architecture", "outcome"):
                if not isinstance(p.get(k), str) or not p[k].strip():
                    errs.append(f"projects[{i}].{k}: required non-empty string")
            if not _is_str_list(p.get("stack")) or not p.get("stack"):
                errs.append(f"projects[{i}].stack: required non-empty array of strings")
            b = p.get("bullets")
            if not _is_str_list(b) or not (3 <= len(b or []) <= 5):
                errs.append(f"projects[{i}].bullets: required array of 3-5 strings")

    certs = data.get("certifications", [])
    if not isinstance(certs, list):
        errs.append("certifications: must be an array")
    else:
        for i, cert in enumerate(certs):
            if isinstance(cert, str):
                continue
            if isinstance(cert, dict) and isinstance(cert.get("name"), str):
                continue
            errs.append(f"certifications[{i}]: must be a string or an object with a name")

    edu = data.get("education")
    if not isinstance(edu, list) or not edu:
        errs.append("education: required non-empty array")
    else:
        for i, ed in enumerate(edu):
            if not isinstance(ed, dict):
                errs.append(f"education[{i}]: must be an object")
                continue
            for k in ("degree", "school"):
                if not isinstance(ed.get(k), str) or not ed[k].strip():
                    errs.append(f"education[{i}].{k}: required non-empty string")

    # ---- content scans over resume-visible fields (metadata excluded) ----
    visible = {k: v for k, v in data.items() if k != "generation_metadata"}
    for path, s in _walk_strings(visible):
        if PLACEHOLDER_RE.search(s):
            errs.append(f"{path}: unresolved placeholder in value: {s[:60]!r}")
        st = s.strip()
        if st.startswith(("{", "[")):
            try:
                json.loads(st)
                errs.append(f"{path}: serialized JSON inside a text field")
            except Exception:
                pass
    return errs


def normalize(data):
    """Map a valid v2 payload onto the renderer's field names."""
    cand = data["candidate"]
    tj = data["target_job"]
    return {
        "name": cand["name"],
        "contact": cand.get("contact", {}),
        "title": tj if isinstance(tj, str) else tj.get("title", ""),
        "professional_summary": data["professional_summary"],
        "technical_skills": data["technical_skills"],
        "experience": data["professional_experience"],
        "projects": data.get("projects", []),
        "certifications": data.get("certifications", []),
        "education": data["education"],
    }
