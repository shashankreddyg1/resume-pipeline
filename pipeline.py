#!/usr/bin/env python3
"""Resume pipeline — JD in, tailored resume out.

Flow: profile (user's real facts) + job description
  -> tailoring engine (tailoring/engine.py, behavior in tailoring/rules.json)
  -> optional LLM rewrite (tailoring/llm.py), guarded by verify.py —
     rewrites that introduce keywords or drop metrics are reverted
  -> PDF export (render.py, Jake's-style ATS-safe)
  -> roundtrip verification (tailoring/verify.py): the rendered PDF is
     re-extracted and checked the way an ATS parser would see it

Usage:
  python3 pipeline.py --profile profiles/shashank.json \
      --jd-file jd.txt --jd-title "Applied AI Demo Engineer" \
      --company Anthropic [--yes]

  --jd-text "..." works instead of --jd-file.
  Without --yes it asks for confirmation at the review gate.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tailoring.engine import tailor, load_rules  # noqa: E402
from tailoring.llm import rewrite_bullets  # noqa: E402
from tailoring.verify import guard_rewrite, verify_pdf, summarize  # noqa: E402
from render import render  # noqa: E402

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--jd-file")
    ap.add_argument("--jd-text")
    ap.add_argument("--from-board", default=None, metavar="MATCH",
                    help="pull the JD from the job board feed (scraper output) "
                         "by company or title substring")
    ap.add_argument("--board-file", default=os.environ.get(
        "RESUME_PIPELINE_BOARD",
        str(Path.home() / "workspace/goals/land-an-ai-engineer-role/hidden_files/scraper-last-run.json")))
    ap.add_argument("--jd-title", default="")
    ap.add_argument("--company", default="Company")
    ap.add_argument("--rules", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--llm", choices=["none", "gemini", "file"], default="none",
                    help="LLM rewrite stage: gemini (needs GEMINI_API_KEY) or file")
    ap.add_argument("--llm-file", default=None, help="JSON list of rewrites for --llm file")
    ap.add_argument("--prompt-file", default=None,
                    help="LLM prompt file to use (default: tailoring/llm_prompt.txt; "
                         "use tailoring/llm_prompt_honest.txt for real runs)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the post-render ATS verification (roundtrip checks + rewrite guard)")
    args = ap.parse_args()

    profile = json.loads(Path(args.profile).read_text())
    jd_text = ""
    if args.from_board:
        feed = json.loads(Path(args.board_file).read_text())
        jobs = feed.get("kept", []) if isinstance(feed, dict) else feed
        m = args.from_board.lower()
        match = next((j for j in jobs
                      if m in j.get("company", "").lower()
                      or m in j.get("title", "").lower()), None)
        if not match:
            sys.exit(f"No board job matches '{args.from_board}' in {args.board_file}")
        jd_text = match.get("jd_text", "")
        args.jd_title = args.jd_title or match.get("title", "")
        args.company = match.get("company", args.company).title()
        print(f"[board] {match.get('title','').strip()} — {match.get('company')} — "
              f"{match.get('location','')} — {match.get('url','')}")
    if not jd_text:
        jd_text = Path(args.jd_file).read_text() if args.jd_file else (args.jd_text or "")
    if not jd_text:
        sys.exit("No JD text: pass --jd-file, --jd-text, or --from-board")

    rules = load_rules(args.rules)
    cfg, report = tailor(profile, args.jd_title, jd_text, rules)

    if args.llm != "none":
        orig = list(cfg["ally_bullets"])
        new, note = rewrite_bullets(orig, args.jd_title,
                                    report["grounded_keywords"],
                                    provider=args.llm, file_path=args.llm_file,
                                    prompt_file=args.prompt_file)
        print(f"[llm] {note}")
        if new != orig:
            if not args.no_verify:
                violations = guard_rewrite(orig, new, rules["skill_lexicon"])
                for v in violations:
                    print(f"[verify] rewrite bullet {v['index']} REVERTED — "
                          f"introduced {v['introduced']}, lost metrics {v['lost_metrics']}")
                    new[v["index"]] = orig[v["index"]]
                if not violations:
                    print("[verify] rewrite guard PASS — no introduced keywords, metrics intact")
            cfg["ally_bullets"] = new

    name = profile["name"].replace(" ", "_")
    out = args.out or str(HERE / "outputs" / f"{name}_Resume_{args.company.replace(' ', '')}.pdf")
    render(profile, cfg, out)
    print("wrote", out)

    if not args.no_verify:
        checks = verify_pdf(out, cfg, profile, report["grounded_keywords"])
        verdict, lines = summarize(checks)
        for ln in lines:
            print(ln)
        vpath = str(out) + ".verify.json"
        Path(vpath).write_text(json.dumps(
            {"verdict": verdict, "checks": checks}, indent=1))
        print("[verify] report saved:", vpath)


if __name__ == "__main__":
    main()
