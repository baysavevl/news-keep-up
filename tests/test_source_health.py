import unittest
from urllib.error import URLError

from news_keep_up.models import Source
from news_keep_up.source_health import failed_source_fetch_log


class SourceHealthTest(unittest.TestCase):
    def test_failed_source_fetch_log_preserves_urlerror_reason(self):
        source = Source(
            name="Blocked Board",
            kind="html",
            url="https://example.com/jobs",
            category="remote-job-board",
        )

        log = failed_source_fetch_log("fde-jobs", source, URLError("timed out"))

        self.assertEqual(log.error_type, "URLError")
        self.assertIn("timed out", log.error_message)


if __name__ == "__main__":
    unittest.main()
