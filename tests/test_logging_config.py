import io
import logging
import time
from unittest import TestCase
from unittest.mock import patch

from run import configure_logging


class LoggingConfigTests(TestCase):
    def test_root_formats_application_and_library_records_in_utc_once(self):
        stream = io.StringIO()
        root = logging.getLogger()
        with patch.object(root, "handlers", []), patch.object(root, "level"), \
             patch.object(logging.Formatter, "converter", time.localtime), \
             patch.dict("os.environ", {"LOG_LEVEL": "INFO"}), patch("sys.stderr", stream):
            configure_logging()
            configure_logging()
            self.assertEqual(len(root.handlers), 1)
            self.assertIs(logging.Formatter.converter, time.gmtime)
            for name in ("discord_bot.app", "httpx"):
                record = logging.LogRecord(name, logging.INFO, __file__, 1, "test record", (), None)
                record.created = 1_704_067_200
                logging.getLogger(name).handle(record)
        self.assertEqual(stream.getvalue().splitlines(), [
            "2024-01-01T00:00:00Z INFO discord_bot.app: test record",
            "2024-01-01T00:00:00Z INFO httpx: test record",
        ])
