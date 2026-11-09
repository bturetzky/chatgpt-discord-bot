"""Sanitized webpage failure diagnostics and connection timeout regressions."""
import json
import socket
import unittest
from unittest.mock import MagicMock, patch

import requests
from urllib3.exceptions import ConnectTimeoutError, ReadTimeoutError

from discord_bot.functions.get_webpage_contents import (
    GetWebPageContents, MAX_BODY_BYTES, PublicHTTPSConnection, fetch_public_html,
)


class PageDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def result_for(self, exc, url="https://example.org/private/path?token=secret"):
        with patch("discord_bot.functions.get_webpage_contents.fetch_public_html", side_effect=exc):
            with self.assertLogs(level="WARNING") as captured:
                result = json.loads(await GetWebPageContents().execute({"url": url}))
        for log in captured.output:
            self.assertNotIn("private/path", log)
            self.assertNotIn("secret", log)
            self.assertNotIn("https://", log)
        error = result["error"]
        self.assertEqual(error["hostname"], "example.org")
        self.assertIsInstance(error["elapsed_ms"], int)
        self.assertGreaterEqual(error["elapsed_ms"], 0)
        self.assertNotIn("secret", json.dumps(error))
        return error

    async def test_http_error_keeps_status_without_exception_text(self):
        response = requests.Response()
        response.status_code = 403
        error = await self.result_for(requests.HTTPError("secret URL", response=response))
        self.assertEqual(error["code"], "HTTP_ERROR")
        self.assertEqual(error["http_status"], 403)
        self.assertIn("403", error["message"])

    async def test_streaming_read_timeout_wrapped_as_connection_error(self):
        wrapped = requests.ConnectionError(ReadTimeoutError(None, "/private/path", "secret"))
        error = await self.result_for(wrapped)
        self.assertEqual(error["code"], "TIMEOUT")
        self.assertIsNone(error["http_status"])

    async def test_connection_and_tls_errors_are_distinct(self):
        for exc, category in [(requests.ConnectionError("secret"), "CONNECTION_ERROR"),
                              (requests.exceptions.SSLError("secret"), "TLS_ERROR")]:
            with self.subTest(category=category):
                self.assertEqual((await self.result_for(exc))["code"], category)

    async def test_invalid_address_and_dns_failures(self):
        with self.assertLogs(level="WARNING") as logs:
            result = json.loads(await GetWebPageContents().execute({"url": "http://127.0.0.1/private?token=secret"}))
        self.assertEqual(result["error"]["code"], "INVALID_URL")
        self.assertNotIn("secret", str(logs.output))
        with patch("discord_bot.functions.get_webpage_contents.socket.getaddrinfo", side_effect=socket.gaierror("secret")):
            with self.assertLogs(level="WARNING"):
                result = json.loads(await GetWebPageContents().execute({"url": "https://example.org/private"}))
        self.assertEqual(result["error"]["code"], "DNS_ERROR")
        self.assertEqual(result["error"]["hostname"], "example.org")

    async def test_malformed_hostname_does_not_enter_logs(self):
        with self.assertLogs(level="WARNING") as logs:
            result = json.loads(await GetWebPageContents().execute({"url": "https://[invalid/private?secret"}))
        self.assertEqual(result["error"]["code"], "INVALID_URL")
        self.assertIsNone(result["error"]["hostname"])
        self.assertNotIn("secret", str(logs.output))


class FetchDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch("discord_bot.functions.get_webpage_contents.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))])
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def session(self, response):
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = response
        response.__enter__.return_value = response
        return session

    def test_size_and_content_type_have_distinct_codes(self):
        for content_type, chunks, code in [
            ("text/html", [b'x' * (MAX_BODY_BYTES + 1)], "BODY_TOO_LARGE"),
            ("application/pdf", [], "UNSUPPORTED_CONTENT"),
        ]:
            response = MagicMock(status_code=200, headers={"Content-Type": content_type})
            response.iter_content.return_value = chunks
            with self.subTest(code=code), patch("discord_bot.functions.get_webpage_contents.requests.Session", return_value=self.session(response)):
                with self.assertRaises(ValueError) as raised:
                    fetch_public_html("https://example.org/private?secret")
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.hostname, "example.org")
                self.assertEqual(raised.exception.http_status, 200)

    def test_http_status_is_preserved_for_final_response(self):
        response = MagicMock(status_code=429, headers={})
        http_response = requests.Response()
        http_response.status_code = 429
        response.raise_for_status.side_effect = requests.HTTPError("secret", response=http_response)
        with patch("discord_bot.functions.get_webpage_contents.requests.Session", return_value=self.session(response)):
            with self.assertRaises(ValueError) as raised:
                fetch_public_html("https://example.org/private?secret")
        self.assertEqual(raised.exception.code, "HTTP_ERROR")
        self.assertEqual(raised.exception.http_status, 429)

    def test_stream_timeout_retains_received_http_status(self):
        response = MagicMock(status_code=200, headers={"Content-Type": "text/html"})
        response.iter_content.side_effect = requests.ConnectionError(ReadTimeoutError(None, "/secret", "timed out"))
        with patch("discord_bot.functions.get_webpage_contents.requests.Session", return_value=self.session(response)):
            with self.assertRaises(ValueError) as raised:
                fetch_public_html("https://example.org/")
        self.assertEqual(raised.exception.code, "TIMEOUT")
        self.assertEqual(raised.exception.http_status, 200)

    def test_connect_timeout_is_preserved(self):
        conn = PublicHTTPSConnection("example.org", port=443, timeout=5)
        with patch("discord_bot.functions.get_webpage_contents.connection.create_connection", side_effect=socket.timeout()):
            with self.assertRaises(ConnectTimeoutError):
                conn._new_conn()
