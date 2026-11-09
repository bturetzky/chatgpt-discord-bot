"""Bounded YouTube reader tests; provider and network are mocked."""
import json
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import requests

from discord_bot.functions.read_youtube import (
    BoundedYouTubeSession, MAX_REQUESTS, MAX_RESPONSE_BYTES, MAX_SEGMENTS, MAX_TRANSCRIPT_CHARS,
    ReadYouTube, _read_youtube,
)
from discord_bot.handlers.chatgpt_handler import ChatGPTHandler
from tests.test_responses_api import text_response
from tests.test_tool_regressions import response, tool_call

VIDEO_ID = "jNQXAC9IVRw"


class Fetched(list):
    language_code = "en"
    is_generated = False


def mock_session(title="Test video", watch_html=None):
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = None
    session.watch_html = watch_html
    session.get.return_value.json.return_value = {"title": title, "author_name": "Creator"}
    return session


def mock_provider(snippets):
    provider = MagicMock()
    selected = provider.return_value.list.return_value.find_transcript.return_value
    selected.fetch.return_value = Fetched(snippets)
    return provider


class YouTubeReaderTests(unittest.TestCase):
    def test_transcript_contains_timestamps_and_metadata(self):
        snippets = [SimpleNamespace(text="Hello there", start=12.5), SimpleNamespace(text="More", start=19)]
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", mock_provider(snippets)):
            result = _read_youtube(VIDEO_ID)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "transcript")
        self.assertEqual(result["transcript"], [{"start_seconds": 12.5, "text": "Hello there"}, {"start_seconds": 19.0, "text": "More"}])
        self.assertTrue(result["transcript_available"])
        self.assertEqual(result["url"], "https://www.youtube.com/watch?v=" + VIDEO_ID)
        self.assertIn("untrusted", result["limitations"][-1])

    def test_captions_unavailable_returns_metadata_not_claimed_video_content(self):
        provider = MagicMock()
        provider.return_value.list.side_effect = RuntimeError("secret query and transcript")
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", provider), self.assertLogs(level="INFO") as logs:
            result = _read_youtube(VIDEO_ID)
        self.assertEqual(result["source"], "metadata")
        self.assertFalse(result["transcript_available"])
        self.assertEqual(result["transcript"], [])
        self.assertIn("not read", result["limitations"][0])
        self.assertNotIn("secret", str(logs.output))

    def test_empty_captions_are_not_marked_available(self):
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", mock_provider([])):
            result = _read_youtube(VIDEO_ID)
        self.assertFalse(result["transcript_available"])
        self.assertIn("No usable caption", result["limitations"][0])

    def test_caption_segments_are_bounded(self):
        snippets = [SimpleNamespace(text="x", start=n) for n in range(MAX_SEGMENTS + 1)]
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", mock_provider(snippets)):
            result = _read_youtube(VIDEO_ID)
        self.assertEqual(len(result["transcript"]), MAX_SEGMENTS)
        self.assertTrue(result["content_truncated"])

    def test_long_first_segment_is_truncated_not_discarded(self):
        snippets = [SimpleNamespace(text="x" * (MAX_TRANSCRIPT_CHARS + 1), start=0)]
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", mock_provider(snippets)):
            result = _read_youtube(VIDEO_ID)
        self.assertTrue(result["transcript_available"])
        self.assertTrue(result["content_truncated"])
        self.assertEqual(len(result["transcript"][0]["text"]), MAX_TRANSCRIPT_CHARS)

    def test_failed_caption_parsing_never_returns_partial_transcript_as_unavailable(self):
        snippets = [SimpleNamespace(text="partial", start=1), SimpleNamespace(text="broken", start="bad")]
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", mock_provider(snippets)):
            result = _read_youtube(VIDEO_ID)
        self.assertFalse(result["transcript_available"])
        self.assertEqual(result["transcript"], [])

    def test_non_english_caption_fallback(self):
        from youtube_transcript_api._errors import NoTranscriptFound
        selected = MagicMock()
        fetched = Fetched([SimpleNamespace(text="Hola", start=1)])
        fetched.language_code = "es"
        selected.fetch.return_value = fetched
        tracks = MagicMock()
        tracks.find_transcript.side_effect = NoTranscriptFound(VIDEO_ID, ["en"], tracks)
        tracks.__iter__.return_value = iter([selected])
        provider = MagicMock()
        provider.return_value.list.return_value = tracks
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", provider):
            result = _read_youtube(VIDEO_ID)
        self.assertTrue(result["transcript_available"])
        self.assertEqual(result["language"], "es")

    def test_description_fallback_must_match_video_id(self):
        player = {"videoDetails": {"videoId": VIDEO_ID, "shortDescription": "Video description"}}
        session = mock_session(watch_html=("ytInitialPlayerResponse = " + json.dumps(player)).encode())
        provider = MagicMock()
        provider.return_value.list.side_effect = RuntimeError("captions blocked")
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=session), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", provider):
            result = _read_youtube(VIDEO_ID)
        self.assertEqual(result["source"], "description")
        self.assertEqual(result["description"], "Video description")
        self.assertFalse(result["transcript_available"])
        player["videoDetails"]["videoId"] = "abcdefghijk"
        session.watch_html = ("ytInitialPlayerResponse = " + json.dumps(player)).encode()
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=session), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", provider):
            result = _read_youtube(VIDEO_ID)
        self.assertNotIn("description", result)

    def test_no_metadata_or_captions_is_failure(self):
        session = mock_session()
        session.get.side_effect = requests.Timeout()
        provider = MagicMock()
        provider.return_value.list.side_effect = RuntimeError()
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=session), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", provider):
            result = _read_youtube(VIDEO_ID)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CONTENT_UNAVAILABLE")


class YouTubeSecurityTests(unittest.TestCase):
    def test_rejects_other_hosts_ports_paths_and_redirects(self):
        session = BoundedYouTubeSession()
        for url in ["https://evil.test/oembed", "http://youtube.com/watch", "https://youtube.com:444/watch",
                    "https://user@youtube.com/watch", "https://youtube.com/private"]:
            with self.subTest(url=url), self.assertRaises(requests.RequestException):
                session.get(url)
        response = MagicMock(status_code=302, headers={})
        with patch("discord_bot.functions.read_youtube.validate_public_url"), \
             patch("requests.Session.request", return_value=response):
            with self.assertRaises(requests.RequestException):
                session.get("https://www.youtube.com/watch?v=" + VIDEO_ID)
        response.close.assert_called_once()

    def test_download_limit_and_request_count(self):
        session = BoundedYouTubeSession()
        response = MagicMock(status_code=200, headers={})
        response.iter_content.return_value = [b"x" * (MAX_RESPONSE_BYTES + 1)]
        with patch("discord_bot.functions.read_youtube.validate_public_url"), \
             patch("requests.Session.request", return_value=response):
            with self.assertRaises(requests.RequestException):
                session.get("https://www.youtube.com/watch?v=" + VIDEO_ID)
        session.request_count = MAX_REQUESTS
        with self.assertRaises(requests.RequestException):
            session.get("https://www.youtube.com/watch?v=" + VIDEO_ID)

    def test_request_log_filter_hides_signed_queries_at_debug(self):
        session = BoundedYouTubeSession()
        response = MagicMock(status_code=200, headers={})
        response.iter_content.return_value = [b"{}"]
        logger = logging.getLogger("urllib3.connectionpool")
        handler = logging.Handler()
        handler.emit = MagicMock()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        with patch.object(logger, "propagate", False), \
             patch("discord_bot.functions.read_youtube.validate_public_url"), \
             patch("requests.Session.request", side_effect=lambda *a, **kw: (logger.warning("signed-secret"), response)[1]):
            session.get("https://www.youtube.com/watch?v=" + VIDEO_ID)
            handler.emit.assert_not_called()
            logger.warning("outside request")
            handler.emit.assert_called_once()


class YouTubeToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_url_never_fetches(self):
        with patch("discord_bot.functions.read_youtube.read_youtube") as fetch:
            result = json.loads(await ReadYouTube().execute({"url": "https://youtube.com.evil.test/watch?v=" + VIDEO_ID}))
        self.assertFalse(result["ok"])
        fetch.assert_not_called()

    async def test_web_reader_routes_youtube_to_specialized_reader(self):
        from discord_bot.functions.get_webpage_contents import GetWebPageContents
        with patch("discord_bot.functions.get_webpage_contents.fetch_public_html") as fetch:
            result = json.loads(await GetWebPageContents().execute({"url": "https://youtu.be/" + VIDEO_ID}))
        self.assertEqual(result["error"]["code"], "USE_YOUTUBE_READER")
        fetch.assert_not_called()

    async def test_real_tool_result_is_returned_to_responses_api(self):
        with patch("discord_bot.handlers.function_handler.FunctionHandler.load_functions", return_value={"read_youtube": ReadYouTube}):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.client.responses.create = AsyncMock(side_effect=[response([
            tool_call("video", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw"}')]), text_response("The caption says hello.")])
        payload = {"ok": True, "url": "https://www.youtube.com/watch?v=" + VIDEO_ID, "source": "transcript",
                   "transcript_available": True, "content_truncated": False,
                   "transcript": [{"start_seconds": 2, "text": "Hello"}]}
        with patch("discord_bot.functions.read_youtube.read_youtube", return_value=payload):
            result = await handler.get_response([{"role": "user", "content": "What's in this video?"}], None)
        self.assertEqual(result, "The caption says hello.")
        request = handler.client.responses.create.await_args.kwargs
        output = next(item for item in request["input"] if item.get("type") == "function_call_output")
        self.assertEqual(json.loads(output["output"])["transcript"][0]["text"], "Hello")
        self.assertIn("cite timestamps", request["instructions"])

    async def test_tool_budget_is_shared_with_webpages(self):
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.function_handler.api_functions = []
        handler.function_handler.execute_function = AsyncMock(return_value="ok")
        handler.client.responses.create = AsyncMock(side_effect=[response([
            tool_call("1", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw"}'),
            tool_call("2", "get_webpage_contents", '{"url":"https://example.org/"}'),
            tool_call("3", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw"}')]), text_response("Done")])
        await handler.get_response([{"role": "user", "content": "Read links"}], None)
        self.assertEqual(handler.function_handler.execute_function.await_count, 2)
        sent = handler.client.responses.create.await_args.kwargs["input"]
        outputs = [item for item in sent if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual(json.loads(outputs[-1]["output"])["error"]["code"], "READ_LIMIT")
