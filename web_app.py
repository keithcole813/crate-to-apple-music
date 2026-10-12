"""Crate to Apple Music — web version.

Upload a Serato .crate from your phone, get back Apple Music streaming
links for every track (most-likely match), with clear notes for songs
that aren't on Apple Music.

Runs on the home server, port 5003.
"""
import html
import os
import tempfile
import threading
import uuid

from flask import Flask, jsonify, request

from apple_matcher import crate_links

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # crates are tiny

JOBS = {}

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crate → Apple Music</title>
<style>
*{box-sizing:border-box}
body{background:#111;color:#eee;font-family:-apple-system,sans-serif;
     margin:0;padding:20px;max-width:640px;margin:0 auto}
h1{color:#f5c518;font-size:1.4em}
.card{background:#1c1c1e;border-radius:14px;padding:18px;margin:14px 0}
input[type=file]{width:100%;margin:10px 0;color:#eee}
button{background:#f5c518;border:0;border-radius:10px;padding:14px 20px;
       font-size:1.05em;font-weight:700;width:100%;color:#111}
#status{margin-top:12px;color:#aaa;min-height:1.4em}
.song{display:block;background:#1c1c1e;border-radius:10px;padding:12px 14px;
      margin:8px 0;color:#fff;text-decoration:none}
.song small{color:#999;display:block;margin-top:2px}
.miss{background:#2a1a1a;color:#c99;padding:12px 14px;border-radius:10px;margin:8px 0}
</style></head><body>
<h1>📱 Crate → Apple Music</h1>
<div class="card">
  <p>Upload a Serato <b>.crate</b> file. Every track gets cross-checked
  against Apple Music and linked to the most likely match.</p>
  <form id="f"><input type="file" name="crate" accept=".crate" required>
  <button type="submit">Find on Apple Music</button></form>
  <div id="status"></div>
</div>
<div id="results"></div>
<script>
const f=document.getElementById('f'),st=document.getElementById('status'),
      res=document.getElementById('results');
f.onsubmit=async e=>{
  e.preventDefault();res.innerHTML='';st.textContent='Checking Apple Music…';
  const r=await fetch('/match',{method:'POST',body:new FormData(f)});
  const j=await r.json();
  if(j.error){st.textContent=j.error;return;}
  poll(j.job_id);
};
async function poll(id){
  const r=await fetch('/status/'+id);const j=await r.json();
  st.textContent=j.status;
  if(j.done){
    st.textContent=`${j.found} of ${j.total} found for streaming.`;
    res.innerHTML=j.items_html;
  } else setTimeout(()=>poll(id),1500);
}
</script></body></html>"""


def esc(s):
    return html.escape(s or "")


@app.route("/")
def index():
    return PAGE


@app.route("/match", methods=["POST"])
def match():
    f = request.files.get("crate")
    if not f or not f.filename.lower().endswith(".crate"):
        return jsonify(error="Upload a .crate file."), 400
    job_id = uuid.uuid4().hex
    tmp = os.path.join(tempfile.gettempdir(), job_id + ".crate")
    f.save(tmp)
    JOBS[job_id] = {"status": "starting…", "done": False,
                    "items": [], "found": 0, "total": 0, "tmp": tmp}
    threading.Thread(target=_run, args=(job_id,), daemon=True).start()
    return jsonify(job_id=job_id)


def _run(job_id):
    job = JOBS[job_id]
    try:
        def prog(i, n, name):
            job["status"] = f"Checking {i}/{n}…"
        for label, match, score in crate_links(job["tmp"], progress_cb=prog):
            job["total"] += 1
            if match:
                job["found"] += 1
                job["items"].append(
                    f'<a class="song" href="{esc(match["trackViewUrl"])}">'
                    f"{esc(match['artistName'])} — {esc(match['trackName'])}"
                    f"<small>for: {esc(label)}</small></a>")
            else:
                job["items"].append(
                    f'<div class="miss">⚠️ Not on Apple Music: {esc(label)}</div>')
        job["status"] = "done"
    except Exception as e:
        job["status"] = f"error: {e}"
    finally:
        job["done"] = True
        try:
            os.unlink(job["tmp"])
        except OSError:
            pass


@app.route("/status/<job_id>")
def status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="unknown job"), 404
    return jsonify(status=job["status"], done=job["done"],
                   found=job["found"], total=job["total"],
                   items_html="\n".join(job["items"]))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5003)
