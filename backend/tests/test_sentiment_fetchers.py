import pytest

from app.sentiment.fetchers.finnhub_news import FinnhubNewsFetcher, parse_company_news
from app.sentiment.fetchers.newsapi import NewsApiFetcher, parse_newsapi


def test_parse_company_news_maps_and_skips_headless():
    data = [
        {"headline": "Samsung beats estimates", "summary": "Strong quarter",
         "url": "http://x", "datetime": 1781000000, "source": "Reuters"},
        {"headline": "", "summary": "no headline -> skipped", "datetime": 1781000001},
    ]
    evs = parse_company_news(data, "005930")
    assert len(evs) == 1
    e = evs[0]
    assert e.source == "finnhub" and e.author_handle == "Reuters" and e.symbols == ["005930"]
    assert e.posted_at.tzinfo is not None
    assert "Samsung beats estimates" in e.text and "Strong quarter" in e.text


def test_parse_newsapi_maps_and_skips_titleless():
    data = {"articles": [
        {"title": "Apple hits record high", "description": "AAPL up",
         "url": "http://y", "publishedAt": "2026-06-16T05:00:00Z", "source": {"name": "Bloomberg"}},
        {"title": "", "description": "no title", "publishedAt": "2026-06-16T05:00:00Z",
         "source": {"name": "x"}},
    ]}
    evs = parse_newsapi(data)
    assert len(evs) == 1
    assert evs[0].source == "newsapi" and evs[0].author_handle == "Bloomberg"
    assert evs[0].posted_at.tzinfo is not None and "Apple hits record high" in evs[0].text


@pytest.mark.asyncio
async def test_news_fetchers_self_disable_without_key():
    assert FinnhubNewsFetcher("").enabled is False
    assert await FinnhubNewsFetcher("").fetch(["AAPL"]) == []
    assert NewsApiFetcher("").enabled is False
    assert await NewsApiFetcher("").fetch(["AAPL"]) == []
