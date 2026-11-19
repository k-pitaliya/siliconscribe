"""A local stand-in for Cloudflare's API: the same URL paths and Bearer-token rule, so the real client code runs end to end.

  GET  /client/v4/accounts/{account}/ai/models/search?per_page=&page=   -> {"result": [...], "success": true}
  POST /client/v4/accounts/{account}/ai/v1/chat/completions             -> an OpenAI-style chat completion

Every request is recorded in `server.requests` so a test can assert what was sent (path, headers, body).
"""
import json
import threading
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer

ACCOUNT = "a" * 32
TOKEN = "test-token-not-a-secret"


class FakeCloudflare:
    def __init__(self, search_pages=None, search_status=200, chat_status=200, chat_text="module m; endmodule"):
        self.search_pages = search_pages if search_pages is not None else [[]]
        self.search_status = search_status
        self.chat_status = chat_status
        self.chat_text = chat_text
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _auth_ok(self):
                return self.headers.get("Authorization") == f"Bearer {TOKEN}"

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                outer.requests.append(("GET", self.path, {k.lower(): v for k, v in self.headers.items()}, None))
                if not self._auth_ok():
                    return self._send(401, {"success": False, "errors": [{"message": "bad token"}]})
                if outer.search_status != 200:
                    return self._send(outer.search_status, {"success": False})
                if f"/accounts/{ACCOUNT}/ai/models/search" not in self.path:
                    return self._send(404, {"success": False})
                query = parse_qs(urlparse(self.path).query)
                page = int((query.get("page") or ["1"])[0])
                pages = outer.search_pages
                self._send(200, {"result": pages[page - 1] if page <= len(pages) else [], "success": True})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append(("POST", self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                if not self._auth_ok():
                    return self._send(401, {"error": {"message": "bad token"}})
                if outer.chat_status != 200:
                    return self._send(outer.chat_status, {"error": {"message": "upstream said no"}})
                if self.path != f"/client/v4/accounts/{ACCOUNT}/ai/v1/chat/completions":
                    return self._send(404, {"error": {"message": "wrong path " + self.path}})
                self._send(200, {"id": "x", "object": "chat.completion", "model": body.get("model"),
                                 "choices": [{"index": 0, "finish_reason": "stop",
                                              "message": {"role": "assistant", "content": outer.chat_text}}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/client/v4"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def model_entry(name, task="Text Generation", description="A model"):
    return {"name": name, "description": description, "task": {"name": task}}
