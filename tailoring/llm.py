#!/usr/bin/env python3
"""LLM rewrite stage for the tailoring engine.

The deterministic engine selects the right bullets; this stage rewrites
them so the JD's language leads — WITHOUT changing any fact.

THE CONTRACT (sent verbatim to the model, and enforced by the review
gate afterwards):
  - Rewrite ONLY the bullets given. Use only facts, tools, employers,
    and outcomes present in the original bullet.
  - Keep every number/metric EXACTLY as written.
  - Never add skills, tools, projects, employers, dates, or results
    that are not in the original bullet.
  - Foreground the target keywords where they naturally fit; do not
    stuff keywords that the bullet's facts don't support.
  - One bullet in -> one bullet out, similar length, plain text
    (the renderer adds HTML where needed).

Providers:
  gemini  — Google AI Studio, free tier. Needs GEMINI_API_KEY in env.
  file    — reads pre-written rewrites from a JSON file (tests/demos).
  none    — returns bullets unchanged (pipeline default).

If the provider fails or no key is set, the stage returns the original
bullets and says so — the pipeline never blocks on the LLM.
"""
import json
import os
import urllib.request
from pathlib import Path

PROMPT_TEMPLATE = """You are a resume editor. Rewrite each bullet below for the target role "{jd_title}".

HARD RULES:
- Use ONLY facts, tools, employers, and outcomes in the original bullet.
- Keep every number and metric EXACTLY as written.
- Never add skills, tools, projects, employers, dates, or results that are not in the original bullet.
- Foreground these target keywords where they naturally fit: {keywords}
- One bullet in, one bullet out. Similar length. Plain text, no markdown.

BULLETS (JSON list):
{bullets}

Return ONLY a JSON list of the rewritten bullets, same order, same count."""


PROMPT_FILE = Path(__file__).resolve().parent / "llm_prompt.txt"


def build_prompt(bullets, jd_title, keywords, prompt_file=None):
    """Prompt template lives in llm_prompt.txt (user-editable).
    Falls back to the built-in template if the file is missing."""
    pf = Path(prompt_file) if prompt_file else PROMPT_FILE
    if pf.exists():
        tmpl = pf.read_text()
    else:
        tmpl = PROMPT_TEMPLATE
    return tmpl.format(
        jd_title=jd_title, keywords=", ".join(keywords[:12]),
        bullets=json.dumps(bullets, indent=1))


import json
import os
import subprocess
import urllib.request
from pathlib import Path

GEMINI_HELPER = (Path.home() / "workspace/custom-connectors/"
                 "custom.google-gemini/bin/gemini_generate.py")


def _gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        # No env key: route through the Secure Vault connector helper —
        # the real key stays in the Vault; the helper uses a surrogate.
        if GEMINI_HELPER.exists():
            try:
                out = subprocess.run(
                    ["python3", str(GEMINI_HELPER)],
                    input=prompt, capture_output=True, text=True, timeout=120)
                if out.returncode == 0 and out.stdout.strip():
                    return out.stdout.strip(), "gemini (via Vault connector)"
                return None, f"connector helper failed: {out.stderr.strip()[:120]}"
            except Exception as e:
                return None, f"connector helper error: {str(e)[:120]}"
        return None, "GEMINI_API_KEY not set and no Vault connector found"
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-flash-lite-latest:generateContent?key={key}")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    return data["candidates"][0]["content"]["parts"][0]["text"], "gemini"


def _file(path):
    return json.loads(Path(path).read_text()), "file"


def rewrite_bullets(bullets, jd_title, keywords, provider="gemini", file_path=None, prompt_file=None):
    """Return (bullets_out, note). On any failure: (originals, reason)."""
    prompt = build_prompt(bullets, jd_title, keywords, prompt_file=prompt_file)
    try:
        if provider == "none":
            return bullets, "llm skipped (provider=none)"
        if provider == "file":
            out, src = _file(file_path)
        else:
            out, src = _gemini(prompt)
            if out is None:
                return bullets, f"llm unavailable: {src}; kept originals"
            # gemini path returns raw model text: strip fences, parse JSON
            txt = out.strip().removeprefix("```json").removeprefix("```")
            txt = txt.removesuffix("```").strip()
            out = json.loads(txt)
        if not isinstance(out, list) or len(out) != len(bullets):
            return bullets, "llm returned wrong shape; kept originals"
        return [str(x) for x in out], f"rewritten by {src}"
    except Exception as e:
        return bullets, f"llm failed ({type(e).__name__}: {str(e)[:80]}); kept originals"
