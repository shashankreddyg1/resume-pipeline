"""Public synthetic-resume demo backend. Never accepts real candidate data."""
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, request, send_file, render_template_string
from synthetic.synthetic_pipeline import PROMPT_FILE, KEY_CONTRACT
from synthetic.validate import validate, normalize
from synthetic.render_synthetic import render_pdf, render_docx
from tailoring.llm import _gemini

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 120_000
_rate = {}
_lock = Lock()
_cache = {}
_cache_lock = Lock()

HTML = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Synthetic Resume Transformation Demo</title>
<style>body{font:16px system-ui;max-width:860px;margin:35px auto;padding:0 16px;color:#182133}textarea,input{box-sizing:border-box;width:100%;padding:10px;margin:7px 0 15px;border:1px solid #bac3d1;border-radius:5px}textarea{min-height:170px}button{padding:11px 18px;background:#173c77;color:white;border:0;border-radius:5px;cursor:pointer}button:disabled{opacity:.5}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6fa;padding:14px}small{color:#555}</style>
<h1>Synthetic Resume Transformation Demo</h1><p><strong>Fictional test profiles only.</strong> Generated employment history, qualifications and projects are synthetic, not verified credentials.</p>
<label>Fictional profile (JSON)</label><textarea id="profile"></textarea>
<label>Target job title</label><input id="title" placeholder="e.g. Database Developer">
<label>Job description</label><textarea id="jd" placeholder="Paste target role requirements"></textarea>
<label><input type="checkbox" id="fictional" style="width:auto"> I confirm this profile is entirely fictional and for testing only.</label><p><button id="go">Generate synthetic demo</button></p><p id="status"></p><div id="exports" hidden><button onclick="download('pdf')">Download labeled PDF</button> <button onclick="download('docx')">Download labeled DOCX</button></div><pre id="result"></pre>
<script>
let token=null;const $=id=>document.getElementById(id);
$('profile').value=JSON.stringify({name:"Alex Carter",contact:{location:"Austin, TX",phone:"(555) 010-2233",email:"alex.carter@example.com"},employer_industries:{"Northwind Retail":"Retail","Brightpath Logistics":"Logistics"},experience:[{company:"Northwind Retail",role:"Data Engineer",dates:"2022–Present",location:"Austin, TX",bullets:["Built retail inventory data pipelines using Python and SQL."]},{company:"Brightpath Logistics",role:"Junior Data Analyst",dates:"2020–2021",location:"Dallas, TX",bullets:["Built shipping dashboards and operational reports."]}],education:[{school:"Example State University",degree:"B.S. Computer Science",dates:"2020"}]},null,2);
$('go').onclick=async()=>{token=null;$('exports').hidden=true;$('result').textContent='';$('go').disabled=true;$('status').textContent='Generating…';try{const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile:JSON.parse($('profile').value),jd_title:$('title').value,jd_text:$('jd').value,fictional:$('fictional').checked})});const ct=r.headers.get('content-type')||'';if(!ct.includes('application/json')){const body=await r.text();throw Error('Server returned '+r.status+' '+(r.status===502||r.status===503||r.status===504?'(backend unavailable or timed out)':'(unexpected HTML response)')+'. Check Render logs.')}const d=await r.json();if(!r.ok)throw Error(d.error||'Generation failed');token=d.download_token;$('result').textContent=JSON.stringify(d.resume,null,2);$('exports').hidden=false;$('status').textContent='Validated synthetic resume generated.'}catch(e){$('status').textContent=e.message}finally{$('go').disabled=false}};
async function download(fmt){if(!token)return;const r=await fetch('/api/download/'+fmt+'/'+encodeURIComponent(token));if(!r.ok){alert('Download expired or unavailable');return}const blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='synthetic-test-resume.'+fmt;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
</script></html>"""

@app.get("/")
def home():
    return render_template_string(HTML)

@app.get("/health")
def health():
    return jsonify(status="ok")

@app.post("/api/generate")
def generate():
    ip = request.remote_addr or "unknown"
    now = time.monotonic()
    with _lock:
        recent = [t for t in _rate.get(ip, []) if now - t < 3600]
        if len(recent) >= 10:
            return jsonify(error="Hourly demo limit reached; try again later."), 429
        recent.append(now)
        _rate[ip] = recent
        if len(_rate) > 5000:
            _rate.clear()
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("fictional") is not True:
        return jsonify(error="Confirm the input profile is fictional test data."), 400
    profile, title, jd = body.get("profile"), body.get("jd_title"), body.get("jd_text")
    if not isinstance(profile, dict) or not isinstance(title, str) or not isinstance(jd, str) or not title.strip() or not jd.strip() or len(jd) > 12000 or len(title) > 180:
        return jsonify(error="Provide a fictional profile, job title and job description."), 400
    if not isinstance(profile.get("experience"), list) or not profile["experience"] or len(profile["experience"]) > 8 or len(json.dumps(profile)) > 30000:
        return jsonify(error="Profile must contain 1–8 fictional employment entries."), 400
    if not os.environ.get("GEMINI_API_KEY"):
        return jsonify(error="Gemini is not configured on the server."), 503
    industries = profile.get("employer_industries", {})
    if not isinstance(industries, dict):
        industries = {}
    original_role = profile["experience"][0].get("role", profile["experience"][0].get("title", ""))
    prompt = (PROMPT_FILE.read_text()
        .replace("{original_resume}", json.dumps(profile))
        .replace("{original_role}", str(original_role))
        .replace("{jd_title}", title)
        .replace("{job_description}", jd[:8000])
        .replace("{keywords}", ", ".join(jd.split()[:35]))
        .replace("{employer_industries}", "; ".join(f"{k}: {v}" for k,v in industries.items()))) + KEY_CONTRACT
    try:
        raw, note = _gemini(prompt)
        if not raw:
            return jsonify(error="Gemini did not return a response."), 502
        txt = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(txt)
        errors = validate(result, original=profile)
        if errors:
            return jsonify(error="Model output failed validation.",details=errors[:8]), 422
        normalized = normalize(result)
        token = secrets.token_urlsafe(24)
        with _cache_lock:
            expired = [k for k,v in _cache.items() if now-v[0]>900]
            for k in expired: del _cache[k]
            _cache[token] = (now, normalized)
        return jsonify(resume=result, download_token=token)
    except Exception:
        app.logger.exception("Generation failed")
        return jsonify(error="Generation failed. Check server logs and retry."), 502

@app.get("/api/download/<fmt>/<token>")
def download(fmt, token):
    if fmt not in ("pdf", "docx"):
        return jsonify(error="Unsupported format"), 400
    with _cache_lock:
        entry = _cache.get(token)
    if not entry or time.monotonic()-entry[0] > 900:
        return jsonify(error="Download expired"), 404
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / ("synthetic-test-resume." + fmt))
        if fmt == "pdf":
            render_pdf(entry[1], path)
        else:
            render_docx(entry[1], path)
        from io import BytesIO
        return send_file(BytesIO(Path(path).read_bytes()),as_attachment=True,download_name="synthetic-test-resume."+fmt,mimetype="application/pdf" if fmt=="pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
