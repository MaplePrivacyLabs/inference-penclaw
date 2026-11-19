"""Require the Maple metrics key on vLLM's Prometheus endpoint.

vLLM's own bearer check covers /v1 and a few other prefixes. It does not cover
/metrics, and vLLM serves every path that starts with /metrics from the same
Prometheus application. This middleware asks for the metrics key on all of
those paths and hands every other request to vLLM untouched.

Loaded with `--middleware maple_metrics_auth.MetricsAuthMiddleware`. It uses
only the standard library, so it adds nothing to the image but this file.
"""

import hashlib
import hmac
import os

GUARDED_PREFIX = "/metrics"
KEY_VARIABLE = "METRICS_API_KEY"

_REFUSAL_BODY = b'{"error":"Unauthorized"}'
_REFUSAL_HEADERS = [
    (b"content-type", b"application/json"),
    (b"content-length", str(len(_REFUSAL_BODY)).encode("ascii")),
    (b"www-authenticate", b"Bearer"),
]


def is_guarded(path):
    """True for any spelling of a path under /metrics.

    Repeated slashes and letter case are folded first. Guarding a path that
    vLLM would not have served costs nothing; missing one would expose it.
    """
    folded = "/" + "/".join(part for part in path.split("/") if part)
    return folded.lower().startswith(GUARDED_PREFIX)


class MetricsAuthMiddleware:
    """Pure ASGI middleware: no response wrapping, no buffering."""

    def __init__(self, app):
        self.app = app
        key = os.environ.get(KEY_VARIABLE, "")
        # Without a key nothing can match, so every guarded request is refused.
        self._key_hash = hashlib.sha256(key.encode("utf-8")).digest() if key else None

    def _authorized(self, scope):
        if self._key_hash is None:
            return False
        values = [
            value
            for name, value in scope.get("headers") or ()
            if name.lower() == b"authorization"
        ]
        if len(values) != 1:
            return False
        scheme, _, token = values[0].partition(b" ")
        if scheme.lower() != b"bearer" or not token:
            return False
        return hmac.compare_digest(hashlib.sha256(token).digest(), self._key_hash)

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        root_path = scope.get("root_path") or ""
        guarded = is_guarded(path) or (
            bool(root_path)
            and path.startswith(root_path)
            and is_guarded(path[len(root_path):])
        )
        if not guarded or self._authorized(scope):
            await self.app(scope, receive, send)
            return

        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": list(_REFUSAL_HEADERS),
            }
        )
        await send({"type": "http.response.body", "body": _REFUSAL_BODY})
