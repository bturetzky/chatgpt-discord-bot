"""YouTube URL routing is independent of providers and performs no fetches."""
import unittest

from discord_bot.youtube_url import canonical_youtube_url, youtube_video_id


class YouTubeURLTests(unittest.TestCase):
    def test_supported_video_urls(self):
        video_id = "jNQXAC9IVRw"
        for url in [f"https://youtube.com/watch?v={video_id}&t=30", f"https://youtu.be/{video_id}?t=30",
                    f"https://m.youtube.com/shorts/{video_id}", f"https://www.youtube.com/live/{video_id}",
                    f"https://www.youtube.com/embed/{video_id}"]:
            with self.subTest(url=url):
                self.assertEqual(youtube_video_id(url), video_id)
        self.assertEqual(canonical_youtube_url(video_id), "https://www.youtube.com/watch?v=jNQXAC9IVRw")

    def test_rejects_unsafe_ambiguous_or_non_video_links(self):
        for url in ["http://youtube.com/watch?v=jNQXAC9IVRw", "https://youtube.com.evil.test/watch?v=jNQXAC9IVRw",
                    "https://youtube.com@evil.test/watch?v=jNQXAC9IVRw", "https://user@youtube.com/watch?v=jNQXAC9IVRw",
                    "https://youtube.com:444/watch?v=jNQXAC9IVRw", "https://youtube.com/watch?v=jNQXAC9IVRw&v=abcdefghijk",
                    "https://youtube.com/playlist?list=jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw/extra",
                    "https://youtube.com/watch?v=bad", "file:///etc/passwd", None]:
            with self.subTest(url=url):
                self.assertIsNone(youtube_video_id(url))
        with self.assertRaises(ValueError):
            canonical_youtube_url("../../private")
