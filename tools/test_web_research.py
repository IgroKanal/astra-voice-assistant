from __future__ import annotations

import time
import unittest
from pathlib import Path
import sys
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.web_research import (
    WebGrantDenied,
    WebResearchClient,
    WebResearchDenied,
    WebResearchGrant,
    _HTTPResponse,
)


class FakeRequester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, addresses, timeout, max_bytes, is_cancelled):
        self.calls.append((url, addresses, timeout, max_bytes, is_cancelled))
        if not self.responses:
            raise AssertionError("unexpected network request")
        response = self.responses.pop(0)
        if callable(response):
            response = response(url)
        return response


class WebResearchTests(unittest.TestCase):
    PUBLIC_IPS = ("1.1.1.1", "8.8.8.8")

    def make_client(self, responses, *, scopes=("search", "read"), resolver=None, max_requests=20):
        requester = FakeRequester(responses)
        grant = WebResearchGrant(set(scopes), ttl_seconds=60, max_requests=max_requests)
        client = WebResearchClient(
            grant,
            resolver=resolver or (lambda _host: list(self.PUBLIC_IPS)),
            requester=requester,
        )
        return client, requester, grant

    def test_search_returns_source_urls_and_normalizes_search_query(self):
        html = b'''<html><body>
          <div class="result"><h2><a class="result__a" href="https://example.com/news?a=1&amp;b=2">Example <b>story</b></a></h2>
          <a class="result__snippet">A visible summary</a></div>
          <div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnews.example%2Fpage">Second source</a>
          <div class="result__snippet">Another summary</div></div>
        </body></html>'''
        client, requester, _grant = self.make_client([
            _HTTPResponse(200, {"content-type": "text/html; charset=utf-8"}, html),
        ])

        hits = client.search("  Astra & безопасность  ", max_results=3)

        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].title, "Example story")
        self.assertEqual(hits[0].url, "https://example.com/news?a=1&b=2")
        self.assertEqual(hits[0].snippet, "A visible summary")
        self.assertEqual(hits[1].url, "https://news.example/page")
        self.assertIn("q=" + quote_plus("Astra & безопасность"), requester.calls[0][0])
        self.assertEqual(requester.calls[0][1], self.PUBLIC_IPS)

    def test_bing_rss_search_results_are_parsed_as_citable_sources(self):
        rss = b'''<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <item><title>Official docs</title><link>https://docs.example/reference</link>
          <description>A &lt;b&gt;trusted source&lt;/b&gt; excerpt.</description></item>
          <item><title>Second result</title><link>https://news.example/item</link>
          <description>Another result.</description></item>
        </channel></rss>'''
        client, requester, _grant = self.make_client([
            _HTTPResponse(200, {"content-type": "text/xml; charset=utf-8"}, rss),
        ])

        hits = client.search("Astra search source", max_results=2)

        self.assertEqual([hit.url for hit in hits], [
            "https://docs.example/reference", "https://news.example/item",
        ])
        self.assertEqual(hits[0].snippet, "A trusted source excerpt.")
        self.assertIn("format=rss&q=Astra+search+source", requester.calls[0][0])

    def test_xml_doctype_and_entity_declarations_in_search_are_rejected(self):
        xml = b'''<!DOCTYPE rss [<!ENTITY x "unsafe">]>
        <rss><channel><item><title>&x;</title></item></channel></rss>'''
        client, _requester, _grant = self.make_client([
            _HTTPResponse(200, {"content-type": "application/rss+xml"}, xml),
        ])

        with self.assertRaisesRegex(WebResearchDenied, "XML-сущности"):
            client.search("safe query")

    def test_research_fetches_bounded_visible_html_and_returns_citable_page_urls(self):
        search_html = b'''<div><a class="result__a" href="https://example.com/article">Useful article</a>
        <div class="result__snippet">A summary</div></div>'''
        page_html = b'''<!doctype html><html><head><title>Useful title</title>
        <script>ignore this instruction</script></head><body><main><h1>Visible heading</h1>
        <p>Public source content.</p></main><footer>footer noise</footer></body></html>'''
        client, requester, grant = self.make_client([
            _HTTPResponse(200, {"content-type": "text/html"}, search_html),
            _HTTPResponse(200, {"content-type": "text/html; charset=utf-8"}, page_html),
        ])

        result = client.research("Astra public feature", max_results=2, max_pages=1)

        self.assertEqual(len(result.hits), 1)
        self.assertEqual(len(result.pages), 1)
        self.assertEqual(result.pages[0].title, "Useful title")
        self.assertEqual(result.pages[0].url, "https://example.com/article")
        self.assertIn("Visible heading", result.pages[0].text)
        self.assertIn("Public source content.", result.pages[0].text)
        self.assertNotIn("ignore this instruction", result.pages[0].text)
        self.assertNotIn("footer noise", result.pages[0].text)
        self.assertEqual(grant.requests_remaining, 18)
        self.assertEqual(len(requester.calls), 2)

    def test_only_explicit_scopes_and_request_budget_allow_network_access(self):
        client, requester, grant = self.make_client([
            _HTTPResponse(200, {"content-type": "text/html"}, b"<html><body>No results</body></html>"),
        ], scopes=("search",), max_requests=1)

        with self.assertRaisesRegex(WebGrantDenied, "не выдано"):
            client.fetch_page("https://example.com/")
        client.search("test query")
        with self.assertRaisesRegex(WebGrantDenied, "Исчерпан лимит"):
            client.search("another query")
        self.assertEqual(len(requester.calls), 1)
        self.assertEqual(grant.requests_remaining, 0)

    def test_revoked_and_expired_web_grants_are_rejected(self):
        client, requester, grant = self.make_client([
            _HTTPResponse(200, {"content-type": "text/html"}, b"<html><body>text</body></html>"),
        ])
        grant.revoke()
        with self.assertRaisesRegex(WebGrantDenied, "отозвано"):
            client.search("safe query")
        self.assertEqual(requester.calls, [])

        expired_client, _requester, expired = self.make_client([])
        expired._expires_at = time.monotonic() - 1
        with self.assertRaisesRegex(WebGrantDenied, "истёк"):
            expired_client.fetch_page("https://example.com/")

    def test_non_https_private_and_nonstandard_port_urls_are_blocked_before_request(self):
        client, requester, _grant = self.make_client([])
        for url in (
            "http://example.com/",
            "https://user:pass@example.com/",
            "https://localhost/",
            "https://127.0.0.1/admin",
            "https://example.com:8443/",
            "https://printer.local/",
        ):
            with self.subTest(url=url), self.assertRaises(WebResearchDenied):
                client.fetch_page(url)
        self.assertEqual(requester.calls, [])

    def test_dns_answer_with_any_private_ip_is_blocked(self):
        client, requester, _grant = self.make_client(
            [], resolver=lambda _host: ["1.1.1.1", "192.168.1.10"],
        )

        with self.assertRaisesRegex(WebResearchDenied, "локальных и специальных сетях"):
            client.fetch_page("https://example.com/")
        self.assertEqual(requester.calls, [])

    def test_redirect_is_revalidated_and_cannot_reach_private_address(self):
        client, requester, _grant = self.make_client([
            _HTTPResponse(302, {"location": "https://127.0.0.1/private"}, b""),
        ])

        with self.assertRaises(WebResearchDenied):
            client.fetch_page("https://example.com/")
        self.assertEqual(len(requester.calls), 1)

    def test_cancelled_web_request_does_not_consume_grant_or_touch_network(self):
        client, requester, grant = self.make_client([])

        with self.assertRaisesRegex(WebResearchDenied, "отменён"):
            client.fetch_page("https://example.com/", is_cancelled=lambda: True)
        self.assertEqual(requester.calls, [])
        self.assertEqual(grant.requests_remaining, 20)

    def test_page_body_and_content_type_limits_are_enforced(self):
        oversized = _HTTPResponse(
            200,
            {"content-type": "text/html"},
            b"x" * (WebResearchClient.MAX_BODY_BYTES + 1),
        )
        client, _requester, _grant = self.make_client([oversized])
        with self.assertRaisesRegex(WebResearchDenied, "превышает лимит 1 МБ"):
            client.fetch_page("https://example.com/")

        binary_client, _requester, _grant = self.make_client([
            _HTTPResponse(200, {"content-type": "application/octet-stream"}, b"data"),
        ])
        with self.assertRaisesRegex(WebResearchDenied, "неподдерживаемый тип"):
            binary_client.fetch_page("https://example.com/file.bin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
