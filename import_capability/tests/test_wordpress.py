import json

import pytest
import requests

from import_capability.providers.wordpress import (
    WordPressProviderError,
    inventory_wordpress,
    write_wordpress_artifacts,
)


class MockResponse:
    def __init__(self, data, error=None):
        self.data = data
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.data


class MockSession:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def get(self, url, *, timeout):
        self.requests.append((url, timeout))
        return self.responses[url]


def wordpress_item(item_id, slug, content_type):
    return {
        "id": item_id,
        "title": {"rendered": f"{content_type.title()} title"},
        "slug": slug,
        "status": "publish",
        "date": "2026-01-02T03:04:05",
        "link": f"https://example.com/{slug}/",
        "excerpt": {"rendered": f"<p>{content_type} excerpt</p>"},
        "content": {"rendered": f"<p>{content_type} content</p>"},
    }


def test_wordpress_provider_fetches_public_posts_and_pages(tmp_path):
    posts_url = "https://example.com/wp-json/wp/v2/posts"
    pages_url = "https://example.com/wp-json/wp/v2/pages"
    session = MockSession(
        {
            posts_url: MockResponse([wordpress_item(1, "news", "post")]),
            pages_url: MockResponse([wordpress_item(2, "about", "page")]),
        }
    )

    artifacts = inventory_wordpress("https://example.com", session)

    assert session.requests == [(posts_url, (5, 20)), (pages_url, (5, 20))]
    assert [page["type"] for page in artifacts["inventory"]["pages"]] == [
        "post",
        "page",
    ]
    assert artifacts["content"]["pages"][0] == {
        "id": 1,
        "type": "post",
        "title": "Post title",
        "slug": "news",
        "status": "publish",
        "date": "2026-01-02T03:04:05",
        "link": "https://example.com/news/",
        "excerpt": "<p>post excerpt</p>",
        "content": "<p>post content</p>",
    }
    assert artifacts["schema"]["content_types"] == [
        {"name": "post", "source": "wordpress"},
        {"name": "page", "source": "wordpress"},
    ]

    result = write_wordpress_artifacts("https://example.com", tmp_path, session)
    assert result == {
        "inventory.json": "inventory.json",
        "content.json": "content.json",
        "schema.json": "schema.json",
    }
    assert json.loads((tmp_path / "content.json").read_text(encoding="utf-8"))[
        "pages"
    ][1]["slug"] == "about"


def test_wordpress_provider_fails_cleanly_when_rest_api_is_unavailable():
    posts_url = "https://example.com/wp-json/wp/v2/posts"
    session = MockSession(
        {posts_url: MockResponse(None, requests.ConnectionError("offline"))}
    )

    with pytest.raises(WordPressProviderError, match="REST API unavailable"):
        inventory_wordpress("https://example.com", session)
