#!/usr/bin/env python3
"""PDF renderer — Jake's-resume-style, single-column serif, ATS-safe.

Generic over any profile: name/contact come from the profile, content
(title, summary, skills, bullets, projects) from the tailoring engine.
"""
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                HRFlowable, Table, TableStyle)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

SERIF, SERIF_B, SERIF_I = "Times-Roman", "Times-Bold", "Times-Italic"
LINK = HexColor("#1a56db")
DARK = HexColor("#111827")
GRAY = HexColor("#4b5563")
PAGE_W = LETTER[0] - 1.2 * inch


def st(name, **kw):
    base = dict(fontName=SERIF, fontSize=10, leading=13, textColor=DARK,
                alignment=TA_LEFT, spaceAfter=0)
    base.update(kw)
    return ParagraphStyle(name, **base)


s_name = st("n", fontName=SERIF_B, fontSize=21, leading=24, alignment=TA_CENTER, spaceAfter=2)
s_title = st("t", fontName=SERIF_B, fontSize=11, leading=13, alignment=TA_CENTER, spaceAfter=2)
s_contact = st("c", fontSize=10, leading=13, alignment=TA_CENTER, textColor=GRAY, spaceAfter=6)
s_section = st("sec", fontName=SERIF_B, fontSize=11.5, leading=14, spaceBefore=7, spaceAfter=2)
s_bullet = st("b", fontSize=10, leading=13, leftIndent=15, bulletIndent=6, spaceAfter=2.5)
s_skill = st("sk", fontSize=10, leading=13.5, spaceAfter=2)
s_edu = st("e", fontSize=10, leading=13, spaceAfter=2)
s_co = st("co", fontName=SERIF_B, fontSize=10.5, leading=13)
s_role = st("r", fontName=SERIF_I, fontSize=10, leading=13)
s_dates = st("d", fontSize=10, leading=13, alignment=TA_RIGHT)
s_loc = st("l", fontSize=10, leading=13, alignment=TA_RIGHT, textColor=GRAY)
s_proj = st("p", fontSize=10.5, leading=13, spaceBefore=4, spaceAfter=1)
s_link = st("lk", fontSize=9, leading=11, textColor=GRAY, spaceAfter=1.5)
s_sum = st("sm", fontSize=10, leading=13, spaceAfter=2)


def section(text):
    return [Paragraph(text.upper(), s_section),
            HRFlowable(width="100%", thickness=0.7, color=DARK, spaceAfter=4)]


def bullets(items):
    return [Paragraph(f"<bullet>&bull;</bullet> {it}", s_bullet) for it in items]


def link_line(links):
    parts = ' &nbsp;|&nbsp; '.join(
        f'<a href="{u}" color="#1a56db"><u>{label}</u></a>' for label, u in links)
    return Paragraph(parts, s_link)


def two_col(left, right, ls, rs):
    t = Table([[Paragraph(left, ls), Paragraph(right, rs)]],
              colWidths=[PAGE_W * 0.72, PAGE_W * 0.28])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def render(profile, cfg, out_path):
    c = profile["contact"]
    story = [Paragraph(profile["name"], s_name),
             Paragraph(cfg["title"], s_title)]
    line1 = f'{c["location"]} &nbsp;|&nbsp; {c["phone"]} &nbsp;|&nbsp; <a href="mailto:{c["email"]}" color="#1a56db"><u>{c["email"]}</u></a>'
    links = []
    if c.get("github"):
        links.append(("GitHub", c["github"]))
    if c.get("portfolio"):
        links.append(("Portfolio", c["portfolio"]))
    line2 = ' &nbsp;|&nbsp; '.join(f'<a href="{u}" color="#1a56db"><u>{l}</u></a>' for l, u in links)
    if c.get("linkedin"):
        line2 += ' &nbsp;|&nbsp; ' + f'<a href="{c["linkedin"]}" color="#1a56db"><u>LinkedIn</u></a>'
    else:
        line2 += ' &nbsp;|&nbsp; LinkedIn'
    story.append(Paragraph(line1 + "<br/>" + line2, s_contact))

    if cfg.get("summary"):
        story += section("Summary")
        story.append(Paragraph(cfg["summary"], s_sum))

    story += section("Technical Skills")
    for g in cfg["skills"]:
        story.append(Paragraph(g, s_skill))

    story += section("Experience")
    picked = {"Ally Financial": cfg["ally_bullets"], "Hitachi": cfg.get("hitachi_bullets", [])}
    for e in profile["experience"]:
        story.append(two_col(e["company"], e["dates"], s_co, s_dates))
        story.append(two_col(e["role"], e["location"], s_role, s_loc))
        blts = picked.get(e["company"], e["bullets"][:4])
        story += bullets(blts)

    story += section("Selected Projects")
    for name, links, blts in cfg["projects"]:
        story.append(Paragraph(f"<b>{name}</b>", s_proj))
        if links:
            story.append(link_line(links))
        story += bullets(blts)

    story += section("Education")
    for ed in profile["education"]:
        txt = f'<b>{ed["school"]}</b> — {ed["degree"]}' + (f', {ed["dates"]}' if ed.get("dates") else "")
        story.append(Paragraph(txt, s_edu))

    doc = SimpleDocTemplate(out_path, pagesize=LETTER,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            title=f'{profile["name"]} — Resume ({cfg["title"]})',
                            author=profile["name"])
    doc.build(story)
    return out_path
