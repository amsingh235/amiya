"""Local server: the dashboard plus a live API, standard library only.

    python serve.py            -> http://localhost:8000
    python serve.py --port 9000

GET  /api/health                 which pipelines can run live
POST /api/classify  {text, pipeline}   harness-timed, harness-priced answer
GET  /api/search?q=...&k=3       policy retrieval (same retriever as pipelines C and D)
GET  /api/results                results.json
POST /api/outbox    {...}        Autopilot files triage decisions to outbox/triage-<date>.jsonl

Binds to 127.0.0.1 only: this exposes your API key's quota, so it never listens on the network.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from harness.service import Service
from pipelines.llm import DailyLimitReached, LLMError, MissingKey

WEB = Path(__file__).resolve().parent / "web"


class Handler(SimpleHTTPRequestHandler):
    service: Service

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/"):
            sys.stderr.write(f"  {self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/health":
            return self._json(200, self.service.health())
        if u.path == "/api/search":
            return self._json(200, self.service.search(q.get("q", [""])[0], int(q.get("k", ["3"])[0])))
        if u.path == "/api/results":
            return self._json(200, self.service.results())
        if u.path.startswith("/api/"):
            return self._json(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > 200_000:
            return self._json(413, {"error": "payload too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON"})
        try:
            if u.path == "/api/classify":
                return self._json(200, self.service.classify(body.get("text", ""), body.get("pipeline", "rules")))
            if u.path == "/api/outbox":
                return self._json(200, {"saved": self.service.save_outbox(body)})
        except (ValueError, MissingKey) as e:
            return self._json(400, {"error": str(e)})
        except DailyLimitReached as e:
            return self._json(429, {"error": f"Groq daily limit reached: {e}"})
        except LLMError as e:
            return self._json(502, {"error": str(e)})
        return self._json(404, {"error": "not found"})


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the Overkill dashboard with a live API")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    Handler.service = Service()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    live = "LLM pipelines live (GROQ_API_KEY found)" if Handler.service.llm_available else \
        "no GROQ_API_KEY: rules live, LLM lanes replay recorded runs"
    print(f"Overkill → http://localhost:{args.port}   ·  {live}   ·  Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
