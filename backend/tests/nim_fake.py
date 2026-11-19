"""A local stand-in for NVIDIA NIM's hosted API (OpenAI-compatible): the same paths and the same Bearer-token rule.

  GET  /v1/models              -> {"object": "list", "data": [{"id": ...}, ...]}
  POST /v1/chat/completions    -> an OpenAI-style chat completion
Every request is recorded in `server.requests` as (method, path, lower-cased headers, body).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

KEY = "nvapi-" + "a" * 40
OTHER_KEY = "nvapi-" + "b" * 40


class FakeNim:
    def __init__(self, models=None, models_status=200, chat_status=200, chat_text="module m; endmodule"):
        self.models = models if models is not None else []
        self.models_status = models_status
        self.chat_status = chat_status
        self.chat_text = chat_text
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _auth_ok(self):
                return self.headers.get("Authorization") == f"Bearer {KEY}"

            def do_GET(self):
                outer.requests.append(("GET", self.path, {k.lower(): v for k, v in self.headers.items()}, None))
                if not self._auth_ok():
                    return self._send(401, {"detail": "Authentication failed"})
                if outer.models_status != 200:
                    return self._send(outer.models_status, {"detail": "no"})
                if self.path != "/v1/models":
                    return self._send(404, {"detail": "not found"})
                self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in outer.models]})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.requests.append(("POST", self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                if not self._auth_ok():
                    return self._send(401, {"detail": "Authentication failed"})
                if outer.chat_status != 200:
                    return self._send(outer.chat_status, {"detail": "upstream said no"})
                if self.path != "/v1/chat/completions":
                    return self._send(404, {"detail": "wrong path " + self.path})
                self._send(200, {"id": "x", "object": "chat.completion", "model": body.get("model"),
                                 "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": outer.chat_text}}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()
