"""Bounded, in-memory Discord image ingestion for one response."""
import asyncio
import base64
import io
import logging
import time
from collections import Counter
from dataclasses import dataclass
from itertools import islice
from pathlib import PurePath
from urllib.parse import urlsplit

import aiohttp
from PIL import Image, UnidentifiedImageError

MAX_IMAGES = 2
MAX_MEDIA_INSPECTED = 20
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
DOWNLOAD_TIMEOUT = 10
REPLY_TIMEOUT = 5
MIME_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
IMAGE_EXTENSIONS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
GENERIC_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
CDN_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}


class ImageFailure(Exception):
    def __init__(self, category):
        self.category = category


@dataclass(frozen=True)
class EmbedImage:
    url: str


def normalized_mime(value):
    return (value or "").split(";", 1)[0].lower().strip()


def attachment_extension_mime(attachment):
    return IMAGE_EXTENSIONS.get(PurePath(getattr(attachment, "filename", "") or "").suffix.lower())


def attachment_url_allowed(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in CDN_HOSTS
                and parsed.username is None and parsed.password is None
                and parsed.port in (None, 443))
    except (TypeError, ValueError):
        return False


def message_media(message, source):
    for attachment in getattr(message, "attachments", None) or ():
        yield attachment, source
    for embed in getattr(message, "embeds", None) or ():
        image = getattr(embed, "image", None)
        direct_url = getattr(image, "url", None)
        proxy_url = getattr(image, "proxy_url", None)
        if not (direct_url or proxy_url) and getattr(embed, "type", None) == "image":
            thumbnail = getattr(embed, "thumbnail", None)
            direct_url = getattr(thumbnail, "url", None) or getattr(embed, "url", None)
            proxy_url = getattr(thumbnail, "proxy_url", None)
        url = proxy_url if attachment_url_allowed(proxy_url) else direct_url or proxy_url
        yield EmbedImage(url) if url else None, source


def validate_image(data, declared_type, response_type):
    """Fully decode one supported still image within a pixel budget."""
    if declared_type not in MIME_FORMATS or response_type != declared_type:
        raise ImageFailure("unsupported_type")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != MIME_FORMATS[declared_type]:
                raise ImageFailure("type_mismatch")
            if image.width * image.height > MAX_PIXELS or getattr(image, "is_animated", False):
                raise ImageFailure("image_limits")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except ImageFailure:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise ImageFailure("invalid_image") from None


class ImageContextBuilder:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(2)

    async def download(self, attachment, remaining):
        is_embed = isinstance(attachment, EmbedImage)
        expected = None
        extension_mime = None
        if not is_embed:
            declared = normalized_mime(getattr(attachment, "content_type", None))
            extension_mime = attachment_extension_mime(attachment)
            expected = extension_mime if declared in GENERIC_TYPES else declared
            if expected not in MIME_FORMATS:
                raise ImageFailure("unsupported_type")
            size = getattr(attachment, "size", None)
            if not isinstance(size, int) or size <= 0 or size > MAX_IMAGE_BYTES or size > remaining:
                raise ImageFailure("size_limit")
        url = getattr(attachment, "url", None)
        if not attachment_url_allowed(url):
            raise ImageFailure("invalid_url")
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=DOWNLOAD_TIMEOUT)
            release_deferred = False
            try:
                timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT)
                async with aiohttp.ClientSession(timeout=timeout, trust_env=False, auto_decompress=False) as session:
                    async with session.get(url, allow_redirects=False, headers={"Accept-Encoding": "identity"}) as response:
                        if response.status != 200:
                            raise ImageFailure("download_unavailable")
                        response_type = normalized_mime(response.headers.get("Content-Type"))
                        if not is_embed and response_type in GENERIC_TYPES:
                            response_type = expected
                        if response_type not in MIME_FORMATS:
                            raise ImageFailure("cdn_unsupported_type")
                        # Discord's declared format can disagree with the original upload.
                        # Only accept the CDN's alternate format when the extension agrees.
                        if expected is not None and response_type not in (expected, extension_mime):
                            raise ImageFailure("cdn_mime_mismatch")
                        if response.headers.get("Content-Encoding", "identity").lower().strip() not in ("", "identity"):
                            raise ImageFailure("unsupported_encoding")
                        data = bytearray()
                        async for chunk in response.content.iter_chunked(65536):
                            data.extend(chunk)
                            if len(data) > min(MAX_IMAGE_BYTES, remaining):
                                raise ImageFailure("size_limit")
                if not data:
                    raise ImageFailure("invalid_image")
                worker = asyncio.create_task(asyncio.to_thread(validate_image, bytes(data), response_type, response_type))
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    # A cancelled await cannot stop a decoder thread. Keep the permit
                    # until it exits, even if the request no longer has a waiter.
                    release_deferred = True
                    def release_after_decode(task):
                        try:
                            if not task.cancelled():
                                task.exception()
                        finally:
                            self.semaphore.release()
                    worker.add_done_callback(release_after_decode)
                    raise
                return bytes(data), response_type
            finally:
                if not release_deferred:
                    self.semaphore.release()
        except ImageFailure:
            raise
        except asyncio.TimeoutError:
            raise ImageFailure("timeout") from None
        except (aiohttp.ClientError, OSError):
            raise ImageFailure("download_error") from None

    async def build(self, message):
        """Only inspect this message and its direct reply; return Responses content."""
        started = time.monotonic()
        failures = []
        candidates = list(islice(message_media(message, "the current message"), MAX_MEDIA_INSPECTED + 1))
        reference = getattr(message, "reference", None)
        if reference is not None:
            resolved = getattr(reference, "resolved", None)
            ref_channel_id = getattr(reference, "channel_id", None)
            if ref_channel_id is not None and ref_channel_id != getattr(message.channel, "id", None):
                failures.append("reply_unavailable")
            else:
                if resolved is None and getattr(reference, "message_id", None):
                    try:
                        resolved = await asyncio.wait_for(message.channel.fetch_message(reference.message_id), REPLY_TIMEOUT)
                    except (Exception, asyncio.TimeoutError):
                        failures.append("reply_unavailable")
                if resolved is not None and hasattr(resolved, "attachments"):
                    author = getattr(getattr(resolved, "author", None), "display_name", "another user")
                    candidates.extend(islice(message_media(resolved, f"the replied-to message from {author}"),
                                             MAX_MEDIA_INSPECTED + 1 - len(candidates)))
                elif resolved is not None:
                    failures.append("reply_unavailable")
        if len(candidates) > MAX_MEDIA_INSPECTED:
            failures.append("media_limit")
        images = []
        attachment_metadata = Counter()
        for attachment, source in candidates[:MAX_MEDIA_INSPECTED]:
            if attachment is None:
                continue
            if isinstance(attachment, EmbedImage):
                if not attachment_url_allowed(attachment.url):
                    failures.append("invalid_url")
                    continue
            else:
                declared = normalized_mime(getattr(attachment, "content_type", None))
                extension_mime = attachment_extension_mime(attachment)
                if not declared:
                    category = "missing"
                elif declared in GENERIC_TYPES:
                    category = "generic"
                elif declared in MIME_FORMATS:
                    category = declared
                else:
                    category = "unsupported"
                attachment_metadata[(category, extension_mime is not None)] += 1
                expected = extension_mime if declared in GENERIC_TYPES else declared
                if expected not in MIME_FORMATS:
                    failures.append("unsupported_type")
                    continue
            if len(images) < MAX_IMAGES:
                images.append((attachment, source))
            elif "image_limit" not in failures:
                failures.append("image_limit")
        parts = []
        total = 0
        count = 0
        for attachment, source in images:
            try:
                data, mime = await self.download(attachment, MAX_TOTAL_BYTES - total)
                total += len(data)
                count += 1
                encoded = base64.b64encode(data).decode("ascii")
                parts.extend([{"type": "input_text", "text": f"Image from {source}."},
                              {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "auto"}])
            except ImageFailure as exc:
                failures.append(exc.category)
        if failures:
            parts.append({"type": "input_text", "text": "Some images could not be provided. Do not claim to have seen them. Failure categories: " + ", ".join(failures) + "."})
        if not parts:
            return None
        metadata = ",".join(
            f"{category}/recognized_extension={str(recognized).lower()}:{occurrences}"
            for (category, recognized), occurrences in sorted(attachment_metadata.items())
        )
        logging.info("Image ingestion: count=%d bytes=%d elapsed_ms=%d failures=%s attachment_mime=%s",
                     count, total, int((time.monotonic() - started) * 1000),
                     ",".join(failures) or "none", metadata or "none")
        return {"role": "user", "content": parts}
