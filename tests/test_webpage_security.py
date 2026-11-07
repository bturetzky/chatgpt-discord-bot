"""Public URL and bounded HTTP fetch security regressions."""
import unittest
from unittest.mock import MagicMock, patch

from discord_bot.functions.get_webpage_contents import (
    MAX_BODY_BYTES, fetch_public_html, validate_public_url,
)


class PublicURLTests(unittest.TestCase):
    def test_blocks_internal_and_non_web_urls(self):
        blocked = [
            "file:///etc/passwd", "http://localhost/", "http://localhost./",
            "http://127.0.0.1/", "http://10.0.0.1/", "http://192.168.13.13/",
            "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
            "http://[fc00::1]/", "http://user:pass@example.org/",
            "http://example.local/", "http://example.org:8080/",
            "http://0.0.0.0/", "http://224.0.0.1/",
        ]
        for url in blocked:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_url(url)

    def test_rejects_dns_with_mixed_public_and_private_results(self):
        with patch("discord_bot.functions.get_webpage_contents.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("93.184.215.14", 443)),
            (2, 1, 6, "", ("192.168.13.13", 443)),
        ]):
            with self.assertRaises(ValueError):
                validate_public_url("https://example.org/")

    def test_accepts_public_https(self):
        with patch("discord_bot.functions.get_webpage_contents.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("93.184.215.14", 443)),
        ]):
            self.assertEqual(validate_public_url("https://example.org/path"), "https://example.org/path")


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch("discord_bot.functions.get_webpage_contents.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("93.184.215.14", 443)),
        ])
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def session(self, responses):
        session = MagicMock()
        session.__enter__.return_value = session
        session.__exit__.return_value = None
        session.get.side_effect = responses
        for response in responses:
            response.__enter__.return_value = response
            response.__exit__.return_value = None
        return session

    def test_public_html_is_streamed(self):
        response = MagicMock(status_code=200, headers={"Content-Type": "text/html; charset=utf-8"})
        response.iter_content.return_value = [b"<p>ok</p>"]
        session = self.session([response])
        with patch("discord_bot.functions.get_webpage_contents.requests.Session", return_value=session):
            self.assertEqual(fetch_public_html("https://example.org/"), b"<p>ok</p>")
        self.assertFalse(session.trust_env)
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
        self.assertTrue(session.get.call_args.kwargs["stream"])

    def test_redirect_to_private_ip_is_blocked(self):
        redirect = MagicMock(status_code=302, headers={"Location": "http://127.0.0.1/admin"})
        session = self.session([redirect])
        with patch("discord_bot.functions.get_webpage_contents.requests.Session", return_value=session):
            with self.assertRaises(ValueError):
                fetch_public_html("https://example.org/")
        session.get.assert_called_once()

    def test_redirect_loop_is_bounded(self):
        responses = [MagicMock(status_code=302, headers={"Location": "/again"}) for _ in range(4)]
        session = self.session(responses)
        with patch("discord_bot.functions.get_webpage_contents.requests.Session", return_value=session):
            with self.assertRaisesRegex(ValueError, "Too many redirects"):
                fetch_public_html("https://example.org/")
        self.assertEqual(session.get.call_count, 4)

    def test_rejects_non_html(self):
        response = MagicMock(status_code=200, headers={"Content-Type": "application/json"})
        session = self.session([response])
        with patch("discord_bot.functions.get_webpage_contents.requests.Session", return_value=session):
            with self.assertRaisesRegex(ValueError, "Only HTML"):
                fetch_public_html("https://example.org/")

    def test_rejects_oversized_body(self):
        response = MagicMock(status_code=200, headers={"Content-Type": "text/html"})
        response.iter_content.return_value = [b"x" * (MAX_BODY_BYTES + 1)]
        session = self.session([response])
        with patch("discord_bot.functions.get_webpage_contents.requests.Session", return_value=session):
            with self.assertRaisesRegex(ValueError, "size limit"):
                fetch_public_html("https://example.org/")


if __name__ == "__main__":
    unittest.main()
