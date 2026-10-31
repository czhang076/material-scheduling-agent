"""Loopback HTTP protocol fixture. It never calls an external model service."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import time


class FixtureServer:
    def __init__(self, responder):
        self.requests = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                content = self.rfile.read(int(self.headers["Content-Length"]))
                owner.requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(content)})
                specification = responder(len(owner.requests), owner.requests[-1])
                status, body = specification.get("status", 200), specification.get("body", b"{}")
                if type(body) is dict:
                    body = json.dumps(body).encode()
                time.sleep(specification.get("header_delay", 0))
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(specification.get("content_length", len(body))))
                    for key, value in specification.get("headers", {}).items():
                        self.send_header(key, value)
                    self.end_headers()
                    if specification.get("drip"):
                        for byte in body:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(specification["drip"])
                    else:
                        self.wfile.write(body)
                except OSError:
                    pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.block_on_close = False
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
