import unittest

from news_keep_up.utils import canonicalize_url, clean_text, fingerprint_text


class UtilsTest(unittest.TestCase):
    def test_canonicalize_url_removes_tracking_and_fragment(self):
        url = "HTTPS://Example.COM/path/?utm_source=newsletter&b=2&a=1#comments"

        self.assertEqual(canonicalize_url(url), "https://example.com/path?a=1&b=2")

    def test_canonicalize_url_removes_trailing_slash_except_root(self):
        self.assertEqual(canonicalize_url("https://example.com/path/"), "https://example.com/path")
        self.assertEqual(canonicalize_url("https://example.com/"), "https://example.com/")

    def test_fingerprint_text_is_stable_for_case_and_whitespace(self):
        first = fingerprint_text(" AI Agents  ", "for   Engineers")
        second = fingerprint_text("ai agents", "for engineers")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_clean_text_collapses_markup_and_whitespace(self):
        self.assertEqual(clean_text("  Hello<br>  AI&nbsp;agents \n "), "Hello AI agents")


if __name__ == "__main__":
    unittest.main()
