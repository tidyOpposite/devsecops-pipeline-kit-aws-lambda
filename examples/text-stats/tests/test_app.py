"""Behavioral tests for the demonstration workload, independent of AWS."""

import base64
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("text_stats_app", ROOT / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def event(path="/analyze", method="POST", text="Привіт, дипломний проєкт!"):
    return {"version": "2.0", "rawPath": path, "requestContext": {"http": {"method": method}},
            "headers": {"content-type": "application/json; charset=utf-8"}, "isBase64Encoded": False,
            "body": json.dumps({"text": text}, ensure_ascii=False)}


class TextStatsTests(unittest.TestCase):
    def invoke(self, request, status=200):
        with redirect_stdout(io.StringIO()):
            result = app.handler(request, None)
        self.assertEqual(result["statusCode"], status, result)
        self.assertEqual(result["headers"]["cache-control"], "no-store")
        self.assertFalse(result["isBase64Encoded"])
        return json.loads(result["body"])

    def test_ukrainian_text_has_exact_documented_statistics(self):
        text = "Привіт, дипломний проєкт!"
        data = self.invoke(event(text=text))
        self.assertEqual(data["statistics"], {"words": 3, "characters": 25, "lines": 1,
            "utf8_bytes": 46, "sha256": hashlib.sha256(text.encode()).hexdigest()})
        self.assertEqual(data["release"], "demo-a")

    def test_unicode_whitespace_newlines_and_codepoints(self):
        data = self.invoke(event(text="one\tдва\n🙂 e\u0301\n"))
        self.assertEqual(data["statistics"]["words"], 4)
        self.assertEqual(data["statistics"]["lines"], 2)
        self.assertEqual(data["statistics"]["characters"], 13)

    def test_both_supplied_events_invoke_real_handler(self):
        for filename in ("health.json", "analyze.json"):
            with self.subTest(filename=filename):
                self.invoke(json.loads((ROOT / "events" / filename).read_text(encoding="utf-8")))

    def test_base64_and_case_insensitive_media_type(self):
        request = event()
        request["headers"] = {"Content-Type": "Application/JSON"}
        request["body"] = base64.b64encode(request["body"].encode()).decode()
        request["isBase64Encoded"] = True
        self.assertEqual(self.invoke(request)["statistics"], self.invoke(event())["statistics"])

    def test_bad_json_base64_utf8_and_surrogates_are_rejected(self):
        for body, encoded in (("{", False), ("not base64!", True), ("/w==", True),
                              ('{"text":"\\ud800"}', False), ("\ud800", False),
                              ("[" * 2000, False), (None, False), ("{}", "false")):
            with self.subTest(body=repr(body)[:60], encoded=encoded):
                self.invoke(event() | {"body": body, "isBase64Encoded": encoded}, 400)

    def test_schema_empty_text_and_wrong_types_are_rejected(self):
        for payload in ({}, [], None, {"text": 1}, {"text": " "}, {"text": "a", "extra": "b"}):
            with self.subTest(payload=payload):
                self.invoke(event() | {"body": json.dumps(payload)}, 400)

    def test_body_and_text_limits_apply_to_plain_and_base64(self):
        self.invoke(event(text="я" * app.MAX_TEXT_CHARACTERS))
        self.invoke(event(text="a" * (app.MAX_TEXT_CHARACTERS + 1)), 413)
        for encoded in (False, True):
            request = event()
            raw = b" " * (app.MAX_BODY_BYTES + 1)
            request["body"] = base64.b64encode(raw).decode() if encoded else raw.decode()
            request["isBase64Encoded"] = encoded
            self.invoke(request, 413)

    def test_json_content_type_is_required(self):
        for headers in ({}, {"content-type": "text/plain"}):
            self.invoke(event() | {"headers": headers}, 415)
        for headers in ([], None, {"content-type": 3}, {1: "application/json"}):
            self.invoke(event() | {"headers": headers}, 400)

    def test_routes_methods_and_invalid_events(self):
        self.invoke(event("/health", "GET"))
        self.assertEqual(self.invoke(event("/version", "GET"))["api_version"], "1")
        self.assertIn("POST /analyze", self.invoke(event("/", "GET"))["routes"])
        self.invoke(event("/missing", "GET"), 404)
        with redirect_stdout(io.StringIO()):
            result = app.handler(event("/analyze", "GET"), None)
        self.assertEqual(result["statusCode"], 405)
        self.assertEqual(result["headers"]["allow"], "POST")
        for request in (None, [], {}, {"version": "1.0"}, {"version": "2.0"},
                        event() | {"rawPath": []}, event() | {"requestContext": []}):
            self.invoke(request, 400)

    def test_failure_and_recovery_images_are_distinguishable(self):
        for release, health, status in (("demo-a", "healthy", 200), ("demo-b", "healthy", 200),
                                        ("demo-fail", "failing", 503)):
            with self.subTest(release=release), patch.object(app, "RELEASE", {"release": release, "health": health}):
                self.assertEqual(self.invoke(event("/health", "GET"), status)["release"], release)
                self.assertEqual(self.invoke(event())["release"], release)

    def test_user_content_headers_and_unknown_paths_are_not_logged(self):
        request = event(text="private-text-sentinel")
        request["headers"]["authorization"] = "private-token-sentinel"
        output = io.StringIO()
        with redirect_stdout(output):
            app.handler(request, None)
            app.handler(event("/private-path-sentinel", "GET"), None)
        self.assertNotIn("private-", output.getvalue())
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(records[-1]["route"], "unknown")
        self.assertEqual(records[0]["status"], 200)


if __name__ == "__main__":
    unittest.main()
