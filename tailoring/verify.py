#!/usr/bin/env python3
"""Post-tailoring verification — the rendered file is checked the way an
ATS parser would see it, and the LLM rewrite is checked against its source.

Two layers, adapted from the open-source Resume-Matcher project
(Apache-2.0, https://github.com/srbhr/Resume-Matcher), whose core pattern
is "tailor, then verify the artifact — never trust the generation step":

1. Roundtrip PDF checks (deterministic): re-extract the rendered PDF's
   text and verify the text layer is real, glyphs aren't garbled, the
   required sections survived, contact details are findable by regex,
   the page count is sane, and every grounded keyword the engine picked
   actually made it into the rendered document (render truncation check).

2. Rewrite guard: for each LLM-rewritten bullet, lexicon keywords that
   appear in the rewrite but NOT in the original bullet are flagged as
   introduced facts, and numbers/metrics from the original must survive
   verbatim. Flagged bullets are reverted to the original by the caller.
"""
import re

EMAIL_RE = re.compile(r"[\w.+-]{1,64}@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
GARBLED_RE = re.compile(r"\(cid:\d+\)|�")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?%?")

REQUIRED_SECTIONS = {
    "summary": ["summary", "profile", "about"],
    "skills": ["skills", "technical skills", "technologies"],
    "experience": ["experience", "employment", "work history"],
    "projects": ["projects"],
    "education": ["education"],
}


def extract_pdf_text(pdf_path):
    """Return (text, page_count) from a rendered PDF."""
    try:
        from pypdf import PdfReader
        r = PdfReader(str(pdf_path))
        return "\n".join((p.extract_text() or "") for p in r.pages), len(r.pages)
    except Exception:
        import subprocess
        out = subprocess.run(["pdftotext", str(pdf_path), "-"],
                             capture_output=True, text=True)
        return out.stdout, out.stdout.count("\f") or 1


def _check(cid, category, severity, status, **params):
    return {"id": cid, "category": category, "severity": severity,
            "status": status, **params}


def verify_pdf(pdf_path, cfg, profile, grounded_keywords):
    """Roundtrip checks on the rendered PDF. Returns a list of checks."""
    text, pages = extract_pdf_text(pdf_path)
    low = text.lower()
    visible = sum(1 for ch in text if not ch.isspace())
    checks = []

    checks.append(_check(
        "text_layer", "extraction", "high",
        "pass" if visible >= 50 else "fail", characters=visible))

    garbled = len(GARBLED_RE.findall(text))
    ratio = garbled / max(1, visible)
    checks.append(_check(
        "garbled_glyphs", "extraction", "high",
        "fail" if ratio > 0.05 else "warn" if ratio > 0.005 else "pass",
        count=garbled))

    missing_sections = [name for name, syns in REQUIRED_SECTIONS.items()
                        if not any(s in low for s in syns)]
    checks.append(_check(
        "required_sections", "structure", "high",
        "pass" if not missing_sections else "fail",
        missing=missing_sections))

    contact = profile.get("contact", {})
    checks.append(_check(
        "email_findable", "contact", "high",
        "pass" if EMAIL_RE.search(text) else "fail"))
    checks.append(_check(
        "phone_findable", "contact", "medium",
        "pass" if (not contact.get("phone") or PHONE_RE.search(text)) else "fail"))

    checks.append(_check(
        "page_count", "structure", "medium",
        "pass" if pages <= 2 else "warn", pages=pages))

    lost = [k for k in grounded_keywords if k.lower() not in low]
    # keywords used only via skill ordering/summary may legitimately sit in
    # sections; count only keywords from picked bullets as render-critical.
    picked_text = " ".join(cfg.get("ally_bullets", []) +
                           cfg.get("hitachi_bullets", [])).lower()
    critical = [k for k in grounded_keywords if k.lower() in picked_text]
    lost_critical = [k for k in critical if k.lower() not in low]
    checks.append(_check(
        "keyword_survival", "content", "high",
        "pass" if not lost_critical else "fail",
        lost=lost_critical, not_rendered=lost))
    return checks


def summarize(checks):
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    verdict = "FAIL" if fails else "PASS (with warnings)" if warns else "PASS"
    lines = [f"[verify] {verdict} — {len(checks)} checks, "
             f"{len(fails)} failed, {len(warns)} warnings"]
    for c in checks:
        if c["status"] != "pass":
            extra = {k: v for k, v in c.items()
                     if k not in ("id", "category", "severity", "status")}
            lines.append(f"[verify]   {c['status'].upper()} {c['id']} {extra}")
    return verdict, lines


def guard_rewrite(originals, rewrites, lexicon):
    """Check each rewritten bullet against its source.

    Returns a list of violations: {index, introduced: [...], lost_metrics: [...]}.
    A violation means the rewrite added a lexicon keyword the original did
    not contain, or dropped/altered a number from the original.
    """
    lex = [t.lower() for t in lexicon]
    violations = []
    for i, (orig, new) in enumerate(zip(originals, rewrites)):
        o, n = orig.lower(), new.lower()
        introduced = sorted({t for t in lex if t in n and t not in o})
        lost_metrics = sorted({m for m in NUMBER_RE.findall(orig)
                               if m not in new})
        if introduced or lost_metrics:
            violations.append({"index": i, "introduced": introduced,
                               "lost_metrics": lost_metrics})
    return violations
