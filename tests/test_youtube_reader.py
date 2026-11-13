"""Bounded YouTube reader tests; provider and network are mocked."""
import json
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import requests

from discord_bot.functions.read_youtube import (
    BoundedYouTubeSession, MAX_REQUESTS, MAX_RESPONSE_BYTES, MAX_SEGMENTS, MAX_SECTIONS, MAX_TRANSCRIPT_CHARS,
    ReadYouTube, _read_youtube, select_transcript_sections, validate_read_options,
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
        snippets = [SimpleNamespace(text="x", start=n) for n in range(MAX_SEGMENTS * MAX_SECTIONS + 1)]
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", mock_provider(snippets)):
            result = _read_youtube(VIDEO_ID)
        self.assertEqual(len(result["transcript"]), MAX_SEGMENTS * MAX_SECTIONS)
        self.assertEqual(len(result["sections"]), MAX_SECTIONS)
        self.assertTrue(result["content_truncated"])
        self.assertEqual(result["next_cursor"]["segment_index"], MAX_SEGMENTS * MAX_SECTIONS)

    def test_long_first_segment_is_truncated_not_discarded(self):
        snippets = [SimpleNamespace(text="x" * (MAX_TRANSCRIPT_CHARS + 1), start=0)]
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", mock_provider(snippets)):
            result = _read_youtube(VIDEO_ID)
        self.assertTrue(result["transcript_available"])
        self.assertFalse(result["content_truncated"])
        self.assertEqual(len(result["sections"]), 2)
        self.assertEqual("".join(item["text"] for item in result["transcript"]), snippets[0].text)

    def test_timestamp_range_includes_overlapping_caption_and_stops_at_end(self):
        snippets = Fetched([SimpleNamespace(text="before", start=10, duration=5),
                            SimpleNamespace(text="overlap", start=18, duration=4),
                            SimpleNamespace(text="inside", start=25, duration=2),
                            SimpleNamespace(text="after", start=30, duration=3)])
        entries, sections, cursor = select_transcript_sections(snippets, start_seconds=20, end_seconds=30)
        self.assertEqual([entry["text"] for entry in entries], ["overlap", "inside"])
        self.assertEqual(sections[0]["start_seconds"], 18)
        self.assertIsNone(cursor)

    def test_range_after_caption_track_is_not_reported_as_missing_captions(self):
        provider = mock_provider([SimpleNamespace(text="first", start=10, duration=3)])
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", return_value=mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", provider):
            result = _read_youtube(VIDEO_ID, start_seconds=500)
        self.assertTrue(result["transcript_available"])
        self.assertTrue(result["range_empty"])
        self.assertFalse(result["content_truncated"])
        self.assertEqual(result["transcript"], [])

    def test_continuation_has_no_gaps_or_duplicates_for_split_segment(self):
        long_text = "a" * (MAX_TRANSCRIPT_CHARS * MAX_SECTIONS + 17)
        snippets = [SimpleNamespace(text=long_text, start=0), SimpleNamespace(text="last", start=20)]
        provider = mock_provider(snippets)
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", side_effect=lambda: mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", provider):
            first = _read_youtube(VIDEO_ID)
            second = _read_youtube(VIDEO_ID, cursor=first["next_cursor"])
        self.assertTrue(first["content_truncated"])
        self.assertFalse(second["content_truncated"])
        combined = first["transcript"] + second["transcript"]
        self.assertEqual("".join(entry["text"] for entry in combined), long_text + "last")

    def test_changed_track_rejects_continuation(self):
        snippets = [SimpleNamespace(text="x", start=n) for n in range(MAX_SEGMENTS * MAX_SECTIONS + 1)]
        provider = mock_provider(snippets)
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", side_effect=lambda: mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", provider):
            first = _read_youtube(VIDEO_ID)
            snippets[-1].text = "changed"
            result = _read_youtube(VIDEO_ID, cursor=first["next_cursor"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_CURSOR")

    def test_cursor_preserves_range_and_rejects_modifications(self):
        cursor = {"segment_index": 200, "char_offset": 0, "track_hash": "a" * 64,
                  "range_start": 500.0, "range_end": 900.0}
        self.assertEqual(validate_read_options({"cursor": cursor}), (500.0, 900.0, cursor))
        with self.assertRaises(ValueError):
            validate_read_options({"cursor": cursor, "start_seconds": 100})

    def test_overlapping_captions_and_repeated_timestamps_are_not_lost_at_boundary(self):
        snippets = Fetched([SimpleNamespace(text=f"line {n}", start=500, duration=2)
                            for n in range(MAX_SECTIONS * MAX_SEGMENTS + 3)])
        first, _, cursor = select_transcript_sections(snippets, start_seconds=500)
        second, _, next_cursor = select_transcript_sections(snippets, start_seconds=500, cursor=cursor)
        self.assertIsNone(next_cursor)
        self.assertEqual([entry["text"] for entry in first + second], [snippet.text for snippet in snippets])

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
    async def test_timestamp_link_continues_at_820(self):
        payload = {"ok": True, "source": "transcript", "transcript_available": True,
                   "content_truncated": False, "sections": []}
        urls = ["https://www.youtube.com/watch?v=E_3W5t1B0bM&t=500s",
                r"https://www.youtube.com/watch?v=E_3W5t1B0bM\&t=500s"]
        for url in urls:
            with self.subTest(url=url), patch("discord_bot.functions.read_youtube.read_youtube", return_value=payload) as fetch:
                result = json.loads(await ReadYouTube().execute({"url": url}))
                self.assertTrue(result["ok"])
                fetch.assert_called_once_with("E_3W5t1B0bM", 500.0, None, None)

    async def test_timestamp_strings_and_invalid_times(self):
        payload = {"ok": True, "source": "transcript", "transcript_available": True,
                   "content_truncated": False, "sections": []}
        for raw in ("8:20", "8m20s", "500s", "500"):
            with self.subTest(raw=raw), patch("discord_bot.functions.read_youtube.read_youtube", return_value=payload) as fetch:
                result = json.loads(await ReadYouTube().execute({"url": "https://youtu.be/" + VIDEO_ID, "start_seconds": raw}))
                self.assertTrue(result["ok"])
                fetch.assert_called_once_with(VIDEO_ID, 500.0, None, None)
        for options in ({"start_seconds": "8:99"}, {"start_seconds": "secret"},
                        {"url": "https://youtu.be/" + VIDEO_ID + "?t=1s&start=2s"}):
            with self.subTest(options=options), patch("discord_bot.functions.read_youtube.read_youtube") as fetch, self.assertLogs(level="WARNING") as logs:
                result = json.loads(await ReadYouTube().execute({"url": "https://youtu.be/" + VIDEO_ID, **options}))
                self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
                self.assertNotIn("secret", str(logs.output))
                self.assertNotIn(VIDEO_ID, str(logs.output))
                fetch.assert_not_called()

    async def test_malformed_cursor_with_timestamp_is_rejected(self):
        for options in (
            {"start_seconds": 500, "cursor": {"segment_index": 200}},
            {"url": "https://youtu.be/" + VIDEO_ID + "?t=500s", "cursor": "invalid"},
        ):
            with self.subTest(options=options), patch("discord_bot.functions.read_youtube.read_youtube") as fetch:
                result = json.loads(await ReadYouTube().execute({"url": "https://youtu.be/" + VIDEO_ID, **options}))
                self.assertEqual(result["error"]["reason"], "CURSOR_SHAPE")
                fetch.assert_not_called()

    async def test_malformed_cursor_without_time_is_rejected_safely(self):
        with patch("discord_bot.functions.read_youtube.read_youtube") as fetch, self.assertLogs(level="WARNING") as logs:
            result = json.loads(await ReadYouTube().execute({"url": "https://youtu.be/" + VIDEO_ID, "cursor": {"secret": "private"}}))
        self.assertEqual(result["error"]["reason"], "CURSOR_SHAPE")
        self.assertIn("start_seconds", result["error"]["message"])
        self.assertNotIn("private", str(logs.output))
        self.assertNotIn(VIDEO_ID, str(logs.output))
        fetch.assert_not_called()
    async def test_invalid_ranges_are_rejected_before_fetch(self):
        cases = [
            {"start_seconds": -1}, {"start_seconds": True}, {"start_seconds": float("nan")},
            {"start_seconds": 10, "end_seconds": 10}, {"cursor": {"segment_index": -1}},
            {"cursor": {"segment_index": 0, "char_offset": 0, "track_hash": "bad", "range_start": None, "range_end": None}},
        ]
        for options in cases:
            with self.subTest(options=options), patch("discord_bot.functions.read_youtube.read_youtube") as fetch:
                result = json.loads(await ReadYouTube().execute({"url": "https://youtu.be/" + VIDEO_ID, **options}))
                self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
                fetch.assert_not_called()

    async def test_time_range_passed_to_reader(self):
        payload = {"ok": True, "source": "transcript", "transcript_available": True,
                   "content_truncated": False, "sections": []}
        with patch("discord_bot.functions.read_youtube.read_youtube", return_value=payload) as fetch:
            result = json.loads(await ReadYouTube().execute({"url": "https://youtu.be/" + VIDEO_ID,
                                                             "start_seconds": 500, "end_seconds": 560}))
        self.assertTrue(result["ok"])
        fetch.assert_called_once_with(VIDEO_ID, 500.0, 560.0, None)

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

    async def test_invalid_inputs_do_not_spend_youtube_read_budget(self):
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.function_handler.api_functions = []
        invalid_url = {"ok": False, "error": {"code": "INVALID_URL"}}
        success = {"ok": True, "source": "transcript", "transcript_available": True,
                   "content_truncated": False, "next_cursor": None, "transcript": [{"start_seconds": 500, "text": "Later."}]}
        handler.function_handler.execute_function = AsyncMock(side_effect=[json.dumps(invalid_url), json.dumps(success)])
        handler.client.responses.create = AsyncMock(side_effect=[
            response([tool_call("1", "read_youtube", '{"url":"bad"}')]),
            response([tool_call("2", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw", "cursor":{}}')]),
            response([tool_call("3", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw", "start_seconds":500}')]),
            text_response("Later in the video...")])
        result = await handler.get_response([{"role": "user", "content": "Try again after 8:20"}], None)
        self.assertEqual(result, "Later in the video...")
        self.assertEqual(handler.function_handler.execute_function.await_count, 2)
        outputs = [item for item in handler.client.responses.create.await_args.kwargs["input"]
                   if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertTrue(json.loads(outputs[-1]["output"])["ok"])

    async def test_retry_after_partial_answer_reaches_later_captions(self):
        with patch("discord_bot.handlers.function_handler.FunctionHandler.load_functions", return_value={"read_youtube": ReadYouTube}):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        video_url = "https://www.youtube.com/watch?v=E_3W5t1B0bM&t=500s"
        bad = json.dumps({"url": "https://www.youtube.com/watch?v=E_3W5t1B0bM", "cursor": {"segment_index": 200}})
        corrected = json.dumps({"url": video_url})
        handler.client.responses.create = AsyncMock(side_effect=[
            response([tool_call("bad", "read_youtube", bad)]),
            response([tool_call("corrected", "read_youtube", corrected)]),
            text_response("After 8:20, the captions say...")])
        later = {"ok": True, "source": "transcript", "transcript_available": True, "content_truncated": False,
                 "next_cursor": None, "sections": [], "transcript": [{"start_seconds": 501, "text": "later captions"}]}
        history = [{"role": "assistant", "content": "I could only read up to 8:20: " + video_url},
                   {"role": "user", "content": "Can you try again?"}]
        with patch("discord_bot.functions.read_youtube.read_youtube", return_value=later) as fetch:
            reply = await handler.get_response(history, None)
        self.assertIn("After 8:20", reply)
        fetch.assert_called_once_with("E_3W5t1B0bM", 500.0, None, None)
        outputs = [item for item in handler.client.responses.create.await_args.kwargs["input"]
                   if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual(json.loads(outputs[0]["output"])["error"]["code"], "INVALID_ARGUMENT")
        self.assertTrue(json.loads(outputs[1]["output"])["ok"])

    async def test_preflight_retries_are_bounded(self):
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.function_handler.api_functions = []
        handler.function_handler.execute_function = AsyncMock(return_value=json.dumps({"ok": False, "error": {"code": "INVALID_ARGUMENT"}}))
        calls = [response([tool_call(str(n), "read_youtube", '{"url":"bad"}')]) for n in range(4)]
        handler.client.responses.create = AsyncMock(side_effect=[*calls, text_response("Could not read")])
        await handler.get_response([{"role": "user", "content": "Try again"}], None)
        self.assertEqual(handler.function_handler.execute_function.await_count, 3)
        outputs = [item for item in handler.client.responses.create.await_args.kwargs["input"]
                   if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual(json.loads(outputs[-1]["output"])["error"]["code"], "VALIDATION_LIMIT")

    async def test_post_fetch_cursor_failures_still_spend_read_budget(self):
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.function_handler.api_functions = []
        handler.function_handler.execute_function = AsyncMock(return_value=json.dumps({"ok": False, "error": {"code": "INVALID_CURSOR"}}))
        calls = [response([tool_call(str(n), "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw"}')]) for n in range(3)]
        handler.client.responses.create = AsyncMock(side_effect=[*calls, text_response("Could not read")])
        await handler.get_response([{"role": "user", "content": "Try again"}], None)
        self.assertEqual(handler.function_handler.execute_function.await_count, 2)
        outputs = [item for item in handler.client.responses.create.await_args.kwargs["input"]
                   if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual(json.loads(outputs[-1]["output"])["error"]["code"], "READ_LIMIT")

    async def test_whole_video_automatically_continues_and_merges_sections(self):
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.function_handler.api_functions = []
        cursor = {"segment_index": 2, "char_offset": 0, "track_hash": "a" * 64, "range_start": None, "range_end": None}
        first = {"ok": True, "source": "transcript", "transcript_available": True, "content_truncated": True,
                 "next_cursor": cursor, "transcript": [{"start_seconds": 1, "text": "first"}],
                 "sections": [{"first_segment": 0, "last_segment_exclusive": 1, "start_seconds": 1, "last_start_seconds": 1}], "limitations": []}
        second = {"ok": True, "source": "transcript", "transcript_available": True, "content_truncated": False,
                  "next_cursor": None, "transcript": [{"start_seconds": 600, "text": "later"}],
                  "sections": [{"first_segment": 0, "last_segment_exclusive": 1, "start_seconds": 600, "last_start_seconds": 600}], "limitations": []}
        handler.function_handler.execute_function = AsyncMock(side_effect=[json.dumps(first), json.dumps(second)])
        handler.client.responses.create = AsyncMock(side_effect=[response([
            tool_call("video", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw"}')]), text_response("Summary")])
        await handler.get_response([{"role": "user", "content": "Summarize the whole video"}], None)
        self.assertEqual(handler.function_handler.execute_function.await_count, 2)
        self.assertEqual(handler.function_handler.execute_function.await_args_list[1].args[1]["cursor"], cursor)
        sent = handler.client.responses.create.await_args.kwargs["input"]
        result = json.loads(next(item for item in sent if item.get("type") == "function_call_output")["output"])
        self.assertEqual([item["text"] for item in result["transcript"]], ["first", "later"])
        self.assertEqual(result["sections"][1]["first_segment"], 1)
        self.assertFalse(result["content_truncated"])

    async def test_explicit_continuation_requires_a_returned_cursor(self):
        with patch("discord_bot.handlers.function_handler.FunctionHandler.load_functions", return_value={"read_youtube": ReadYouTube}):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        url = "https://youtu.be/" + VIDEO_ID
        cursor = {"segment_index": 2, "char_offset": 0, "track_hash": "a" * 64,
                  "range_start": None, "range_end": 60}
        initial = {"url": url, "end_seconds": 60}
        continuation = {"url": url, "cursor": cursor}
        handler.client.responses.create = AsyncMock(side_effect=[
            response([tool_call(str(n), "read_youtube", json.dumps(args))])
            for n, args in enumerate((continuation, initial, continuation, initial))
        ] + [text_response("Done")])
        completed = {"ok": True, "source": "transcript", "transcript_available": True,
                     "content_truncated": False, "next_cursor": None}
        first = {**completed, "content_truncated": True, "next_cursor": cursor}
        with patch("discord_bot.functions.read_youtube.read_youtube", side_effect=[first, completed]) as fetch:
            await handler.get_response([{"role": "user", "content": "Read the first minute"}], None)
        self.assertEqual(fetch.call_count, 2)
        fetch.assert_called_with(VIDEO_ID, None, 60.0, cursor)
        request = handler.client.responses.create.await_args.kwargs
        self.assertIs(request["tools"][0]["strict"], False)
        self.assertNotIn("cursor", request["tools"][0]["parameters"]["required"])
        outputs = [json.loads(item["output"]) for item in request["input"]
                   if item.get("type") == "function_call_output"]
        self.assertEqual(outputs[0]["error"]["code"], "INVALID_ARGUMENT")
        self.assertIsNone(outputs[2]["next_cursor"])
        self.assertEqual(outputs[3]["error"]["code"], "READ_LIMIT")

    async def test_whole_video_path_returns_late_captions_end_to_end(self):
        snippets = [SimpleNamespace(text=f"caption {n} " + "字" * 44, start=n * 5, duration=4)
                    for n in range(900)]
        with patch("discord_bot.handlers.function_handler.FunctionHandler.load_functions", return_value={"read_youtube": ReadYouTube}):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.client.responses.create = AsyncMock(side_effect=[response([
            tool_call("video", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw", "start_seconds":0}')]), text_response("Summary")])
        with patch("discord_bot.functions.read_youtube.BoundedYouTubeSession", side_effect=lambda: mock_session()), \
             patch("discord_bot.functions.read_youtube.YouTubeTranscriptApi", mock_provider(snippets)):
            await handler.get_response([{"role": "user", "content": "Summarize the whole video"}], None)
        sent = handler.client.responses.create.await_args.kwargs["input"]
        result = json.loads(next(item for item in sent if item.get("type") == "function_call_output")["output"])
        self.assertEqual(len(result["transcript"]), 900)
        self.assertEqual(result["transcript"][-1]["text"], "caption 899 " + "字" * 44)
        self.assertFalse(result["content_truncated"])

    async def test_failed_automatic_continuation_reports_partial_coverage(self):
        from discord_bot.handlers.chatgpt_handler import combine_youtube_pages
        first = {"ok": True, "content_truncated": True, "next_cursor": {"segment_index": 200},
                 "transcript": [{"start_seconds": 500, "text": "last"}], "limitations": []}
        for second in (None, {"ok": False, "error": {"code": "BUSY"}}):
            result = combine_youtube_pages(first, second)
            self.assertTrue(result["content_truncated"])
            self.assertEqual(result["next_cursor"], first["next_cursor"])
            self.assertIn("only the returned caption range", result["limitations"][-1])

    async def test_automatic_continuation_timeout_does_not_lose_first_page(self):
        import asyncio
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.function_handler.api_functions = []
        first = {"ok": True, "source": "transcript", "transcript_available": True, "content_truncated": True,
                 "next_cursor": {"segment_index": 200}, "transcript": [{"start_seconds": 500, "text": "first"}],
                 "sections": [], "limitations": []}
        async def execute(_name, args):
            if "cursor" in args:
                await asyncio.sleep(1)
            return json.dumps(first)
        handler.function_handler.execute_function = AsyncMock(side_effect=execute)
        handler.client.responses.create = AsyncMock(side_effect=[response([
            tool_call("video", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw"}')]), text_response("Partial")])
        with patch("discord_bot.handlers.chatgpt_handler.YOUTUBE_CONTINUATION_TIMEOUT", 0.01):
            await handler.get_response([{"role": "user", "content": "Summarize"}], None)
        sent = handler.client.responses.create.await_args.kwargs["input"]
        output = json.loads(next(item for item in sent if item.get("type") == "function_call_output")["output"])
        self.assertTrue(output["content_truncated"])
        self.assertIn("failed or timed out", output["limitations"][-1])
        self.assertEqual(output["transcript"][0]["text"], "first")

    async def test_targeted_time_range_does_not_automatically_spend_second_read(self):
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            handler = ChatGPTHandler("test-key")
        handler.client = MagicMock()
        handler.function_handler.api_functions = []
        page = {"ok": True, "source": "transcript", "transcript_available": True, "content_truncated": True,
                "next_cursor": {"segment_index": 200}, "transcript": [], "sections": [], "limitations": []}
        handler.function_handler.execute_function = AsyncMock(return_value=json.dumps(page))
        handler.client.responses.create = AsyncMock(side_effect=[response([
            tool_call("video", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw", "start_seconds":500}')]), text_response("Partial")])
        await handler.get_response([{"role": "user", "content": "What happens after 8:20?"}], None)
        handler.function_handler.execute_function.assert_awaited_once()

    async def test_multiple_youtube_reads_send_at_most_one_progress_message(self):
        callback = AsyncMock()
        with patch("discord_bot.handlers.chatgpt_handler.FunctionHandler"):
            handler = ChatGPTHandler("test-key", callback)
        handler.client = MagicMock()
        handler.function_handler.api_functions = []
        handler.function_handler.execute_function = AsyncMock(return_value="ok")
        handler.client.responses.create = AsyncMock(side_effect=[response([
            tool_call("1", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw", "quick_update":"Reading"}'),
            tool_call("2", "read_youtube", '{"url":"https://youtu.be/jNQXAC9IVRw", "quick_update":"Still reading"}')]), text_response("Done")])
        await handler.get_response([{"role": "user", "content": "Summarize"}], None)
        callback.assert_awaited_once_with(None, "Reading")
