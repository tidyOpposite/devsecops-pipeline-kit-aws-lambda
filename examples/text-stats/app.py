"""Small stateless Lambda workload for the diploma demonstration.

Only API Gateway HTTP API payload v2 is accepted. No text is stored or logged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path


RELEASE = json.loads(Path(__file__).with_name("release.json").read_text(encoding="utf-8"))
MAX_BODY_BYTES = 65_536
MAX_TEXT_CHARACTERS = 10_000
ROUTES = {"/": "GET", "/health": "GET", "/version": "GET", "/analyze": "POST"}


def response(status: int, payload: dict, **headers: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store",
                    "x-content-type-options": "nosniff", **headers},
        "isBase64Encoded": False,
        "body": json.dumps({"service": "text-stats", "release": RELEASE["release"], **payload}, ensure_ascii=False),
    }


def analyze(event: dict) -> dict:
    headers = event.get("headers", {})
    if not isinstance(headers, dict) or any(not isinstance(name, str) or not isinstance(value, str)
                                            for name, value in headers.items()):
        return response(400, {"error": "Invalid request headers."})
    headers = {name.lower(): value for name, value in headers.items()}
    media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        return response(415, {"error": "Use Content-Type: application/json and a UTF-8 body."})
    body = event.get("body")
    encoded = event.get("isBase64Encoded", False)
    if not isinstance(body, str) or not isinstance(encoded, bool):
        return response(400, {"error": "A JSON request body is required."})
    try:
        raw = body.encode("utf-8")
        if len(raw) > ((MAX_BODY_BYTES + 2) // 3) * 4:
            return response(413, {"error": "Request body exceeds 65536 bytes."})
        if encoded:
            raw = base64.b64decode(raw, validate=True)
        if len(raw) > MAX_BODY_BYTES:
            return response(413, {"error": "Request body exceeds 65536 bytes."})
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, binascii.Error, RecursionError):
        return response(400, {"error": "Body must be valid UTF-8 JSON (or valid base64 containing it)."})
    if not isinstance(payload, dict) or set(payload) != {"text"} or not isinstance(payload["text"], str):
        return response(400, {"error": 'Provide exactly one string field: "text".'})
    text = payload["text"]
    if len(text) > MAX_TEXT_CHARACTERS:
        return response(413, {"error": "Text exceeds 10000 Unicode characters."})
    if not text.strip():
        return response(400, {"error": "Text must contain at least one non-whitespace character."})
    try:
        utf8 = text.encode("utf-8")
    except UnicodeError:
        return response(400, {"error": "Text contains an invalid Unicode surrogate."})
    return response(200, {"statistics": {
        "words": len(text.split()), "characters": len(text), "lines": len(text.splitlines()),
        "utf8_bytes": len(utf8), "sha256": hashlib.sha256(utf8).hexdigest(),
    }})


def handler(event: dict, context) -> dict:
    if not isinstance(event, dict) or event.get("version") != "2.0":
        return response(400, {"error": "API Gateway HTTP API payload v2 is required."})
    request = event.get("requestContext")
    http = request.get("http") if isinstance(request, dict) else None
    method = http.get("method") if isinstance(http, dict) else None
    path = event.get("rawPath")
    if not isinstance(path, str) or not isinstance(method, str):
        result = response(400, {"error": "HTTP method and rawPath are required."})
    elif path not in ROUTES:
        result = response(404, {"error": "Route not found."})
    elif method != ROUTES[path]:
        result = response(405, {"error": "Method not allowed."}, allow=ROUTES[path])
    elif path == "/health":
        healthy = RELEASE["health"] == "healthy"
        result = response(200 if healthy else 503, {"status": "ok" if healthy else "unhealthy"})
    elif path == "/version":
        result = response(200, {"api_version": "1"})
    elif path == "/":
        result = response(200, {"routes": [f"{method} {path}" for path, method in ROUTES.items()]})
    else:
        result = analyze(event)
    # Log only an allowlisted route and fixed result metadata, never the body,
    # caller headers, query string, credentials or the submitted text.
    route = path if isinstance(path, str) and path in ROUTES else "unknown"
    print(json.dumps({"service": "text-stats", "release": RELEASE["release"],
                      "route": route, "status": result["statusCode"]}))
    return result
