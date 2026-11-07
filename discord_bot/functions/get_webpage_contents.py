"""Fetch public web pages only; reject internal addresses and oversized responses."""
import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .base import BaseFunction

MAX_REDIRECTS = 3
MAX_BODY_BYTES = 1_000_000
ALLOWED_TYPES = ("text/html", "application/xhtml+xml")


def validate_public_url(url):
    """Reject non-web URLs, credentials, internal names and non-global DNS results."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Only public HTTP(S) URLs are allowed")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Credentials in URLs are not allowed")
        hostname = parsed.hostname.rstrip(".")
        if not hostname or hostname.lower() == "localhost" or hostname.lower().endswith((".localhost", ".local", ".internal")):
            raise ValueError("Internal hostnames are not allowed")
        port = parsed.port  # Raises ValueError for invalid ports.
        if port is not None and port not in (80, 443):
            raise ValueError("Only standard HTTP(S) ports are allowed")
        if parsed.fragment:
            # Fragments are not sent over HTTP; normalize away rather than reject.
            url = url.split("#", 1)[0]
        try:
            addresses = [ipaddress.ip_address(hostname)]
        except ValueError:
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(hostname, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            ]
        if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
            raise ValueError("Private, reserved or non-global addresses are not allowed")
        return url
    except (socket.gaierror, UnicodeError, OverflowError) as exc:
        raise ValueError("Unable to resolve a public hostname") from exc


def fetch_public_html(url):
    """Validate every redirect; disable ambient proxy configuration and stream with a cap."""
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(MAX_REDIRECTS + 1):
            url = validate_public_url(url)
            with session.get(url, timeout=(5, 10), allow_redirects=False, stream=True) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Redirect missing Location")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type not in ALLOWED_TYPES:
                    raise ValueError("Only HTML pages are supported")
                body = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise ValueError("Webpage exceeds the download size limit")
                return bytes(body)
        raise ValueError("Too many redirects")


class GetWebPageContents(BaseFunction):
    name = "get_webpage_contents"
    description = "Fetches public HTML webpage content for summarization. Internal URLs and non-HTML resources are blocked."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "A public HTTP(S) webpage URL."}
        },
        "required": ["url"]
    }

    @staticmethod
    def score_tag(tag):
        return (
            len(tag.find_all("p", recursive=False))
            + len(tag.find_all(["ul", "ol"], recursive=False)) * 2
            + len(tag.find_all("li", recursive=False))
        )

    async def execute(self, args):
        url = args.get("url")
        if not url:
            return "You need to provide a URL."
        try:
            content = await asyncio.to_thread(fetch_public_html, url)
            soup = BeautifulSoup(content, "lxml")
            for tag in soup.find_all(["script", "style", "footer"]):
                tag.decompose()
            main = max(soup.find_all(["div", "article"]), key=self.score_tag, default=soup)
            text = main.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = "\n".join(chunk for chunk in chunks if chunk)
            return text[:4000] + "..." if len(text) > 4000 else text
        except (requests.RequestException, ValueError) as exc:
            return f"Error fetching the webpage: {exc}"
