import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os

import requests

from crawler import (
    extract_links,
    resolve_crawled_url,
    fetch_page_with_retry,
    mark_non_retryable_error,
    build_crawl_queue,
    CrawlMode,
)
from database import Database


class CrawlerUrlHandlingTests(unittest.TestCase):
    def test_extract_links_disallows_subdomains_by_default(self):
        config = {
            "site": {"base_url": "https://paperzilla.ai"},
            "crawler": {"exclude_patterns": []},
        }
        html = """
        <a href="/about">About</a>
        <a href="https://docs.paperzilla.ai/intro">Docs</a>
        """

        links = extract_links(html, "https://paperzilla.ai", config)
        self.assertEqual(links, ["https://paperzilla.ai/about"])

    def test_extract_links_allows_explicit_subdomain(self):
        config = {
            "site": {
                "base_url": "https://paperzilla.ai",
                "allowed_subdomains": ["docs"],
            },
            "crawler": {"exclude_patterns": []},
        }
        html = """
        <a href="/about">About</a>
        <a href="https://docs.paperzilla.ai/intro">Docs</a>
        <a href="https://blog.paperzilla.ai/post">Blog</a>
        """

        links = extract_links(html, "https://paperzilla.ai", config)
        self.assertEqual(
            links,
            ["https://paperzilla.ai/about", "https://docs.paperzilla.ai/intro"],
        )

    def test_extract_links_allows_all_subdomains_when_enabled(self):
        config = {
            "site": {"base_url": "https://paperzilla.ai", "allow_subdomains": True},
            "crawler": {"exclude_patterns": []},
        }
        html = """
        <a href="https://docs.paperzilla.ai/intro">Docs</a>
        <a href="https://blog.paperzilla.ai/post">Blog</a>
        <a href="https://example.com/page">External</a>
        """

        links = extract_links(html, "https://paperzilla.ai", config)
        self.assertEqual(
            links,
            ["https://docs.paperzilla.ai/intro", "https://blog.paperzilla.ai/post"],
        )

    def test_resolve_crawled_url_prefers_final_response_url(self):
        resolved = resolve_crawled_url(
            "https://paperzilla.ai/docs", "https://docs.paperzilla.ai/intro#install"
        )
        self.assertEqual(resolved, "https://docs.paperzilla.ai/intro")

    def test_extract_links_ignores_template_placeholder_urls(self):
        config = {
            "site": {
                "base_url": "https://docs.paperzilla.ai",
                "allow_subdomains": True,
            },
            "crawler": {"exclude_patterns": []},
        }
        html = """
        <a href="/guides/{path">Broken Template Link</a>
        <a href="/guides/cli">Valid Link</a>
        """

        links = extract_links(html, "https://docs.paperzilla.ai", config)
        self.assertEqual(links, ["https://docs.paperzilla.ai/guides/cli"])

    def test_extract_links_ignores_markdown_urls(self):
        config = {
            "site": {
                "base_url": "https://docs.paperzilla.ai",
                "allow_subdomains": True,
            },
            "crawler": {"exclude_patterns": []},
        }
        html = """
        <a href="/guides/install.md">Markdown Guide</a>
        <a href="/guides/cli">Valid Link</a>
        """

        links = extract_links(html, "https://docs.paperzilla.ai", config)
        self.assertEqual(links, ["https://docs.paperzilla.ai/guides/cli"])

    @patch("crawler.requests.get")
    def test_fetch_page_404_is_not_retryable(self, mock_get):
        response = MagicMock()
        response.status_code = 404
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Client Error", response=response
        )
        mock_get.return_value = response

        config = {"crawler": {"user_agent": "TestBot/1.0", "timeout": 10}}
        fetched_response, should_retry = fetch_page_with_retry(
            "https://docs.paperzilla.ai/{path", config, 0
        )

        self.assertIsNone(fetched_response)
        self.assertFalse(should_retry)

    def test_mark_non_retryable_error_sets_retry_count_to_max(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        url = "https://docs.paperzilla.ai/{path"
        try:
            with Database(db_path) as db:
                db.save_url(url, status="error", http_status=None)
                mark_non_retryable_error(db, url, max_retries=5)

                self.assertEqual(db.get_url_retry_count(url), 5)
                with db.get_cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM urls WHERE url = ?",
                        (url,),
                    )
                    row = cursor.fetchone()
                    self.assertEqual(row["status"], "error")
        finally:
            os.remove(db_path)

    def test_build_crawl_queue_filters_template_retry_urls(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        template_url = "https://docs.paperzilla.ai/{path"
        valid_retry_url = "https://docs.paperzilla.ai/guides/cli"
        config = {
            "site": {"base_url": "https://paperzilla.ai"},
            "crawler": {"max_retries": 5},
        }

        try:
            with Database(db_path) as db:
                db.save_url(template_url, status="error", http_status=None)
                db.save_url(valid_retry_url, status="error", http_status=None)

                # Make both retry candidates eligible immediately.
                with db.get_cursor() as cursor:
                    cursor.execute(
                        "UPDATE urls SET last_crawled = NULL, retry_count = 1 WHERE url IN (?, ?)",
                        (template_url, valid_retry_url),
                    )

                urls_to_visit, retry_count, _ = build_crawl_queue(
                    db, config, CrawlMode.NORMAL, "https://paperzilla.ai", preview=False
                )

                self.assertEqual(retry_count, 1)
                self.assertEqual(urls_to_visit, [valid_retry_url])

                with db.get_cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM urls WHERE url = ?",
                        (template_url,),
                    )
                    row = cursor.fetchone()
                    self.assertEqual(row["status"], "invalid")
        finally:
            os.remove(db_path)

    def test_build_crawl_queue_filters_markdown_retry_urls(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        markdown_url = "https://docs.paperzilla.ai/guides/install.md"
        valid_retry_url = "https://docs.paperzilla.ai/guides/cli"
        config = {
            "site": {"base_url": "https://paperzilla.ai"},
            "crawler": {"max_retries": 5},
        }

        try:
            with Database(db_path) as db:
                db.save_url(markdown_url, status="error", http_status=None)
                db.save_url(valid_retry_url, status="error", http_status=None)

                with db.get_cursor() as cursor:
                    cursor.execute(
                        "UPDATE urls SET last_crawled = NULL, retry_count = 1 WHERE url IN (?, ?)",
                        (markdown_url, valid_retry_url),
                    )

                urls_to_visit, retry_count, _ = build_crawl_queue(
                    db, config, CrawlMode.NORMAL, "https://paperzilla.ai", preview=False
                )

                self.assertEqual(retry_count, 1)
                self.assertEqual(urls_to_visit, [valid_retry_url])

                with db.get_cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM urls WHERE url = ?",
                        (markdown_url,),
                    )
                    row = cursor.fetchone()
                    self.assertEqual(row["status"], "invalid")
        finally:
            os.remove(db_path)


if __name__ == "__main__":
    unittest.main()
