"""Local web app. Stdlib only; binds to 127.0.0.1. Essays leave the machine only
through the Claude calls, and the page loads nothing from other sites."""

from __future__ import annotations

import json
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import llm
from . import review as review_mod
from .review import get_corpus, review
from .apply import apply_all, flag_partial
from .chat import chat
from .revise import revise

WEB = Path(__file__).resolve().parent / "web"
MAX_BODY = 200_000
KEEP_JOBS = 20

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _history_file(name: str) -> Path | None:
    # Read the module attribute at call time so tests can point history elsewhere.
    f = review_mod.HISTORY_DIR / f"{name}.json"
    return f if name.replace("-", "").isdigit() and f.exists() else None


def _load_saved(path: Path) -> dict:
    with _lock:  # write-backs rewrite the file in place, so a read outside the lock can catch it half-written
        return json.loads(path.read_text())


def _meta_from(req: dict) -> dict:
    essay_type = req.get("essay_type") or "personal"
    raw_limit = str(req.get("word_limit") or "").strip()
    limit = int(raw_limit) if raw_limit.isdigit() else (650 if essay_type == "personal" else None)
    return {"prompt": req.get("prompt", ""), "essay_type": essay_type, "word_limit": limit, "school": req.get("school", "")}


def _do_review(req: dict, corpus_path: str | None, progress) -> dict:
    return review(
        req.get("essay", ""),
        **_meta_from(req),
        model="sonnet" if req.get("fast") else None,
        n_compare=min(max(int(req.get("compare", 3)), 0), 5),
        n_anchor=min(max(int(req.get("anchors", 4)), 0), 4),
        corpus_path=corpus_path,
        progress=progress,
    )


def _do_revise(req: dict, progress) -> dict:
    rid = str(req.get("review_id") or "")
    saved, path = None, None
    if rid:
        path = _history_file(rid)
        if not path:
            raise ValueError("That saved review was not found. Run the review again, then ask for a revision.")
        saved = _load_saved(path)
    meta = saved["meta"] if saved else _meta_from(req)
    result = revise(
        saved["essay"] if saved else req.get("essay", ""),
        prompt=meta.get("prompt", ""), essay_type=meta.get("essay_type", "personal"),
        word_limit=meta.get("word_limit"), school=meta.get("school", ""),
        review=saved, model="sonnet" if req.get("fast") else None, progress=progress,
    )
    if path:
        with _lock:  # two revisions of one review finishing together must not interleave writes
            current = json.loads(path.read_text())
            current["revision"] = result
            path.write_text(json.dumps(current, indent=1))
    return result


def _do_chat(req: dict, progress) -> dict:
    rid = str(req.get("review_id") or "")
    saved, path = None, None
    if rid:
        path = _history_file(rid)
        if not path:
            raise ValueError("That saved review was not found. Run the review again, then ask for changes.")
        saved = _load_saved(path)
    meta = saved["meta"] if saved else _meta_from(req)
    original = saved["essay"] if saved else str(req.get("essay") or "")
    history = req.get("history") if isinstance(req.get("history"), list) else []
    result = chat(original, str(req.get("draft") or original), str(req.get("message") or ""),
                  history=history, meta=meta, review=saved, advice=str(req.get("advice") or "")[:2000], progress=progress)
    if path:
        with _lock:  # the same lock as revision write-backs, so the two never interleave
            current = json.loads(path.read_text())
            current.setdefault("chat", []).append(result)
            path.write_text(json.dumps(current, indent=1))
    return result


def _do_apply(req: dict, progress) -> dict:
    rid = str(req.get("review_id") or "")
    saved, path = None, None
    if rid:
        path = _history_file(rid)
        if not path:
            raise ValueError("That saved review was not found. Run the review again, then make the changes.")
        saved = _load_saved(path)
    meta = saved["meta"] if saved else _meta_from(req)
    edits = saved.get("edits") if saved else req.get("edits")
    result = apply_all(saved["essay"] if saved else str(req.get("essay") or ""), edits if isinstance(edits, list) else [],
                       meta=meta, model="sonnet" if req.get("fast") else None, progress=progress)
    if path:
        with _lock:  # the same lock as the other write-backs, so they never interleave
            current = json.loads(path.read_text())
            current["applied"] = result
            path.write_text(json.dumps(current, indent=1))
    return result


def _run_job(job_id: str, kind: str, req: dict, corpus_path: str | None) -> None:
    def progress(msg: str) -> None:
        with _lock:
            _jobs[job_id]["progress"].append(msg)

    try:
        result = (_do_revise(req, progress) if kind == "revise" else _do_chat(req, progress) if kind == "chat"
                  else _do_apply(req, progress) if kind == "apply" else _do_review(req, corpus_path, progress))
        with _lock:
            _jobs[job_id].update(status="done", result=result)
    except (llm.LLMError, ValueError) as err:
        with _lock:
            _jobs[job_id].update(status="error", error=str(err))
    except Exception as err:  # surface anything unexpected to the UI instead of hanging
        with _lock:
            _jobs[job_id].update(status="error", error=f"{type(err).__name__}: {err}")


def make_handler(corpus_path: str | None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode())

        def _addressed_locally(self) -> bool:
            # A web page that rebinds its domain to 127.0.0.1 still sends its own Host
            # header; refusing those keeps other sites from reading saved essays.
            port = self.server.server_address[1]
            host = (self.headers.get("Host") or "").lower()
            return host in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

        def do_GET(self):
            if not self._addressed_locally():
                return self._json(403, {"error": "forbidden host"})
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/api/job/"):
                with _lock:
                    job = _jobs.get(path.rsplit("/", 1)[-1])
                    snap = json.loads(json.dumps(job)) if job else None
                return self._json(200, snap) if snap else self._json(404, {"error": "unknown job"})
            if path == "/api/history":
                items = []
                for f in sorted(review_mod.HISTORY_DIR.glob("*.json"), reverse=True)[:50]:
                    try:
                        r = json.loads(f.read_text())
                    except (OSError, json.JSONDecodeError):
                        continue
                    items.append({"id": f.stem, "created": r.get("created"), "score": r.get("score"),
                                  "band": r.get("band"), "first_line": r.get("essay", "").strip()[:90]})
                return self._json(200, items)
            if path.startswith("/api/history/"):
                name = path.rsplit("/", 1)[-1]
                f = _history_file(name)
                if not f:
                    return self._json(404, {"error": "not found"})
                saved = _load_saved(f)
                saved.setdefault("id", name)  # reviews saved before ids existed
                if isinstance(saved.get("edits"), list):
                    saved["edits"] = flag_partial(str(saved.get("essay") or ""), saved["edits"])
                return self._json(200, saved)
            if path == "/api/status":
                try:
                    n = len(get_corpus(corpus_path))
                except FileNotFoundError:
                    n = 0
                return self._json(200, {"corpus_size": n})
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._addressed_locally():
                return self._json(403, {"error": "forbidden host"})
            kind = {"/api/review": "review", "/api/revise": "revise", "/api/chat": "chat", "/api/apply": "apply"}.get(self.path)
            if not kind:
                return self._json(404, {"error": "not found"})
            # Requiring JSON forces a CORS preflight for cross-site pages, which this server
            # never approves, and the Origin check covers browsers that send one anyway.
            origin = self.headers.get("Origin")
            if not (self.headers.get("Content-Type") or "").startswith("application/json") or (
                    origin and origin.lower() != "http://" + (self.headers.get("Host") or "").lower()):
                return self._json(403, {"error": "cross-site request refused"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0:
                return self._json(400, {"error": "bad Content-Length"})
            if n > MAX_BODY:
                return self._json(413, {"error": "essay too long"})
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "bad JSON"})
            job_id = uuid.uuid4().hex[:12]
            with _lock:
                # Finished jobs hold whole essays; keep only the most recent ones in memory.
                finished = [k for k, j in _jobs.items() if j["status"] != "running"]
                for k in finished[:-KEEP_JOBS]:
                    del _jobs[k]
                _jobs[job_id] = {"status": "running", "progress": [], "result": None, "error": None}
            threading.Thread(target=_run_job, args=(job_id, kind, req, corpus_path), daemon=True).start()
            return self._json(202, {"job": job_id})

    return Handler


def serve(port: int = 8765, open_browser: bool = True, corpus_path: str | None = None) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(corpus_path))
    url = f"http://127.0.0.1:{port}/"
    print(f"GaryAdmit running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
