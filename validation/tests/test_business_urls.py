"""Business source links must not expose repository navigation."""

from __future__ import annotations

import unittest

from validation.business_urls import contains_source_repository_url


class BusinessSourceUrlTests(unittest.TestCase):
    def test_repository_links_are_detected(self):
        for text in (
            "https://github.com/example/repo",
            "[参考](https://github.com/example/repo/blob/abc1234/README.md#L3)",
            "https://gitlab.com/example/repo/-/blob/abc1234/README.md",
            "https://code.example.invalid/example/repo/commit/abc1234",
            "HTTPS://GITHUB.COM/EXAMPLE/REPO",
        ):
            with self.subTest(text=text):
                self.assertTrue(contains_source_repository_url(text))

    def test_ordinary_web_links_are_allowed(self):
        for text in (
            "[帮助](https://example.invalid/help/orders)",
            "https://github.com/features",
            "[规则说明](https://example.invalid/rules#section-2)",
            "https://news.example.invalid/article/2026/10/26",
        ):
            with self.subTest(text=text):
                self.assertFalse(contains_source_repository_url(text))
