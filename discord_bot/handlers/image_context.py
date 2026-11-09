"""Bounded, in-memory Discord attachment ingestion for one response."""
import asyncio
import base64
import io
import logging
import time
from urllib.parse import urlsplit

import aiohttp
from PIL import Image, UnidentifiedImageError

MAX_IMAGES = 2
MAX_ATTACHMENTS_INSPECTED = 20
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
DOWNLOAD_TIMEOUT = 10
REPLY_TIMEOUT = 5
MIME_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
CDN_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}


class ImageFailure(Exception):
    def __init__(self, category):
        self.category = category


def attachment_url_allowed(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in CDN_HOSTS
                and parsed.username is None and parsed.password is None
                and parsed.port in (None, 443))
    except (TypeError, ValueError):
        return False


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
        declared = (getattr(attachment, "content_type", None) or "").split(";", 1)[0].lower().strip()
        size = getattr(attachment, "size", None)
        if declared not in MIME_FORMATS:
            raise ImageFailure("unsupported_type")
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
                        response_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
                        if response_type != declared:
                            raise ImageFailure("unsupported_type")
                        if response.headers.get("Content-Encoding", "identity").lower().strip() not in ("", "identity"):
                            raise ImageFailure("unsupported_encoding")
                        data = bytearray()
                        async for chunk in response.content.iter_chunked(65536):
                            data.extend(chunk)
                            if len(data) > min(MAX_IMAGE_BYTES, remaining):
                                raise ImageFailure("size_limit")
                if not data:
                    raise ImageFailure("invalid_image")
                worker = asyncio.create_task(asyncio.to_thread(validate_image, bytes(data), declared, response_type))
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
                return bytes(data), declared
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
        candidates = [(a, "the current message") for a in (getattr(message, "attachments", None) or [])]
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
                    candidates.extend((a, f"the replied-to message from {author}") for a in (resolved.attachments or []))
                elif resolved is not None:
                    failures.append("reply_unavailable")
        if not candidates and not failures:
            return None
        if len(candidates) > MAX_ATTACHMENTS_INSPECTED:
            failures.append("attachment_limit")
        images = []
        for attachment, source in candidates[:MAX_ATTACHMENTS_INSPECTED]:
            mime = (getattr(attachment, "content_type", None) or "").split(";", 1)[0].lower().strip()
            if mime not in MIME_FORMATS:
                failures.append("unsupported_type")
            elif len(images) < MAX_IMAGES:
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
                parts.extend([{"type": "input_text", "text": f"Image attached to {source}."},
                              {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "auto"}])
            except ImageFailure as exc:
                failures.append(exc.category)
        if failures:
            parts.append({"type": "input_text", "text": "Some attached or referenced images could not be provided. Do not claim to have seen them. Failure categories: " + ", ".join(failures) + "."})
        logging.info("Image ingestion: count=%d bytes=%d elapsed_ms=%d failures=%s", count, total,
                     int((time.monotonic() - started) * 1000), ",".join(failures) or "none")
        return {"role": "user", "content": parts}
