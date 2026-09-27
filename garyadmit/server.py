"""Local web app. Stdlib only; binds to 127.0.0.1 so nothing leaves your machine
except the Claude calls themselves."""

from __future__ import annotations

import json
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import llm
from .review import HISTORY_DIR, get_corpus, review

WEB = Path(__file__).resolve().parent / "web"
MAX_BODY = 200_000

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _run_job(job_id: str, req: dict, corpus_path: str | None) -> None:
    def progress(msg: str) -> None:
        with _lock:
            _jobs[job_id]["progress"].append(msg)

    try:
        essay_type = req.get("essay_type") or "personal"
        raw_limit = str(req.get("word_limit") or "").strip()
        limit = int(raw_limit) if raw_limit.isdigit() else (650 if essay_type == "personal" else None)
        result = review(
            req.get("essay", ""),
            prompt=req.get("prompt", ""),
            essay_type=essay_type,
            word_limit=limit,
            school=req.get("school", ""),
            model="sonnet" if req.get("fast") else None,
            n_compare=int(req.get("compare", 3)),
            n_anchor=int(req.get("anchors", 4)),
            corpus_path=corpus_path,
            progress=progress,
        )
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

        def do_GET(self):
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
                for f in sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:50]:
                    try:
                        r = json.loads(f.read_text())
                    except (OSError, json.JSONDecodeError):
                        continue
                    items.append({"id": f.stem, "created": r.get("created"), "score": r.get("score"),
                                  "band": r.get("band"), "first_line": r.get("essay", "").strip()[:90]})
                return self._json(200, items)
            if path.startswith("/api/history/"):
                name = path.rsplit("/", 1)[-1]
                f = HISTORY_DIR / f"{name}.json"
                if not name.replace("-", "").isdigit() or not f.exists():
                    return self._json(404, {"error": "not found"})
                return self._send(200, f.read_bytes())
            if path == "/api/status":
                try:
                    n = len(get_corpus(corpus_path))
                except FileNotFoundError:
                    n = 0
                return self._json(200, {"corpus_size": n})
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/review":
                return self._json(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._json(413, {"error": "essay too long"})
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "bad JSON"})
            job_id = uuid.uuid4().hex[:12]
            with _lock:
                _jobs[job_id] = {"status": "running", "progress": [], "result": None, "error": None}
            threading.Thread(target=_run_job, args=(job_id, req, corpus_path), daemon=True).start()
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
