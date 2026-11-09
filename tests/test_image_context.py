"""Discord image input ingestion without network calls or credentials."""
import asyncio
import base64
import io
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from PIL import Image

from discord_bot.handlers.image_context import (
    ImageContextBuilder, ImageFailure, MAX_IMAGE_BYTES, attachment_url_allowed, validate_image,
)
from discord_bot.handlers.chatgpt_handler import ChatGPTHandler
from tests.test_reliability import make_handler, make_message
from tests.test_responses_api import text_response


def image_bytes(fmt="PNG"):
    out = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(out, format=fmt)
    return out.getvalue()


def attachment(data=None, mime="image/png", url="https://cdn.discordapp.com/attachments/1/2/image.png?sig=private"):
    data = data if data is not None else image_bytes()
    return SimpleNamespace(content_type=mime, size=len(data), url=url)


def message(attachments=(), reference=None):
    return SimpleNamespace(attachments=list(attachments), reference=reference,
                           channel=SimpleNamespace(id=12, fetch_message=AsyncMock()))


class ImageValidationTests(unittest.TestCase):
    def test_formats_decode_and_declared_type_must_match(self):
        for fmt, mime in [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]:
            with self.subTest(fmt=fmt):
                validate_image(image_bytes(fmt), mime, mime)
        with self.assertRaises(ImageFailure) as raised:
            validate_image(image_bytes("JPEG"), "image/png", "image/png")
        self.assertEqual(raised.exception.category, "type_mismatch")

    def test_truncated_or_forged_image_is_rejected(self):
        with self.assertRaises(ImageFailure):
            validate_image(b"\x89PNG\r\n\x1a\nnot an image", "image/png", "image/png")

    def test_only_https_discord_cdn_without_userinfo_is_allowed(self):
        self.assertTrue(attachment_url_allowed("https://cdn.discordapp.com/attachments/a/b/c?secret=1"))
        self.assertTrue(attachment_url_allowed("https://media.discordapp.net/attachments/a/b/c"))
        for url in ["http://cdn.discordapp.com/a", "https://cdn.discordapp.com.evil.test/a",
                    "https://user@cdn.discordapp.com/a", "https://127.0.0.1/a",
                    "https://cdn.discordapp.com:444/a", "https://evil.test/a"]:
            with self.subTest(url=url):
                self.assertFalse(attachment_url_allowed(url))


class ImageBuilderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.builder = ImageContextBuilder()

    async def test_current_and_reply_images_keep_source_and_order(self):
        first, second = attachment(), attachment(image_bytes("JPEG"), "image/jpeg")
        reply = SimpleNamespace(attachments=[second], author=SimpleNamespace(display_name="Alice"))
        ref = SimpleNamespace(resolved=reply, channel_id=12, message_id=55)
        msg = message([first], ref)
        self.builder.download = AsyncMock(side_effect=[(image_bytes(), "image/png"), (image_bytes("JPEG"), "image/jpeg")])
        result = await self.builder.build(msg)
        parts = result["content"]
        self.assertEqual([x["type"] for x in parts], ["input_text", "input_image", "input_text", "input_image"])
        self.assertIn("current message", parts[0]["text"])
        self.assertIn("Alice", parts[2]["text"])
        self.assertTrue(parts[1]["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(parts[1]["image_url"].split(",", 1)[1]), image_bytes())
        msg.channel.fetch_message.assert_not_awaited()

    async def test_unresolved_reply_is_fetched_once_and_not_recursive(self):
        ref = SimpleNamespace(resolved=None, channel_id=12, message_id=55)
        msg = message(reference=ref)
        msg.channel.fetch_message.return_value = SimpleNamespace(attachments=[attachment()], author=SimpleNamespace(display_name="Sam"), reference=object())
        self.builder.download = AsyncMock(return_value=(image_bytes(), "image/png"))
        result = await self.builder.build(msg)
        msg.channel.fetch_message.assert_awaited_once_with(55)
        self.assertIn("Sam", result["content"][0]["text"])
        self.assertEqual(self.builder.download.await_count, 1)

    async def test_missing_reply_is_explicit_without_image(self):
        ref = SimpleNamespace(resolved=None, channel_id=12, message_id=55)
        msg = message(reference=ref)
        msg.channel.fetch_message.side_effect = RuntimeError("secret URL")
        result = await self.builder.build(msg)
        self.assertIn("reply_unavailable", result["content"][0]["text"])
        self.assertNotIn("secret", str(result))

    async def test_cross_channel_reply_is_not_fetched(self):
        ref = SimpleNamespace(resolved=None, channel_id=99, message_id=55)
        msg = message(reference=ref)
        result = await self.builder.build(msg)
        self.assertIn("reply_unavailable", result["content"][0]["text"])
        msg.channel.fetch_message.assert_not_awaited()

    async def test_no_images_preserves_text_only_path(self):
        self.assertIsNone(await self.builder.build(message()))

    async def test_more_than_two_is_bounded_and_disclosed(self):
        self.builder.download = AsyncMock(return_value=(image_bytes(), "image/png"))
        result = await self.builder.build(message([attachment(), attachment(), attachment()]))
        self.assertEqual(self.builder.download.await_count, 2)
        self.assertIn("image_limit", result["content"][-1]["text"])

    async def test_unsupported_files_do_not_displace_two_images(self):
        self.builder.download = AsyncMock(return_value=(image_bytes(), "image/png"))
        result = await self.builder.build(message([attachment(mime="application/pdf"), attachment(), attachment()]))
        self.assertEqual(self.builder.download.await_count, 2)
        self.assertEqual(sum(part["type"] == "input_image" for part in result["content"]), 2)
        self.assertIn("unsupported_type", result["content"][-1]["text"])
        self.assertNotIn("image_limit", result["content"][-1]["text"])

    async def test_unsupported_current_files_do_not_displace_reply_image(self):
        reply = SimpleNamespace(attachments=[attachment()], author=SimpleNamespace(display_name="Sam"))
        ref = SimpleNamespace(resolved=reply, channel_id=12, message_id=55)
        self.builder.download = AsyncMock(return_value=(image_bytes(), "image/png"))
        result = await self.builder.build(message([attachment(mime="application/pdf"), attachment()], ref))
        self.assertEqual(self.builder.download.await_count, 2)
        self.assertIn("Sam", result["content"][2]["text"])

    async def test_failed_image_is_not_sent_and_logs_no_url_or_data(self):
        self.builder.download = AsyncMock(side_effect=ImageFailure("download_unavailable"))
        with self.assertLogs(level="INFO") as logs:
            result = await self.builder.build(message([attachment()]))
        self.assertNotIn("input_image", str(result))
        self.assertIn("download_unavailable", result["content"][0]["text"])
        self.assertNotIn("secret", str(logs.output))
        self.assertNotIn("cdn.discordapp", str(logs.output))
        self.assertNotIn("base64", str(logs.output))

    async def test_unsupported_and_oversized_rejected_before_network(self):
        unsupported = attachment(mime="application/pdf")
        oversized = attachment(); oversized.size = MAX_IMAGE_BYTES + 1
        for a, category in [(unsupported, "unsupported_type"), (oversized, "size_limit")]:
            with self.subTest(category=category), patch("discord_bot.handlers.image_context.aiohttp.ClientSession") as session:
                with self.assertRaises(ImageFailure) as raised:
                    await self.builder.download(a, MAX_IMAGE_BYTES)
                self.assertEqual(raised.exception.category, category)
                session.assert_not_called()

    async def test_stream_size_and_redirect_are_bounded(self):
        for status, chunks, category in [(302, [], "download_unavailable"), (200, [b'x' * (MAX_IMAGE_BYTES + 1)], "size_limit")]:
            response = MagicMock(status=status, headers={"Content-Type": "image/png"})
            response.__aenter__ = AsyncMock(return_value=response)
            response.__aexit__ = AsyncMock(return_value=None)
            async def stream(_size):
                for chunk in chunks:
                    yield chunk
            response.content.iter_chunked = stream
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.get.return_value = response
            with self.subTest(category=category), patch("discord_bot.handlers.image_context.aiohttp.ClientSession", return_value=session):
                with self.assertRaises(ImageFailure) as raised:
                    await self.builder.download(attachment(), MAX_IMAGE_BYTES)
                self.assertEqual(raised.exception.category, category)
                self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
                self.assertEqual(session.get.call_args.kwargs["headers"], {"Accept-Encoding": "identity"})

    async def test_download_error_is_categorized_without_exception_text(self):
        session = MagicMock()
        session.__aenter__ = AsyncMock(side_effect=aiohttp.ClientConnectionError("private URL"))
        session.__aexit__ = AsyncMock(return_value=None)
        with patch("discord_bot.handlers.image_context.aiohttp.ClientSession", return_value=session):
            with self.assertRaises(ImageFailure) as raised:
                await self.builder.download(attachment(), MAX_IMAGE_BYTES)
        self.assertEqual(raised.exception.category, "download_error")
        self.assertNotIn("private", str(raised.exception))

    async def test_successful_download_verifies_mime_and_decodes(self):
        response = MagicMock(status=200, headers={"Content-Type": "image/png"})
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        async def stream(_size):
            yield image_bytes()
        response.content.iter_chunked = stream
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.get.return_value = response
        with patch("discord_bot.handlers.image_context.aiohttp.ClientSession", return_value=session) as factory:
            data, mime = await self.builder.download(attachment(), MAX_IMAGE_BYTES)
        self.assertEqual(data, image_bytes())
        self.assertEqual(mime, "image/png")
        self.assertFalse(factory.call_args.kwargs["trust_env"])
        self.assertFalse(factory.call_args.kwargs["auto_decompress"])
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    async def test_timeout_reports_failure(self):
        session = MagicMock()
        session.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        session.__aexit__ = AsyncMock(return_value=None)
        with patch("discord_bot.handlers.image_context.aiohttp.ClientSession", return_value=session):
            with self.assertRaises(ImageFailure) as raised:
                await self.builder.download(attachment(), MAX_IMAGE_BYTES)
        self.assertEqual(raised.exception.category, "timeout")

    async def test_compressed_http_response_is_rejected(self):
        response = MagicMock(status=200, headers={"Content-Type": "image/png", "Content-Encoding": "gzip"})
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.get.return_value = response
        with patch("discord_bot.handlers.image_context.aiohttp.ClientSession", return_value=session):
            with self.assertRaises(ImageFailure) as raised:
                await self.builder.download(attachment(), MAX_IMAGE_BYTES)
        self.assertEqual(raised.exception.category, "unsupported_encoding")

    async def test_concurrent_downloads_do_not_exceed_two(self):
        active = 0
        peak = 0

        class Response:
            status = 200
            headers = {"Content-Type": "image/png"}
            content = None

            async def __aenter__(self):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                self.content = self
                return self

            async def __aexit__(self, *args):
                nonlocal active
                active -= 1

            async def iter_chunked(self, _size):
                await asyncio.sleep(0.01)
                yield image_bytes()

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def get(self, *args, **kwargs):
                return Response()

        with patch("discord_bot.handlers.image_context.aiohttp.ClientSession", side_effect=lambda **kwargs: Session()):
            await asyncio.gather(*(self.builder.download(attachment(), MAX_IMAGE_BYTES) for _ in range(3)))
        self.assertEqual(peak, 2)

    async def test_cancelled_decode_keeps_permit_until_worker_finishes(self):
        started, release = threading.Event(), threading.Event()

        def blocked_decode(*args):
            started.set()
            release.wait(3)

        class Response:
            status = 200
            headers = {"Content-Type": "image/png"}
            content = None

            async def __aenter__(self):
                self.content = self
                return self

            async def __aexit__(self, *args):
                pass

            async def iter_chunked(self, _size):
                yield image_bytes()

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def get(self, *args, **kwargs):
                return Response()

        with patch("discord_bot.handlers.image_context.aiohttp.ClientSession", side_effect=lambda **kwargs: Session()), \
             patch("discord_bot.handlers.image_context.validate_image", side_effect=blocked_decode):
            task = asyncio.create_task(self.builder.download(attachment(), MAX_IMAGE_BYTES))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(self.builder.semaphore._value, 1)
            finally:
                release.set()
            for _ in range(100):
                if self.builder.semaphore._value == 2:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(self.builder.semaphore._value, 2)


class DiscordImageRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_unmentioned_messages_do_not_ingest_images(self):
        handler, msg = make_handler(), make_message()
        handler.client.user.mentioned_in.return_value = False
        handler.image_context_builder = MagicMock()
        handler.image_context_builder.build = AsyncMock()
        msg.attachments = [attachment()]
        await handler.process_message(msg)
        handler.image_context_builder.build.assert_not_awaited()

    async def test_mentioned_message_appends_images_after_text_memory_query(self):
        handler, msg = make_handler(), make_message()
        msg.attachments = [attachment()]
        handler.image_context_builder = MagicMock()
        content = {"role": "user", "content": [{"type": "input_text", "text": "Image attached to current message."},
                                                 {"type": "input_image", "image_url": "data:image/png;base64,abc", "detail": "auto"}]}
        handler.image_context_builder.build = AsyncMock(return_value=content)
        handler.vector_handler.get_relevant_contexts.return_value = []
        handler.vector_handler.get_relationship_contexts.return_value = []
        with patch("discord_bot.handlers.discord_handler.asyncio.sleep", new_callable=AsyncMock):
            await handler.process_message(msg)
        messages = handler.chatgpt_handler.get_response.await_args.args[0]
        self.assertEqual(messages[-1], content)
        handler.vector_handler.get_relevant_contexts.assert_called_once_with("hi")

    async def test_multimodal_message_reaches_responses_api(self):
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.client.responses.create = AsyncMock(return_value=text_response("A red image."))
        handler.function_handler.api_functions = []
        item = {"role": "user", "content": [{"type": "input_text", "text": "Current image"},
                                           {"type": "input_image", "image_url": "data:image/png;base64,YWJj", "detail": "auto"}]}
        history = [{"role": "user", "content": "What is this?"}, item]
        self.assertEqual(await handler.get_response(history, None), "A red image.")
        sent = handler.client.responses.create.await_args.kwargs
        self.assertEqual(sent["input"][:2], history)
        self.assertIn("Do not automatically save image", sent["instructions"])
