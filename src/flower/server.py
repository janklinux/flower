"""Minimal stdlib HTTP control API for a running :class:`~flower.controller.Controller`.

Zero extra dependencies (``http.server``). Endpoints match the admin_flower app
contract:

===========================  ======================================================
``GET  /api/status``         live snapshot: relays + latest sensor values + settings
``GET  /api/settings``       the settings/command flag file
``GET  /api/timeseries/<s>`` last ``?n=`` samples per channel (moisture/rht/room)
``POST /api/settings/<key>`` body ``{"value": ...}`` — set a flag
``POST /api/relay/<name>``   body ``{"on": bool}``  — hold a (direct) relay
``POST /api/command/<key>``  trigger a one-shot flag (water/fill/…)
===========================  ======================================================

Auth: ``Authorization: Bearer <token>``. Cleartext, meant for a trusted LAN —
add TLS (or an SSH tunnel) if it ever leaves it.
"""

from __future__ import annotations

import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("flower.server")


class _Handler(BaseHTTPRequestHandler):
    server_version = "flower/0.1"

    # route to the controller/token carried by the server instance
    @property
    def controller(self):
        return self.server.controller

    @property
    def token(self):
        return self.server.token

    def log_message(self, fmt, *args):  # funnel access logs through logging
        log.info("%s %s", self.address_string(), fmt % args)

    # -- helpers --------------------------------------------------------------
    def _authed(self) -> bool:
        if not self.token:                       # no token configured (insecure)
            return True
        hdr = self.headers.get("Authorization", "")
        pre = "Bearer "
        return hdr.startswith(pre) and hmac.compare_digest(hdr[len(pre):], self.token)

    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if n <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}

    @staticmethod
    def _parts(path: str):
        u = urlparse(path)
        return [p for p in u.path.split("/") if p], u

    # -- verbs ----------------------------------------------------------------
    def do_GET(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        parts, u = self._parts(self.path)
        try:
            if parts == ["api", "status"]:
                return self._send(200, self.controller.snapshot())
            if parts == ["api", "settings"]:
                return self._send(200, self.controller.settings.load())
            if len(parts) == 3 and parts[:2] == ["api", "timeseries"]:
                try:
                    n = int(parse_qs(u.query).get("n", ["200"])[0])
                except ValueError:
                    n = 200
                data = self.controller.timeseries(parts[2], n)
                if data is None:
                    return self._send(404, {"error": f"unknown store '{parts[2]}'"})
                return self._send(200, data)
        except Exception as exc:                 # never leak a stack trace as 200
            log.exception("GET %s failed", self.path)
            return self._send(500, {"error": str(exc)})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        parts, _ = self._parts(self.path)
        body = self._read_json()
        try:
            if len(parts) == 3 and parts[:2] == ["api", "settings"]:
                self.controller.settings.set(parts[2], body.get("value"))
                self.controller.apply_settings()
                return self._send(200, {"ok": True, "settings": self.controller.settings.load()})
            if len(parts) == 3 and parts[:2] == ["api", "relay"]:
                name = parts[2]
                if name not in self.controller.bank:
                    return self._send(404, {"error": f"unknown relay '{name}'"})
                self.controller.settings.set(name, bool(body.get("on")))
                self.controller.apply_settings()
                return self._send(200, {"ok": True, "relay": name,
                                        "on": self.controller.bank[name].is_on})
            if len(parts) == 3 and parts[:2] == ["api", "command"]:
                self.controller.settings.set(parts[2], True)
                self.controller.apply_settings()
                return self._send(200, {"ok": True, "command": parts[2]})
        except Exception as exc:
            log.exception("POST %s failed", self.path)
            return self._send(500, {"error": str(exc)})
        return self._send(404, {"error": "not found"})


class ApiServer(ThreadingHTTPServer):
    """A threading HTTP server bound to a :class:`Controller` + token."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, controller, host: str = "0.0.0.0", port: int = 8080,
                 token: str | None = None) -> None:
        super().__init__((host, port), _Handler)
        self.controller = controller
        self.token = token


def serve(controller, host: str = "0.0.0.0", port: int = 8080,
          token: str | None = None) -> None:
    """Serve the control API for ``controller`` until interrupted (blocking)."""
    srv = ApiServer(controller, host, port, token)
    log.info("flower API on http://%s:%d (auth: %s)", host, srv.server_address[1],
             "token" if token else "NONE - insecure!")
    try:
        srv.serve_forever()
    finally:
        srv.shutdown()
        srv.server_close()
